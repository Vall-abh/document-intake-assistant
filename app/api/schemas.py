"""Versioned HTTP API contracts."""
from __future__ import annotations
from typing import Any
from pydantic import BaseModel, Field, field_validator
from app.domain.state import FieldStatus
from app.domain.updates import Change, Conflict, Rejection

class SendMessageRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    @field_validator("message")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        v=v.strip()
        if not v: raise ValueError("message must not be blank")
        return v

class FieldView(BaseModel):
    value: Any=None
    status: FieldStatus
    applicable: bool

class StateView(BaseModel):
    fields: dict[str, FieldView]
    structured: dict[str, Any]
    missing_fields: list[str]
    unconfirmed_fields: list[str]
    is_complete: bool
    # Compatibility aliases for the earlier UI/tests.
    data: dict[str, Any]
    status: dict[str, str]

class MessageView(BaseModel):
    role: str
    content: str

class SessionResponse(BaseModel):
    session_id: str
    messages: list[MessageView]
    state: StateView
    document_markdown: str
    document: str | None = None
    version: int = 0
    expires_at: float | None = None
    complete: bool = False
    fields_done: int = 0
    fields_total: int = 0

class TurnResponse(SessionResponse):
    assistant_message: str
    reply: str | None = None
    changes: list[Change] = Field(default_factory=list)
    rejected: list[Rejection] = Field(default_factory=list)
    conflicts: list[Conflict] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

class PatchFieldRequest(BaseModel):
    value: Any = None
    confirmed: bool = True

class HealthResponse(BaseModel):
    status: str
    llm_provider: str
    llm_configured: bool
    llm_ready: bool = False
    detail: str | None = None
    version: str = "2.0.0"

class ErrorBody(BaseModel):
    code: str
    message: str
    request_id: str | None = None
class ErrorResponse(BaseModel):
    error: ErrorBody
