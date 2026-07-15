"""
Resident portal + flat-level authorization.

RLS scopes to the society; these prove the second layer — a resident may only
ever see or answer their OWN flat's visitors, never a neighbour's. No Claude API
is used: the authorization checks all run before the agent pipeline, so the
negative cases never reach an agent.

    python -m pytest backend/tests/test_portal.py -v
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from backend import db_models as m
from backend.deps import system_session
from backend.main import app
from backend.security import create_access_token, hash_password

client = TestClient(app)


@pytest.fixture
def society():
    """One society, two flats (A-101 / A-102), each with a linked resident user
    and a session awaiting a reply. Plus a resident user linked to no flat."""
    ids = {}
    with system_session() as db:
        db.execute(text("DELETE FROM societies WHERE name = 'PORTAL-Test'"))
        soc = m.Society(name="PORTAL-Test")
        db.add(soc)
        db.flush()

        r1 = m.Resident(
            society_id=soc.id, flat_number="A-101", name="Priya Sharma",
            standing_rules=[{"type": "always_allow", "match": "Swiggy"}],
            delivery_preferences={"auto_log_daytime": True},
        )
        r2 = m.Resident(society_id=soc.id, flat_number="A-102", name="Arun Mehta")
        db.add_all([r1, r2])
        db.flush()

        u1 = m.User(society_id=soc.id, email="p@portal.test", password_hash=hash_password("x"),
                    role="resident", full_name="Priya", resident_id=r1.id)
        u2 = m.User(society_id=soc.id, email="a@portal.test", password_hash=hash_password("x"),
                    role="resident", full_name="Arun", resident_id=r2.id)
        u3 = m.User(society_id=soc.id, email="orphan@portal.test", password_hash=hash_password("x"),
                    role="resident", full_name="Orphan", resident_id=None)
        db.add_all([u1, u2, u3])

        s1 = m.VisitorSession(society_id=soc.id, visitor_name="Vikram", flat_number="A-101",
                              purpose="guest", purpose_detail="Dinner", status="awaiting_resident")
        s2 = m.VisitorSession(society_id=soc.id, visitor_name="Neighbour Guest", flat_number="A-102",
                              purpose="guest", purpose_detail="Visit", status="awaiting_resident")
        db.add_all([s1, s2])
        db.flush()

        ids = {
            "sid": soc.id,
            "u1": str(u1.id), "u2": str(u2.id), "u3": str(u3.id),
            "s1": str(s1.id), "s2": str(s2.id),
        }

    yield ids

    with system_session() as db:
        db.execute(text("DELETE FROM societies WHERE name = 'PORTAL-Test'"))


def _hdr(user_id, society_id):
    token = create_access_token(user_id=user_id, society_id=str(society_id), role="resident")
    return {"Authorization": f"Bearer {token}"}


def test_portal_me_returns_own_flat(society):
    r = client.get("/portal/me", headers=_hdr(society["u1"], society["sid"]))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["flat_number"] == "A-101"
    assert {"type": "always_allow", "match": "Swiggy"} in body["standing_rules"]


def test_portal_sessions_only_own_flat(society):
    r = client.get("/portal/sessions", headers=_hdr(society["u1"], society["sid"]))
    assert r.status_code == 200, r.text
    flats = {s["flat_number"] for s in r.json()}
    assert flats == {"A-101"}  # A-102's session must not leak


def test_resident_can_read_own_flat_session(society):
    r = client.get(f"/sessions/{society['s1']}", headers=_hdr(society["u1"], society["sid"]))
    assert r.status_code == 200
    assert r.json()["flat_number"] == "A-101"


def test_resident_cannot_read_other_flat_session(society):
    # 404 (not 403) so we don't confirm the session exists.
    r = client.get(f"/sessions/{society['s2']}", headers=_hdr(society["u1"], society["sid"]))
    assert r.status_code == 404


def test_resident_cannot_reply_to_other_flat_session(society):
    r = client.post(
        f"/sessions/{society['s2']}/reply",
        json={"reply": "ALLOW"},
        headers=_hdr(society["u1"], society["sid"]),
    )
    assert r.status_code == 404  # rejected before the intercom agent runs


def test_resident_updates_own_rules(society):
    r = client.patch(
        "/portal/rules",
        json={
            "standing_rules": [{"type": "never_allow", "after": "21:00"}],
            "delivery_preferences": {"auto_log_daytime": False, "notify_after_hours": True},
        },
        headers=_hdr(society["u1"], society["sid"]),
    )
    assert r.status_code == 200, r.text
    assert r.json()["standing_rules"] == [{"type": "never_allow", "after": "21:00"}]

    # Persisted, and the flat was not changed by the update.
    r2 = client.get("/portal/me", headers=_hdr(society["u1"], society["sid"]))
    assert r2.json()["flat_number"] == "A-101"
    assert r2.json()["delivery_preferences"]["notify_after_hours"] is True


def test_resident_user_without_flat_is_rejected(society):
    r = client.get("/portal/me", headers=_hdr(society["u3"], society["sid"]))
    assert r.status_code == 403


def test_non_resident_cannot_use_portal(society):
    token = create_access_token(user_id=society["u1"], society_id=str(society["sid"]), role="guard")
    r = client.get("/portal/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403
