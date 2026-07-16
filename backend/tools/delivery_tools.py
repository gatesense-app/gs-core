"""
Tools the Delivery Triage Agent can call — now backed by Postgres.

Mirrors gate_tools: each tool receives a DeliveryContext (the request's
tenant-scoped DB session + identifiers) as its first argument, then the
arguments Claude supplied. society_id comes from the context, NEVER from
Claude's tool input, and ctx.db is the RLS-scoped session, so every query
here is automatically restricted to the caller's society.

Data sources:
  - classify_delivery_service   → a curated known-service list, cross-checked
                                   against this society's known-service visitors
  - get_delivery_pattern_history→ visitor_sessions (real runtime deliveries) +
                                   the society's known delivery visitors
  - get_resident_delivery_preferences → the flat's preferences, else the
                                   primary contact's (tools/resolve.py)
  - flag_anomaly                → inserts an escalations row
  - create_visitor_log          → stamps the session row auto_approved
"""

import json
from datetime import datetime, timezone

from sqlalchemy import func, select

from backend import db_models as m
from backend.tools import resolve

# Domain knowledge (not tenant data): common Indian delivery brands. Used as a
# first-pass classifier; anything not here is cross-checked against the society's
# own known-service visitors before being declared unknown.
_KNOWN_SERVICES = [
    "swiggy", "zomato", "blinkit", "zepto", "bigbasket",
    "amazon", "flipkart", "meesho", "myntra", "nykaa",
    "dunzo", "porter", "delhivery", "bluedart", "dtdc",
    "ecom express", "xpressbees", "shadowfax",
]


class DeliveryContext:
    """Threaded through the delivery agent loop so tools reach the scoped DB."""

    def __init__(self, db, society_id, session_uuid):
        self.db = db
        self.society_id = society_id
        self.session_uuid = session_uuid


def classify_delivery_service(ctx: DeliveryContext, purpose_detail: str) -> dict:
    """
    Decide whether purpose_detail names a known delivery service. Checks the
    curated brand list first, then this society's known-service visitors
    (RLS-scoped) so tenant-specific vendors also register as known.
    """
    detail_lower = purpose_detail.lower()

    curated = [s for s in _KNOWN_SERVICES if s in detail_lower]
    if curated:
        return {"is_known_service": True, "matched_service": curated[0], "confidence": "high"}

    # Fall back to services this society has actually seen and marked as known.
    known_visitors = ctx.db.execute(
        select(m.Visitor.name).where(m.Visitor.is_known_service.is_(True))
    ).scalars().all()
    tenant_match = next((v for v in known_visitors if v and v.lower() in detail_lower), None)
    if tenant_match:
        return {"is_known_service": True, "matched_service": tenant_match, "confidence": "medium"}

    return {
        "is_known_service": False,
        "matched_service": None,
        "confidence": "low",
        "note": "Service name not recognized — could be a local courier or unknown vendor",
    }


def get_delivery_pattern_history(ctx: DeliveryContext, flat_number: str) -> dict:
    """
    Delivery pattern for this flat, drawn from real data (RLS-scoped):
      - counts of prior delivery sessions for the flat + last one
      - typical hours / common services from the society's known delivery visitors
    """
    stats = ctx.db.execute(
        select(
            func.count(m.VisitorSession.id),
            func.max(m.VisitorSession.entry_time),
        ).where(
            m.VisitorSession.flat_number == flat_number,
            m.VisitorSession.purpose == "delivery",
        )
    ).one()
    delivery_count, last_delivery_at = stats

    known_delivery_visitors = ctx.db.execute(
        select(m.Visitor)
        .where(m.Visitor.visitor_type == "delivery", m.Visitor.is_known_service.is_(True))
        .order_by(m.Visitor.visit_count.desc())
    ).scalars().all()

    common_services = [v.name for v in known_delivery_visitors[:5]]

    # Union the known services' typical windows into one envelope for the society.
    starts = [v.typical_hours["start"] for v in known_delivery_visitors if v.typical_hours and v.typical_hours.get("start")]
    ends = [v.typical_hours["end"] for v in known_delivery_visitors if v.typical_hours and v.typical_hours.get("end")]
    typical_hours = {"start": min(starts), "end": max(ends)} if starts and ends else None

    return {
        "flat_number": flat_number,
        "prior_delivery_count": delivery_count,
        "last_delivery_at": last_delivery_at.isoformat() if last_delivery_at else None,
        "typical_hours": typical_hours,
        "most_common_services": common_services,
        "note": None if delivery_count else "No prior delivery sessions recorded for this flat",
    }


