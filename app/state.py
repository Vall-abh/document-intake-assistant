"""Pure state logic: validate model-proposed updates and apply them to the structured state.

Nothing here knows about LLMs or HTTP, which keeps it easy to test.
"""
from dataclasses import dataclass, field
import re

from app.schemas import FIELD_PATHS, FieldUpdate, WishesData, WishesState

LABELS = {
    "full_name": "full name",
    "home_address": "home address",
    "covers_worldwide_assets": "worldwide-assets preference",
    "has_children": "children",
    "children_names": "children's names",
    "executor.name": "executor's name",
    "executor.relationship": "executor's relationship to you",
    "specific_gifts": "specific gifts",
    "additional_wishes": "additional wishes",
}
BOOL_FIELDS = {"covers_worldwide_assets", "has_children"}
STRING_FIELDS = {"full_name", "home_address", "executor.name", "executor.relationship"}
MAX_TEXT = 300
MAX_ITEMS = 50
_ORDER = {p: i for i, p in enumerate(FIELD_PATHS)}


def new_state() -> WishesState:
    return WishesState()


def get_value(data: WishesData, path: str):
    obj = data
    for part in path.split("."):
        obj = getattr(obj, part)
    return obj


def set_value(data: WishesData, path: str, value) -> None:
    *parents, leaf = path.split(".")
    obj = data
    for part in parents:
        obj = getattr(obj, part)
    setattr(obj, leaf, value)


def _norm(text: str) -> str:
    return " ".join(text.casefold().split())


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.casefold())


def _appears_as_phrase(value: str, message: str) -> bool:
    """Allow harmless paraphrase/inserted words without accepting invented text.

    A proposed phrase is grounded when its normalized tokens occur in order in the
    user's message. This handles e.g. ``watch to Tom`` inside ``my watch to my son Tom``
    while still rejecting a name that never appeared.
    """
    value_tokens = _tokens(value)
    message_tokens = _tokens(message)
    if not value_tokens:
        return False
    pos = 0
    for token in value_tokens:
        try:
            pos = message_tokens.index(token, pos) + 1
        except ValueError:
            return False
    return True


# ---------- Validation ----------
def coerce_value(path: str, raw):
    """Validate a model-proposed value for a field. Raises ValueError if unusable."""
    if raw is None:
        return None
    if path in BOOL_FIELDS:
        if isinstance(raw, bool):
            return raw
        raise ValueError("expected true or false")
    if path in STRING_FIELDS:
        if not isinstance(raw, str):
            raise ValueError("expected text")
        text = " ".join(raw.split())
        if not text:
            raise ValueError("empty text")
        if len(text) > MAX_TEXT:
            raise ValueError("text too long")
        return text
    if not isinstance(raw, list) or not all(isinstance(i, str) for i in raw):
        raise ValueError("expected a list of text items")
    items: list[str] = []
    for item in raw:
        text = " ".join(item.split())
        if len(text) > MAX_TEXT:
            raise ValueError("list item too long")
        if text and text not in items:
            items.append(text)
    if len(items) > MAX_ITEMS:
        raise ValueError("too many items")
    return items


def _grounded(value, current, message_norm: str) -> bool:
    """Guard against invented facts: new text must appear in what the user actually said."""
    if isinstance(value, bool):
        return True
    if isinstance(value, str):
        return value == current or _norm(value) in message_norm or _appears_as_phrase(value, message_norm)
    existing = current or []
    return all(i in existing or _norm(i) in message_norm or _appears_as_phrase(i, message_norm) for i in value)


# ---------- Applying updates ----------
@dataclass
class ApplyResult:
    state: WishesState
    warnings: list[str] = field(default_factory=list)  # diagnostics
    clarifications: list[str] = field(default_factory=list)  # must be put to the user


def apply_updates(state: WishesState, updates: list[FieldUpdate], user_message: str) -> ApplyResult:
    """Return a NEW state with every valid update applied; invalid ones are rejected individually."""
    result = ApplyResult(state=state.model_copy(deep=True))
    message_norm = _norm(user_message)
    for upd in sorted(updates, key=lambda u: _ORDER.get(u.field, len(_ORDER))):
        path = upd.field
        if path not in _ORDER:
            result.warnings.append(f"Ignored unknown field '{path}'.")
            continue
        try:
            value = coerce_value(path, upd.value)
        except ValueError as exc:
            result.warnings.append(f"Rejected '{path}': {exc}.")
            result.clarifications.append(
                f"I couldn't record your {LABELS[path]}. Could you tell me again?"
            )
            continue
        confirmed = upd.confirmed
        if value is not None and confirmed and not _grounded(value, get_value(result.state.data, path), message_norm):
            confirmed = False
            result.warnings.append(f"'{path}' was not clearly stated by the user; marked unconfirmed.")
        _apply_one(result, path, value, confirmed)
    return result


def _apply_one(result: ApplyResult, path: str, value, confirmed: bool) -> None:
    state, data = result.state, result.state.data

    if path == "has_children" and value is False and data.children_names:
        if not confirmed:
            result.warnings.append("Conflict: 'has_children' false but children already recorded.")
            result.clarifications.append(
                "Earlier you gave me children's names, but now it sounds like you have none. Which is right?"
            )
            return
        data.children_names = None
        state.status.pop("children_names", None)
        result.warnings.append("Cleared children's names because the user now has no children.")

    if path == "has_children" and value is True and data.children_names == []:
        data.children_names = None
        state.status.pop("children_names", None)

    if path == "children_names" and value:
        if data.has_children is False and state.status.get("has_children") == "confirmed":
            result.warnings.append("Conflict: children named but 'has_children' is confirmed false.")
            result.clarifications.append(
                "You told me you have no children, but you've now named some. Do you have children?"
            )
            return
        if data.has_children is not True:  # naming children implies having them
            _set(state, "has_children", True, confirmed)

    if path == "children_names" and value == [] and data.has_children is True:
        result.warnings.append("Conflict: empty children list while 'has_children' is true.")
        result.clarifications.append(
            "You said you have children, so I need at least one name. Do you have children?"
        )
        return

    _set(state, path, value, confirmed)


def _set(state: WishesState, path: str, value, confirmed: bool) -> None:
    set_value(state.data, path, value)
    if value is None:
        state.status[path] = "skipped"
    else:
        state.status[path] = "confirmed" if confirmed else "unconfirmed"


# ---------- Derived views ----------
def required_paths(data: WishesData) -> list[str]:
    """Children's names only matter once we know the user has children."""
    return [p for p in FIELD_PATHS if p != "children_names" or data.has_children is True]


def missing_fields(state: WishesState) -> list[str]:
    return [
        p for p in required_paths(state.data)
        if get_value(state.data, p) is None and state.status.get(p) != "skipped"
    ]


def unconfirmed_fields(state: WishesState) -> list[str]:
    return [p for p in required_paths(state.data) if state.status.get(p) == "unconfirmed"]


def is_complete(state: WishesState) -> bool:
    return not missing_fields(state) and not unconfirmed_fields(state)


def pending_field(state: WishesState) -> str | None:
    """The field to deal with next: resolve unconfirmed answers right away, then ask for missing ones."""
    todo = unconfirmed_fields(state) + missing_fields(state)
    return todo[0] if todo else None


def progress(state: WishesState) -> tuple[int, int]:
    required = required_paths(state.data)
    done = sum(1 for p in required if state.status.get(p) in ("confirmed", "skipped"))
    return done, len(required)
