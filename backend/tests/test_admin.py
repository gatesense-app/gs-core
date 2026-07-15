"""
Admin observability endpoints: notification health + per-session audit.

Covers the role gates (guards/residents must not reach admin observability) and
tenant scoping (Society B's admin must never see Society A's notifications). No
Claude API is used — rows are seeded directly.

    python -m pytest backend/tests/test_admin.py -v
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from backend import db_models as m
from backend.deps import system_session
from backend.main import app
from backend.security import create_access_token

client = TestClient(app)


@pytest.fixture
def two_societies():
    """Society A has a session with an escalation + notification; B is separate."""
    with system_session() as db:
        db.execute(text("DELETE FROM societies WHERE name IN ('ADM-Test-A', 'ADM-Test-B')"))
        a = m.Society(name="ADM-Test-A")
        b = m.Society(name="ADM-Test-B")
        db.add_all([a, b])
        db.flush()

        res = m.Resident(society_id=a.id, flat_number="A-101", name="Priya Sharma")
        db.add(res)
        db.flush()

        sess = m.VisitorSession(
            society_id=a.id, visitor_name="Vikram Nair", flat_number="A-101",
            purpose="guest", purpose_detail="Dinner", status="awaiting_resident",
        )
        db.add(sess)
        db.flush()

        db.add(m.NotificationDeliveryLog(
            society_id=a.id, session_id=sess.id, resident_id=res.id,
            channel="in_app", status="sent",
        ))
        db.add(m.Escalation(
            society_id=a.id, session_id=sess.id, reason="[unknown_service] Unrecognized courier",
            escalated_to="guard_default", status="open",
        ))
        db.add(m.ConversationLog(
            society_id=a.id, session_id=sess.id, turn_number=1,
            speaker="agent", message="Visitor at the gate",
        ))
        db.flush()

        ids = {"a": a.id, "b": b.id, "session": str(sess.id)}

    yield ids

    with system_session() as db:
        db.execute(text("DELETE FROM societies WHERE name IN ('ADM-Test-A', 'ADM-Test-B')"))


def _hdr(society_id, role="society_admin"):
    token = create_access_token(
        user_id="00000000-0000-0000-0000-000000000000",
        society_id=str(society_id) if society_id else None,
        role=role,
    )
    return {"Authorization": f"Bearer {token}"}


def test_notification_log_lists_own_society(two_societies):
    r = client.get("/admin/notification-log", headers=_hdr(two_societies["a"]))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] >= 1
    assert body["summary"].get("sent", 0) >= 1
    row = next(n for n in body["notifications"] if n["session_id"] == two_societies["session"])
    assert row["resident_name"] == "Priya Sharma"
    assert row["flat_number"] == "A-101"
    assert row["visitor_name"] == "Vikram Nair"
    assert row["status"] == "sent"


def test_notification_log_is_tenant_scoped(two_societies):
    # Society B's admin sees none of A's notifications (RLS).
    r = client.get("/admin/notification-log", headers=_hdr(two_societies["b"]))
    assert r.status_code == 200
    assert r.json()["notifications"] == []


def test_session_audit_returns_full_trail(two_societies):
    r = client.get(f"/admin/sessions/{two_societies['session']}/audit", headers=_hdr(two_societies["a"]))
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["escalations"]) == 1
    assert "unknown_service" in body["escalations"][0]["reason"]
    assert body["escalations"][0]["escalated_to"] == "guard_default"
    assert len(body["notifications"]) == 1
    assert body["notifications"][0]["resident_name"] == "Priya Sharma"
    assert [t["speaker"] for t in body["conversation_log"]] == ["agent"]


def test_session_audit_is_tenant_scoped(two_societies):
    # A's session is invisible to B's admin -> 404, not another society's data.
    r = client.get(f"/admin/sessions/{two_societies['session']}/audit", headers=_hdr(two_societies["b"]))
    assert r.status_code == 404


@pytest.mark.parametrize("role", ["guard", "resident"])
def test_non_admins_cannot_reach_admin_endpoints(two_societies, role):
    h = _hdr(two_societies["a"], role=role)
    assert client.get("/admin/notification-log", headers=h).status_code == 403
    assert client.get(f"/admin/sessions/{two_societies['session']}/audit", headers=h).status_code == 403


def test_admin_endpoints_require_auth(two_societies):
    assert client.get("/admin/notification-log").status_code == 401
