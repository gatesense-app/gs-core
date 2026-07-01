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

import json
import httpx
from typing import Literal
from typing_extensions import TypedDict

import anthropic
from dotenv import load_dotenv
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import interrupt, Command

from backend.tools.intercom_tools import (
    send_notification,
    get_visitor_context,
    update_visitor_session,
    escalate_to_backup_contact,
    log_conversation_turn,
)

load_dotenv()

_http_client = httpx.Client(verify=False)
claude = anthropic.Anthropic(http_client=_http_client)
MODEL = "claude-sonnet-4-6"


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
def notify_resident(state: IntercomState) -> dict:
    """Compose and send the initial notification to the resident."""
    print(f"\n[Node: notify_resident]")

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
        messages=[{"role": "user", "content": prompt}],
    )
    message_text = response.content[0].text

    send_notification(state["flat_number"], state["resident_name"], message_text)
    log_conversation_turn(state["session_id"], 1, "agent", message_text)

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
def await_reply(state: IntercomState) -> dict:
    """
    Pause execution and wait for the resident's reply.

    interrupt() does three things:
      1. Saves the entire graph state to the checkpointer.
      2. Returns control to whoever called graph.invoke() / graph.stream().
      3. When the caller calls graph.invoke() again with Command(resume=<value>),
         execution picks up from exactly this line.
    """
    print(f"\n[Node: await_reply] Graph paused — waiting for resident reply...")
    reply = interrupt("Waiting for resident reply")   # execution suspends here
    print(f"[Node: await_reply] Resumed with reply: '{reply}'")

    turn = state["turn_number"] + 1
    log_conversation_turn(state["session_id"], turn, "resident", reply)

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
def clarify_loop(state: IntercomState) -> dict:
    """Handle a clarification request: ask guard, relay answer to resident."""
    print(f"\n[Node: clarify_loop]")

    # In production: send a message to the guard kiosk UI and wait for input.
    # Here we simulate it with another interrupt() — same mechanism.
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
        messages=[{"role": "user", "content": relay_prompt}],
    )
    relay_message = response.content[0].text

    send_notification(state["flat_number"], state["resident_name"], relay_message)
    turn = state["turn_number"] + 1
    log_conversation_turn(state["session_id"], turn, "agent", relay_message)

    return {
        "turn_number": turn,
        "conversation_history": state["conversation_history"] + [
            {"speaker": "guard", "message": guard_answer},
            {"speaker": "agent", "message": relay_message},
        ],
    }


# ---------------------------------------------------------------------------
# NODE 5: resolve
# Resident approved or denied — finalize the session.
# ---------------------------------------------------------------------------
def resolve(state: IntercomState) -> dict:
    """Commit the resident's final approve/deny decision."""
    print(f"\n[Node: resolve] Decision: {state['decision']}")

    status = "approved" if state["decision"] == "approve" else "denied"
    update_visitor_session(state["session_id"], status, resolved_by="resident")

    reason = f"Resident {state['resident_name']} replied: '{state['last_resident_reply']}'"
    return {"decision": status, "decision_reason": reason}


# ---------------------------------------------------------------------------
# NODE 6: escalate
# Timeout or defer — hand off to backup contact or guard default policy.
# ---------------------------------------------------------------------------
def escalate(state: IntercomState) -> dict:
    """Escalate to backup contact when resident times out or defers."""
    print(f"\n[Node: escalate]")

    reason = (
        "Resident timed out" if state.get("timed_out")
        else f"Resident deferred: '{state['last_resident_reply']}'"
    )
    escalate_to_backup_contact(state["session_id"], reason)
    update_visitor_session(state["session_id"], "escalated", resolved_by="backup_contact")

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

    # MemorySaver: checkpoints state in memory so interrupt() can pause/resume.
    # Swap with SqliteSaver("sessions.db") or PostgresSaver for persistence.
    checkpointer = MemorySaver()
    return builder.compile(checkpointer=checkpointer)


# Module-level graph instance (shared across calls)
graph = build_intercom_graph()


# ---------------------------------------------------------------------------
# PUBLIC API
# ---------------------------------------------------------------------------
def start_intercom_session(
    session_id: str,
    flat_number: str,
    visitor_name: str,
    purpose_detail: str,
    resident_name: str,
) -> dict:
    """
    Start a new intercom session. The graph runs until the first interrupt()
    (after sending the notification), then pauses and returns.

    Returns {"status": "awaiting_reply", "session_id": session_id}
    """
    config = {"configurable": {"thread_id": session_id}}
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
    for event in graph.stream(initial_state, config=config, stream_mode="values"):
        pass  # events emitted per node; we only care about the final pause

    return {"status": "awaiting_reply", "session_id": session_id}


def submit_reply(session_id: str, reply: str) -> dict:
    """
    Resume a paused session with the resident's (or guard's) reply.
    The graph picks up exactly where interrupt() left it.

    Returns the current state — check state["decision"] to know if it's done.
    """
    config = {"configurable": {"thread_id": session_id}}

    final_state = None
    for event in graph.stream(
        Command(resume=reply), config=config, stream_mode="values"
    ):
        final_state = event

    decision = final_state.get("decision", "") if final_state else ""
    done = decision in ("approved", "denied", "escalated")

    return {
        "session_id": session_id,
        "done": done,
        "decision": decision,
        "decision_reason": final_state.get("decision_reason", "") if final_state else "",
        "status": "resolved" if done else "awaiting_reply",
    }


# ---------------------------------------------------------------------------
# Manual test — simulates the full lifecycle step by step
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uuid

    SESSION = str(uuid.uuid4())[:8]
    print(f"\n{'='*60}")
    print(f"INTERCOM AGENT TEST — session {SESSION}")
    print(f"{'='*60}")

    # Step 1: Gate agent routed an unknown guest — start the intercom session
    print("\n--- Step 1: Starting session (graph runs to first interrupt) ---")
    result = start_intercom_session(
        session_id=SESSION,
        flat_number="A-202",
        visitor_name="Vikram Nair",
        purpose_detail="Friend visiting for dinner",
        resident_name="Priya Sharma",
    )
    print(f"Graph paused. Status: {result['status']}")

    # Step 2: Simulate resident asking a clarifying question
    print("\n--- Step 2: Resident replies with a question ---")
    result = submit_reply(SESSION, "Who is it? I'm not expecting anyone.")
    print(f"After reply: done={result['done']}, decision={result['decision']}")

    # Step 3: Simulate guard providing clarification
    print("\n--- Step 3: Guard provides clarification ---")
    result = submit_reply(SESSION, "He says he's Vikram, your college friend, here for dinner")
    print(f"After guard input: done={result['done']}, decision={result['decision']}")

    # Step 4: Resident now approves
    print("\n--- Step 4: Resident approves ---")
    result = submit_reply(SESSION, "Oh yes! Please let him in, ALLOW")
    print(f"\nFinal: done={result['done']}, decision={result['decision']}")
    print(f"Reason: {result['decision_reason']}")

    print(f"\n{'='*60}")
    print("SECOND TEST: Resident denies immediately")
    print(f"{'='*60}")

    SESSION2 = str(uuid.uuid4())[:8]
    start_intercom_session(
        session_id=SESSION2,
        flat_number="A-202",
        visitor_name="Unknown Salesman",
        purpose_detail="Sales visit",
        resident_name="Priya Sharma",
    )
    result = submit_reply(SESSION2, "DENY, I don't want any salesman")
    print(f"\nFinal: done={result['done']}, decision={result['decision']}")
    print(f"Reason: {result['decision_reason']}")
