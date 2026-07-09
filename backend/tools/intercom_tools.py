"""
Tools the Intercom Conversational Agent (LangGraph) calls — now backed by
Postgres.

Same tenant-scoping contract as the gate/delivery tools: each tool takes an
IntercomContext (the request's RLS-scoped DB session + identifiers) as its first
argument. society_id comes from the context, never from graph state, and ctx.db
is the scoped session so every write lands in the caller's society.

The LangGraph nodes call these functions directly (there is no execute_tool
dispatch here — the graph itself is the control loop). ctx is injected into the
graph via config["configurable"]["ctx"] on each stream call; see intercom_agent.

Delivery is still "mock" in the sense that no real SMS/WhatsApp is sent — but the
notification is now recorded in notification_delivery_log so the audit trail is
real. Swap send_notification's body for Twilio / FCM in production.
"""

from datetime import datetime, timezone

from sqlalchemy import select

from backend import db_models as m


class IntercomContext:
    """Threaded through the graph so nodes/tools reach the tenant-scoped DB."""

    def __init__(self, db, society_id, session_uuid):
        self.db = db
        self.society_id = society_id
        self.session_uuid = session_uuid


def send_notification(ctx: IntercomContext, flat_number: str, resident_name: str, message: str) -> dict:
    """
    Deliver a message to the resident and record it. No real SMS is sent yet;
    we log an in-app notification so the delivery is auditable (RLS-scoped).
    """
    resident = ctx.db.execute(
        select(m.Resident).where(m.Resident.flat_number == flat_number)
    ).scalars().first()

    log = m.NotificationDeliveryLog(
        society_id=ctx.society_id,
        session_id=ctx.session_uuid,
        resident_id=resident.id if resident else None,
        channel="in_app",
        status="sent",
    )
    ctx.db.add(log)
    ctx.db.flush()
    print(f"\n[NOTIFY -> {resident_name} ({flat_number})]: {message}")
    return {"delivered": True, "sent_at": datetime.now(timezone.utc).isoformat(), "channel": "in_app"}


def log_conversation_turn(ctx: IntercomContext, turn_number: int, speaker: str, message: str) -> dict:
    """Append a turn to the normalized conversation_log table (RLS-scoped)."""
    turn = m.ConversationLog(
        society_id=ctx.society_id,
        session_id=ctx.session_uuid,
        turn_number=turn_number,
        speaker=speaker,
        message=message,
    )
    ctx.db.add(turn)
    ctx.db.flush()
    print(f"\n[CONV LOG] Turn {turn_number} ({speaker}): {message}")
    return {"logged": True, "turn_number": turn_number, "speaker": speaker}


def update_visitor_session(ctx: IntercomContext, status: str, resolved_by: str) -> dict:
    """Stamp the session row with the final intercom decision (RLS-scoped)."""
    row = ctx.db.get(m.VisitorSession, ctx.session_uuid)
    if row is not None:
        row.status = status
        row.resolved_by = resolved_by
        row.resolved_at = datetime.now(timezone.utc)
        ctx.db.flush()
    print(f"\n[DB] Session {ctx.session_uuid} -> status={status}, resolved_by={resolved_by}")
    return {"success": True, "session_id": str(ctx.session_uuid), "status": status}


def escalate_to_backup_contact(ctx: IntercomContext, reason: str) -> dict:
    """
    Escalate to the flat's backup contact: record an escalations row and a
    notification to the backup resident (if one is configured). RLS-scoped.
    """
    row = ctx.db.get(m.VisitorSession, ctx.session_uuid)
    backup = None
    if row is not None:
        resident = ctx.db.execute(
            select(m.Resident).where(m.Resident.flat_number == row.flat_number)
        ).scalars().first()
        if resident is not None and resident.backup_contact_id is not None:
            backup = ctx.db.get(m.Resident, resident.backup_contact_id)

    escalation = m.Escalation(
        society_id=ctx.society_id,
        session_id=ctx.session_uuid,
        reason=reason,
        escalated_to="backup_contact",
        status="open",
    )
    ctx.db.add(escalation)
    if backup is not None:
        ctx.db.add(m.NotificationDeliveryLog(
            society_id=ctx.society_id,
            session_id=ctx.session_uuid,
            resident_id=backup.id,
            channel="in_app",
            status="sent",
        ))
    ctx.db.flush()
    print(f"\n[ESCALATE] Session {ctx.session_uuid} -> backup contact | reason: {reason}")
    return {
        "escalated": True,
        "session_id": str(ctx.session_uuid),
        "escalated_to": "backup_contact",
        "backup_notified": backup is not None,
        "reason": reason,
    }
