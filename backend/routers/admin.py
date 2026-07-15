"""
Admin observability: notification health + the full per-session audit trail.

The agents already write escalations and notification_delivery_log rows as they
work, but nothing surfaced them. These endpoints expose that evidence to a
society_admin (RLS scopes every query to their own society).

The per-session audit is a separate endpoint rather than extra fields on
GET /sessions/{id} on purpose: serialize() is also used by the list endpoints,
so folding these joins in would turn the dashboard into an N+1.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select

from backend import db_models as m
from backend.deps import CurrentUser, get_db, require_role
from backend.routers.common import parse_uuid

router = APIRouter(prefix="/admin", tags=["admin"])

_admins = require_role("society_admin", "platform_admin")


@router.get("/notification-log")
def notification_log(
    limit: int = 100,
    _: CurrentUser = Depends(_admins),
    db=Depends(get_db),
):
    """
    Notification delivery health for this society: who we tried to reach, on
    what channel, and whether it landed. Joined to the session/resident so the
    row is readable without a second lookup.
    """
    rows = db.execute(
        select(m.NotificationDeliveryLog, m.VisitorSession, m.Resident)
        .outerjoin(m.VisitorSession, m.NotificationDeliveryLog.session_id == m.VisitorSession.id)
        .outerjoin(m.Resident, m.NotificationDeliveryLog.resident_id == m.Resident.id)
        .order_by(m.NotificationDeliveryLog.created_at.desc())
        .limit(min(limit, 500))
    ).all()

    # Status mix across the whole society, not just the page above.
    summary = {
        status: count
        for status, count in db.execute(
            select(m.NotificationDeliveryLog.status, func.count(m.NotificationDeliveryLog.id))
            .group_by(m.NotificationDeliveryLog.status)
        ).all()
    }

    return {
        "summary": summary,
        "total": sum(summary.values()),
        "notifications": [
            {
                "id": str(n.id),
                "session_id": str(n.session_id) if n.session_id else None,
                "visitor_name": sess.visitor_name if sess else None,
                "flat_number": sess.flat_number if sess else (res.flat_number if res else None),
                "resident_name": res.name if res else None,
                "channel": n.channel,
                "status": n.status,
                "created_at": n.created_at.isoformat() if n.created_at else None,
            }
            for n, sess, res in rows
        ],
    }


@router.get("/sessions/{session_id}/audit")
def session_audit(
    session_id: str,
    _: CurrentUser = Depends(_admins),
    db=Depends(get_db),
):
    """
    The evidence behind one session: escalations raised, notifications sent, and
    the normalized conversation turns. Complements the decision_trace already on
    the session row.
    """
    sid = parse_uuid(session_id)
    row = db.get(m.VisitorSession, sid)
    if row is None:  # RLS hides other societies' sessions -> looks like 404
        raise HTTPException(404, "Session not found")

    escalations = db.execute(
        select(m.Escalation)
        .where(m.Escalation.session_id == sid)
        .order_by(m.Escalation.created_at)
    ).scalars().all()

    notifications = db.execute(
        select(m.NotificationDeliveryLog, m.Resident)
        .outerjoin(m.Resident, m.NotificationDeliveryLog.resident_id == m.Resident.id)
        .where(m.NotificationDeliveryLog.session_id == sid)
        .order_by(m.NotificationDeliveryLog.created_at)
    ).all()

    turns = db.execute(
        select(m.ConversationLog)
        .where(m.ConversationLog.session_id == sid)
        .order_by(m.ConversationLog.turn_number)
    ).scalars().all()

    return {
        "session_id": session_id,
        "escalations": [
            {
                "id": str(e.id),
                "reason": e.reason,
                "escalated_to": e.escalated_to,
                "status": e.status,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in escalations
        ],
        "notifications": [
            {
                "id": str(n.id),
                "resident_name": res.name if res else None,
                "flat_number": res.flat_number if res else None,
                "channel": n.channel,
                "status": n.status,
                "created_at": n.created_at.isoformat() if n.created_at else None,
            }
            for n, res in notifications
        ],
        "conversation_log": [
            {
                "turn_number": t.turn_number,
                "speaker": t.speaker,
                "message": t.message,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
            for t in turns
        ],
    }
