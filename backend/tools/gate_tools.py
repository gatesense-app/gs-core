"""
Mock implementations of tools the Gate Visitor Agent can call.

In production these would query Postgres. For now they return realistic
fake data so you can run the agent loop and see it working end-to-end
without needing a database set up.

Each function signature matches the `input` shape Claude will send
when it decides to call that tool.
"""

import json
from datetime import datetime


def lookup_visitor_history(visitor_name: str, flat_number: str) -> dict:
    """
    Returns past visit records for this name+flat combination.
    In prod: SELECT * FROM visitor_history JOIN visitors ON ...
    """
    # Simulate known visitors with history
    known = {
        ("Raju", "A-202"): {
            "found": True,
            "visit_count": 12,
            "last_visit_at": "2026-06-28T14:30:00",
            "typical_hours": {"start": "09:00", "end": "18:00"},
            "notes": "Regular plumber, known to resident",
        },
        ("Swiggy", "B-101"): {
            "found": True,
            "visit_count": 45,
            "last_visit_at": "2026-06-30T19:45:00",
            "typical_hours": {"start": "11:00", "end": "22:00"},
            "notes": "Frequent delivery",
        },
    }
    key = (visitor_name, flat_number)
    if key in known:
        return known[key]
    return {"found": False, "visit_count": 0, "last_visit_at": None, "notes": "No history"}


def get_resident_rules(flat_number: str) -> dict:
    """
    Returns the standing_rules and delivery_preferences for this flat.
    In prod: SELECT standing_rules, delivery_preferences FROM residents WHERE flat_number = $1
    """
    rules_by_flat = {
        "A-202": {
            "standing_rules": [
                {"type": "always_allow", "match": "Raju"},
                {"type": "never_allow", "after": "21:00"},
            ],
            "delivery_preferences": {
                "auto_log_daytime": True,
                "notify_after_hours": True,
            },
            "resident_name": "Priya Sharma",
        },
        "B-101": {
            "standing_rules": [
                {"type": "always_allow", "match": "Swiggy"},
                {"type": "always_allow", "match": "Zomato"},
            ],
            "delivery_preferences": {
                "auto_log_daytime": True,
                "notify_after_hours": False,
            },
            "resident_name": "Arun Mehta",
        },
    }
    return rules_by_flat.get(
        flat_number,
        {
            "standing_rules": [],
            "delivery_preferences": {"auto_log_daytime": False, "notify_after_hours": True},
            "resident_name": "Unknown Resident",
        },
    )


def get_flat_details(flat_number: str) -> dict:
    """
    Returns contact info for the flat so downstream agents know who to reach.
    In prod: SELECT name, contact, backup_contact_id FROM residents WHERE flat_number = $1
    """
    flats = {
        "A-202": {"flat_number": "A-202", "resident_name": "Priya Sharma", "contact": "+91-9876543210"},
        "B-101": {"flat_number": "B-101", "resident_name": "Arun Mehta", "contact": "+91-9123456789"},
    }
    return flats.get(flat_number, {"flat_number": flat_number, "resident_name": "Unknown", "contact": None})


def create_visitor_log(
    session_id: str,
    visitor_name: str,
    flat_number: str,
    purpose: str,
    decision: str,
    reasoning: str,
) -> dict:
    """
    Persists the visitor session with the agent's decision.
    In prod: INSERT INTO visitor_sessions (...) VALUES (...)
    """
    entry = {
        "session_id": session_id,
        "visitor_name": visitor_name,
        "flat_number": flat_number,
        "purpose": purpose,
        "decision": decision,
        "reasoning": reasoning,
        "logged_at": datetime.utcnow().isoformat(),
    }
    # In dev, just print so you can see it happening
    print(f"\n[DB] visitor_log created: {json.dumps(entry, indent=2)}")
    return {"success": True, "session_id": session_id}


def route_to_delivery_agent(session_id: str, reason: str) -> dict:
    """
    Signals that the Delivery Triage Agent should handle this session.
    In prod: publish to internal queue / call the next agent.
    """
    print(f"\n[ROUTE] → Delivery Triage Agent | session={session_id} | reason={reason}")
    return {"routed_to": "delivery_agent", "session_id": session_id}


def route_to_intercom_agent(session_id: str, reason: str) -> dict:
    """
    Signals that the Intercom Conversational Agent should handle this session.
    """
    print(f"\n[ROUTE] → Intercom Agent | session={session_id} | reason={reason}")
    return {"routed_to": "intercom_agent", "session_id": session_id}


# ---------------------------------------------------------------------------
# Tool registry — maps name → callable so the agent loop can dispatch by name
# ---------------------------------------------------------------------------
TOOL_REGISTRY = {
    "lookup_visitor_history": lookup_visitor_history,
    "get_resident_rules": get_resident_rules,
    "get_flat_details": get_flat_details,
    "create_visitor_log": create_visitor_log,
    "route_to_delivery_agent": route_to_delivery_agent,
    "route_to_intercom_agent": route_to_intercom_agent,
}


def execute_tool(tool_name: str, tool_input: dict) -> str:
    """
    The dispatcher. Called by the agent loop whenever Claude returns
    stop_reason='tool_use'. Looks up the function, calls it, returns
    a JSON string (Claude expects tool results as strings).
    """
    fn = TOOL_REGISTRY.get(tool_name)
    if fn is None:
        return json.dumps({"error": f"Unknown tool: {tool_name}"})
    try:
        result = fn(**tool_input)
        return json.dumps(result)
    except Exception as e:
        return json.dumps({"error": str(e)})
