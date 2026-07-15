"""
Durable checkpointing for the intercom graph.

The intercom agent pauses on `interrupt()` after messaging a resident and
resumes when they reply — possibly minutes later, in a different HTTP request.
That pause lives in a LangGraph checkpointer.

With the in-memory checkpointer this survived only as long as the process did:
restart (a deploy, a crash, a Railway sleep) and every in-flight conversation
was unresumable. The session row would sit at `awaiting_resident` forever and
the resident's reply would fail, with a visitor still standing at the gate.

So checkpoints go to Postgres, keyed by thread_id (the visitor_session id).

Two notes:

  * LangGraph owns these tables (`checkpoints`, `checkpoint_writes`,
    `checkpoint_blobs`) and they carry no society_id, so they are NOT under RLS
    like the rest of the schema. They hold conversation state, so treat them as
    sensitive. Access is only ever by thread_id — a session UUID the caller has
    already been authorized for (see main._assert_flat_access) — so this doesn't
    open a cross-tenant read path; it just isn't defended in depth the way the
    application tables are.
  * LangGraph needs psycopg 3 while SQLAlchemy uses psycopg2. Both are
    installed; this module is the only psycopg 3 user, with its own pool.
"""

import sys

from langgraph.checkpoint.memory import MemorySaver

from backend.config import DATABASE_URL

_checkpointer = None


def _postgres_checkpointer():
    """Build (and set up) the Postgres checkpointer, or return None if unavailable."""
    try:
        from langgraph.checkpoint.postgres import PostgresSaver
        from psycopg_pool import ConnectionPool
    except ImportError as e:  # dependency missing
        print(f"[checkpointer] Postgres checkpointer unavailable ({e}).", file=sys.stderr)
        return None

    try:
        pool = ConnectionPool(
            conninfo=DATABASE_URL,
            max_size=5,
            # LangGraph requires autocommit; without it .setup() and writes hang
            # inside an open transaction.
            kwargs={"autocommit": True, "prepare_threshold": 0},
            open=True,
        )
        saver = PostgresSaver(pool)
        saver.setup()  # idempotent: creates LangGraph's checkpoint tables
        return saver
    except Exception as e:  # noqa: BLE001 - fall back rather than fail to boot
        print(f"[checkpointer] Could not open Postgres checkpointer: {e}", file=sys.stderr)
        return None


def get_checkpointer():
    """
    The process-wide checkpointer. Postgres when reachable, otherwise in-memory
    so local/test runs still work — with a loud warning, because in-memory means
    a restart drops live conversations.
    """
    global _checkpointer
    if _checkpointer is None:
        _checkpointer = _postgres_checkpointer()
        if _checkpointer is None:
            print(
                "[checkpointer] WARNING: falling back to in-memory checkpoints. "
                "In-flight resident conversations will NOT survive a restart.",
                file=sys.stderr,
            )
            _checkpointer = MemorySaver()
    return _checkpointer
