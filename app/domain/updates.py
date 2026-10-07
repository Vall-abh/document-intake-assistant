"""Validate model-proposed updates and apply them to the state.

The LLM never mutates state directly: it proposes `FieldUpdate`s, and this module
decides what is accepted, downgraded to "unconfirmed", rejected, or flagged as a conflict.
"""
from __future__ import annotations

import re
from typing import Any, Literal
from difflib import SequenceMatcher

from pydantic import BaseModel, Field

from app.domain.state import FieldKey, FieldStatus, FieldValue, WishesState, coerce_value

# Fields where a "confirmed" value must literally appear in the user's own words.
# Guards against the model inventing or "normalising" names/addresses.
GROUNDED_FIELDS = {
    FieldKey.FULL_NAME,
    FieldKey.HOME_ADDRESS,
    FieldKey.CHILDREN_NAMES,
    FieldKey.EXECUTOR_NAME,
}


class FieldUpdate(BaseModel):
    """One proposed change, as emitted by the model (deliberately lenient on `field`/`value`)."""

    field: str
    action: Literal["set", "clear"] = "set"
    value: Any = None
    confidence: Literal["confirmed", "unconfirmed"] = "confirmed"
    evidence: str | None = None


class Change(BaseModel):
    field: FieldKey
    old_value: Any = None
    new_value: Any = None
    status: FieldStatus
    note: str | None = None


class Rejection(BaseModel):
    field: str
    reason: str


class Conflict(BaseModel):
    field: FieldKey
    message: str


class ApplyResult(BaseModel):
    changes: list[Change] = Field(default_factory=list)
    rejected: list[Rejection] = Field(default_factory=list)
    conflicts: list[Conflict] = Field(default_factory=list)


def _norm(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text.lower()).split())


def _grounded_phrase(value: Any, haystack: str) -> bool:
    items = value if isinstance(value, list) else [value]
    hay = _norm(haystack)
    for item in items:
        needle = _norm(str(item))
        if not needle:
            return False
        if needle in hay:
            continue
        # Accept short paraphrases such as "watch to Tom" for "my watch to my son Tom".
        tokens = needle.split()
        if len(tokens) >= 2 and all(t in hay.split() for t in tokens):
            continue
        # Last-resort similarity for punctuation/inflection differences, never for a lone invented token.
        if len(tokens) >= 3 and SequenceMatcher(None, needle, hay).ratio() >= 0.55:
            continue
        return False
    return True

def _is_grounded(value: Any, haystack: str, evidence: str | None = None) -> bool:
    if evidence and _norm(evidence) not in _norm(haystack):
        return False
    return _grounded_phrase(value, haystack)


def _set(state: WishesState, key: FieldKey, value: Any, status: FieldStatus,
         result: ApplyResult, note: str | None = None) -> None:
    old = state.slots[key]
    if old.value == value and old.status == status:
        return
    state.slots[key] = FieldValue(value=value, status=status)
    result.changes.append(Change(field=key, old_value=old.value, new_value=value, status=status, note=note))


def apply_updates(
    state: WishesState, updates: list[FieldUpdate], grounding_text: str
) -> tuple[WishesState, ApplyResult]:
    """Return (new_state, result). The input state is never mutated."""
    new = state.model_copy(deep=True)
    result = ApplyResult()

    for upd in updates:
        aliases = {"executor.name": FieldKey.EXECUTOR_NAME, "executor.relationship": FieldKey.EXECUTOR_RELATIONSHIP}
        try:
            key = aliases[upd.field] if upd.field in aliases else FieldKey(upd.field)
        except ValueError:
            result.rejected.append(Rejection(field=upd.field, reason="unknown field"))
            continue

        if upd.action == "clear":
            if new.status(key) != FieldStatus.UNKNOWN:
                _set(new, key, None, FieldStatus.UNKNOWN, result, note="cleared by user")
                if key == FieldKey.HAS_CHILDREN:
                    _set(new, FieldKey.CHILDREN_NAMES, None, FieldStatus.UNKNOWN, result,
                         note="cleared because children answer was cleared")
            continue

        try:
            value = coerce_value(key, upd.value)
        except ValueError as exc:
            result.rejected.append(Rejection(field=key.value, reason=str(exc)))
            continue
        if key == FieldKey.CHILDREN_NAMES and not value:
            result.rejected.append(Rejection(field=key.value, reason="at least one name is required"))
            continue

        status = FieldStatus.CONFIRMED if upd.confidence == "confirmed" else FieldStatus.UNCONFIRMED
        note = None
        if key in GROUNDED_FIELDS and status == FieldStatus.CONFIRMED and not _is_grounded(value, grounding_text, upd.evidence):
            status, note = FieldStatus.UNCONFIRMED, "value not found in the user's own words"

        # Conflict: children named although the user said they have none. Ask, don't guess.
        if key == FieldKey.CHILDREN_NAMES and new.value(FieldKey.HAS_CHILDREN) is False:
            result.conflicts.append(Conflict(
                field=key,
                message="You earlier said you have no children, but you've now mentioned children's names.",
            ))
            continue

        _set(new, key, value, status, result, note)

        # Side effects that keep the state internally consistent.
        if key == FieldKey.HAS_CHILDREN and value is False:
            _set(new, FieldKey.CHILDREN_NAMES, None, FieldStatus.UNKNOWN, result,
                 note="cleared because the user has no children")
        if key == FieldKey.CHILDREN_NAMES and new.value(FieldKey.HAS_CHILDREN) is not True:
            _set(new, FieldKey.HAS_CHILDREN, True, status, result, note="derived from children's names")

    return new, result
