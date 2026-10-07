"""Deterministic, offline stand-in for a real model.

It implements the same contract as a real provider: TurnRequest in, raw JSON text out
(`{"updates": [...], "reply": ""}`). It returns an empty reply, so the application's
deterministic fallback question is used. It is rule-based and deliberately simple.
"""
import json
import re

from app.schemas import FIELD_PATHS, TurnRequest
from app.domain.state import FieldKey



REL = r"(brother|sister|wife|husband|partner|son|daughter|mother|father|friend|cousin|uncle|aunt|nephew|niece|solicitor|lawyer|accountant)"
NAME = r"([A-Z][\w'’-]*(?:\s+[A-Z][\w'’-]*){0,3})"
YES = re.compile(r"^\s*(yes|yeah|yep|y|correct|right|that'?s (?:right|correct)|sure|ok(?:ay)?)\b", re.I)
NO = re.compile(r"^\s*(no|nope|nah|none|nothing|not really)\b", re.I)
HEDGE = re.compile(r"\b(maybe|not sure|i think|probably|i guess|perhaps)\b", re.I)
SKIP = re.compile(r"\b(i don'?t know|skip|prefer not to say|rather not say)\b", re.I)
WORLD_T = re.compile(r"\b(worldwide|world[- ]wide|all over the world|around the world|globally|internationally|abroad)\b", re.I)
WORLD_F = re.compile(r"\b(only|just)\b.*\b(uk|england|country|here|domestic|local)\b|\bno (?:overseas|foreign|international)\b|\bnot worldwide\b", re.I)
NO_KIDS = re.compile(r"\b(no (?:children|kids)|(?:don'?t|do not) have (?:any )?(?:children|kids)|childless)\b", re.I)
HAS_KIDS = re.compile(r"\b(?:i have|we have)\s+(?:\w+\s+)?(?:children|kids|sons?|daughters?)\b", re.I)
KID_NAMES = re.compile(r"(?i:(?:children|kids)(?: are| names are|:)|named|called)\s+(.+)")
ADDRESS = re.compile(r"(?i:i live (?:at|in)|my (?:home )?address is|i reside (?:at|in)|living (?:at|in))\s+(.+)")
PERSON_NAME = re.compile(r"(?i:my (?:full )?name is|i am|i'm|call me)\s+" + NAME)
EXEC_A = re.compile(r"(?i:my\s+" + REL + r")\s+" + NAME)
EXEC_B = re.compile(NAME + r"\s+(?i:is\s+my\s+" + REL + r")")
EXEC_C = re.compile(r"(?i:executor is|appoint|choose)\s+" + NAME)
REL_ONLY = re.compile(r"(?i:my\s+)?" + REL, re.I)
GIFT = re.compile(r"(?i:\b(?:leave|give|gift|bequeath)\b)\s+(.+?)\s*\.?$")
WISH = re.compile(r"(?i:i wish|my wish is|i would like (?:that|my))\s+(.+?)\s*\.?$")


def _names(text: str) -> list[str] | None:
    parts = [p.strip(" .") for p in re.split(r",|\band\b|&", text) if p.strip(" .")]
    return parts if parts and all(re.fullmatch(NAME, p) for p in parts) else None


class MockLLMClient:
    name = "mock"

    def complete(self, request: TurnRequest) -> str:
        return json.dumps({"updates": self._interpret(request), "reply": ""})

    def _interpret(self, r: TurnRequest) -> list[dict]:
        msg, data, pending = r.user_message.strip(), r.state, r.pending_field
        hedged = bool(HEDGE.search(msg))
        ups: list[dict] = []

        def add(field: str, value) -> None:
            ups.append({"field": field, "value": value, "confirmed": not hedged})

        if pending in r.unconfirmed_fields and YES.match(msg):
            return [{"field": pending, "value": data.slots[FieldKey(pending)].value, "confirmed": True}]
        if SKIP.search(msg) and pending in FIELD_PATHS:
            return [{"field": pending, "value": None, "confirmed": True}]

        if m := PERSON_NAME.search(msg):
            add("full_name", m.group(1))
        elif pending == "full_name" and re.fullmatch(NAME, msg.rstrip(".")):
            add("full_name", msg.rstrip("."))

        if m := ADDRESS.search(msg):
            add("home_address", m.group(1).strip(" ."))
        elif pending == "home_address" and any(c.isdigit() for c in msg):
            add("home_address", msg.strip(" ."))

        if WORLD_F.search(msg):
            add("covers_worldwide_assets", False)
        elif WORLD_T.search(msg):
            add("covers_worldwide_assets", True)
        elif pending == "covers_worldwide_assets" and (YES.match(msg) or NO.match(msg)):
            add("covers_worldwide_assets", bool(YES.match(msg)))

        if NO_KIDS.search(msg):
            add("has_children", False)
        elif HAS_KIDS.search(msg):
            add("has_children", True)
        elif pending == "has_children" and (YES.match(msg) or NO.match(msg)):
            add("has_children", bool(YES.match(msg)))
        if m := KID_NAMES.search(msg):
            if (names := _names(m.group(1))):
                add("children_names", names)
        elif pending == "children_names" and (names := _names(msg)):
            add("children_names", names)

        if pending and pending.startswith("executor") or "executor" in msg.lower():
            if m := EXEC_A.search(msg):
                add("executor.relationship", m.group(1).lower())
                add("executor.name", m.group(2))
            elif m := EXEC_B.search(msg):
                add("executor.name", m.group(1))
                add("executor.relationship", m.group(2).lower())
            elif m := EXEC_C.search(msg):
                add("executor.name", m.group(1))
            elif pending == "executor.name" and re.fullmatch(NAME, msg.rstrip(".")):
                add("executor.name", msg.rstrip("."))
            elif pending == "executor.relationship" and (m := REL_ONLY.search(msg)):
                add("executor.relationship", m.group(1).lower())

        existing_gifts = list(data.value(FieldKey.SPECIFIC_GIFTS) or [])
        if pending == "specific_gifts" and NO.match(msg):
            add("specific_gifts", [])
        elif (m := GIFT.search(msg)) and " to " in m.group(1):
            add("specific_gifts", existing_gifts + [m.group(1)])
        elif pending == "specific_gifts" and " to " in msg:
            add("specific_gifts", existing_gifts + [msg.strip(" .")])

        existing_wishes = list(data.value(FieldKey.ADDITIONAL_WISHES) or [])
        if pending == "additional_wishes" and NO.match(msg):
            add("additional_wishes", [])
        elif m := WISH.search(msg):
            add("additional_wishes", existing_wishes + [m.group(1)])
        elif pending == "additional_wishes" and not YES.match(msg):
            add("additional_wishes", existing_wishes + [msg.strip()])
        return ups
