"""
Delivery Triage Agent — raw Claude API, no framework.

Same loop pattern as gate_agent.py. Goal: reinforce the primitive.

Decision logic:
  - Known service + within typical hours + auto_log_daytime = True  -> auto_approved
  - Known service + after hours + notify_after_hours = True          -> route_to_intercom_agent
  - Unknown service                                                   -> flag_anomaly + route_to_intercom_agent
  - Unusual delivery pattern (e.g. 3rd delivery today)               -> flag_anomaly + route_to_intercom_agent
"""

import json

from backend.tools.delivery_tools import execute_tool
from backend.config import MODEL
from backend.llm import client  # shared client: TLS on by default + timeouts

DELIVERY_TOOLS = [
    {
        "name": "classify_delivery_service",
        "description": (
            "Checks whether the purpose_detail matches a known delivery service "
            "(Swiggy, Amazon, Blinkit, etc.). Returns is_known_service and the matched name."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "purpose_detail": {
                    "type": "string",
                    "description": "The free-text purpose detail provided by the guard or visitor",
                },
            },
            "required": ["purpose_detail"],
        },
    },
    {
        "name": "get_delivery_pattern_history",
        "description": (
            "Returns the historical delivery pattern for this flat: average deliveries per week, "
            "typical delivery hours, and most common services. Use this to detect anomalies."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "flat_number": {"type": "string"},
            },
            "required": ["flat_number"],
        },
    },
    {
        "name": "get_resident_delivery_preferences",
        "description": (
            "Returns the resident's delivery preferences: whether to auto-log daytime deliveries "
            "and whether to notify after hours."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "flat_number": {"type": "string"},
            },
            "required": ["flat_number"],
        },
    },
    {
        "name": "flag_anomaly",
        "description": (
            "Flag an anomaly on this delivery session. Call this before routing to intercom "
            "whenever something is unusual: unknown service, after-hours delivery when resident "
            "said to notify, or suspicious pattern."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string"},
                "anomaly_type": {
                    "type": "string",
                    "enum": ["unknown_service", "after_hours", "unusual_pattern", "suspicious"],
                },
                "details": {
                    "type": "string",
                    "description": "One sentence describing what triggered the anomaly flag",
                },
            },
            "required": ["session_id", "anomaly_type", "details"],
        },
    },
    {
        "name": "create_visitor_log",
        "description": (
            "Log the session as auto_approved. Only call this for clean, routine deliveries "
            "that match all three criteria: known service + daytime + auto_log_daytime=true."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string"},
                "visitor_name": {"type": "string"},
                "flat_number": {"type": "string"},
                "purpose": {"type": "string"},
                "decision": {"type": "string", "enum": ["auto_approved"]},
                "reasoning": {"type": "string"},
            },
            "required": ["session_id", "visitor_name", "flat_number", "purpose", "decision", "reasoning"],
        },
    },
    {
        "name": "route_to_intercom_agent",
        "description": (
            "Route this delivery session to the Intercom Agent so the resident can confirm. "
            "Use after flag_anomaly, or whenever auto-approval criteria are not fully met."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string"},
                "reason": {"type": "string"},
            },
            "required": ["session_id", "reason"],
        },
    },
]

SYSTEM_PROMPT = """You are the Delivery Triage Agent for a residential society management system.

You receive delivery visitors that were routed to you by the Gate Visitor Agent.
Your job: decide whether to auto-approve a routine delivery or flag it for resident confirmation.

Decision logic (apply in order):
1. classify_delivery_service — is this a known service?
2. get_delivery_pattern_history — does this fit the flat's normal delivery pattern?
3. get_resident_delivery_preferences — has the resident opted into auto-logging?

AUTO-APPROVE (call create_visitor_log with decision=auto_approved) if ALL of:
  - is_known_service = true
  - Current time is within the flat's typical delivery hours
  - auto_log_daytime = true

FLAG + ROUTE TO INTERCOM (call flag_anomaly then route_to_intercom_agent) if ANY of:
  - Service is unknown
  - Delivery is after hours AND notify_after_hours = true
  - Pattern seems unusual (e.g. far outside typical hours, service never seen before)

Always gather all three data points before deciding.
Be concise in your final text response.
"""


def run_delivery_agent(
    ctx,
    visitor_name: str,
    flat_number: str,
    purpose_detail: str,
) -> dict:
    """
    Entry point. In the real pipeline this is called after the Gate Agent's
    route_to_delivery_agent tool. Tools are DB-backed via the DeliveryContext.

    Args:
        ctx:            DeliveryContext (tenant-scoped DB session + session id)
        visitor_name:   Visitor name (e.g. "Swiggy", "Rahul from Delhivery")
        flat_number:    Flat being delivered to
        purpose_detail: Free-text from the guard (e.g. "Blinkit grocery delivery")
    """
    from datetime import datetime
    session_id = str(ctx.session_uuid)  # the real DB session id
    current_time = datetime.now().strftime("%H:%M")

    initial_message = (
        f"A delivery visitor has been routed to you for triage.\n"
        f"Session ID: {session_id}\n"
        f"Visitor name: {visitor_name}\n"
        f"Flat: {flat_number}\n"
        f"Purpose detail: {purpose_detail}\n"
        f"Current time: {current_time}\n\n"
        f"Check the service, delivery history, and resident preferences, then decide."
    )

    messages = [{"role": "user", "content": initial_message}]

    print(f"\n{'='*60}")
    print(f"[Delivery Agent] Session: {session_id}")
    print(f"  {visitor_name} -> Flat {flat_number} | {purpose_detail}")
    print(f"{'='*60}")

    iteration = 0
    while True:
        iteration += 1
        print(f"\n[Loop iteration {iteration}] Calling Claude...")

        response = client.messages.create(
            model=MODEL,
            max_tokens=1024,
            thinking={"type": "disabled"},
            system=SYSTEM_PROMPT,
            tools=DELIVERY_TOOLS,
            messages=messages,
        )

        print(f"  stop_reason: {response.stop_reason}")

        if response.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": response.content})

            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    print(f"  -> Tool call: {block.name}({json.dumps(block.input)})")
                    result_str = execute_tool(block.name, block.input, ctx)
                    result_data = json.loads(result_str)
                    print(f"     <- Result: {json.dumps(result_data)}")
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result_str,
                    })

            messages.append({"role": "user", "content": tool_results})

        elif response.stop_reason == "end_turn":
            messages.append({"role": "assistant", "content": response.content})

            final_text = "".join(
                block.text for block in response.content if hasattr(block, "text")
            )
            print(f"\n[Delivery Agent] Final decision: {final_text}")

            outcome = _infer_outcome(messages)
            return {
                "session_id": session_id,
                "outcome": outcome,
                "final_message": final_text,
                "message_history": messages,
            }

        else:
            raise RuntimeError(f"Unexpected stop_reason: {response.stop_reason}")


def _infer_outcome(messages: list) -> str:
    for msg in messages:
        if msg["role"] == "assistant":
            content = msg["content"] if isinstance(msg["content"], list) else []
            for block in content:
                if hasattr(block, "type") and block.type == "tool_use":
                    if block.name == "create_visitor_log":
                        return "auto_approved"
                    if block.name == "route_to_intercom_agent":
                        return "routed_intercom"
    return "unknown"


if __name__ == "__main__":
    # Standalone demos were removed: run_delivery_agent now requires a
    # DeliveryContext (a tenant-scoped DB session). Exercise it through the
    # pipeline / API, or the backend/tests suite, instead.
    print("run_delivery_agent requires a DeliveryContext — run it via the API or tests.")
