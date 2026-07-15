"""
The headline multi-tenancy proof: Postgres RLS keeps Society A's data invisible
to a Society B request, even for a crafted query — and blocks cross-tenant
writes. Runs against the live database (docker-compose Postgres).

    python -m pytest backend/tests/test_rls.py -v
"""

import pytest
from sqlalchemy import select, text

from backend import db_models as m
from backend.deps import scoped_session, system_session


@pytest.fixture
def two_societies():
    """Two throwaway societies, one resident each. Cleaned up after."""
    ids = {}
    with system_session() as db:
        a = m.Society(name="RLS-Test-A")
        b = m.Society(name="RLS-Test-B")
        db.add_all([a, b])
        db.flush()
        db.add(m.Resident(society_id=a.id, flat_number="A-1", name="Alice"))
        db.add(m.Resident(society_id=b.id, flat_number="B-1", name="Bob"))
        db.flush()
        ids["a"], ids["b"] = a.id, b.id

    yield ids

    with system_session() as db:
        db.execute(
            text("DELETE FROM societies WHERE name IN ('RLS-Test-A', 'RLS-Test-B')")
        )


def test_scoped_read_sees_only_own_society(two_societies):
    a, b = two_societies["a"], two_societies["b"]

    with scoped_session(a) as db:
        rows = db.execute(select(m.Resident)).scalars().all()
        assert rows, "Society A should see its own residents"
        assert all(str(r.society_id) == str(a) for r in rows)

        # Crafted cross-tenant query returns nothing — RLS filters before WHERE.
        crafted = db.execute(
            select(m.Resident).where(m.Resident.society_id == b)
        ).scalars().all()
        assert crafted == []

    with scoped_session(b) as db:
        names = [r.name for r in db.execute(select(m.Resident)).scalars().all()]
        assert "Bob" in names
        assert "Alice" not in names


def test_scoped_write_check_blocks_cross_tenant_insert(two_societies):
    a, b = two_societies["a"], two_societies["b"]

    # Scoped to A, try to insert a row belonging to B -> RLS WITH CHECK violation.
    with pytest.raises(Exception):
        with scoped_session(a) as db:
            db.add(m.Resident(society_id=b, flat_number="X-9", name="Mallory"))
            db.flush()


def test_platform_bypass_sees_all(two_societies):
    with scoped_session(None, bypass=True) as db:
        names = [r.name for r in db.execute(select(m.Resident)).scalars().all()]
        assert "Alice" in names
        assert "Bob" in names
