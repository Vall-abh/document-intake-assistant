"""Persistent SQLite session repository with versioned state history."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Protocol

from pydantic import BaseModel, Field

from app.domain.state import FieldKey, WishesState
from app.errors import SessionNotFound
from app.llm.base import ChatTurn


def utc_ts() -> float:
    return time.time()


class StateEvent(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    session_id: str
    version: int
    field: str
    old_value: object = None
    new_value: object = None
    status: str
    source: str = "conversation"
    created_at: float = Field(default_factory=utc_ts)


class Session(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    state: WishesState = Field(default_factory=WishesState)
    history: list[ChatTurn] = Field(default_factory=list)
    last_asked: FieldKey | None = None
    version: int = 0
    created_at: float = Field(default_factory=utc_ts)
    updated_at: float = Field(default_factory=utc_ts)
    expires_at: float | None = None
    events: list[StateEvent] = Field(default_factory=list)

    @property
    def messages(self):
        return self.history


class SessionStore(Protocol):
    def save(self, session: Session) -> None: ...
    def get(self, session_id: str) -> Session: ...
    def create(self) -> Session: ...
    def list_events(self, session_id: str) -> list[StateEvent]: ...


class SQLiteSessionStore:
    def __init__(self, path: str = "data/sessions.db", ttl_seconds: int = 86400):
        self.path = path
        self.ttl_seconds = ttl_seconds
        self._lock = threading.RLock()
        if path != ":memory:":
            import os
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self._init_db()

    def _connect(self):
        conn = sqlite3.connect(self.path, timeout=10, check_same_thread=False, uri=self.path.startswith("file:"))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                state_json TEXT NOT NULL,
                history_json TEXT NOT NULL,
                last_asked TEXT,
                version INTEGER NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                expires_at REAL
            );
            CREATE TABLE IF NOT EXISTS state_events (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                field TEXT NOT NULL,
                old_value TEXT,
                new_value TEXT,
                status TEXT NOT NULL,
                source TEXT NOT NULL,
                created_at REAL NOT NULL,
                FOREIGN KEY(session_id) REFERENCES sessions(id)
            );
            CREATE INDEX IF NOT EXISTS idx_events_session ON state_events(session_id, version);
            """)

    def create(self) -> Session:
        session = Session(expires_at=utc_ts() + self.ttl_seconds)
        self.save(session)
        return session

    def save(self, session: Session) -> None:
        with self._lock, self._connect() as db:
            now = utc_ts()
            session.updated_at = now
            session.expires_at = now + self.ttl_seconds
            db.execute("""INSERT INTO sessions(id,state_json,history_json,last_asked,version,created_at,updated_at,expires_at)
                         VALUES(?,?,?,?,?,?,?,?)
                         ON CONFLICT(id) DO UPDATE SET state_json=excluded.state_json, history_json=excluded.history_json,
                         last_asked=excluded.last_asked, version=excluded.version, updated_at=excluded.updated_at,
                         expires_at=excluded.expires_at""",
                       (session.id, session.state.model_dump_json(),
                        json.dumps([m.model_dump(mode="json") for m in session.history]),
                        session.last_asked.value if session.last_asked else None, session.version,
                        session.created_at, session.updated_at, session.expires_at))
            for event in session.events:
                db.execute("""INSERT OR IGNORE INTO state_events
                    (id,session_id,version,field,old_value,new_value,status,source,created_at)
                    VALUES(?,?,?,?,?,?,?,?,?)""",
                           (event.id, event.session_id, event.version, event.field,
                            json.dumps(event.old_value), json.dumps(event.new_value), event.status,
                            event.source, event.created_at))
            session.events.clear()

    def get(self, session_id: str) -> Session:
        with self._lock, self._connect() as db:
            row = db.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
            if not row or (row["expires_at"] is not None and row["expires_at"] < utc_ts()):
                if row:
                    db.execute("DELETE FROM sessions WHERE id=?", (session_id,))
                raise SessionNotFound("Session not found or expired. Start a new session.")
            state = WishesState.model_validate_json(row["state_json"])
            from app.llm.base import ChatTurn
            history = [ChatTurn.model_validate(x) for x in json.loads(row["history_json"])]
            events = self.list_events(session_id)
            return Session(id=row["id"], state=state, history=history,
                           last_asked=FieldKey(row["last_asked"]) if row["last_asked"] else None,
                           version=row["version"], created_at=row["created_at"],
                           updated_at=row["updated_at"], expires_at=row["expires_at"], events=events)

    def list_events(self, session_id: str) -> list[StateEvent]:
        with self._connect() as db:
            rows = db.execute("SELECT * FROM state_events WHERE session_id=? ORDER BY version,id", (session_id,)).fetchall()
        return [StateEvent(id=r["id"], session_id=r["session_id"], version=r["version"], field=r["field"],
                           old_value=json.loads(r["old_value"]), new_value=json.loads(r["new_value"]),
                           status=r["status"], source=r["source"], created_at=r["created_at"]) for r in rows]

    def undo(self, session_id: str) -> Session:
        with self._lock:
            session = self.get(session_id)
            events = self.list_events(session_id)
            if not events:
                return session
            target_version = max(0, session.version - 1)
            replay = WishesState()
            for e in events:
                if e.version > target_version:
                    break
                try:
                    key = FieldKey(e.field)
                    from app.domain.state import FieldValue, FieldStatus
                    replay.slots[key] = FieldValue(value=e.new_value, status=FieldStatus(e.status))
                except Exception:
                    continue
            session.state = replay
            session.version = target_version
            session.history = session.history[:-2] if len(session.history) >= 2 else session.history
            session.last_asked = session.state.next_field()
            self.save(session)
            return session


class InMemorySessionStore(SQLiteSessionStore):
    """Test-friendly SQLite store backed by a temporary file so connections can be reopened."""
    def __init__(self):
        import tempfile
        self._tmp = tempfile.NamedTemporaryFile(prefix="document-intake-", suffix=".db", delete=False)
        self._tmp.close()
        super().__init__(self._tmp.name)
