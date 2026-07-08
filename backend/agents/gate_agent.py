"""
Gate Visitor Agent — built with the raw Claude API, no framework.

WHY raw API first?
  A framework like LangGraph wraps this loop in abstractions. Before using
  those abstractions you need to see the seam they're hiding: Claude asks for
  a tool call, you run it, you feed the result back, repeat. Once this is
  obvious from reading code, the framework is a convenience — not magic.

HOW the loop works:
  1. Build a messages list starting with the user's visitor entry.
  2. POST to Claude with the list of tools it's allowed to call.
  3. If Claude's stop_reason == "tool_use": execute every tool it requested,
     append both Claude's response and our tool results to messages, go to 2.
  4. If stop_reason == "end_turn": Claude is done — return its final text.
"""

import json
import uuid
from datetime import datetime

import httpx
import anthropic
from dotenv import load_dotenv

from backend.tools.gate_tools import execute_tool
from backend.config import MODEL

load_dotenv()

# Corporate proxy intercepts TLS and re-signs with an internal CA that Python
# doesn't trust. This disables verification for the Anthropic API calls only.
# Replace with SSL_CERT_FILE pointing to your corporate CA cert for a proper fix.
_http_client = httpx.Client(verify=False)
client = anthropic.Anthropic(http_client=_http_client)

# ---------------------------------------------------------------------------
# Tool definitions — Claude reads these to know what it's allowed to call.
# The "input_schema" is a JSON Schema describing the arguments.
# ---------------------------------------------------------------------------
GATE_TOOLS = [
    {
        "name": "lookup_visitor_history",
        "description": (
            "Look up how many times this visitor has visited this flat before, "
            "when they last came, and their typical visiting hours. "
            "Use this to distinguish known regulars from first-time visitors."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "visitor_name": {"type": "string", "description": "Name given by the visitor or guard"},
                "flat_number": {"type": "string", "description": "The flat they claim to be visiting, e.g. A-202"},
            },
            "required": ["visitor_name", "flat_number"],
        },
    },
    {
        "name": "get_resident_rules",
        "description": (
            "Fetch the standing rules the resident has configured for their flat. "
            "Rules can auto-approve known visitors (e.g. always_allow Swiggy) or "
            "auto-deny certain times (e.g. never_allow after 21:00). "
            "Always call this before making a decision."
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
        "name": "get_flat_details",
        "description": "Get the resident's name and contact info for a given flat number.",
        "input_schema": {
            "type": "object",
            "properties": {
                "flat_number": {"type": "string"},
            },
            "required": ["flat_number"],
        },
    },
    {
        "name": "create_visitor_log",
        "description": (
            "Log the final visitor session with the decision made. "
            "Call this once you have reached a final decision: "
            "auto_approved or denied. Do NOT call for awaiting_resident — "
            "routing agents handle that status themselves."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string"},
                "visitor_name": {"type": "string"},
                "flat_number": {"type": "string"},
                "purpose": {"type": "string"},
                "decision": {
                    "type": "string",
                    "enum": ["auto_approved", "denied"],
                },
                "reasoning": {"type": "string", "description": "One sentence explaining why this decision was made"},
            },
            "required": ["session_id", "visitor_name", "flat_number", "purpose", "decision", "reasoning"],
        },
    },
    {
        "name": "route_to_delivery_agent",
        "description": (
            "Route this session to the Delivery Triage Agent. "
            "Use when purpose is 'delivery' and no standing rule already covers it."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string"},
                "reason": {"type": "string", "description": "Why you're routing to delivery agent"},
            },
            "required": ["session_id", "reason"],
        },
    },
    {
        "name": "route_to_intercom_agent",
        "description": (
            "Route this session to the Intercom Conversational Agent to contact the resident. "
            "Use when no standing rule matches and resident confirmation is required."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string"},
                "reason": {"type": "string", "description": "Why resident confirmation is needed"},
            },
            "required": ["session_id", "reason"],
        },
    },
]

SYSTEM_PROMPT = """You are the Gate Visitor Agent for a residential society management system.

Your job: given a visitor's entry at the gate, decide what to do.

Decision logic (in priority order):
1. Check visitor history + resident rules.
2. If a standing rule matches (always_allow or never_allow) → act on it immediately.
   - always_allow match → auto_approved, call create_visitor_log, stop.
   - never_allow match (e.g. after-hours) → denied, call create_visitor_log, stop.
3. If purpose is "delivery" and no standing rule covers it → route_to_delivery_agent.
4. If no rule matches → route_to_intercom_agent so the resident can decide.

Always call lookup_visitor_history and get_resident_rules before deciding.
Log every check mentally — the decision_trace field on the session depends on your reasoning.
Be concise in your final text response: one sentence stating what you decided and why.
"""


