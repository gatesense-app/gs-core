"""
Delivery tools are DB-backed and tenant-scoped. These tests hit the live
database (no Claude API) so they run cheaply in CI.

    python -m pytest backend/tests/test_delivery_tools.py -v
"""

import pytest
from sqlalchemy import select, text

from backend import db_models as m
from backend.deps import scoped_session, system_session
from backend.tools.delivery_tools import (
    DeliveryContext,
    classify_delivery_service,
    flag_anomaly,
    get_delivery_pattern_history,
    get_resident_delivery_preferences,
)


@pytest.fixture
def two_societies():
    """
    Society A: resident with delivery prefs, a known delivery visitor (Blinkit),
    a tenant-specific known service (Milkman), and a pending delivery session
    (so flag_anomaly has a real session to attach an escalation to).
    Society B is separate, for the tenant-scoping check.
    """
    ids = {}
    with system_session() as db:
        a = m.Society(name="DT-Test-A")
        b = m.Society(name="DT-Test-B")
        db.add_all([a, b])
        db.flush()

        db.add(m.Resident(
            society_id=a.id, flat_number="A-101", name="Priya Sharma",
            delivery_preferences={"auto_log_daytime": True, "notify_after_hours": True, "after_hours_threshold": "20:00"},
        ))
        db.add(m.Visitor(
            society_id=a.id, name="Blinkit", visitor_type="delivery",
            is_known_service=True, visit_count=52,
            typical_hours={"start": "07:00", "end": "23:00"},
        ))
        db.add(m.Visitor(
            society_id=a.id, name="Milkman", visitor_type="delivery",
            is_known_service=True, visit_count=200,
            typical_hours={"start": "06:00", "end": "08:00"},
        ))
        db.add(m.Resident(society_id=b.id, flat_number="B-101", name="Arun Mehta"))

        session = m.VisitorSession(
            society_id=a.id, visitor_name="Rajesh", flat_number="A-101",
            purpose="delivery", purpose_detail="Parcel from a local shop", status="pending",
        )
        db.add(session)
        db.flush()
        ids["a"], ids["b"], ids["session"] = a.id, b.id, session.id

    yield ids

    with system_session() as db:
        db.execute(text("DELETE FROM societies WHERE name IN ('DT-Test-A', 'DT-Test-B')"))


def test_resident_delivery_preferences(two_societies):
    with scoped_session(two_societies["a"]) as db:
        ctx = DeliveryContext(db, two_societies["a"], None)
        prefs = get_resident_delivery_preferences(ctx, "A-101")
        assert prefs["found"] is True
        assert prefs["auto_log_daytime"] is True
        assert prefs["after_hours_threshold"] == "20:00"


def test_classify_curated_service(two_societies):
    with scoped_session(two_societies["a"]) as db:
        ctx = DeliveryContext(db, two_societies["a"], None)
        result = classify_delivery_service(ctx, "Blinkit grocery delivery")
        assert result["is_known_service"] is True
        assert result["matched_service"] == "blinkit"
        assert result["confidence"] == "high"


def test_classify_tenant_specific_service(two_societies):
    # "Milkman" isn't in the curated brand list, but this society knows it.
    with scoped_session(two_societies["a"]) as db:
        ctx = DeliveryContext(db, two_societies["a"], None)
        result = classify_delivery_service(ctx, "Daily milkman drop-off")
        assert result["is_known_service"] is True
        assert result["matched_service"] == "Milkman"
        assert result["confidence"] == "medium"


def test_classify_unknown_service(two_societies):
    with scoped_session(two_societies["a"]) as db:
        ctx = DeliveryContext(db, two_societies["a"], None)
        result = classify_delivery_service(ctx, "Parcel from a local shop")
        assert result["is_known_service"] is False


def test_pattern_history_uses_known_delivery_visitors(two_societies):
    with scoped_session(two_societies["a"]) as db:
        ctx = DeliveryContext(db, two_societies["a"], None)
        hist = get_delivery_pattern_history(ctx, "A-101")
        # Envelope spans the earliest start (Milkman 06:00) to latest end (Blinkit 23:00).
        assert hist["typical_hours"] == {"start": "06:00", "end": "23:00"}
        assert "Milkman" in hist["most_common_services"]
        # The seeded session is 'pending' delivery — counts toward prior deliveries.
        assert hist["prior_delivery_count"] >= 1


def test_flag_anomaly_persists_escalation(two_societies):
    with scoped_session(two_societies["a"]) as db:
        ctx = DeliveryContext(db, two_societies["a"], two_societies["session"])
        result = flag_anomaly(ctx, str(two_societies["session"]), "unknown_service", "Unrecognized courier")
        assert result["flagged"] is True

    # A separate scoped session confirms the row was committed and is tenant-scoped.
    with scoped_session(two_societies["a"]) as db:
        esc = db.execute(
            select(m.Escalation).where(m.Escalation.session_id == two_societies["session"])
        ).scalars().first()
        assert esc is not None
        assert esc.status == "open"
        assert "unknown_service" in esc.reason


def test_tools_are_tenant_scoped(two_societies):
    # From Society B, A's resident + known services are invisible (RLS).
    with scoped_session(two_societies["b"]) as db:
        ctx = DeliveryContext(db, two_societies["b"], None)
        assert get_resident_delivery_preferences(ctx, "A-101")["found"] is False
        assert classify_delivery_service(ctx, "Daily milkman drop-off")["is_known_service"] is False
