"""Application service: LLM extracts; deterministic code validates, transitions, persists and responds."""
from __future__ import annotations

import threading
import time
from collections import defaultdict

from pydantic import BaseModel, Field

from app.domain.questions import GREETING, LABELS, next_prompt, question_for
from app.domain.state import FieldKey, FieldStatus
from app.domain.updates import ApplyResult, FieldUpdate as DomainFieldUpdate, apply_updates
from app.errors import MalformedModelOutput
from app.llm.base import ChatTurn, LLMClient, LLMRequest, LLMTurnOutput
from app.llm.parsing import parse_llm_output
from app.storage.sessions import Session, SessionStore, StateEvent

MAX_ACK_CHARS = 300


class TurnResult(BaseModel):
    session: Session
    assistant_message: str
    result: ApplyResult = Field(default_factory=ApplyResult)
    retries: int = 0
    latency_ms: float = 0
    warnings: list[str] = Field(default_factory=list)


class ConversationService:
    def __init__(self, llm: LLMClient, store: SessionStore, *, max_retries: int = 1, max_history: int = 12):
        self.llm, self.store = llm, store
        self.max_retries, self.max_history = max_retries, max_history
        self._locks: dict[str, threading.Lock] = defaultdict(threading.Lock)
        self.metrics = {"turns": 0, "retries": 0, "errors": 0}

    def start_session(self) -> TurnResult:
        session = self.store.create()
        message = GREETING + question_for(FieldKey.FULL_NAME, session.state)
        session.history.append(ChatTurn(role="assistant", content=message))
        session.last_asked = FieldKey.FULL_NAME
        self.store.save(session)
        return TurnResult(session=session, assistant_message=message)

    def get_session(self, session_id: str) -> Session:
        return self.store.get(session_id)

    def handle_message(self, session_id: str, message: str) -> TurnResult:
        with self._locks[session_id]:
            started = time.perf_counter()
            session = self.store.get(session_id)
            try:
                output, retries = self._ask_model(session, message)
            except MalformedModelOutput as exc:
                self.metrics["errors"] += 1
                reply = "Sorry, I had trouble understanding that. Could you rephrase it?"
                session.history += [ChatTurn(role="user", content=message), ChatTurn(role="assistant", content=reply)]
                self.store.save(session)
                return TurnResult(session=session, assistant_message=reply, retries=self.max_retries,
                                  warnings=[exc.message])
            grounding = " ".join([t.content for t in session.history if t.role == "user"] + [message])
            domain_updates = [DomainFieldUpdate(field=u.field, action="clear" if u.value is None else "set", value=u.value, confidence="confirmed" if u.confirmed else "unconfirmed", evidence=u.evidence) for u in output.updates]
            new_state, result = apply_updates(session.state, domain_updates, grounding)
            reply = self._compose_reply(output, new_state, result)
            old_state = session.state
            session.state = new_state
            session.history += [ChatTurn(role="user", content=message), ChatTurn(role="assistant", content=reply)]
            session.last_asked = new_state.next_field()
            session.version += 1
            for change in result.changes:
                session.events.append(StateEvent(session_id=session.id, version=session.version,
                    field=change.field.value, old_value=change.old_value, new_value=change.new_value,
                    status=change.status.value, source="conversation"))
            self.store.save(session)
            latency = (time.perf_counter() - started) * 1000
            self.metrics["turns"] += 1
            self.metrics["retries"] += retries
            return TurnResult(session=session, assistant_message=reply, result=result, retries=retries, latency_ms=latency)

    def patch_field(self, session_id: str, field: str, value, confirmed: bool = True) -> TurnResult:
        with self._locks[session_id]:
            session = self.store.get(session_id)
            from app.domain.updates import FieldUpdate
            update = FieldUpdate(field=field, value=value, confidence="confirmed" if confirmed else "unconfirmed")
            new_state, result = apply_updates(session.state, [update], str(value))
            if not result.changes:
                return TurnResult(session=session, assistant_message="No change was made.", result=result)
            session.state = new_state
            session.version += 1
            for change in result.changes:
                session.events.append(StateEvent(session_id=session.id, version=session.version,
                    field=change.field.value, old_value=change.old_value, new_value=change.new_value,
                    status=change.status.value, source="direct_edit"))
            session.last_asked = new_state.next_field()
            self.store.save(session)
            return TurnResult(session=session, assistant_message="Updated.", result=result)

    def undo(self, session_id: str) -> Session:
        with self._locks[session_id]:
            return self.store.undo(session_id)

    def _ask_model(self, session: Session, message: str) -> tuple[LLMTurnOutput, int]:
        hint = None
        last_error = None
        for attempt in range(self.max_retries + 1):
            request = LLMRequest(state=session.state,
                missing_fields=[k.value for k in session.state.missing()],
                unconfirmed_fields=[k.value for k in session.state.unconfirmed()],
                pending_field=session.last_asked.value if session.last_asked else None,
                history=session.history[-self.max_history:], user_message=message, repair_hint=hint)
            raw = self.llm.complete(request)
            try:
                return parse_llm_output(raw), attempt
            except MalformedModelOutput as exc:
                last_error, hint = exc, f"Your previous output failed validation: {exc.message}. Return only the structured turn."
        self.metrics["errors"] += 1
        raise MalformedModelOutput("The assistant returned an unusable response. Nothing was changed; please try again.") from last_error

    @staticmethod
    def _compose_reply(output: LLMTurnOutput, state, result: ApplyResult) -> str:
        parts: list[str] = []
        if result.conflicts:
            parts.extend(c.message for c in result.conflicts)
            parts.append(next_prompt(state))
            return " ".join(parts)
        ack = output.text.strip()
        if ack and "?" not in ack and len(ack) <= MAX_ACK_CHARS:
            parts.append(ack)
        elif result.changes:
            parts.append("Thanks, noted.")
        elif not result.rejected:
            parts.append("I didn't catch any new details in that.")
        for rej in result.rejected:
            label = LABELS.get(FieldKey(rej.field), rej.field) if rej.field in FieldKey._value2member_map_ else rej.field
            parts.append(f"I couldn't use that for {label} ({rej.reason}).")
        parts.append(next_prompt(state))
        return " ".join(parts)
