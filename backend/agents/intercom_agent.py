"""
Intercom Conversational Agent — built with LangGraph.

WHY LangGraph here and not for the previous two agents?
  Gate and Delivery agents run to completion in one shot — a while loop works fine.
  This agent must PAUSE after sending a notification and RESUME when the resident
  replies (potentially minutes or hours later). It may loop multiple times on
  clarification. The raw loop has no way to pause and hand control back to the caller.

  LangGraph's interrupt() primitive solves exactly this: it checkpoints the full
  graph state to memory (or a DB), returns control to your app, and resumes from
  the exact same node when you call .invoke() again with the resident's reply.

GRAPH STRUCTURE:
  notify -> await_reply -> classify_reply -> resolve        (happy path)
                        -> clarify_loop   -> await_reply    (clarification cycle)
                        -> escalate       -> END            (timeout path)

KEY CONCEPTS introduced here:
  - TypedDict as graph State: the object that flows through every node
  - @node functions: each step is a plain Python function
  - interrupt(): pauses the graph, saves state, waits for external input
  - conditional_edge: branches based on state values
  - MemorySaver: in-memory checkpointer (swap for SqliteSaver / PostgresSaver in prod)
  - thread_id in config: identifies which session is being resumed
"""

from typing import Literal
from typing_extensions import TypedDict

from langgraph.graph import StateGraph, END
from langgraph.types import interrupt, Command

from backend.checkpointer import get_checkpointer

from backend.tools.intercom_tools import (
    send_notification,
    update_visitor_session,
    escalate_to_backup_contact,
    log_conversation_turn,
)
from backend.config import MODEL
from backend.llm import client as claude  # shared client: TLS on by default + timeouts


def _ctx(config):
    """Pull the request's tenant-scoped IntercomContext out of the run config.

    ctx is injected per stream() call (see start_intercom_session / submit_reply)
    and is NOT part of the checkpointed state, so a live DB session can ride here
    safely without the checkpointer trying to serialize it.
    """
    return config["configurable"]["ctx"]


# ---------------------------------------------------------------------------
# STATE — the single object that flows through every node in the graph.
# Every node reads from it and returns a partial dict to update it.
# LangGraph merges the partial dict into the running state automatically.
# ---------------------------------------------------------------------------
class IntercomState(TypedDict):
    session_id: str
    flat_number: str
    visitor_name: str
    purpose_detail: str
    resident_name: str

    # Conversation tracking
    turn_number: int
    conversation_history: list[dict]   # [{speaker, message}]
    last_resident_reply: str           # most recent reply text

    # Decision
    decision: str                      # "approved" | "denied" | "escalated" | ""
    decision_reason: str

    # Timeout / escalation
    timed_out: bool


# ---------------------------------------------------------------------------
# NODE 1: notify_resident
# Composes a context-aware first message using Claude, then sends it.
# ---------------------------------------------------------------------------
def notify_resident(state: IntercomState, config) -> dict:
    """Compose and send the initial notification to the resident."""
    print(f"\n[Node: notify_resident]")
    ctx = _ctx(config)

    # Ask Claude to draft a concise, friendly notification
    prompt = (
        f"You are a society gate intercom system. Draft a short WhatsApp-style message "
        f"to notify the resident that a visitor is at the gate.\n\n"
        f"Visitor: {state['visitor_name']}\n"
        f"Purpose: {state['purpose_detail']}\n"
        f"Resident: {state['resident_name']}, Flat {state['flat_number']}\n\n"
        f"Keep it under 2 sentences. End with 'Reply ALLOW or DENY (or ask a question).'"
    )
    response = claude.messages.create(
        model=MODEL,
        max_tokens=200,
        thinking={"type": "disabled"},
        messages=[{"role": "user", "content": prompt}],
    )
    message_text = response.content[0].text

    send_notification(ctx, state["flat_number"], state["resident_name"], message_text)
    log_conversation_turn(ctx, 1, "agent", message_text)

    return {
        "turn_number": 1,
        "conversation_history": [{"speaker": "agent", "message": message_text}],
    }


# ---------------------------------------------------------------------------
# NODE 2: await_reply
# This is the key node. interrupt() pauses the graph here and hands
# control back to the caller. The graph resumes when .invoke() is called
# again with the resident's reply in the Command.resume value.
# ---------------------------------------------------------------------------
def await_reply(state: IntercomState, config) -> dict:
    """
    Pause execution and wait for the resident's reply.

    interrupt() does three things:
      1. Saves the entire graph state to the checkpointer.
      2. Returns control to whoever called graph.invoke() / graph.stream().
      3. When the caller calls graph.invoke() again with Command(resume=<value>),
         execution picks up from exactly this line.
    """
    print(f"\n[Node: await_reply] Graph paused - waiting for resident reply...")
    reply = interrupt("Waiting for resident reply")   # execution suspends here
    print(f"[Node: await_reply] Resumed with reply: '{reply}'")

    ctx = _ctx(config)
    turn = state["turn_number"] + 1
    log_conversation_turn(ctx, turn, "resident", reply)

    return {
        "last_resident_reply": reply,
        "turn_number": turn,
        "conversation_history": state["conversation_history"] + [
            {"speaker": "resident", "message": reply}
        ],
    }


