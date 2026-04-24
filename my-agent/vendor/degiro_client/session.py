"""Session manager: holds current session, handles transparent relogin."""

from __future__ import annotations

import threading
from datetime import datetime, timedelta

from . import auth, storage
from .models import Credentials, SessionState

SESSION_MAX_IDLE = timedelta(minutes=25)


class SessionManager:
    def __init__(self) -> None:
        self._state: SessionState | None = storage.load_session()
        self._lock = threading.Lock()

    @property
    def state(self) -> SessionState | None:
        return self._state

    def require(self) -> SessionState:
        state = self._state
        if state is None or self._is_stale(state):
            return self._relogin()
        return state

    def invalidate(self) -> None:
        with self._lock:
            self._state = None
            storage.delete_session()

    def force_login(self, creds: Credentials) -> SessionState:
        with self._lock:
            state = auth.login(creds)
            self._persist(state)
            return state

    def touch(self) -> None:
        if self._state is None:
            return
        self._state.last_activity = datetime.utcnow()
        storage.save_session(self._state)

    @staticmethod
    def _is_stale(state: SessionState) -> bool:
        return datetime.utcnow() - state.last_activity > SESSION_MAX_IDLE

    def _relogin(self) -> SessionState:
        with self._lock:
            if self._state and not self._is_stale(self._state):
                return self._state
            creds = storage.load_credentials()
            if creds is None:
                raise RuntimeError(
                    "No stored credentials — configure Degiro options first"
                )
            state = auth.login(creds)
            self._persist(state)
            return state

    def _persist(self, state: SessionState) -> None:
        self._state = state
        storage.save_session(state)
