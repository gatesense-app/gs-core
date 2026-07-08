"""
Gate tools are DB-backed and tenant-scoped. These tests hit the live database
(no Claude API) so they run cheaply in CI.

    python -m pytest backend/tests/test_gate_tools.py -v
"""

import pytest
from sqlalchemy import text

from backend import db_models as m
from backend.deps import scoped_session, system_session
from backend.tools.gate_tools import GateContext, get_resident_rules, lookup_visitor_history


@pytest.fixture
def two_societies():
    """Society A has a resident with a rule + a known visitor; B is separate."""
    ids = {}
    with system_session() as db:
        a = m.Society(name="GT-Test-A")
        b = m.Society(name="GT-Test-B")
        db.add_all([a, b])
        db.flush()
        db.add(m.Resident(
            society_id=a.id, flat_number="A-101", name="Priya Sharma",
            standing_rules=[{"type": "always_allow", "match": "Swiggy"}],
            delivery_preferences={"auto_log_daytime": True},
        ))
        db.add(m.Visitor(
            society_id=a.id, name="Swiggy", visitor_type="delivery",
            is_known_service=True, visit_count=40,
            typical_hours={"start": "11:00", "end": "22:00"},
        ))
        db.add(m.Resident(society_id=b.id, flat_number="B-101", name="Arun Mehta"))
        db.flush()
        ids["a"], ids["b"] = a.id, b.id

    yield ids

    with system_session() as db:
        db.execute(text("DELETE FROM societies WHERE name IN ('GT-Test-A', 'GT-Test-B')"))


def test_get_resident_rules_returns_standing_rules(two_societies):
    with scoped_session(two_societies["a"]) as db:
        ctx = GateContext(db, two_societies["a"], None)
        rules = get_resident_rules(ctx, "A-101")
        assert rules["resident_name"] == "Priya Sharma"
        assert {"type": "always_allow", "match": "Swiggy"} in rules["standing_rules"]


def test_lookup_visitor_history_found(two_societies):
    with scoped_session(two_societies["a"]) as db:
        ctx = GateContext(db, two_societies["a"], None)
        hist = lookup_visitor_history(ctx, "Swiggy", "A-101")
        assert hist["found"] is True
        assert hist["visit_count"] == 40
        assert hist["is_known_service"] is True


def test_lookup_unknown_visitor(two_societies):
    with scoped_session(two_societies["a"]) as db:
        ctx = GateContext(db, two_societies["a"], None)
        assert lookup_visitor_history(ctx, "Nobody", "A-101")["found"] is False


def test_tools_are_tenant_scoped(two_societies):
    # From Society B, A's visitor and resident are invisible (RLS).
    with scoped_session(two_societies["b"]) as db:
        ctx = GateContext(db, two_societies["b"], None)
        assert lookup_visitor_history(ctx, "Swiggy", "A-101")["found"] is False
        assert get_resident_rules(ctx, "A-101")["resident_name"] == "Unknown Resident"