def run_gate_agent(visitor_name: str, flat_number: str, purpose: str, purpose_detail: str) -> dict:
    """
    Entry point. Call this with the visitor details from the guard/kiosk.

    Returns a dict with:
      - session_id
      - outcome: "auto_approved" | "denied" | "routed_delivery" | "routed_intercom"
      - final_message: Claude's last text response
      - message_history: the full conversation, so you can inspect every step
    """
    session_id = str(uuid.uuid4())[:8]  # short ID for readability in dev
    current_time = datetime.now().strftime("%H:%M")

    # -------------------------------------------------------------------------
    # The initial user message — this is the trigger for the whole pipeline.
    # In production this comes from a POST /sessions API request.
    # -------------------------------------------------------------------------
    initial_message = (
        f"A visitor has arrived at the gate.\n"
        f"Session ID: {session_id}\n"
        f"Visitor name: {visitor_name}\n"
        f"Claiming to visit: flat {flat_number}\n"
        f"Purpose: {purpose}\n"
        f"Purpose detail: {purpose_detail}\n"
        f"Current time: {current_time}\n\n"
        f"Please check their history, check the resident's rules, and decide what to do."
    )

    messages = [{"role": "user", "content": initial_message}]

    print(f"\n{'='*60}")
    print(f"[Gate Agent] New session: {session_id}")
    print(f"  Visitor: {visitor_name} -> Flat {flat_number} ({purpose})")
    print(f"{'='*60}")

    # -------------------------------------------------------------------------
    # THE TOOL-CALLING LOOP
    # This is the core of agentic AI with a raw API. No framework needed.
    # -------------------------------------------------------------------------
    iteration = 0
    while True:
        iteration += 1
        print(f"\n[Loop iteration {iteration}] Calling Claude...")

        response = client.messages.create(
            model=MODEL,
            max_tokens=1024,
            thinking={"type": "disabled"},
            system=SYSTEM_PROMPT,
            tools=GATE_TOOLS,
            messages=messages,
        )

        print(f"  stop_reason: {response.stop_reason}")

        # ------------------------------------------------------------------
        # CASE 1: Claude wants to call one or more tools.
        # It returns stop_reason="tool_use" and content blocks of type "tool_use".
        # ------------------------------------------------------------------
        if response.stop_reason == "tool_use":
            # Append Claude's response to the conversation history.
            # We must do this BEFORE adding tool results — the API requires
            # the assistant turn to appear before the user's tool_result turn.
            messages.append({"role": "assistant", "content": response.content})

            # Claude may request multiple tools in one turn. Process all of them.
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    print(f"  → Tool call: {block.name}({json.dumps(block.input)})")
                    result_str = execute_tool(block.name, block.input)
                    result_data = json.loads(result_str)
                    print(f"    ← Result: {json.dumps(result_data)}")

                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,  # must match the tool_use block's id
                            "content": result_str,
                        }
                    )

            # Feed all tool results back to Claude as a user turn.
            messages.append({"role": "user", "content": tool_results})
            # Loop continues — Claude will now process the results.

        # ------------------------------------------------------------------
        # CASE 2: Claude is done. It returns stop_reason="end_turn" and a
        # text block with its final response.
        # ------------------------------------------------------------------
        elif response.stop_reason == "end_turn":
            messages.append({"role": "assistant", "content": response.content})

            final_text = ""
            for block in response.content:
                if hasattr(block, "text"):
                    final_text += block.text

            print(f"\n[Gate Agent] Final decision: {final_text}")

            # Infer outcome from what tools were called (look through history)
            outcome = _infer_outcome(messages)

            return {
                "session_id": session_id,
                "outcome": outcome,
                "final_message": final_text,
                "message_history": messages,
            }

        else:
            # Unexpected stop reason (e.g. max_tokens hit). Surface it clearly.
            raise RuntimeError(f"Unexpected stop_reason: {response.stop_reason}")


def _infer_outcome(messages: list) -> str:
    """
    Walk the message history to find what the agent actually decided.
    Looks for tool calls to create_visitor_log or route_* functions.
    """
    for msg in messages:
        if msg["role"] == "assistant":
            content = msg["content"] if isinstance(msg["content"], list) else []
            for block in content:
                if hasattr(block, "type") and block.type == "tool_use":
                    if block.name == "create_visitor_log":
                        return block.input.get("decision", "unknown")
                    if block.name == "route_to_delivery_agent":
                        return "routed_delivery"
                    if block.name == "route_to_intercom_agent":
                        return "routed_intercom"
    return "unknown"


# ---------------------------------------------------------------------------
# Quick manual test — run this file directly to try the agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("\n--- Test 1: Known visitor with always_allow rule ---")
    result = run_gate_agent(
        visitor_name="Raju",
        flat_number="A-202",
        purpose="service",
        purpose_detail="Plumbing repair",
    )
    print(f"\nOutcome: {result['outcome']}")

    print("\n\n--- Test 2: Delivery with always_allow rule ---")
    result = run_gate_agent(
        visitor_name="Swiggy",
        flat_number="B-101",
        purpose="delivery",
        purpose_detail="Food delivery",
    )
    print(f"\nOutcome: {result['outcome']}")

    print("\n\n--- Test 3: Unknown visitor → should route to intercom ---")
    result = run_gate_agent(
        visitor_name="Vikram Nair",
        flat_number="A-202",
        purpose="guest",
        purpose_detail="Friend visiting for dinner",
    )
    print(f"\nOutcome: {result['outcome']}")
