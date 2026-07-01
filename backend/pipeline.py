"""
Pipeline coordinator — chains Gate → Delivery → Intercom agents.

This module is the only place that knows about agent sequencing.
Each agent remains independently importable and testable; the pipeline
just interprets their outcomes and calls the next one.

How decision_trace gets built:
  - Gate agent runs → we extract which tools it called from message_history
    and write a TraceEntry to the session
  - Same for Delivery agent
  - Intercom agent writes its own conversation_history; we copy that in too
"""

import json
from backend.models import VisitorSession
from backend import session_store
from backend.agents.gate_agent import run_gate_agent
from backend.agents.delivery_agent import run_delivery_agent
from backend.agents.intercom_agent import start_intercom_session, submit_reply as intercom_reply


# ---------------------------------------------------------------------------
# Helpers to extract tool call names from raw agent message histories.
# The agents return their full message_history so we can mine it for
# the decision_trace without the agents needing to know about VisitorSession.
# ---------------------------------------------------------------------------
def _extract_tool_calls(message_history: list) -> list[str]:
    """Return ordered list of tool names Claude called in this agent's run."""
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
    """Pull the agent's final text response as the reasoning summary."""
    for msg in reversed(message_history):
        if msg.get("role") == "assistant":
            content = msg.get("content", [])
            if isinstance(content, list):
                for block in content:
                    if hasattr(block, "text"):
                        return block.text[:300]   # cap at 300 chars for trace
    return ""


# ---------------------------------------------------------------------------
# Entry point — called by POST /sessions
# ---------------------------------------------------------------------------
def handle_visitor_entry(
    visitor_name: str,
    flat_number: str,
    purpose: str,
    purpose_detail: str,
) -> VisitorSession:
    """
    Start a new visitor session and run it through the pipeline as far
    as it can go synchronously. If the intercom agent is needed, the
    session pauses at status=awaiting_resident and waits for reply calls.
    """
    # Create and persist the session immediately so it's queryable right away
    session = VisitorSession(
        visitor_name=visitor_name,
        flat_number=flat_number,
        purpose=purpose,
        purpose_detail=purpose_detail,
    )
    session_store.create(session)
    print(f"\n[Pipeline] New session {session.session_id}: {visitor_name} -> {flat_number}")

    # ------------------------------------------------------------------
    # STAGE 1: Gate Visitor Agent
    # ------------------------------------------------------------------
    gate_result = run_gate_agent(
        visitor_name=visitor_name,
        flat_number=flat_number,
        purpose=purpose,
        purpose_detail=purpose_detail,
    )

    tool_calls = _extract_tool_calls(gate_result["message_history"])
    reasoning = _extract_agent_reasoning(gate_result["message_history"])
    outcome = gate_result["outcome"]

    session.add_trace(
        agent="gate",
        action=f"gate_decision: {outcome}",
        reasoning=reasoning,
        tool_calls=tool_calls,
    )

    if outcome == "auto_approved":
        session.resolve("auto_approved", resolved_by="agent")
        session_store.update(session)
        return session

    if outcome == "denied":
        session.resolve("denied", resolved_by="agent")
        session_store.update(session)
        return session

    # ------------------------------------------------------------------
    # STAGE 2: Delivery Triage Agent (only if gate routed here)
    # ------------------------------------------------------------------
    if outcome == "routed_delivery":
        delivery_result = run_delivery_agent(
            session_id=session.session_id,
            visitor_name=visitor_name,
            flat_number=flat_number,
            purpose_detail=purpose_detail,
        )

        d_tool_calls = _extract_tool_calls(delivery_result["message_history"])
        d_reasoning = _extract_agent_reasoning(delivery_result["message_history"])
        d_outcome = delivery_result["outcome"]

        session.add_trace(
            agent="delivery",
            action=f"delivery_decision: {d_outcome}",
            reasoning=d_reasoning,
            tool_calls=d_tool_calls,
        )

        if d_outcome == "auto_approved":
            session.resolve("auto_approved", resolved_by="agent")
            session_store.update(session)
            return session

        # Delivery agent flagged anomaly → falls through to intercom
        outcome = "routed_intercom"

    # ------------------------------------------------------------------
    # STAGE 3: Intercom Conversational Agent
    # ------------------------------------------------------------------
    if outcome == "routed_intercom":
        # Look up resident name for the notification
        # In prod this comes from the DB; here we re-use the mock tool
        from backend.tools.gate_tools import get_resident_rules
        rules = get_resident_rules(flat_number)
        resident_name = rules.get("resident_name", "Resident")

        start_intercom_session(
            session_id=session.session_id,
            flat_number=flat_number,
            visitor_name=visitor_name,
            purpose_detail=purpose_detail,
            resident_name=resident_name,
        )

        session.status = "awaiting_resident"
        session.add_trace(
            agent="intercom",
            action="notification_sent",
            reasoning=f"No standing rule matched. Resident {resident_name} notified for confirmation.",
            tool_calls=["send_notification", "log_conversation_turn"],
        )
        session_store.update(session)

    return session


# ---------------------------------------------------------------------------
# Called by POST /sessions/{session_id}/reply
# ---------------------------------------------------------------------------
def handle_resident_reply(session_id: str, reply: str) -> VisitorSession:
    """
    Resume the paused intercom graph with the resident's reply.
    Updates and returns the session.
    """
    session = session_store.get(session_id)
    if session is None:
        raise ValueError(f"Session {session_id} not found")

    result = intercom_reply(session_id, reply)

    # Append this reply turn to the session's conversation history
    session.conversation_history.append({"speaker": "resident", "message": reply})

    if result["done"]:
        decision = result["decision"]
        status_map = {"approved": "approved", "denied": "denied", "escalated": "escalated"}
        final_status = status_map.get(decision, "approved")

        session.resolve(final_status, resolved_by="resident")
        session.add_trace(
            agent="intercom",
            action=f"resident_decision: {final_status}",
            reasoning=result["decision_reason"],
            tool_calls=["update_visitor_session"],
        )
    else:
        # Still in clarification loop — update conversation history only
        session.conversation_history.append({"speaker": "agent", "message": "(relayed to guard)"})

    session_store.update(session)
    return session
