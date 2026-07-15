"""
Hand-labeled ground truth for the agent eval.

Each scenario is a visitor arriving at a flat whose rules we control, plus the
outcome a human reviewer says is correct. The label is the *status the session
should end in*, which is what actually matters to a resident — not which tokens
the model emitted.

Fixture flats (created by run_eval.setup):
  A-101  always_allow Swiggy        | auto_log_daytime=True,  notify_after_hours=True
  A-102  never_allow after 21:00    | auto_log_daytime=True,  notify_after_hours=True
  A-103  (no rules)                 | auto_log_daytime=False, notify_after_hours=True
  A-104  always_allow Amazon        | auto_log_daytime=False, notify_after_hours=True

Known visitors: Swiggy / Amazon / Blinkit (known delivery services),
Raju Plumber and Lakshmi (Maid) (known people, not services).

`replies` drives the intercom leg: each string is sent in order as if the
resident (or guard) typed it, and `expected` is checked after the last one.

Time sensitivity: a couple of delivery cases depend on the flat's typical
delivery window (07:00-23:00). Those are marked `daytime_only` and are skipped
outside that window rather than reported as failures.
"""

SCENARIOS = [
    # --- Gate: standing rules -------------------------------------------------
    {
        "id": "gate-01",
        "why": "A standing always_allow rule matches the visitor exactly -> let them in, no resident needed.",
        "flat": "A-101", "visitor": "Swiggy", "purpose": "delivery",
        "detail": "Swiggy food delivery",
        "expected": "auto_approved",
    },
    {
        "id": "gate-02",
        "why": "Rule matching should be case-insensitive; 'swiggy' is the same rule.",
        "flat": "A-101", "visitor": "swiggy", "purpose": "delivery",
        "detail": "swiggy order drop-off",
        "expected": "auto_approved",
    },
    {
        "id": "gate-03",
        "why": "Unknown guest, no rule covers it -> must ask the resident, never guess.",
        "flat": "A-103", "visitor": "Vikram Nair", "purpose": "guest",
        "detail": "Friend visiting for dinner",
        "expected": "awaiting_resident",
    },
    {
        "id": "gate-04",
        "why": "A known person (not a service) with no rule still needs resident confirmation.",
        "flat": "A-103", "visitor": "Raju Plumber", "purpose": "service",
        "detail": "Plumbing repair",
        "expected": "awaiting_resident",
    },
    {
        "id": "gate-05",
        "why": "A rule for one flat must not leak to another flat.",
        "flat": "A-103", "visitor": "Swiggy", "purpose": "delivery",
        "detail": "Swiggy food delivery",
        "expected": "awaiting_resident",
    },
    {
        "id": "gate-06",
        "why": "Cabs are not covered by any rule -> resident decides.",
        "flat": "A-103", "visitor": "Uber", "purpose": "cab",
        "detail": "Cab waiting at the gate",
        "expected": "awaiting_resident",
    },
    {
        # Originally labeled against A-101 and expected awaiting_resident. That
        # label was wrong: A-101 also sets auto_log_daytime=True, so the delivery
        # agent rightly clears any known service in-window regardless of which
        # brand the always_allow rule names. Re-pointed at A-104 (auto-logging
        # off) to isolate what this is actually testing. See deliv-05 for the
        # A-101 behaviour, now labeled correctly.
        "id": "gate-07",
        "why": "A-104's always_allow names Amazon, not Zomato; with auto-logging off the resident must decide.",
        "flat": "A-104", "visitor": "Zomato", "purpose": "delivery",
        "detail": "Zomato food delivery",
        "expected": "awaiting_resident",
    },
    {
        "id": "gate-08",
        "why": "always_allow on A-104 is Amazon -> exact match auto-approves.",
        "flat": "A-104", "visitor": "Amazon", "purpose": "delivery",
        "detail": "Amazon package delivery",
        "expected": "auto_approved",
    },

    # --- Delivery triage ------------------------------------------------------
    {
        "id": "deliv-01",
        "why": "Unknown local courier -> anomaly, must not auto-approve.",
        "flat": "A-103", "visitor": "Rajesh", "purpose": "delivery",
        "detail": "Parcel from an unnamed local shop",
        "expected": "awaiting_resident",
        "expect_escalation": True,
    },
    {
        "id": "deliv-02",
        "why": "Known service but the resident opted OUT of auto-logging -> ask them.",
        "flat": "A-104", "visitor": "Blinkit", "purpose": "delivery",
        "detail": "Blinkit grocery delivery",
        "expected": "awaiting_resident",
    },
    {
        "id": "deliv-03",
        "why": "Known service + resident opted IN to daytime auto-logging -> clear it.",
        "flat": "A-101", "visitor": "Blinkit", "purpose": "delivery",
        "detail": "Blinkit grocery delivery",
        "expected": "auto_approved",
        "daytime_only": True,
    },
    {
        "id": "deliv-04",
        "why": "A vague 'courier' with no brand is not a known service.",
        "flat": "A-103", "visitor": "Courier", "purpose": "delivery",
        "detail": "Some courier guy with a box",
        "expected": "awaiting_resident",
        "expect_escalation": True,
    },
    {
        "id": "deliv-05",
        "why": ("auto_log_daytime is a blanket opt-in: on A-101 any known service in-window "
                "clears even though the always_allow rule names a different brand."),
        "flat": "A-101", "visitor": "Zomato", "purpose": "delivery",
        "detail": "Zomato food delivery",
        "expected": "auto_approved",
        "daytime_only": True,
    },

    # --- Intercom: interpreting the resident --------------------------------
    {
        "id": "icom-01",
        "why": "A plain ALLOW approves entry.",
        "flat": "A-103", "visitor": "Vikram Nair", "purpose": "guest",
        "detail": "Friend visiting for dinner",
        "replies": ["ALLOW"],
        "expected": "approved",
    },
    {
        "id": "icom-02",
        "why": "A plain DENY refuses entry.",
        "flat": "A-103", "visitor": "Unknown Salesman", "purpose": "other",
        "detail": "Door-to-door sales visit",
        "replies": ["DENY"],
        "expected": "denied",
    },
    {
        "id": "icom-03",
        "why": "Natural-language yes should be read as approval, not just the literal word.",
        "flat": "A-103", "visitor": "Meena Iyer", "purpose": "guest",
        "detail": "Cousin dropping by",
        "replies": ["yes that's my cousin, let her come up"],
        "expected": "approved",
    },
    {
        "id": "icom-04",
        "why": "Natural-language refusal should be read as a denial.",
        "flat": "A-103", "visitor": "Unknown Man", "purpose": "other",
        "detail": "Says he wants to discuss an investment plan",
        "replies": ["no, I don't know him, send him away"],
        "expected": "denied",
    },
    {
        "id": "icom-05",
        "why": "A question is not a decision -> stay open, don't resolve.",
        "flat": "A-103", "visitor": "Vikram Nair", "purpose": "guest",
        "detail": "Friend visiting for dinner",
        "replies": ["who is it? I'm not expecting anyone"],
        "expected": "awaiting_resident",
    },
    {
        "id": "icom-06",
        "why": "Full clarification loop: question -> guard answers -> resident approves.",
        "flat": "A-103", "visitor": "Vikram Nair", "purpose": "guest",
        "detail": "Friend visiting for dinner",
        "replies": [
            "who is it? I'm not expecting anyone",
            "he says he's Vikram, your college friend, here for dinner",
            "oh yes! let him in",
        ],
        "expected": "approved",
    },
    {
        "id": "icom-07",
        "why": "Deferring to the guard escalates rather than approving.",
        "flat": "A-103", "visitor": "Delivery Guy", "purpose": "delivery",
        "detail": "Parcel from an unnamed shop",
        "replies": ["I'm in a meeting, ask the guard to decide"],
        "expected": "escalated",
    },
    {
        "id": "icom-08",
        "why": "Clarification then refusal must end denied, not approved.",
        "flat": "A-103", "visitor": "Stranger", "purpose": "other",
        "detail": "Says he is here to read the water meter",
        "replies": [
            "did the society announce a meter reading today?",
            "no, the guard says there is no meter reading scheduled",
            "then don't let him in",
        ],
        "expected": "denied",
    },
]
