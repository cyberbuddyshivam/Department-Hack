import asyncio
import logging
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from agents import triage
from agents.triage import TriageInput

logging.basicConfig(level=logging.WARNING, format='%(message)s')

original_parse = triage._parse_llm_response

def intercept_parse(raw: str):
    print("\n--- RAW LLM RESPONSE ---")
    print(raw)
    print("------------------------")
    return original_parse(raw)

async def test_model(model_slug: str):
    print(f"\n==============================================")
    print(f"TESTING MODEL: {model_slug}")
    print(f"==============================================\n")
    
    triage.SMALL_MODEL = model_slug
    import llm_gateway
    
    inp = TriageInput(
        incident_id=f"live-test",
        consolidated_text="I have a bad headache and feel dizzy, started an hour ago"
    )
    
    with patch("agents.triage._parse_llm_response", side_effect=intercept_parse):
        for i in range(1, 4):
            print(f"\n================ RUN {i} ================")
            print("Sending live request to Triage Agent...")
            llm_gateway.reset_circuit_breaker()
            result = await triage.run(inp)
            
            print(f"\n*** Final Triage Agent Result (Run {i}) ***")
            print(result.model_dump_json(indent=2))

async def main():
    await test_model("openai/gpt-oss-20b:free")

if __name__ == "__main__":
    asyncio.run(main())
