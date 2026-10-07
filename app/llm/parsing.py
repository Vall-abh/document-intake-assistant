"""Turn raw model text into a validated `LLMTurnOutput`, or raise MalformedModelOutput."""
from __future__ import annotations

import json
import re

from pydantic import ValidationError

from app.errors import MalformedModelOutput
from app.llm.base import LLMTurnOutput

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def parse_llm_output(raw: str) -> LLMTurnOutput:
    text = _FENCE.sub("", (raw or "").strip()).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise MalformedModelOutput("response did not contain a JSON object")
    try:
        data = json.loads(text[start:end + 1])
    except json.JSONDecodeError as exc:
        raise MalformedModelOutput(f"response was not valid JSON: {exc.msg}") from exc
    try:
        return LLMTurnOutput.model_validate(data)
    except ValidationError as exc:
        first = exc.errors()[0]
        loc = ".".join(str(p) for p in first["loc"])
        raise MalformedModelOutput(f"schema violation at '{loc}': {first['msg']}") from exc
