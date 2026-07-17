"""
agents/ambulance_classifier.py
AEGIS — Ambulance Classifier Agent (Step 7 in build order)

Responsibility:
  Determine the appropriate ambulance type (BLS, ALS, trauma, neonatal) and
  any specific required equipment based on the incident text and severity score.

Contract (from architecture.md §4):
  Input:  ClassifierInput (contains incident text and finalised severity score)
  Output: AgentResult[ClassifierOutput]
  Fallback trigger: LLM call fails (LLMGatewayError) → returns ClassifierOutput
                    with type "ALS" (safe default), source="fallback", confidence≤0.4.

Prompt design:
  Provides the exact taxonomy of ambulance types and equipment from models/ambulance.py.
  Uses SMALL_MODEL to return a JSON object with type and required_equipment.
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Optional

from pydantic import BaseModel, Field

from llm_gateway import complete, LLMGatewayError, SMALL_MODEL
from models.agent_result import AgentResult
from models.ambulance import AmbulanceType, AmbulanceEquipment

logger = logging.getLogger(__name__)

AGENT_NAME = "ambulance_classifier"


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class ClassifierInput(BaseModel):
    """Input subset required by the Ambulance Classifier."""
    incident_id: str = Field(description="Used for logging.")
    consolidated_text: str = Field(description="The clean incident description.")
    severity_score: int = Field(description="Finalized severity score (1-10) after Triage/Verifier.")


class ClassifierOutput(BaseModel):
    """Agent-specific typed output for Ambulance Classifier."""
    ambulance_type: AmbulanceType = Field(
        description="Required service level: BLS, ALS, trauma, or neonatal."
    )
    required_equipment: list[AmbulanceEquipment] = Field(
        default_factory=list,
        description="Any specific equipment explicitly required by the incident."
    )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def run(input_data: ClassifierInput) -> AgentResult[ClassifierOutput]:
    """
    Determine the required ambulance type and equipment.

    Parameters
    ----------
    input_data : ClassifierInput
        Contains the incident text and finalized severity score.

    Returns
    -------
    AgentResult[ClassifierOutput]
        Always returns a result. Fallback defaults to 'ALS'.
    """
    t_start = time.monotonic()
    
    prompt = (
        "You are an expert emergency dispatcher. Based on the incident description and severity score, "
        "determine the appropriate ambulance type and any specific required equipment.\n\n"
        "Ambulance Types:\n"
        "- BLS (Basic Life Support): Stable, non-critical medical issues or minor injuries (Severity 1-4).\n"
        "- ALS (Advanced Life Support): Critical medical emergencies (e.g., cardiac arrest, respiratory failure, stroke, severe chest pain), even for Severity 9-10.\n"
        "- trauma: Physical injuries, accidents, major trauma, severe bleeding (Severity 5-10).\n"
        "- neonatal: Any incident explicitly involving a newborn or neonate.\n\n"
        "Available Equipment (choose ONLY from these exact strings if explicitly needed, otherwise empty array):\n"
        "stretcher, oxygen, aed, basic_first_aid, splints, pulse_oximeter, cardiac_monitor, "
        "iv_access, epinephrine, intubation_kit, 12_lead_ecg, ventilator, blood_products, "
        "thoracic_decompression_kit, tourniquet_set, trauma_dressings, neonatal_incubator, "
        "neonatal_ventilator, neonatal_monitor, umbilical_catheter_kit, neonatal_iv_access, surfactant\n\n"
        f"Severity Score: {input_data.severity_score}\n"
        f"Incident Description:\n\"{input_data.consolidated_text}\"\n\n"
        "Respond with ONLY a JSON object in this exact format and nothing else:\n"
        '{"ambulance_type": "<BLS|ALS|trauma|neonatal>", "required_equipment": ["<eq1>", "<eq2>"], '
        '"confidence": <0.0-1.0>, "reasoning": "<1-2 sentences>"}'
    )

    try:
        raw = await complete(
            prompt=prompt,
            model=SMALL_MODEL,
            temperature=0.0,
            max_tokens=150,
        )

        parsed = _parse_llm_response(raw)
        if parsed is None:
            raise ValueError(f"Could not parse LLM response: {raw!r}")

        amb_type = parsed.get("ambulance_type")
        if amb_type not in ("BLS", "ALS", "trauma", "neonatal"):
            raise ValueError(f"Invalid ambulance type: {amb_type}")

        equipment = parsed.get("required_equipment", [])
        if not isinstance(equipment, list):
            equipment = []
        
        # Filter to only valid equipment strings to prevent Pydantic validation errors downstream
        valid_equipment_set = {
            "stretcher", "oxygen", "aed", "basic_first_aid", "splints", "pulse_oximeter",
            "cardiac_monitor", "iv_access", "epinephrine", "intubation_kit", "12_lead_ecg", "ventilator",
            "blood_products", "thoracic_decompression_kit", "tourniquet_set", "trauma_dressings",
            "neonatal_incubator", "neonatal_ventilator", "neonatal_monitor", "umbilical_catheter_kit",
            "neonatal_iv_access", "surfactant"
        }
        clean_equipment = [eq for eq in equipment if eq in valid_equipment_set]

        llm_confidence = float(parsed.get("confidence", 0.5))
        llm_reasoning = str(parsed.get("reasoning", "LLM classified ambulance."))

        output = ClassifierOutput(
            ambulance_type=amb_type,
            required_equipment=clean_equipment
        )
        
        confidence = min(llm_confidence, 0.95)
        source = "llm"
        reasoning = llm_reasoning

    except LLMGatewayError as exc:
        logger.warning(
            "ClassifierAgent[%s]: LLM call failed — %s. Using fallback.",
            input_data.incident_id,
            exc,
        )
        output, reasoning, source, confidence = _fallback_result(f"LLM unavailable: {exc}")
    except (ValueError, KeyError, TypeError) as exc:
        logger.warning(
            "ClassifierAgent[%s]: LLM parse error — %s. Using fallback.",
            input_data.incident_id,
            exc,
        )
        output, reasoning, source, confidence = _fallback_result(f"Parse error: {exc}")

    latency_ms = (time.monotonic() - t_start) * 1000

    logger.info(
        "ClassifierAgent: %s | type=%s | eq=%d | src=%s | conf=%.2f | %.0f ms",
        input_data.incident_id,
        output.ambulance_type,
        len(output.required_equipment),
        source,
        confidence,
        latency_ms,
    )

    return AgentResult(
        agent_name=AGENT_NAME,
        result=output,
        reasoning=reasoning,
        confidence=confidence,
        source=source,  # type: ignore[arg-type]
        latency_ms=round(latency_ms, 1),
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _fallback_result(reason: str) -> tuple[ClassifierOutput, str, str, float]:
    """
    Fallback when Classifier LLM fails.
    Defaults to ALS as it's a safe middle ground.
    Confidence=0.3 ensures human review.
    """
    output = ClassifierOutput(ambulance_type="ALS", required_equipment=[])
    reasoning = (
        f"Classifier evaluation failed ({reason}). "
        "Defaulted to ALS ambulance type. "
        "Human review required."
    )
    return output, reasoning, "fallback", 0.3


def _parse_llm_response(raw: str) -> Optional[dict]:
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    text = text.strip()

    brace_start = text.find("{")
    brace_end = text.rfind("}")
    if brace_start == -1 or brace_end == -1:
        return None

    json_str = text[brace_start: brace_end + 1]
    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        return None
