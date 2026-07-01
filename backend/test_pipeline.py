"""
End-to-end pipeline tests — exercises all three code paths:
  1. Gate auto-approves (standing rule match)
  2. Gate -> Delivery -> auto_approved (known daytime delivery)
  3. Gate -> Intercom -> clarify -> approve (unknown guest)
"""

import json
from backend.pipeline import handle_visitor_entry, handle_resident_reply


def print_trace(session):
    print(f"\n  decision_trace ({len(session.decision_trace)} entries):")
    for entry in session.decision_trace:
        print(f"    [{entry.agent}] {entry.action}")
        print(f"      tools: {entry.tool_calls}")
        print(f"      reason: {entry.reasoning[:120]}...")


# ---------------------------------------------------------------------------
print("\n" + "="*60)
print("TEST 1: Gate auto-approves via always_allow rule")
print("="*60)

session = handle_visitor_entry(
    visitor_name="Raju",
    flat_number="A-202",
    purpose="service",
    purpose_detail="Plumbing repair",
)
print(f"\nFinal status : {session.status}")
print(f"Resolved by  : {session.resolved_by}")
print_trace(session)


# ---------------------------------------------------------------------------
print("\n" + "="*60)
print("TEST 2: Gate -> Delivery -> auto_approved (Blinkit, daytime)")
print("="*60)

session = handle_visitor_entry(
    visitor_name="Blinkit Delivery",
    flat_number="A-202",
    purpose="delivery",
    purpose_detail="Blinkit grocery delivery",
)
print(f"\nFinal status : {session.status}")
print(f"Resolved by  : {session.resolved_by}")
print_trace(session)


# ---------------------------------------------------------------------------
print("\n" + "="*60)
print("TEST 3: Gate -> Intercom -> clarify loop -> approve")
print("="*60)

session = handle_visitor_entry(
    visitor_name="Vikram Nair",
    flat_number="A-202",
    purpose="guest",
    purpose_detail="Friend visiting for dinner",
)
print(f"\nStatus after gate: {session.status}  (should be awaiting_resident)")
print_trace(session)

# Simulate resident asking a question
print("\n--- Resident: 'Who is it exactly?' ---")
session = handle_resident_reply(session.session_id, "Who is it exactly?")
print(f"Status: {session.status}  (still awaiting — clarify loop)")

# Simulate guard providing clarification (second interrupt in clarify_loop)
print("\n--- Guard: 'He says he's your college friend Vikram' ---")
session = handle_resident_reply(session.session_id, "He says he's your college friend Vikram")
print(f"Status: {session.status}  (still awaiting — waiting for resident's final reply)")

# Resident approves
print("\n--- Resident: 'Yes let him in, ALLOW' ---")
session = handle_resident_reply(session.session_id, "Yes let him in, ALLOW")
print(f"\nFinal status : {session.status}")
print(f"Resolved by  : {session.resolved_by}")
print_trace(session)
