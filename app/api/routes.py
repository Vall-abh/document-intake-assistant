from __future__ import annotations

from fastapi import APIRouter, Request

from app.api.schemas import (ErrorResponse, FieldView, HealthResponse, MessageView, SendMessageRequest,
                             SessionResponse, StateView, TurnResponse)
from app.domain.state import WishesState
from app.services.conversation import ConversationService, TurnResult
from app.services.document import render_document
from app.storage.sessions import Session

router = APIRouter(prefix="/api")
ERRORS = {404: {"model": ErrorResponse}, 502: {"model": ErrorResponse}, 503: {"model": ErrorResponse}}


def _state_view(state: WishesState) -> StateView:
    return StateView(
        fields={k.value: FieldView(value=s.value, status=s.status, applicable=state.is_applicable(k))
                for k, s in state.slots.items()},
        structured=state.to_structured(),
        missing_fields=[k.value for k in state.missing()],
        unconfirmed_fields=[k.value for k in state.unconfirmed()],
        is_complete=state.is_complete(),
    )


def _session_fields(session: Session) -> dict:
    return dict(
        session_id=session.id,
        messages=[MessageView(role=t.role, content=t.content) for t in session.history],
        state=_state_view(session.state),
        document_markdown=render_document(session.state),
    )


def _turn_response(turn: TurnResult) -> TurnResponse:
    return TurnResponse(**_session_fields(turn.session), assistant_message=turn.assistant_message,
                        changes=turn.result.changes, rejected=turn.result.rejected,
                        conflicts=turn.result.conflicts)


def _service(request: Request) -> ConversationService:
    return request.app.state.service


@router.get("/health", response_model=HealthResponse)
def health(request: Request) -> HealthResponse:
    llm = request.app.state.llm
    return HealthResponse(status="ok", llm_provider=llm.name, llm_configured=llm.is_configured)


@router.post("/sessions", status_code=201, response_model=TurnResponse, responses=ERRORS)
def create_session(request: Request) -> TurnResponse:
    return _turn_response(_service(request).start_session())


@router.get("/sessions/{session_id}", response_model=SessionResponse, responses=ERRORS)
def get_session(session_id: str, request: Request) -> SessionResponse:
    return SessionResponse(**_session_fields(_service(request).get_session(session_id)))


@router.post("/sessions/{session_id}/messages", response_model=TurnResponse, responses=ERRORS)
def send_message(session_id: str, body: SendMessageRequest, request: Request) -> TurnResponse:
    return _turn_response(_service(request).handle_message(session_id, body.message))
