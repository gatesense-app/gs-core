"""
Resident reply timeouts -> escalation.

Without this, a resident who simply never replies leaves the visitor waiting at
the gate forever: the session sits at `awaiting_resident` and nothing ever moves
it. The intercom graph could only escalate when a resident *explicitly* deferred.
This closes the PRD's fallback chain — resident -> backup contact -> guard.

Design: a periodic sweep over the database, not an in-memory timer per session.
An in-process timer would be lost on the very restart we just made the
checkpointer survive, and would silently strand sessions. The sweep derives
everything from stored timestamps, so a restarted (or newly deployed) backend
picks up any timeout that came due while it was down.

"Last activity" is the newest conversation turn, falling back to the session's
entry_time. That means a resident asking a question, or the guard answering,
restarts the clock — we only escalate on real silence.

Scope: this is an internal job, not a user request, so it uses a system session
(RLS bypassed) to sweep every society at once. Nothing here is reachable from a
request path.
"""

import asyncio
import sys
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from backend import db_models as m
from backend.config import RESIDENT_TIMEOUT_MINUTES, TIMEOUT_SWEEP_SECONDS
from backend.deps import system_session
from backend.pipeline import serialize
from backend.realtime import manager
from backend.tools.intercom_tools import IntercomContext, escalate_to_backup_contact


def _now():
    return datetime.now(timezone.utc)


def sweep_once(timeout_minutes: int | None = None) -> list[str]:
    """
    Escalate every session whose resident has gone quiet past the timeout.

    Returns the ids escalated. Safe to call repeatedly: a session leaves
    `awaiting_resident` as soon as it is escalated, so it is never double-counted.
    """
    minutes = RESIDENT_TIMEOUT_MINUTES if timeout_minutes is None else timeout_minutes
    cutoff = _now() - timedelta(minutes=minutes)
    escalated: list[str] = []

    with system_session() as db:
        # Newest turn per session; sessions with no turns fall back to entry_time.
        last_turn = (
            select(
                m.ConversationLog.session_id.label("sid"),
                func.max(m.ConversationLog.created_at).label("last_at"),
            )
            .group_by(m.ConversationLog.session_id)
            .subquery()
        )
        rows = db.execute(
            select(m.VisitorSession)
            .outerjoin(last_turn, last_turn.c.sid == m.VisitorSession.id)
            .where(
                m.VisitorSession.status == "awaiting_resident",
                func.coalesce(last_turn.c.last_at, m.VisitorSession.entry_time) < cutoff,
            )
        ).scalars().all()

        for row in rows:
            ctx = IntercomContext(db, row.society_id, row.id)
            reason = f"Resident did not reply within {minutes} minutes"
            result = escalate_to_backup_contact(ctx, reason)

            row.status = "escalated"
            # Whoever actually picked it up: the backup contact if the flat has
            # one configured, otherwise the guard's default policy.
            row.resolved_by = "backup_contact" if result["backup_notified"] else "guard_default"
            row.resolved_at = _now()

            trace = list(row.decision_trace or [])
            trace.append({
                "agent": "intercom",
                "action": f"timeout: escalated to {row.resolved_by}",
                "reasoning": (
                    f"No reply from the resident for {minutes} minutes. Escalated to "
                    f"{row.resolved_by.replace('_', ' ')} so the visitor isn't left waiting."
                ),
                "tool_calls": ["escalate_to_backup_contact", "update_visitor_session"],
                "timestamp": _now().isoformat(),
            })
            row.decision_trace = trace
            db.flush()

            escalated.append(str(row.id))
            # Push the change to whoever is watching (guard dashboard, portal).
            manager.publish(str(row.society_id), {"type": "session_update", "session": serialize(row)})
            print(f"[timeouts] escalated {row.id} to {row.resolved_by} after {minutes}m of silence")

    return escalated


async def run_sweeper() -> None:
    """Background loop: sweep forever. Started from the app lifespan."""
    print(
        f"[timeouts] sweeper started: escalating after {RESIDENT_TIMEOUT_MINUTES}m "
        f"of silence, checked every {TIMEOUT_SWEEP_SECONDS}s"
    )
    while True:
        try:
            await asyncio.sleep(TIMEOUT_SWEEP_SECONDS)
            # Blocking DB work: keep it off the event loop.
            await asyncio.to_thread(sweep_once)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 - a bad sweep must not kill the loop
            print(f"[timeouts] sweep failed: {type(e).__name__}: {e}", file=sys.stderr)