def get_resident_delivery_preferences(ctx: DeliveryContext, flat_number: str) -> dict:
    """
    Delivery preferences for this flat (E6-S3: per flat, not per resident).

    The flat's own preferences win when set; otherwise the primary contact's
    apply — the same person the gate and intercom legs resolve to.
    """
    resolved = resolve.resolve_rules(ctx.db, ctx.society_id, flat_number)
    resident = resolved["resident"]

    if resident is None:
        return {
            "found": False,
            "auto_log_daytime": False,
            "notify_after_hours": True,
            "after_hours_threshold": "21:00",
        }

    prefs = resolved["delivery_preferences"] or {}
    return {
        "found": True,
        "resident_name": resident.name,
        "auto_log_daytime": prefs.get("auto_log_daytime", False),
        "notify_after_hours": prefs.get("notify_after_hours", True),
        "after_hours_threshold": prefs.get("after_hours_threshold", "21:00"),
    }


def flag_anomaly(ctx: DeliveryContext, session_id: str, anomaly_type: str, details: str) -> dict:
    """
    Record an anomaly as an escalations row (RLS-checked against the society).
    The pipeline decides the session's status; this tool only files the flag.
    """
    escalated_to = "backup_contact" if anomaly_type in ("suspicious", "unusual_pattern") else "guard_default"
    escalation = m.Escalation(
        society_id=ctx.society_id,
        session_id=ctx.session_uuid,
        reason=f"[{anomaly_type}] {details}",
        escalated_to=escalated_to,
        status="open",
    )
    ctx.db.add(escalation)
    ctx.db.flush()
    return {"flagged": True, "session_id": session_id, "anomaly_type": anomaly_type, "escalation_id": str(escalation.id)}


def create_visitor_log(
    ctx: DeliveryContext,
    session_id: str,
    visitor_name: str,
    flat_number: str,
    purpose: str,
    decision: str,
    reasoning: str,
) -> dict:
    """Stamp the session row auto_approved (mirrors the gate tool of the same name)."""
    row = ctx.db.get(m.VisitorSession, ctx.session_uuid)
    if row is not None:
        row.status = decision
        row.resolved_by = "agent"
        row.resolved_at = datetime.now(timezone.utc)
        ctx.db.flush()
    return {"success": True, "session_id": session_id, "decision": decision}


def route_to_intercom_agent(ctx: DeliveryContext, session_id: str, reason: str) -> dict:
    """Signal that the Intercom Conversational Agent should handle this session."""
    return {"routed_to": "intercom_agent", "session_id": session_id, "reason": reason}


TOOL_REGISTRY = {
    "classify_delivery_service": classify_delivery_service,
    "get_delivery_pattern_history": get_delivery_pattern_history,
    "get_resident_delivery_preferences": get_resident_delivery_preferences,
    "flag_anomaly": flag_anomaly,
    "create_visitor_log": create_visitor_log,
    "route_to_intercom_agent": route_to_intercom_agent,
}


def execute_tool(tool_name: str, tool_input: dict, ctx: DeliveryContext) -> str:
    """Dispatch a tool call to its DB-backed implementation, return JSON string."""
    fn = TOOL_REGISTRY.get(tool_name)
    if fn is None:
        return json.dumps({"error": f"Unknown tool: {tool_name}"})
    try:
        result = fn(ctx, **tool_input)
        return json.dumps(result, default=str)
    except Exception as e:  # surface tool failures to Claude rather than crashing the loop
        return json.dumps({"error": str(e)})
