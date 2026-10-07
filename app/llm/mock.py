"""Deterministic rule-based stand-in for an LLM. Same contract as a real provider.

Good enough to demo the whole flow offline; it is NOT meant to be clever. Replace it by
setting ANTHROPIC_API_KEY (see README). Send the message "__malformed__" to simulate a broken model.
"""
from __future__ import annotations

import json
import re

from app.domain.state import FieldKey as K
from app.errors import LLMConfigError
from app.llm.base import LLMRequest

MALFORMED_TRIGGER = "__malformed__"
NAME = r"[A-Z][\w'’\-]+(?:\s+[A-Z][\w'’\-]+)*"
REL = ("brother|sister|mother|father|mum|mom|dad|son|daughter|wife|husband|partner|spouse|"
       "friend|cousin|uncle|aunt|niece|nephew|solicitor|lawyer|accountant|sibling")
HEDGE = re.compile(r"\b(maybe|perhaps|not sure|i think|probably|might)\b", re.I)
YES = re.compile(r"^\s*(yes|yeah|yep|correct|that'?s right|right|sure|ok|okay)\b", re.I)
NO = re.compile(r"^\s*(no|nope|nah|not really)\b", re.I)
NONE = re.compile(r"^\s*(no|none|nothing|nope|n/a)\b", re.I)
CLEAR_WORDS = {"gift": K.SPECIFIC_GIFTS, "gifts": K.SPECIFIC_GIFTS, "executor": K.EXECUTOR_NAME,
               "address": K.HOME_ADDRESS, "wishes": K.ADDITIONAL_WISHES}


def _names(text: str) -> list[str]:
    parts = [p.strip(" .") for p in re.split(r"\s*(?:,|&|\band\b)\s*", text.strip()) if p.strip(" .")]
    return parts if parts and all(re.fullmatch(NAME, p) for p in parts) else []


