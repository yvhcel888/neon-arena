"""Bearer-token HTTP sessions and bounded request history."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import secrets
import time
from typing import Any


RATE_LIMIT = 20
RATE_WINDOW_SECONDS = 1.0
LOBBY_IDLE_SECONDS = 30.0
ENDED_RETENTION_SECONDS = 600.0


@dataclass(eq=False)
class Session:
    token: str
    participant: Any
    created_at: float
    last_poll: float
    requests: deque[float] = field(default_factory=deque)
    ended_result: dict | None = None
    ended_match: dict | None = None
    ended_at: float | None = None


class SessionManager:
    def __init__(self):
        self._sessions: dict[str, Session] = {}

    def __len__(self) -> int:
        return len(self._sessions)

    def create(self, participant) -> Session:
        token = secrets.token_urlsafe(24)
        while token in self._sessions:
            token = secrets.token_urlsafe(24)
        now = time.monotonic()
        session = Session(
            token=token, participant=participant,
            created_at=now, last_poll=now,
        )
        participant.session = session
        self._sessions[token] = session
        return session

    def get(self, token: str | None) -> Session | None:
        if not isinstance(token, str):
            return None
        return self._sessions.get(token)

    def drop(self, token: str) -> None:
        self._sessions.pop(token, None)

    def allow_request(self, session: Session, now: float) -> bool:
        cutoff = now - RATE_WINDOW_SECONDS
        while session.requests and session.requests[0] <= cutoff:
            session.requests.popleft()
        if len(session.requests) >= RATE_LIMIT:
            return False
        session.requests.append(now)
        return True

    def cleanup(self, now: float) -> list[Session]:
        expired = []
        for session in self._sessions.values():
            participant = session.participant
            lobby_expired = (
                participant.state == "lobby"
                and (now - session.last_poll > LOBBY_IDLE_SECONDS)
            )
            ended_expired = (
                session.ended_result is not None
                and session.ended_at is not None
                and now - session.ended_at > ENDED_RETENTION_SECONDS
            )
            if lobby_expired or ended_expired:
                expired.append(session)
        return expired


__all__ = ["Session", "SessionManager"]
