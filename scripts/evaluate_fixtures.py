"""Run recorded/scripted model conversations and print deterministic safety metrics."""
from __future__ import annotations
import json
from pathlib import Path
from app.llm.parsing import parse_llm_output

ROOT=Path(__file__).resolve().parents[1]
FIXTURE=ROOT/"tests/fixtures/llm_outputs.json"

def main():
    data=json.loads(FIXTURE.read_text())
    total=valid=0
    for name, raw in data.items():
        total += 1
        try:
            parse_llm_output(json.dumps(raw) if isinstance(raw,dict) else raw)
            valid += 1
            print(f"PASS {name}")
        except Exception as exc:
            print(f"REJECT {name}: {exc}")
    print(f"\nFixture schema acceptance: {valid}/{total} ({100*valid/total:.1f}%)")

if __name__ == "__main__": main()
