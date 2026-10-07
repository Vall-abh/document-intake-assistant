"""Deterministic question wording. Which question is asked is decided by code, never by the LLM."""
from __future__ import annotations

from typing import Any

from app.domain.state import FieldKey, FieldStatus, WishesState

GREETING = ("Hi! I'll help you draft a fictional Personal Wishes Document "
            "(a demo only, not legal advice). ")

COMPLETION_MESSAGE = ("Thanks, I have everything I need. Your draft is shown in the preview. "
                      "Tell me if you'd like to change anything.")

LABELS: dict[FieldKey, str] = {
    FieldKey.FULL_NAME: "full name",
    FieldKey.HOME_ADDRESS: "home address",
    FieldKey.COVERS_WORLDWIDE_ASSETS: "worldwide assets answer",
    FieldKey.HAS_CHILDREN: "children answer",
    FieldKey.CHILDREN_NAMES: "children's names",
    FieldKey.EXECUTOR_NAME: "executor's name",
    FieldKey.EXECUTOR_RELATIONSHIP: "executor's relationship",
    FieldKey.SPECIFIC_GIFTS: "specific gifts",
    FieldKey.ADDITIONAL_WISHES: "additional wishes",
}


def display_value(value: Any) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, list):
        return ", ".join(value) if value else "none"
    return str(value)


def question_for(key: FieldKey, state: WishesState) -> str:
    if key == FieldKey.EXECUTOR_NAME and state.status(FieldKey.EXECUTOR_RELATIONSHIP) != FieldStatus.UNKNOWN:
        rel = state.value(FieldKey.EXECUTOR_RELATIONSHIP)
        return f"What is the name of your executor (your {rel})?"
    if key == FieldKey.EXECUTOR_RELATIONSHIP and state.status(FieldKey.EXECUTOR_NAME) != FieldStatus.UNKNOWN:
        return f"What is {state.value(FieldKey.EXECUTOR_NAME)}'s relationship to you?"
    return {
        FieldKey.FULL_NAME: "What is your full name?",
        FieldKey.HOME_ADDRESS: "What is your home address?",
        FieldKey.COVERS_WORLDWIDE_ASSETS: "Should this document cover your assets worldwide, or not?",
        FieldKey.HAS_CHILDREN: "Do you have any children?",
        FieldKey.CHILDREN_NAMES: "What are your children's names?",
        FieldKey.EXECUTOR_NAME: "Who would you like to appoint as your executor?",
        FieldKey.EXECUTOR_RELATIONSHIP: "What is your executor's relationship to you?",
        FieldKey.SPECIFIC_GIFTS: "Are there any specific gifts you'd like to leave to someone? (You can say 'none'.)",
        FieldKey.ADDITIONAL_WISHES: "Do you have any additional wishes to include? (You can say 'none'.)",
    }[key]


def confirm_question(key: FieldKey, state: WishesState) -> str:
    return (f"Please confirm your {LABELS[key]}: \"{display_value(state.value(key))}\". "
            "Is that correct?")


def next_prompt(state: WishesState) -> str:
    key = state.next_field()
    if key is None:
        return COMPLETION_MESSAGE
    if state.status(key) == FieldStatus.UNCONFIRMED:
        return confirm_question(key, state)
    return question_for(key, state)
