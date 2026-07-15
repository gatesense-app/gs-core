"""
The API speaks one error shape, and internals never reach the client.

    python -m pytest backend/tests/test_errors.py -v
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from backend import db_models as m
from backend import main as mn
from backend.deps import system_session
from backend.main import app
from backend.security import create_access_token

client = TestClient(app)
SOCIETY = "00000000-0000-0000-0000-0000000000aa"


@pytest.fixture
def society_with_session():
    """A real society with one session, so list_sessions actually serializes a row."""
    with system_session() as db:
        db.execute(text("DELETE FROM societies WHERE name = 'ERR-Test'"))
        soc = m.Society(name="ERR-Test")
        db.add(soc)
        db.flush()
        db.add(m.VisitorSession(
            society_id=soc.id, visitor_name="Vikram", flat_number="A-101",
            purpose="guest", purpose_detail="Dinner", status="awaiting_resident",
        ))
        db.flush()
        sid = str(soc.id)
    yield sid
    with system_session() as db:
        db.execute(text("DELETE FROM societies WHERE name = 'ERR-Test'"))


def _hdr(role="society_admin", society=SOCIETY):
    token = create_access_token(
        user_id="00000000-0000-0000-0000-000000000000", society_id=society, role=role)
    return {"Authorization": f"Bearer {token}"}


def _assert_shape(body):
    assert set(body) == {"error"}, body
    assert set(body["error"]) == {"code", "message"}
    assert isinstance(body["error"]["message"], str) and body["error"]["message"]


def test_unauthorized_shape():
    r = client.get("/sessions")
    assert r.status_code == 401
    _assert_shape(r.json())
    assert r.json()["error"]["code"] == "unauthorized"


def test_forbidden_shape():
    # A guard may not reach admin observability.
    r = client.get("/admin/notification-log", headers=_hdr(role="guard"))
    assert r.status_code == 403
    _assert_shape(r.json())
    assert r.json()["error"]["code"] == "forbidden"


def test_not_found_shape():
    r = client.get(f"/sessions/{'0' * 8}-0000-0000-0000-000000000000", headers=_hdr())
    assert r.status_code == 404
    _assert_shape(r.json())
    assert r.json()["error"]["code"] == "not_found"


def test_validation_error_names_fields_without_echoing_values():
    secret = "sup3r-s3cret-value"
    r = client.post("/sessions", headers=_hdr(role="guard"),
                    json={"visitor_name": secret})  # missing required fields
    assert r.status_code == 422
    body = r.json()
    _assert_shape(body)
    assert body["error"]["code"] == "validation_error"
    # Names the offending fields...
    assert "flat_number" in body["error"]["message"]
    # ...but does not echo submitted input back to the caller.
    assert secret not in body["error"]["message"]


def test_unhandled_exception_is_generic_and_leaks_nothing(society_with_session, monkeypatch):
    """A crash must not disclose the traceback, exception text, or SQL."""
    boom = "SECRET_INTERNAL_DETAIL_relation_visitor_sessions"

    def explode(*a, **k):
        raise RuntimeError(boom)

    # list_sessions calls serialize() per row; make it blow up on a real row.
    monkeypatch.setattr(mn, "serialize", explode)

    # Let the app's handler produce the response instead of re-raising.
    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.get("/sessions", headers=_hdr(society=society_with_session))

    assert r.status_code == 500
    body = r.json()
    _assert_shape(body)
    assert body["error"]["code"] == "internal_error"
    assert boom not in r.text
    assert "Traceback" not in r.text
    assert "RuntimeError" not in r.text
