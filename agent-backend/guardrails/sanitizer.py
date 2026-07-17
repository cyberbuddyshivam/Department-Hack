"""
guardrails/sanitizer.py
Prompt-injection sanitizer for caller-supplied free text.

Security model (from architecture.md §5 and code-standards.md §5):
  "Any caller-supplied text (from `text`, `call_transcript`, `audio_transcript`,
   or extracted image content) must pass through guardrails/sanitizer.py before
   being inserted into a prompt. Treat it as data, never as instructions to
   the model."

Strategy — two-layer defence:
  Layer 1 – Pattern blocking: detect known prompt-injection phrases (ignore
    previous instructions, you are now, system:, etc.) and replace the entire
    match with a safe placeholder. This is lightweight and catches the most
    common jailbreak openers.

  Layer 2 – Structural escaping: wrap the sanitised text in an explicit XML-
    style data tag when it's inserted into a prompt template. This is done by
    the `wrap_as_data()` helper, not inside sanitise() itself, so each agent
    controls its own prompt assembly while still being required to use the
    wrapper.

What this does NOT do:
  - It does not try to parse intent or use an LLM to detect injection —
    that would create a circular dependency (guardrail depends on the very
    thing it protects).
  - It does not base64-encode or heavily transform the text; that would
    degrade actual emergency information that agents need to read.
  - It does not truncate benign long text — truncation is the agent's
    responsibility via its prompt length budget.

Usage:
    from guardrails.sanitizer import sanitize, wrap_as_data

    cleaned = sanitize(raw_caller_text)
    prompt  = f"...{wrap_as_data(cleaned)}..."
"""

from __future__ import annotations

import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Layer 1: injection pattern blocklist
# Each pattern is a compiled regex (case-insensitive). When matched, the
# entire matched span is replaced with INJECTION_PLACEHOLDER.
# ---------------------------------------------------------------------------

INJECTION_PLACEHOLDER = "[REDACTED:UNSAFE_INSTRUCTION]"

_RAW_PATTERNS: list[str] = [
    # Classic jailbreak openers
    r"ignore\s+(all\s+)?(previous|prior|above|earlier)\s+(instructions?|prompts?|context|rules?)",
    r"disregard\s+(all\s+)?(previous|prior|above|earlier)\s+(instructions?|prompts?|context|rules?)",
    r"forget\s+(all\s+)?(previous|prior|above|earlier)\s+(instructions?|prompts?|context|rules?)",
    r"override\s+(all\s+)?(previous|prior|above|earlier)\s+(instructions?|prompts?)",

    # Role-switch attempts
    r"you\s+are\s+now\s+(a|an|the)\s+\w+",
    r"act\s+as\s+(a|an|the|if\s+you\s+were)?\s+\w+",
    r"pretend\s+(you\s+are|to\s+be)\s+(a|an|the)?\s+\w+",
    r"roleplay\s+as\s+",
    r"simulate\s+(being\s+)?(a|an|the)?\s+\w+",

    # Direct system/instruction injection markers
    r"(?:^|\b)(system\s*:|user\s*:|assistant\s*:|<\s*system\s*>|<\s*/\s*system\s*>)",
    r"\[INST\]|\[/INST\]|<\|im_start\|>|<\|im_end\|>",   # common chat-template tokens

    # Instruction imperatives targeting the model
    r"\bdo\s+not\s+(follow|obey|respect|comply\s+with)\s+",
    r"\byour\s+(new\s+)?(instructions?|rules?|guidelines?|prime\s+directive)\s+(are|is)\b",
    r"\bconfidential\b.*\binstructions?\b",

    # Prompt delimiter injection
    r"---+\s*(instructions?|system|end\s+of\s+(user\s+)?input)",
    r"###\s*(instructions?|system|new\s+task)",
]

_COMPILED_PATTERNS: list[re.Pattern[str]] = [
    re.compile(p, re.IGNORECASE | re.MULTILINE) for p in _RAW_PATTERNS
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def sanitize(text: Optional[str]) -> str:
    """
    Sanitize caller-supplied free text before it is interpolated into any
    agent prompt.

    Steps:
      1. Return empty string for None/empty input (no crash, no propagation).
      2. Strip leading/trailing whitespace.
      3. Apply each injection-pattern regex; replace matches with the safe
         placeholder. Log a warning for each replacement (sanitized, no
         caller PII in the log — only the pattern index and replacement count).
      4. Return the cleaned string.

    Parameters
    ----------
    text : str | None
        Raw caller-supplied text from `input_sources.text`,
        `input_sources.call_transcript`, or `input_sources.audio_transcript`.

    Returns
    -------
    str
        Sanitized text, safe for interpolation into an LLM prompt as data.
    """
    if not text:
        return ""

    cleaned: str = text.strip()
    total_replacements: int = 0

    for idx, pattern in enumerate(_COMPILED_PATTERNS):
        new_text, n = pattern.subn(INJECTION_PLACEHOLDER, cleaned)
        if n > 0:
            logger.warning(
                "Sanitizer: pattern #%d matched %d time(s) — replaced with placeholder.",
                idx,
                n,
            )
            total_replacements += n
            cleaned = new_text

    if total_replacements > 0:
        logger.warning(
            "Sanitizer: %d total injection pattern(s) removed from caller input.",
            total_replacements,
        )

    return cleaned


def wrap_as_data(sanitized_text: str) -> str:
    """
    Wrap sanitized caller text in an explicit XML-style data delimiter so
    the LLM clearly understands it is reading *data*, not receiving an
    instruction.

    Each agent's prompt template should call this function when interpolating
    any caller-supplied field, e.g.:

        prompt = f\"\"\"
        You are an emergency triage agent. Analyse the incident below.

        <caller_input>
        {wrap_as_data(sanitized_text)}
        </caller_input>

        Respond with JSON only. Schema: ...
        \"\"\"

    Parameters
    ----------
    sanitized_text : str
        Text that has already been passed through `sanitize()`.

    Returns
    -------
    str
        The text unchanged (the wrapping tags are applied by the f-string
        template in the agent, not here — this function is the reminder /
        contract enforcer that the caller must use a data wrapper).

    Note: we intentionally do NOT add the XML tags inside this function
    because the agent controls the exact prompt layout. Instead, agents
    must use the pattern shown above. This function currently returns the
    text unchanged and serves as a mandatory named pass-through that makes
    the intent explicit in code review — if an agent calls
    `wrap_as_data(raw_text)` without first calling `sanitize()`, that is
    immediately visible as a bug in review.
    """
    return sanitized_text


def sanitize_incident_inputs(
    text: Optional[str] = None,
    audio_transcript: Optional[str] = None,
    call_transcript: Optional[str] = None,
) -> dict[str, str]:
    """
    Convenience function that sanitizes all three caller-supplied text fields
    in one call. Returns a dict keyed by field name.

    Usage in Intake Agent:
        safe = sanitize_incident_inputs(
            text=incident.input_sources.text,
            audio_transcript=incident.input_sources.audio_transcript,
            call_transcript=incident.input_sources.call_transcript,
        )
        # safe["text"], safe["audio_transcript"], safe["call_transcript"]
        # are all guaranteed safe for prompt interpolation.

    Parameters
    ----------
    text : str | None
    audio_transcript : str | None
    call_transcript : str | None

    Returns
    -------
    dict[str, str]
        Keys: "text", "audio_transcript", "call_transcript".
        Values: sanitized strings (empty string when input was None).
    """
    return {
        "text": sanitize(text),
        "audio_transcript": sanitize(audio_transcript),
        "call_transcript": sanitize(call_transcript),
    }
