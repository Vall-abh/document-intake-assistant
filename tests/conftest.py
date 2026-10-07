import json
from pathlib import Path

import pytest

from app.sessions import Session

FIXTURES = json.loads((Path(__file__).parent / "fixtures" / "llm_outputs.json").read_text())


def fixture(name):
    return FIXTURES[name]


class ScriptedLLM:
    """Test double: replays canned raw outputs (dicts are serialised, strings are sent as-is)."""

    name = "scripted"

    def __init__(self, *outputs):
        self.outputs = list(outputs)
        self.requests = []

    def complete(self, request):
        self.requests.append(request)
        out = self.outputs.pop(0) if len(self.outputs) > 1 else self.outputs[0]
        if isinstance(out, Exception):
            raise out
        return out if isinstance(out, str) else json.dumps(out)


@pytest.fixture
def session():
    return Session(id="test")
