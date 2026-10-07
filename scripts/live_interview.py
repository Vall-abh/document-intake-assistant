"""Run a real Gemini/Anthropic interview and save a replay fixture without secrets."""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

# Allow `python scripts/live_interview.py` from the repository root on Windows/Linux.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import load_settings
from app.domain.state import WishesState
from app.llm.base import ChatTurn, LLMRequest
from app.llm.factory import build_llm_client
from app.llm.parsing import parse_llm_output

CONVERSATION = [
    "My name is Jane Smith and I live at 12 Oak Road, London.",
    "Maybe worldwide.",
    "Yes, confirm that.",
    "I have no children.",
    "My brother James Smith should be my executor.",
    "I'd like to leave my watch to my son Tom.",
    "Actually, I don't have a son Tom. That gift is wrong.",
]


def main() -> int:
    settings = load_settings()
    if settings.llm_provider not in {"gemini", "anthropic"}:
        print(
            "Set LLM_PROVIDER=gemini (or anthropic) before running the live interview.",
            file=sys.stderr,
        )
        return 2

    key_present = (
        bool(settings.gemini_api_key) if settings.llm_provider == "gemini" else bool(settings.anthropic_api_key)
    )
    if not key_present:
        variable = "GEMINI_API_KEY" if settings.llm_provider == "gemini" else "ANTHROPIC_API_KEY"
        print(f"{variable} is not set; refusing to fake a live-model run.", file=sys.stderr)
        return 2

    client = build_llm_client(settings)
    state = WishesState()
    history = []
    records = []

    for message in CONVERSATION:
        next_field = state.next_field()
        req = LLMRequest(
            state=state,
            missing_fields=[x.value for x in state.missing()],
            unconfirmed_fields=[x.value for x in state.unconfirmed()],
            pending_field=next_field.value if next_field else None,
            history=history[-settings.history_window :],
            user_message=message,
        )
        started = time.perf_counter()
        raw = client.complete(req)
        latency = (time.perf_counter() - started) * 1000
        record = {"user": message, "raw_model_output": raw, "latency_ms": round(latency, 1)}
        try:
            turn = parse_llm_output(raw)
            record["parsed"] = turn.model_dump(mode="json")
        except Exception as exc:
            record["parse_error"] = str(exc)
        records.append(record)
        history.append(ChatTurn(role="user", content=message))

    out = Path("tests/fixtures/live_model_latest.json")
    out.parent.mkdir(exist_ok=True)
    out.write_text(
        json.dumps(
            {"provider": settings.llm_provider, "model": settings.llm_model, "records": records},
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"Saved replay fixture to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
