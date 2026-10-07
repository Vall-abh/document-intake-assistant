"""HTTP application layer with persistence, security controls and versioned APIs."""
from __future__ import annotations
import logging, time, uuid
from pathlib import Path
from threading import Lock
from fastapi import FastAPI, Request, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from app.api.schemas import *
from app.application import ConversationService
from app.config import Settings, load_settings
from app.domain.questions import GREETING
from app.domain.state import FieldKey, FieldStatus
from app.errors import AppError
from app.export import pdf_bytes, docx_bytes
from app.llm.base import LLMError
from app.llm.factory import build_llm_client
from app.services.document import render_document
from app.storage.sessions import InMemorySessionStore, SQLiteSessionStore, Session

logger=logging.getLogger(__name__)
STATIC_DIR=Path(__file__).resolve().parent.parent / "static"

class RateLimiter:
    def __init__(self, limit:int): self.limit=limit; self.data={}; self.lock=Lock()
    def allow(self, key:str)->bool:
        now=time.time()
        with self.lock:
            hits=[x for x in self.data.get(key,[]) if x>now-60]
            if len(hits)>=self.limit: self.data[key]=hits; return False
            hits.append(now); self.data[key]=hits
            if len(self.data)>5000:
                self.data={k:v for k,v in self.data.items() if v and v[-1]>now-60}
            return True

def _state_view(state):
    fields={k.value: FieldView(value=s.value,status=s.status,applicable=state.is_applicable(k)) for k,s in state.slots.items()}
    structured=state.to_structured()
    return StateView(fields=fields,structured=structured,missing_fields=[k.value for k in state.missing()],
                     unconfirmed_fields=[k.value for k in state.unconfirmed()],is_complete=state.is_complete(),
                     data=structured,status={k.value:s.status.value for k,s in state.slots.items()})

def _session_response(session:Session):
    return SessionResponse(session_id=session.id,messages=[MessageView(role=m.role,content=m.content) for m in session.history],
        state=_state_view(session.state),document_markdown=render_document(session.state),document=render_document(session.state),
        version=session.version,expires_at=session.expires_at,complete=session.state.is_complete(),
        fields_done=sum(1 for k in session.state.slots if session.state.status(k) == FieldStatus.CONFIRMED),
        fields_total=sum(1 for k in session.state.slots if session.state.is_applicable(k)))

def _turn_response(turn):
    snap=_session_response(turn.session)
    return TurnResponse(**snap.model_dump(),assistant_message=turn.assistant_message, reply=turn.assistant_message,
        changes=turn.result.changes,rejected=turn.result.rejected,conflicts=turn.result.conflicts,warnings=turn.warnings)

def create_app(settings:Settings|None=None,llm=None,store=None)->FastAPI:
    logging.basicConfig(level=logging.INFO)
    settings=settings or load_settings()
    app=FastAPI(title="Document Intake Assistant",version=settings.app_version)
    llm_error=None
    if llm is None:
        try: llm=build_llm_client(settings)
        except LLMError as exc: llm_error=exc; logger.error("LLM unavailable: %s", exc.message)
    sessions=store or SQLiteSessionStore(settings.database_url,settings.session_ttl_seconds)
    service=ConversationService(llm,sessions, max_history=settings.history_window) if llm else None
    limiter=RateLimiter(settings.rate_limit_per_minute)

    @app.middleware("http")
    async def security(request:Request,call_next):
        request_id=uuid.uuid4().hex[:16]; request.state.request_id=request_id
        if request.url.path.startswith("/api/") and not limiter.allow(request.client.host if request.client else "unknown"):
            return JSONResponse({"error":{"code":"rate_limited","message":"Too many requests. Please try again shortly.","request_id":request_id}}, status_code=429, headers={"Retry-After":"60","X-Request-ID":request_id})
        response=await call_next(request); response.headers["X-Request-ID"]=request_id
        response.headers["X-Content-Type-Options"]="nosniff"; response.headers["X-Frame-Options"]="DENY"; response.headers["Referrer-Policy"]="no-referrer"
        return response

    @app.exception_handler(AppError)
    async def app_error(request,exc):
        return JSONResponse({"error":{"code":exc.code,"message":exc.message,"request_id":getattr(request.state,'request_id',None)}}, status_code=exc.status_code)
    @app.exception_handler(LLMError)
    async def llm_exc(request,exc):
        return JSONResponse({"error":{"code":exc.code,"message":exc.message,"request_id":getattr(request.state,'request_id',None)}}, status_code=exc.status_code)
    @app.exception_handler(RequestValidationError)
    async def validation(request,exc):
        return JSONResponse({"error":{"code":"invalid_request","message":"Send valid request data.","request_id":getattr(request.state,'request_id',None)}}, status_code=422)

    def get_service():
        if service is None: raise llm_error
        return service

    @app.get("/api/health",response_model=HealthResponse)
    def health(): return {"status":"ok","llm_provider":settings.llm_provider,"llm_configured":service is not None,"llm_ready":service is not None,"detail":llm_error.message if llm_error else None,"version":settings.app_version}

    @app.post("/api/sessions",response_model=TurnResponse,status_code=201)
    @app.post("/api/v1/sessions",response_model=TurnResponse,status_code=201)
    def create_session():
        if service is not None:
            return _turn_response(service.start_session())
        from app.storage.sessions import Session as StoredSession
        session = sessions.create()
        message = GREETING + "What is your full name?"
        from app.llm.base import ChatTurn
        session.history.append(ChatTurn(role="assistant", content=message))
        session.last_asked = FieldKey.FULL_NAME
        sessions.save(session)
        from app.application import TurnResult
        return _turn_response(TurnResult(session=session, assistant_message=message))

    @app.get("/api/sessions/{session_id}",response_model=SessionResponse)
    @app.get("/api/v1/sessions/{session_id}",response_model=SessionResponse)
    def read_session(session_id:str): return _session_response(get_service().get_session(session_id))

    @app.post("/api/sessions/{session_id}/messages",response_model=TurnResponse)
    @app.post("/api/v1/sessions/{session_id}/messages",response_model=TurnResponse)
    def send_message(session_id:str,body:SendMessageRequest): return _turn_response(get_service().handle_message(session_id,body.message))

    @app.patch("/api/v1/sessions/{session_id}/fields/{field:path}",response_model=TurnResponse)
    def patch_field(session_id:str,field:str,body:PatchFieldRequest): return _turn_response(get_service().patch_field(session_id,field,body.value,body.confirmed))

    @app.post("/api/v1/sessions/{session_id}/undo",response_model=SessionResponse)
    def undo(session_id:str): return _session_response(get_service().undo(session_id))

    @app.get("/api/v1/sessions/{session_id}/history")
    def history(session_id:str): return [e.model_dump(mode="json") for e in sessions.list_events(session_id)]

    @app.get("/api/v1/sessions/{session_id}/export.pdf")
    def export_pdf(session_id:str): return Response(pdf_bytes(get_service().get_session(session_id)),media_type="application/pdf",headers={"Content-Disposition":"attachment; filename=personal-wishes-draft.pdf"})

    @app.get("/api/v1/sessions/{session_id}/export.docx")
    def export_docx(session_id:str): return Response(docx_bytes(get_service().get_session(session_id)),media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",headers={"Content-Disposition":"attachment; filename=personal-wishes-draft.docx"})

    @app.get("/api/v1/metrics")
    def metrics(): return service.metrics if service else {"turns":0,"retries":0,"errors":0}

    app.mount("/",StaticFiles(directory=STATIC_DIR,html=True),name="static")
    return app

app=create_app()
