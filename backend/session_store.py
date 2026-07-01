"""
In-memory session store. Swap for a Postgres-backed store in production.

Keyed by session_id. The pipeline reads/writes here so all three agents
share the same VisitorSession object.
"""

from backend.models import VisitorSession

_store: dict[str, VisitorSession] = {}


def create(session: VisitorSession) -> VisitorSession:
    _store[session.session_id] = session
    return session


def get(session_id: str) -> VisitorSession | None:
    return _store.get(session_id)


def update(session: VisitorSession) -> VisitorSession:
    _store[session.session_id] = session
    return session


def all_sessions() -> list[VisitorSession]:
    return list(_store.values())
