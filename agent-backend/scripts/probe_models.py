"""Quick probe: test two model IDs with a minimal payload, no gateway overhead."""
import asyncio, os, httpx
from dotenv import load_dotenv
load_dotenv()

KEY = os.environ.get("OPENROUTER_API_KEY", "")
ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"

CANDIDATES = [
    ("SMALL", "google/gemma-4-26b-a4b-it:free"),
    ("SMALL_alt", "poolside/laguna-xs-2.1:free"),
    ("LARGE", "nvidia/nemotron-3-super-120b-a12b:free"),
    ("LARGE_alt", "nvidia/nemotron-3-ultra-550b-a55b:free"),
]

async def probe(label, model_id):
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(
            ENDPOINT,
            headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"},
            json={"model": model_id, "messages": [{"role": "user", "content": 'Reply with only: {"ok":true}'}], "max_tokens": 32, "temperature": 0},
        )
        status = r.status_code
        if status == 200:
            try:
                text = r.json()["choices"][0]["message"]["content"]
            except Exception:
                text = r.text[:80]
            print(f"  [{label}] {model_id} -> HTTP {status}: {text[:60]!r}")
        else:
            print(f"  [{label}] {model_id} -> HTTP {status}: {r.text[:120]}")

async def main():
    print(f"API key present: {bool(KEY)}\n")
    for label, mid in CANDIDATES:
        await probe(label, mid)
        await asyncio.sleep(5)

asyncio.run(main())
