"""
Pipeline coordinator — chains Gate → Delivery → Intercom agents and persists
the shared session (and its decision_trace) to Postgres.

The session is a `visitor_sessions` row created up front so it has an id; each
agent's outcome is appended to the row's decision_trace JSONB and the row's
status/resolution is updated in place. Everything runs inside the request's
tenant-scoped DB session, so writes are RLS-checked against the caller's society.

The Gate (Phase 2) and Delivery (Phase 3) agents are fully DB-backed; Intercom
still uses mock tools (retrofitted in Phase 4).
"""

from datetime import datetime, timezone

from backend import db_models as m
from backend.agents.gate_agent import run_gate_agent
from backend.agents.delivery_agent import run_delivery_agent
from backend.agents.intercom_agent import start_intercom_session, submit_reply as intercom_reply
from backend.tools.gate_tools import GateContext, get_resident_rules
from backend.tools.delivery_tools import DeliveryContext


def _now():
    return datetime.now(timezone.utc)


def _iso():
    return _now().isoformat()


# ---------------------------------------------------------------------------
# Mine the agent message histories for the decision_trace (agents stay unaware
# of the DB — they just return their raw conversation).
# ---------------------------------------------------------------------------
def _extract_tool_calls(message_history: list) -> list[str]:
    calls = []
    for msg in message_history:
        if msg.get("role") == "assistant":
            content = msg.get("content", [])
            if isinstance(content, list):
                for block in content:
                    if hasattr(block, "type") and block.type == "tool_use":
                        calls.append(block.name)
    return calls


def _extract_agent_reasoning(message_history: list) -> str:
    for msg in reversed(message_history):
        if msg.get("role") == "assistant":
            content = msg.get("content", [])
            if isinstance(content, list):
                for block in content:
                    if hasattr(block, "text"):
                        return block.text[:300]
    return ""


def _trace_entry(agent, action, reasoning, tool_calls):
    return {
        "agent": agent,
        "action": action,
        "reasoning": reasoning,
        "tool_calls": tool_calls,
        "timestamp": _iso(),
    }


def serialize(row: m.VisitorSession) -> dict:
    """API-facing shape (keeps the field names the frontend already uses)."""
    return {
        "session_id": str(row.id),
        "visitor_name": row.visitor_name,
        "flat_number": row.flat_number,
        "purpose": row.purpose,
        "purpose_detail": row.purpose_detail,
        "status": row.status,
        "resolved_by": row.resolved_by,
        "resolved_at": row.resolved_at.isoformat() if row.resolved_at else None,
        "entry_time": row.entry_time.isoformat() if row.entry_time else None,
        "decision_trace": row.decision_trace or [],
        "conversation_history": row.conversation_history or [],
    }


# ---------------------------------------------------------------------------
# Called by POST /sessions
# ---------------------------------------------------------------------------
def handle_visitor_entry(db, society_id, visitor_name, flat_number, purpose, purpose_detail) -> m.VisitorSession:
    row = m.VisitorSession(
        society_id=society_id,
        visitor_name=visitor_name,
        flat_number=flat_number,
        purpose=purpose,
        purpose_detail=purpose_detail,
        status="pending",
        decision_trace=[],
        conversation_history=[],
    )
    db.add(row)
    db.flush()  # populate row.id

    ctx = GateContext(db, society_id, row.id)
    trace: list[dict] = []

    # STAGE 1: Gate Visitor Agent (DB-backed)
    gate_result = run_gate_agent(ctx, visitor_name, flat_number, purpose, purpose_detail)
    outcome = gate_result["outcome"]
    trace.append(_trace_entry(
        "gate",
        f"gate_decision: {outcome}",
        _extract_agent_reasoning(gate_result["message_history"]),
        _extract_tool_calls(gate_result["message_history"]),
    ))

    if outcome in ("auto_approved", "denied"):
        row.status = outcome
        row.resolved_by = "agent"
        row.resolved_at = _now()
        row.decision_trace = trace
        db.flush()
        return row

    # STAGE 2: Delivery Triage Agent (DB-backed)
    if outcome == "routed_delivery":
        delivery_ctx = DeliveryContext(db, society_id, row.id)
        delivery_result = run_delivery_agent(
            delivery_ctx,
            visitor_name=visitor_name,
            flat_number=flat_number,
            purpose_detail=purpose_detail,
        )
        d_outcome = delivery_result["outcome"]
        trace.append(_trace_entry(
            "delivery",
            f"delivery_decision: {d_outcome}",
            _extract_agent_reasoning(delivery_result["message_history"]),
            _extract_tool_calls(delivery_result["message_history"]),
        ))
        if d_outcome == "auto_approved":
            row.status = "auto_approved"
            row.resolved_by = "agent"
            row.resolved_at = _now()
            row.decision_trace = trace
            db.flush()
            return row
        outcome = "routed_intercom"

    # STAGE 3: Intercom Conversational Agent (mock until Phase 4)
    if outcome == "routed_intercom":
        resident_name = get_resident_rules(ctx, flat_number).get("resident_name", "Resident")
        start_intercom_session(
            session_id=str(row.id),
            flat_number=flat_number,
            visitor_name=visitor_name,
            purpose_detail=purpose_detail,
            resident_name=resident_name,
        )
        row.status = "awaiting_resident"
        trace.append(_trace_entry(
            "intercom",
            "notification_sent",
            f"No standing rule matched. Resident {resident_name} notified for confirmation.",
            ["send_notification", "log_conversation_turn"],
        ))

    row.decision_trace = trace
    db.flush()
    return row


# ---------------------------------------------------------------------------
# Called by POST /sessions/{id}/reply
# ---------------------------------------------------------------------------
def handle_resident_reply(db, row: m.VisitorSession, reply: str) -> m.VisitorSession:
    result = intercom_reply(str(row.id), reply)

    conversation = list(row.conversation_history or [])
    conversation.append({"speaker": "resident", "message": reply})
    trace = list(row.decision_trace or [])

    if result["done"]:
        decision = result["decision"]
        final_status = {"approved": "approved", "denied": "denied", "escalated": "escalated"}.get(decision, "approved")
        row.status = final_status
        row.resolved_by = "resident"
        row.resolved_at = _now()
        trace.append(_trace_entry(
            "intercom",
            f"resident_decision: {final_status}",
            result.get("decision_reason", ""),
            ["update_visitor_session"],
        ))
    else:
        conversation.append({"speaker": "agent", "message": "(relayed to guard)"})

    row.conversation_history = conversation
    row.decision_trace = trace
    db.flush()
    return row