class MockLLM:
    name = "mock"
    is_configured = True

    def complete(self, request: LLMRequest) -> str:
        msg = request.user_message.strip()
        if msg == MALFORMED_TRIGGER:
            return "Sorry, here is some text {that is not JSON"
        fields = request.state_snapshot["fields"]
        asked = request.last_asked_field
        conf = "unconfirmed" if HEDGE.search(msg) else "confirmed"
        updates: list[dict] = []

        def add(key: K, value, confidence: str = conf, action: str = "set") -> None:
            updates.append({"field": key.value, "action": action, "value": value, "confidence": confidence})

        # Answering a confirmation question
        if asked in request.unconfirmed_fields:
            if YES.match(msg):
                add(K(asked), fields[asked]["value"], "confirmed")
                return self._out(updates)
            if NO.match(msg):
                add(K(asked), None, action="clear")
                return self._out(updates)

        if m := re.search(rf"(?i:my name is|call me|i am called|i'm called)\s+({NAME})", msg):
            add(K.FULL_NAME, m.group(1))
        elif asked == K.FULL_NAME.value and re.fullmatch(NAME, msg):
            add(K.FULL_NAME, msg)

        if m := re.search(r"(?i:i live (?:at|in)|my (?:home )?address is|i reside at)\s+(.+?)(?:\.(?:\s|$)|$)", msg):
            add(K.HOME_ADDRESS, m.group(1).strip())
        elif asked == K.HOME_ADDRESS.value and not updates:
            add(K.HOME_ADDRESS, msg.rstrip("."))

        wide = re.search(r"worldwide|world wide|globally|around the world|everywhere", msg, re.I)
        narrow = re.search(r"(?i:\bnot\b.*(worldwide|global)|only in|just in|\b\w+ only\b)", msg)
        if wide and not narrow:
            add(K.COVERS_WORLDWIDE_ASSETS, True)
        elif narrow:
            add(K.COVERS_WORLDWIDE_ASSETS, False)
        elif asked == K.COVERS_WORLDWIDE_ASSETS.value and (YES.match(msg) or NO.match(msg)):
            add(K.COVERS_WORLDWIDE_ASSETS, bool(YES.match(msg)))

        no_kids = re.search(r"(?i:no children|no kids|don't have (?:any )?(?:children|kids)|do not have (?:any )?(?:children|kids))", msg)
        if no_kids:
            add(K.HAS_CHILDREN, False)
        elif re.search(r"(?i:\bi have (?:\w+ )?(?:children|kids|child|daughters?|sons?)\b)", msg):
            add(K.HAS_CHILDREN, True)
        elif asked == K.HAS_CHILDREN.value and YES.match(msg):
            add(K.HAS_CHILDREN, True)
        elif asked == K.HAS_CHILDREN.value and NO.match(msg):
            add(K.HAS_CHILDREN, False)
        if m := re.search(rf"(?i:children|kids|child|son|daughter)\s*(?i:are|is|called|named|:)\s*((?:{NAME})(?:\s*(?:,|&|and)\s*{NAME})*)", msg):
            add(K.CHILDREN_NAMES, _names(m.group(1)))
        elif asked == K.CHILDREN_NAMES.value and _names(msg):
            add(K.CHILDREN_NAMES, _names(msg))

        in_exec = asked in (K.EXECUTOR_NAME.value, K.EXECUTOR_RELATIONSHIP.value) or re.search("executor", msg, re.I)
        if in_exec:
            if m := re.search(rf"(?i:my\s+({REL}))\s+({NAME})", msg):
                add(K.EXECUTOR_RELATIONSHIP, m.group(1).lower())
                add(K.EXECUTOR_NAME, m.group(2))
            elif m := re.search(rf"(?i:my\s+({REL}))\b", msg):
                add(K.EXECUTOR_RELATIONSHIP, m.group(1).lower())
            elif asked == K.EXECUTOR_NAME.value and (m := re.fullmatch(rf"(?:(?i:it'?s|maybe)\s+)?({NAME})\.?", msg)):
                add(K.EXECUTOR_NAME, m.group(1))
            elif asked == K.EXECUTOR_RELATIONSHIP.value and len(msg.split()) <= 4:
                add(K.EXECUTOR_RELATIONSHIP, re.sub(r"(?i)^(he|she|they)('s| is| are)?\s*(my )?|^my ", "", msg).rstrip(".").lower())

        if asked == K.SPECIFIC_GIFTS.value and not updates:
            add(K.SPECIFIC_GIFTS, [] if NONE.match(msg) else [p.strip() for p in re.split(r";|\n", msg) if p.strip()])
        elif m := re.search(r"(?i:i(?:'d| would)? (?:like to )?(?:leave|give))\s+(.+)", msg):
            add(K.SPECIFIC_GIFTS, [m.group(0).rstrip(".")])
        if asked == K.ADDITIONAL_WISHES.value and not updates:
            add(K.ADDITIONAL_WISHES, [] if NONE.match(msg) else [p.strip() for p in re.split(r";|\n", msg) if p.strip()])

        if m := re.search(r"(?i:(?:remove|clear|forget|delete))\s+(?:my |the )?(\w+)", msg):
            if (key := CLEAR_WORDS.get(m.group(1).lower())) and not updates:
                add(key, None, action="clear")
        return self._out(updates)

    @staticmethod
    def _out(updates: list[dict]) -> str:
        labels = ", ".join(dict.fromkeys(u["field"].replace("_", " ") for u in updates))
        ack = f"Noted: {labels}." if updates else ""
        return json.dumps({"updates": updates, "acknowledgement": ack})


class UnconfiguredLLM:
    """Used when a real provider is selected but its credentials are missing."""

    name = "unconfigured"
    is_configured = False

    def __init__(self, reason: str):
        self._reason = reason

    def complete(self, request: LLMRequest) -> str:
        raise LLMConfigError(self._reason)