# ---------------------------------------------------------------------------
# NODE 3: classify_reply
# Uses Claude to understand what the resident actually meant.
# Returns a routing decision in state so the conditional edge can branch.
# ---------------------------------------------------------------------------
def classify_reply(state: IntercomState) -> dict:
    """Ask Claude to classify the resident's reply into one of four intents."""
    print(f"\n[Node: classify_reply]")

    prompt = (
        f"A resident replied to a gate intercom notification. Classify their intent.\n\n"
        f"Resident reply: \"{state['last_resident_reply']}\"\n\n"
        f"Classify as exactly one of:\n"
        f"- approve: resident is allowing the visitor in\n"
        f"- deny: resident is refusing entry\n"
        f"- clarify: resident is asking a question or needs more info before deciding\n"
        f"- defer: resident says to ask the guard to decide, or is unavailable\n\n"
        f"Reply with ONLY the single word classification."
    )
    response = claude.messages.create(
        model=MODEL,
        max_tokens=10,
        thinking={"type": "disabled"},
        messages=[{"role": "user", "content": prompt}],
    )
    intent = response.content[0].text.strip().lower()
    # Guard against unexpected outputs
    if intent not in ("approve", "deny", "clarify", "defer"):
        intent = "clarify"

    print(f"  Classified intent: {intent}")
    return {"decision": intent}


# ---------------------------------------------------------------------------
# NODE 4: clarify_loop
# Resident asked a question — relay it to the guard, get an answer,
# send it back to the resident, then loop back to await_reply.
# ---------------------------------------------------------------------------
def clarify_loop(state: IntercomState, config) -> dict:
    """Handle a clarification request: ask guard, relay answer to resident."""
    print(f"\n[Node: clarify_loop]")
    ctx = _ctx(config)

    # In production: send a message to the guard kiosk UI and wait for input.
    # Here we simulate it with another interrupt() - same mechanism.
    question = state["last_resident_reply"]
    guard_prompt = f"Resident of {state['flat_number']} asks: \"{question}\" — what is your answer?"
    print(f"[Guard prompt]: {guard_prompt}")

    guard_answer = interrupt(f"Guard: {guard_prompt}")
    print(f"[Guard answered]: {guard_answer}")

    # Compose a reply back to the resident
    relay_prompt = (
        f"Relay this guard's answer to the resident in one friendly sentence.\n"
        f"Guard said: \"{guard_answer}\"\n"
        f"End with 'Reply ALLOW or DENY.'"
    )
    response = claude.messages.create(
        model=MODEL,
        max_tokens=150,
        thinking={"type": "disabled"},
        messages=[{"role": "user", "content": relay_prompt}],
    )
    relay_message = response.content[0].text

    guard_turn = state["turn_number"] + 1
    relay_turn = guard_turn + 1
    log_conversation_turn(ctx, guard_turn, "guard", guard_answer)
    send_notification(ctx, state["flat_number"], state["resident_name"], relay_message)
    log_conversation_turn(ctx, relay_turn, "agent", relay_message)

    return {
        "turn_number": relay_turn,
        "conversation_history": state["conversation_history"] + [
            {"speaker": "guard", "message": guard_answer},
            {"speaker": "agent", "message": relay_message},
        ],
    }


# ---------------------------------------------------------------------------
# NODE 5: resolve
# Resident approved or denied — finalize the session.
# ---------------------------------------------------------------------------
def resolve(state: IntercomState, config) -> dict:
    """Commit the resident's final approve/deny decision."""
    print(f"\n[Node: resolve] Decision: {state['decision']}")
    ctx = _ctx(config)

    status = "approved" if state["decision"] == "approve" else "denied"
    update_visitor_session(ctx, status, resolved_by="resident")

    reason = f"Resident {state['resident_name']} replied: '{state['last_resident_reply']}'"
    return {"decision": status, "decision_reason": reason}


# ---------------------------------------------------------------------------
# NODE 6: escalate
# Timeout or defer — hand off to backup contact or guard default policy.
# ---------------------------------------------------------------------------
def escalate(state: IntercomState, config) -> dict:
    """Escalate to backup contact when resident times out or defers."""
    print(f"\n[Node: escalate]")
    ctx = _ctx(config)

    reason = (
        "Resident timed out" if state.get("timed_out")
        else f"Resident deferred: '{state['last_resident_reply']}'"
    )
    escalate_to_backup_contact(ctx, reason)
    update_visitor_session(ctx, "escalated", resolved_by="backup_contact")

    return {"decision": "escalated", "decision_reason": reason}


