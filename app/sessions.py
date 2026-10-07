"""Legacy in-process session facade retained for compatibility tests and examples.
The HTTP application uses app.storage.sessions.SQLiteSessionStore.
"""
from __future__ import annotations
import threading, uuid
from pydantic import BaseModel, Field
from app.schemas import ChatMessage
from app.state import WishesState

class Session(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    state: WishesState = Field(default_factory=WishesState)
    messages: list[ChatMessage] = Field(default_factory=list)
    lock: object = None
    def model_post_init(self, __context):
        object.__setattr__(self, "lock", threading.Lock())

class InMemorySessionStore:
    def __init__(self): self._data={}; self._lock=threading.Lock()
    def create(self):
        s=Session(); self._data[s.id]=s; return s
    def save(self,s): self._data[s.id]=s
    def get(self,sid): return self._data.get(sid)
