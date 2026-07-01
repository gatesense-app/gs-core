"""
Mock tool implementations for the Intercom Conversational Agent.

send_notification is mocked to print + return a fake delivery receipt.
In production: Twilio / Firebase push / WhatsApp Business API.
"""

import json
from datetime import datetime


def send_notification(flat_number: str, resident_name: str, message: str) -> dict:
    """Send a message to the resident. Mocked — prints to console."""
    print(f"\n[SMS -> {resident_name} ({flat_number})]: {message}")
    return {
        "delivered": True,
        "sent_at": datetime.utcnow().isoformat(),
        "channel": "sms_mock",
    }


def get_visitor_context(session_id: str) -> dict:
    """
    Fetch full visitor context for composing a notification.
    In prod: JOIN visitor_sessions + visitors + residents.
    """
    # Hardcoded mock matching our test sessions
    return {
        "session_id": session_id,
        "visitor_name": "Vikram Nair",
        "purpose": "guest",
        "purpose_detail": "Friend visiting for dinner",
        "flat_number": "A-202",
        "resident_name": "Priya Sharma",
        "entry_time": datetime.utcnow().isoformat(),
    }


def update_visitor_session(session_id: str, status: str, resolved_by: str) -> dict:
    """
    Update the session status in the DB.
    In prod: UPDATE visitor_sessions SET status=$1, resolved_by=$2, resolved_at=NOW()
    """
    print(f"\n[DB] Session {session_id} -> status={status}, resolved_by={resolved_by}")
    return {"success": True, "session_id": session_id, "status": status}


def escalate_to_backup_contact(session_id: str, reason: str) -> dict:
    """
    Escalate to the flat's backup contact (e.g. spouse, family member).
    In prod: look up backup_contact_id from residents, send notification.
    """
    print(f"\n[ESCALATE] Session {session_id} -> backup contact | reason: {reason}")
    return {
        "escalated": True,
        "session_id": session_id,
        "escalated_to": "backup_contact",
        "reason": reason,
    }


def log_conversation_turn(
    session_id: str, turn_number: int, speaker: str, message: str
) -> dict:
    """
    Append a turn to conversation_log.
    In prod: INSERT INTO conversation_log (...) VALUES (...)
    """
    entry = {
        "session_id": session_id,
        "turn_number": turn_number,
        "speaker": speaker,
        "message": message,
        "timestamp": datetime.utcnow().isoformat(),
    }
    print(f"\n[CONV LOG] Turn {turn_number} ({speaker}): {message}")
    return {"logged": True, **entry}


TOOL_REGISTRY = {
    "send_notification": send_notification,
    "get_visitor_context": get_visitor_context,
    "update_visitor_session": update_visitor_session,
    "escalate_to_backup_contact": escalate_to_backup_contact,
    "log_conversation_turn": log_conversation_turn,
}


def execute_tool(tool_name: str, tool_input: dict) -> str:
    fn = TOOL_REGISTRY.get(tool_name)
    if fn is None:
        return json.dumps({"error": f"Unknown tool: {tool_name}"})
    try:
        return json.dumps(fn(**tool_input))
    except Exception as e:
        return json.dumps({"error": str(e)})