# ---------------------------------------------------------------------------
# CONDITIONAL EDGES — these are just functions that return the next node name.
# LangGraph calls them after a node finishes to decide where to go next.
# ---------------------------------------------------------------------------
def route_after_classify(state: IntercomState) -> Literal["resolve", "clarify_loop", "escalate"]:
    intent = state["decision"]
    if intent in ("approve", "deny"):
        return "resolve"
    elif intent == "clarify":
        return "clarify_loop"
    else:  # defer
        return "escalate"


# ---------------------------------------------------------------------------
# BUILD THE GRAPH
# ---------------------------------------------------------------------------
def build_intercom_graph():
    builder = StateGraph(IntercomState)

    # Register nodes
    builder.add_node("notify_resident", notify_resident)
    builder.add_node("await_reply", await_reply)
    builder.add_node("classify_reply", classify_reply)
    builder.add_node("clarify_loop", clarify_loop)
    builder.add_node("resolve", resolve)
    builder.add_node("escalate", escalate)

    # Entry point
    builder.set_entry_point("notify_resident")

    # Edges
    builder.add_edge("notify_resident", "await_reply")
    builder.add_edge("await_reply", "classify_reply")
    builder.add_conditional_edges("classify_reply", route_after_classify)
    builder.add_edge("clarify_loop", "await_reply")   # loop back for another reply
    builder.add_edge("resolve", END)
    builder.add_edge("escalate", END)

    # The checkpointer is what makes interrupt() survive the gap between the
    # notification and the resident's reply — which is a different HTTP request,
    # and possibly a different process after a deploy. Postgres-backed; see
    # backend/checkpointer.py.
    return builder.compile(checkpointer=get_checkpointer())


# Built on first use, not at import: compiling opens the checkpointer's DB pool,
# and importing this module (tests, tooling, `--help`) shouldn't require a
# reachable database.
_graph = None


def get_graph():
    global _graph
    if _graph is None:
        _graph = build_intercom_graph()
    return _graph


# ---------------------------------------------------------------------------
# PUBLIC API
# ---------------------------------------------------------------------------
def _config(ctx):
    """Run config: thread_id identifies the checkpointed session; ctx injects the
    request's tenant-scoped DB session (not checkpointed)."""
    return {"configurable": {"thread_id": str(ctx.session_uuid), "ctx": ctx}}


def start_intercom_session(
    ctx,
    flat_number: str,
    visitor_name: str,
    purpose_detail: str,
    resident_name: str,
) -> dict:
    """
    Start a new intercom session. The graph runs until the first interrupt()
    (after sending the notification), then pauses and returns.

    Returns {"status", "session_id", "conversation_history"} — the pipeline
    mirrors conversation_history onto the session row for the UI.
    """
    session_id = str(ctx.session_uuid)
    initial_state: IntercomState = {
        "session_id": session_id,
        "flat_number": flat_number,
        "visitor_name": visitor_name,
        "purpose_detail": purpose_detail,
        "resident_name": resident_name,
        "turn_number": 0,
        "conversation_history": [],
        "last_resident_reply": "",
        "decision": "",
        "decision_reason": "",
        "timed_out": False,
    }

    # Run until the first interrupt
    final_state = None
    for event in get_graph().stream(initial_state, config=_config(ctx), stream_mode="values"):
        final_state = event

    return {
        "status": "awaiting_reply",
        "session_id": session_id,
        "conversation_history": final_state.get("conversation_history", []) if final_state else [],
    }


def submit_reply(ctx, reply: str) -> dict:
    """
    Resume a paused session with the resident's (or guard's) reply.
    The graph picks up exactly where interrupt() left it.

    Returns the current state — check ["done"] to know if it's resolved.
    """
    final_state = None
    for event in get_graph().stream(
        Command(resume=reply), config=_config(ctx), stream_mode="values"
    ):
        final_state = event

    decision = final_state.get("decision", "") if final_state else ""
    done = decision in ("approved", "denied", "escalated")

    return {
        "session_id": str(ctx.session_uuid),
        "done": done,
        "decision": decision,
        "decision_reason": final_state.get("decision_reason", "") if final_state else "",
        "status": "resolved" if done else "awaiting_reply",
        "conversation_history": final_state.get("conversation_history", []) if final_state else [],
    }


# ---------------------------------------------------------------------------
# Manual test — simulates the full lifecycle step by step
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Standalone demos were removed: the intercom graph now requires an
    # IntercomContext (a tenant-scoped DB session) injected via config. Exercise
    # it through the pipeline / API, or the backend/tests suite, instead.
    print("The intercom agent requires an IntercomContext - run it via the API or tests.")
