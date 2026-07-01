"""
Mock tool implementations for the Delivery Triage Agent.

Same pattern as gate_tools.py — in production these hit Postgres.
For dev, they return realistic fake data.
"""

import json
from datetime import datetime


def classify_delivery_service(purpose_detail: str) -> dict:
    """
    Checks whether the purpose_detail matches a known delivery service.
    In prod: fuzzy match against a curated list of known services.
    """
    known_services = [
        "swiggy", "zomato", "blinkit", "zepto", "bigbasket",
        "amazon", "flipkart", "meesho", "myntra", "nykaa",
        "dunzo", "porter", "delhivery", "bluedart", "dtdc",
        "ecom express", "xpressbees", "shadowfax",
    ]
    detail_lower = purpose_detail.lower()
    matched = [s for s in known_services if s in detail_lower]

    if matched:
        return {
            "is_known_service": True,
            "matched_service": matched[0],
            "confidence": "high",
        }
    return {
        "is_known_service": False,
        "matched_service": None,
        "confidence": "low",
        "note": "Service name not recognized — could be a local courier or unknown vendor",
    }


def get_delivery_pattern_history(flat_number: str) -> dict:
    """
    Returns delivery frequency and timing patterns for this flat.
    In prod: aggregate query on visitor_history WHERE purpose='delivery'.
    """
    patterns = {
        "A-202": {
            "avg_deliveries_per_week": 3,
            "typical_hours": {"start": "10:00", "end": "20:00"},
            "most_common_services": ["Amazon", "Blinkit"],
            "last_delivery_at": "2026-06-30T15:00:00",
        },
        "B-101": {
            "avg_deliveries_per_week": 8,
            "typical_hours": {"start": "11:00", "end": "22:00"},
            "most_common_services": ["Swiggy", "Zomato", "BigBasket"],
            "last_delivery_at": "2026-06-30T20:30:00",
        },
    }
    return patterns.get(
        flat_number,
        {
            "avg_deliveries_per_week": 0,
            "typical_hours": None,
            "most_common_services": [],
            "last_delivery_at": None,
            "note": "No delivery history for this flat",
        },
    )


def get_resident_delivery_preferences(flat_number: str) -> dict:
    """
    Fetches the delivery_preferences field from the residents table.
    In prod: SELECT delivery_preferences FROM residents WHERE flat_number = $1
    """
    prefs = {
        "A-202": {
            "auto_log_daytime": True,
            "notify_after_hours": True,
            "after_hours_threshold": "20:00",
        },
        "B-101": {
            "auto_log_daytime": True,
            "notify_after_hours": False,
            "after_hours_threshold": "22:00",
        },
    }
    return prefs.get(
        flat_number,
        {
            "auto_log_daytime": False,
            "notify_after_hours": True,
            "after_hours_threshold": "21:00",
        },
    )


def flag_anomaly(session_id: str, anomaly_type: str, details: str) -> dict:
    """
    Records an anomaly on the session and surfaces it for human review.
    In prod: UPDATE visitor_sessions SET status='escalated', INSERT INTO escalations.
    """
    record = {
        "session_id": session_id,
        "anomaly_type": anomaly_type,
        "details": details,
        "flagged_at": datetime.utcnow().isoformat(),
    }
    print(f"\n[ANOMALY] Flagged: {json.dumps(record, indent=2)}")
    return {"flagged": True, "session_id": session_id, "anomaly_type": anomaly_type}


def create_visitor_log(
    session_id: str,
    visitor_name: str,
    flat_number: str,
    purpose: str,
    decision: str,
    reasoning: str,
) -> dict:
    """Same as gate_tools version — logs the final decision."""
    entry = {
        "session_id": session_id,
        "visitor_name": visitor_name,
        "flat_number": flat_number,
        "purpose": purpose,
        "decision": decision,
        "reasoning": reasoning,
        "logged_by": "delivery_triage_agent",
        "logged_at": datetime.utcnow().isoformat(),
    }
    print(f"\n[DB] visitor_log created: {json.dumps(entry, indent=2)}")
    return {"success": True, "session_id": session_id}


def route_to_intercom_agent(session_id: str, reason: str) -> dict:
    """Routes an anomalous delivery to the Intercom Agent for resident confirmation."""
    print(f"\n[ROUTE] -> Intercom Agent | session={session_id} | reason={reason}")
    return {"routed_to": "intercom_agent", "session_id": session_id}


TOOL_REGISTRY = {
    "classify_delivery_service": classify_delivery_service,
    "get_delivery_pattern_history": get_delivery_pattern_history,
    "get_resident_delivery_preferences": get_resident_delivery_preferences,
    "flag_anomaly": flag_anomaly,
    "create_visitor_log": create_visitor_log,
    "route_to_intercom_agent": route_to_intercom_agent,
}


def execute_tool(tool_name: str, tool_input: dict) -> str:
    fn = TOOL_REGISTRY.get(tool_name)
    if fn is None:
        return json.dumps({"error": f"Unknown tool: {tool_name}"})
    try:
        return json.dumps(fn(**tool_input))
    except Exception as e:
        return json.dumps({"error": str(e)})
