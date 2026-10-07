"""Provider-neutral LLM contracts."""
from __future__ import annotations
from typing import Protocol
from app.schemas import ChatMessage, ModelTurn, TurnRequest

ChatTurn = ChatMessage
LLMRequest = TurnRequest
LLMTurnOutput = ModelTurn

class LLMError(Exception):
    code="llm_error"; status_code=502
    def __init__(self,message:str): super().__init__(message); self.message=message
class LLMNotConfigured(LLMError): code="llm_not_configured"; status_code=503
class LLMUnavailable(LLMError): code="llm_unavailable"; status_code=502

class LLMClient(Protocol):
    name: str
    is_configured: bool
    def complete(self, request: TurnRequest) -> str: ...
