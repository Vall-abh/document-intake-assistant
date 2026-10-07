"""Data contracts: the structured state, the LLM turn contract and the public API models."""
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator

# Every collectable field, in the order the assistant asks for them.
FIELD_PATHS = (
    "full_name",
    "home_address",
    "covers_worldwide_assets",
    "has_children",
    "children_names",
    "executor.name",
    "executor.relationship",
    "specific_gifts",
    "additional_wishes",
)

# confirmed   = the user clearly stated it
# unconfirmed = hedged, inferred or not grounded in the user's words; must be confirmed
# skipped     = the user doesn't know / declined to say
FieldStatus = Literal["confirmed", "unconfirmed", "skipped"]


# ---------- Structured state (the application's source of truth) ----------
class Executor(BaseModel):
    name: Optional[str] = None
    relationship: Optional[str] = None


class WishesData(BaseModel):
    """None means unknown. For lists, [] means 'the user said there are none'."""

    full_name: Optional[str] = None
    home_address: Optional[str] = None
    covers_worldwide_assets: Optional[bool] = None
    has_children: Optional[bool] = None
    children_names: Optional[list[str]] = None
    executor: Executor = Field(default_factory=Executor)
    specific_gifts: Optional[list[str]] = None
    additional_wishes: Optional[list[str]] = None


class WishesState(BaseModel):
    data: WishesData = Field(default_factory=WishesData)
    status: dict[str, FieldStatus] = Field(default_factory=dict)


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


# ---------- LLM interaction contract ----------
class FieldUpdate(BaseModel):
    field: str  # validated against FIELD_PATHS in state.py so one bad update can't sink the turn
    value: Any  # required; null means "user doesn't know / declined"
    confirmed: bool = True
    evidence: Optional[str] = None  # optional verbatim quote supporting the proposed value


class ModelTurn(BaseModel):
    """Provider output contract. `reply` is the canonical field; acknowledgement is a compatibility alias."""
    updates: list[FieldUpdate] = Field(default_factory=list)
    reply: str = ""
    acknowledgement: str = ""

    @property
    def text(self) -> str:
        return self.reply or self.acknowledgement


class TurnRequest(BaseModel):
    """Everything an LLM client needs for one turn (provider-agnostic)."""

    state: Any
    missing_fields: list[str]
    unconfirmed_fields: list[str]
    pending_field: Optional[str]
    history: list[ChatMessage]
    user_message: str
    repair_hint: Optional[str] = None


# ---------- Public API ----------
class MessageIn(BaseModel):
    message: str = Field(min_length=1, max_length=2000)

    @field_validator("message")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("message must not be blank")
        return v


class Snapshot(BaseModel):
    session_id: str
    messages: list[ChatMessage]
    state: Any
    missing_fields: list[str]
    unconfirmed_fields: list[str]
    fields_done: int
    fields_total: int
    complete: bool
    document: str


class MessageOut(Snapshot):
    reply: str
    warnings: list[str] = Field(default_factory=list)
