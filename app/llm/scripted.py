"""Replay recorded real-model outputs for deterministic demos and regression tests."""
from __future__ import annotations
import json
from pathlib import Path
from app.llm.base import LLMRequest

class ScriptedLLMClient:
    name="scripted"
    is_configured=True
    def __init__(self, fixture_path:str):
        self.records=json.loads(Path(fixture_path).read_text()).get("records",[])
        self.index=0
    def complete(self, request:LLMRequest)->str:
        if self.index >= len(self.records):
            raise RuntimeError("scripted conversation exhausted")
        raw=self.records[self.index].get("raw_model_output","")
        self.index += 1
        return raw
