"""
Tools the Gate Visitor Agent can call — now backed by Postgres.

Each tool receives a GateContext (the request's tenant-scoped DB session +
identifiers) as its first argument, then the arguments Claude supplied. The
society context comes from the context object, NEVER from Claude's tool input —
the model only knows the visitor name/flat. Because ctx.db is the RLS-scoped
session, every query here is automatically restricted to the caller's society.
"""

import json
from datetime import datetime, timezone

from sqlalchemy import func, select

from backend import db_models as m


class GateContext:
    """Threaded through the agent loop so tools can reach the tenant-scoped DB."""

    def __init__(self, db, society_id, session_uuid):
        self.db = db
        self.society_id = society_id
        self.session_uuid = session_uuid


def lookup_visitor_history(ctx: GateContext, visitor_name: str, flat_number: str) -> dict:
    """Past visit records for this visitor within the society (RLS-scoped)."""
    visitor = ctx.db.execute(
        select(m.Visitor).where(func.lower(m.Visitor.name) == visitor_name.lower())
    ).scalars().first()

    if visitor is None:
        return {"found": False, "visit_count": 0, "last_visit_at": None, "notes": "No history"}

    return {
        "found": True,
        "visit_count": visitor.visit_count,
        "last_visit_at": visitor.last_visit_at.isoformat() if visitor.last_visit_at else None,
        "typical_hours": visitor.typical_hours,
        "is_known_service": visitor.is_known_service,
        "notes": visitor.notes or "",
    }


def get_resident_rules(ctx: GateContext, flat_number: str) -> dict:
    """Standing rules + delivery preferences for a flat."""
    resident = ctx.db.execute(
        select(m.Resident).where(m.Resident.flat_number == flat_number)
    ).scalars().first()

    if resident is None:
        return {
            "standing_rules": [],
            "delivery_preferences": {"auto_log_daytime": False, "notify_after_hours": True},
            "resident_name": "Unknown Resident",
        }

    return {
        "standing_rules": resident.standing_rules or [],
        "delivery_preferences": resident.delivery_preferences or {},
        "resident_name": resident.name,
    }


def get_flat_details(ctx: GateContext, flat_number: str) -> dict:
    """Contact info for the flat so downstream agents know who to reach."""
    resident = ctx.db.execute(
        select(m.Resident).where(m.Resident.flat_number == flat_number)
    ).scalars().first()

    if resident is None:
        return {"flat_number": flat_number, "resident_name": "Unknown", "contact": None}

    return {"flat_number": flat_number, "resident_name": resident.name, "contact": resident.phone}


def create_visitor_log(
    ctx: GateContext,
    session_id: str,
    visitor_name: str,
    flat_number: str,
    purpose: str,
    decision: str,
    reasoning: str,
) -> dict:
    """
    Record the agent's final decision on the session row. The pipeline already
    created the row (status=pending); here we stamp the decision the agent
    reached. The pipeline also mirrors this when it finalises the trace.
    """
    row = ctx.db.get(m.VisitorSession, ctx.session_uuid)
    if row is not None:
        row.status = decision
        row.resolved_by = "agent"
        row.resolved_at = datetime.now(timezone.utc)
        ctx.db.flush()
    return {"success": True, "session_id": session_id, "decision": decision}


def route_to_delivery_agent(ctx: GateContext, session_id: str, reason: str) -> dict:
    """Signal that the Delivery Triage Agent should handle this session."""
    return {"routed_to": "delivery_agent", "session_id": session_id, "reason": reason}


def route_to_intercom_agent(ctx: GateContext, session_id: str, reason: str) -> dict:
    """Signal that the Intercom Conversational Agent should handle this session."""
    return {"routed_to": "intercom_agent", "session_id": session_id, "reason": reason}


TOOL_REGISTRY = {
    "lookup_visitor_history": lookup_visitor_history,
    "get_resident_rules": get_resident_rules,
    "get_flat_details": get_flat_details,
    "create_visitor_log": create_visitor_log,
    "route_to_delivery_agent": route_to_delivery_agent,
    "route_to_intercom_agent": route_to_intercom_agent,
}


def execute_tool(tool_name: str, tool_input: dict, ctx: GateContext) -> str:
    """Dispatch a tool call to its DB-backed implementation, return JSON string."""
    fn = TOOL_REGISTRY.get(tool_name)
    if fn is None:
        return json.dumps({"error": f"Unknown tool: {tool_name}"})
    try:
        result = fn(ctx, **tool_input)
        return json.dumps(result, default=str)
    except Exception as e:  # surface tool failures to Claude rather than crashing the loop
        return json.dumps({"error": str(e)})
