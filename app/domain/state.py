"""Structured state: the application's single source of truth (not the chat history)."""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class FieldKey(str, Enum):
    FULL_NAME = "full_name"
    HOME_ADDRESS = "home_address"
    COVERS_WORLDWIDE_ASSETS = "covers_worldwide_assets"
    HAS_CHILDREN = "has_children"
    CHILDREN_NAMES = "children_names"
    EXECUTOR_NAME = "executor_name"
    EXECUTOR_RELATIONSHIP = "executor_relationship"
    SPECIFIC_GIFTS = "specific_gifts"
    ADDITIONAL_WISHES = "additional_wishes"


class FieldStatus(str, Enum):
    UNKNOWN = "unknown"          # nothing captured yet
    UNCONFIRMED = "unconfirmed"  # captured but hedged / ungrounded: needs user confirmation
    CONFIRMED = "confirmed"      # stated clearly by the user


FIELD_ORDER: list[FieldKey] = list(FieldKey)

# "bool" | "str" | "str_list". For lists, an empty list is a valid confirmed answer ("none").
FIELD_KIND: dict[FieldKey, str] = {
    FieldKey.FULL_NAME: "str",
    FieldKey.HOME_ADDRESS: "str",
    FieldKey.COVERS_WORLDWIDE_ASSETS: "bool",
    FieldKey.HAS_CHILDREN: "bool",
    FieldKey.CHILDREN_NAMES: "str_list",
    FieldKey.EXECUTOR_NAME: "str",
    FieldKey.EXECUTOR_RELATIONSHIP: "str",
    FieldKey.SPECIFIC_GIFTS: "str_list",
    FieldKey.ADDITIONAL_WISHES: "str_list",
}

MAX_TEXT = 500
MAX_ITEMS = 20


def _clean_str(raw: Any) -> str:
    if not isinstance(raw, str):
        raise ValueError("expected a string")
    text = " ".join(raw.split())
    if not text:
        raise ValueError("value is empty")
    if len(text) > MAX_TEXT:
        raise ValueError(f"value longer than {MAX_TEXT} characters")
    return text


def coerce_value(key: FieldKey, raw: Any) -> Any:
    """Strictly validate a model-proposed value for a field. Raises ValueError."""
    kind = FIELD_KIND[key]
    if kind == "bool":
        if isinstance(raw, bool):
            return raw
        raise ValueError("expected a JSON boolean (true/false)")
    if kind == "str":
        return _clean_str(raw)
    if not isinstance(raw, list):
        raise ValueError("expected a list of strings")
    if len(raw) > MAX_ITEMS:
        raise ValueError(f"too many items (max {MAX_ITEMS})")
    return [_clean_str(item) for item in raw]


class FieldValue(BaseModel):
    value: Any = None
    status: FieldStatus = FieldStatus.UNKNOWN


class WishesState(BaseModel):
    slots: dict[FieldKey, FieldValue] = Field(
        default_factory=lambda: {k: FieldValue() for k in FieldKey}
    )

    def value(self, key: FieldKey) -> Any:
        return self.slots[key].value

    def status(self, key: FieldKey) -> FieldStatus:
        return self.slots[key].status

    def is_applicable(self, key: FieldKey) -> bool:
        if key == FieldKey.CHILDREN_NAMES:
            return self.value(FieldKey.HAS_CHILDREN) is True
        return True

    def missing(self) -> list[FieldKey]:
        return [k for k in FIELD_ORDER if self.is_applicable(k) and self.status(k) == FieldStatus.UNKNOWN]

    def unconfirmed(self) -> list[FieldKey]:
        return [k for k in FIELD_ORDER if self.is_applicable(k) and self.status(k) == FieldStatus.UNCONFIRMED]

    def is_complete(self) -> bool:
        return not self.missing() and not self.unconfirmed()

    def next_field(self) -> FieldKey | None:
        """What to ask about next: confirm hedged values first, then fill gaps in order."""
        pending = self.unconfirmed() or self.missing()
        return pending[0] if pending else None

    def snapshot(self) -> dict[str, Any]:
        return {"fields": {k.value: v.model_dump(mode="json") for k, v in self.slots.items()}}

    def to_structured(self) -> dict[str, Any]:
        """Nested view matching the brief's example (executor is an object, etc.)."""
        v = self.value
        out: dict[str, Any] = {
            "full_name": v(FieldKey.FULL_NAME),
            "home_address": v(FieldKey.HOME_ADDRESS),
            "covers_worldwide_assets": v(FieldKey.COVERS_WORLDWIDE_ASSETS),
            "has_children": v(FieldKey.HAS_CHILDREN),
        }
        if v(FieldKey.HAS_CHILDREN) is True:
            out["children"] = v(FieldKey.CHILDREN_NAMES)
        out["executor"] = {
            "name": v(FieldKey.EXECUTOR_NAME),
            "relationship": v(FieldKey.EXECUTOR_RELATIONSHIP),
        }
        out["specific_gifts"] = v(FieldKey.SPECIFIC_GIFTS)
        out["additional_wishes"] = v(FieldKey.ADDITIONAL_WISHES)
        return out
