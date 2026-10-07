"""Orchestration of one conversational turn: LLM call -> parse -> validate -> apply -> reply."""
import json
import logging
import re
from dataclasses import dataclass, field

from pydantic import ValidationError

from app.llm.base import LLMClient
from app.schemas import ChatMessage, ModelTurn, TurnRequest
from app.sessions import Session
from app.state import (LABELS, apply_updates, get_value, missing_fields, pending_field,
                       unconfirmed_fields)

logger = logging.getLogger(__name__)
MAX_ATTEMPTS = 2
DEGRADED_REPLY = "Sorry, I had trouble understanding that. Could you rephrase it?"
GREETING = ("Hello! I'll help you draft a fictional Personal Wishes Document (a demo, not legal advice). "
            "What is your full name? Feel free to give me several details at once.")


class MalformedModelOutput(ValueError):
    pass


@dataclass
class TurnResult:
    reply: str
    warnings: list[str] = field(default_factory=list)


def parse_model_output(raw: str) -> ModelTurn:
    """Tolerate code fences / chatter around the JSON, but nothing that breaks the contract."""
    text = raw.strip()
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.S)
    if fenced:
        text = fenced.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise MalformedModelOutput("no JSON object found")
    try:
        payload = json.loads(text[start:end + 1])
        return ModelTurn.model_validate(payload)
    except json.JSONDecodeError as exc:
        raise MalformedModelOutput(f"invalid JSON ({exc.msg})") from exc
    except ValidationError as exc:
        raise MalformedModelOutput("JSON does not match the response contract") from exc


def question_for(state, path: str) -> str:
    if path == "executor.relationship":
        name = state.data.executor.name
        return f"How is {name} related to you?" if name else "How is your executor related to you?"
    return {
        "full_name": "What is your full name?",
        "home_address": "What is your home address?",
        "covers_worldwide_assets": "Should this document cover your assets worldwide?",
        "has_children": "Do you have any children?",
        "children_names": "What are your children's names?",
        "executor.name": "Who would you like to appoint as your executor?",
        "specific_gifts": "Is there anything you'd like to leave to specific people? Say \"none\" if not.",
        "additional_wishes": "Do you have any additional wishes to include? Say \"none\" if not.",
    }[path]


def fallback_reply(state) -> str:
    """Deterministic next question, used when the model's reply is empty or untrustworthy."""
    path = pending_field(state)
    if path is None:
        return "Thank you, I have everything I need. Your draft is ready; tell me if anything should change."
    if path in unconfirmed_fields(state):
        value = get_value(state.data, path)
        shown = ", ".join(value) if isinstance(value, list) else ("yes" if value is True else "no" if value is False else value)
        return f"Just to confirm, I have your {LABELS[path]} as: {shown or 'none'}. Is that right?"
    return question_for(state, path)


class ConversationService:
    def __init__(self, llm: LLMClient, history_window: int = 12):
        self._llm = llm
        self._window = history_window

    def handle_message(self, session: Session, text: str) -> TurnResult:
        state = session.state
        request = TurnRequest(
            state=state,
            missing_fields=missing_fields(state),
            unconfirmed_fields=unconfirmed_fields(state),
            pending_field=pending_field(state),
            history=session.messages[-self._window:],
            user_message=text,
        )
        turn, hint = None, None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            raw = self._llm.complete(request.model_copy(update={"repair_hint": hint}))
            try:
                turn = parse_model_output(raw)
                break
            except MalformedModelOutput as exc:
                logger.warning("Malformed model output (attempt %d): %s", attempt, exc)
                hint = f"Your previous reply was rejected ({exc}). Reply with ONLY the JSON object."

        if turn is None:  # state untouched; keep the conversation alive
            self._record(session, text, DEGRADED_REPLY)
            return TurnResult(DEGRADED_REPLY, ["The assistant's response could not be processed; nothing was changed."])

        result = apply_updates(state, turn.updates, text)
        session.state = result.state
        if result.clarifications:  # model's reply may assume rejected updates were applied
            reply = " ".join(result.clarifications)
        else:
            reply = turn.reply.strip() or fallback_reply(result.state)
        self._record(session, text, reply)
        return TurnResult(reply, result.warnings)

    @staticmethod
    def _record(session: Session, user_text: str, reply: str) -> None:
        session.messages.append(ChatMessage(role="user", content=user_text))
        session.messages.append(ChatMessage(role="assistant", content=reply))
