"""
Who does a flat mean, and whose rules apply? (E6-S3 / D3)

One module, because this is the question that decides who a real visitor waits
on. Before this, `gate_tools`, `delivery_tools` and `intercom_tools` each ran
their own `.first()` on `flat_number` — with one resident per flat that was
invisible, but with a family it means notifying an arbitrary person, and the
person notified could differ between the gate leg and the intercom leg of the
same visit.

Two rules, and everything here follows from them:

  1. **The contact is the flat's primary resident**, never "whichever row came
     back first". Every query is ordered, so the answer is the same every time.
  2. **Rules belong to the door.** A flat's own rules win when set; otherwise
     they fall back to the primary resident's. NULL means "not set" — distinct
     from [] meaning "explicitly no rules" — so introducing a layout can't
     silently overrule the rules a society already had.

Everything is keyed on `flat_number`, not `flat_id`: until reconcile runs, a
resident's flat_id is NULL, and the guard types a string. Callers pass
`society_id` explicitly rather than leaning on RLS, because the timeout sweeper
runs on a system session where a flat_number alone matches that flat in *every*
society.
"""

from sqlalchemy import select

from backend import db_models as m


def _residents_q(society_id, flat_number):
    """Every *live* resident of a flat, in a stable, total order."""
    return (
        select(m.Resident)
        .where(
            m.Resident.society_id == society_id,
            m.Resident.flat_number == flat_number,
            # A soft-deleted resident is gone as far as the gate is concerned;
            # this is the one filter that keeps a removed person unreachable.
            m.Resident.deleted_at.is_(None),
        )
        # is_primary first, then oldest. The id tiebreak makes this a total
        # order: created_at can collide (a CSV import writes many rows in one
        # transaction, and now() is fixed per transaction), and a tie here would
        # reintroduce exactly the arbitrariness this module exists to remove.
        .order_by(
            m.Resident.is_primary.desc(),
            m.Resident.created_at.asc(),
            m.Resident.id.asc(),
        )
    )


def primary_resident(db, society_id, flat_number: str):
    """
    The one person the agents contact for this flat, or None if it's vacant.

    Falls back to the oldest resident when no primary flag is set, so a flat
    whose primary was removed is never left uncontactable — the next read
    promotes the same deterministic successor the API would have chosen.
    """
    return db.execute(_residents_q(society_id, flat_number)).scalars().first()


def flat_residents(db, society_id, flat_number: str) -> list:
    """Everyone behind this door, primary first (D3)."""
    return list(db.execute(_residents_q(society_id, flat_number)).scalars().all())


def other_flat_residents(db, society_id, flat_number: str, exclude_id) -> list:
    """
    The rest of the household — the escalation chain.

    A visitor left waiting on a silent primary should reach the spouse standing
    right there before it reaches the guard.
    """
    return [r for r in flat_residents(db, society_id, flat_number) if r.id != exclude_id]


def flat_for(db, society_id, flat_number: str):
    """The live Flat whose code is this string, or None if there's no layout yet."""
    return db.execute(
        select(m.Flat).where(
            m.Flat.society_id == society_id,
            m.Flat.code == flat_number,
            m.Flat.deleted_at.is_(None),
        )
    ).scalars().first()


def has_primary(db, society_id, flat_number: str) -> bool:
    """
    Is anyone actually *flagged* the contact for this door?

    Distinct from `primary_resident`, which always answers with somebody when the
    flat has residents (it falls back to the oldest). Callers deciding whether to
    appoint a contact need to know the difference: appointing one where a flag
    already exists would depose a contact somebody chose.
    """
    return db.execute(
        select(m.Resident.id).where(
            m.Resident.society_id == society_id,
            m.Resident.flat_number == flat_number,
            m.Resident.is_primary,
            m.Resident.deleted_at.is_(None),
        )
    ).first() is not None


# ---------------------------------------------------------------------------
# Maintaining the invariant
#
# These write helpers live next to the readers on purpose: "exactly one primary
# per flat" is enforced by a partial unique index, and any caller that moves a
# resident between flats has to keep that index happy. One home for the rule
# beats four routers each remembering it.
# ---------------------------------------------------------------------------
def link_exact_matches(db, society_id, flat) -> int:
    """
    Adopt the residents already sitting on this flat's code (D4).

    Introducing a layout must not orphan anyone, so every path that brings a flat
    into existence — typing one in (E4-S2), importing a file (E3), or the
    reconcile sweep (E4-S4) — adopts the free-text residents already on its code.
    It lives here rather than in a router so those paths can't drift apart.

    Exact string match only: an inexact guess is a human's call (see the
    reconcile report's suggestions). Never re-points a resident who is already
    linked, so running it twice is a no-op rather than a reshuffle. Deliberately
    does not touch `is_primary` — adopting somebody is not a reason to depose the
    contact their door already had.
    """
    rows = db.execute(
        select(m.Resident).where(
            m.Resident.society_id == society_id,
            m.Resident.flat_number == flat.code,
            m.Resident.flat_id.is_(None),
            m.Resident.deleted_at.is_(None),  # don't resurrect a removed resident
        )
    ).scalars().all()
    for resident in rows:
        resident.flat_id = flat.id
    if rows:
        db.flush()
    return len(rows)


def ensure_primary(db, society_id, flat_number: str):
    """
    Guarantee a flat with residents has exactly one primary.

    Called after anything that could leave a flat without one — a resident added,
    moved, removed, or reconciled onto a different code. A flat with residents is
    never left uncontactable; an empty one needs no contact.
    """
    residents = flat_residents(db, society_id, flat_number)
    if not residents:
        return None
    primaries = [r for r in residents if r.is_primary]
    if primaries:
        return primaries[0]  # the index guarantees there is at most one
    # Deterministic promotion: the oldest, which is the same successor
    # primary_resident() would already have been falling back to.
    residents[0].is_primary = True
    db.flush()
    return residents[0]


def resync_primary(db, society_id, flat_number: str):
    """
    Re-elect the flat's primary contact from the role its occupancy calls for.

    A tenant-occupied flat should reach a *tenant*; an owner-occupied one, the
    *owner*. So the gate's contact (is_primary) is drawn from that role's pool,
    falling back to the whole household when the pool is empty — a tenant-occupied
    flat with no tenant yet still reaches its owner rather than nobody.

    Idempotent: if the sitting primary already belongs to the right pool it stays,
    so this never reshuffles a contact somebody deliberately chose within the pool.
    Callers run it after anything that could change the answer — occupancy toggled,
    a resident added, removed, or re-roled. Reads is_primary; the gate is untouched.
    """
    residents = flat_residents(db, society_id, flat_number)
    if not residents:
        return None
    flat = flat_for(db, society_id, flat_number)
    prefer = flat.occupancy if flat is not None else "owner"
    pool = [r for r in residents if r.role == prefer] or residents
    current = next((r for r in residents if r.is_primary), None)
    chosen = current if current is not None and current in pool else pool[0]
    if not chosen.is_primary:
        claim_primary(db, chosen)
    return chosen


def claim_primary(db, resident) -> None:
    """
    Make this resident their flat's primary contact, demoting the incumbent.

    The demote must be flushed before the claim: the partial unique index would
    otherwise see two primaries for the flat mid-statement and reject it.
    """
    for other in flat_residents(db, resident.society_id, resident.flat_number):
        if other.id != resident.id and other.is_primary:
            other.is_primary = False
    db.flush()
    resident.is_primary = True
    db.flush()


def release_primary(db, resident) -> None:
    """
    Take a resident out of the primary slot before their flat_number changes.

    Moving a primary onto a door that already has one violates the index, so
    callers that rewrite flat_number (reconcile, resident edit) release first
    and re-`ensure_primary` both doors afterwards.
    """
    if resident.is_primary:
        resident.is_primary = False
        db.flush()


def resolve_rules(db, society_id, flat_number: str) -> dict:
    """
    The standing rules and delivery preferences that apply at this door.

    The flat wins where it has an opinion; each field falls back independently,
    so a flat can set delivery preferences without being forced to restate its
    standing rules. `resident` is the person those rules will reach; it is None
    for a flat nobody lives in, and each caller keeps its own shape for that.

    Only None means "unset". An empty {} is a resident's real answer and is
    returned as-is — substituting defaults for it would quietly change what the
    agents see.
    """
    resident = primary_resident(db, society_id, flat_number)
    flat = flat_for(db, society_id, flat_number)

    rules = flat.standing_rules if flat is not None else None
    prefs = flat.delivery_preferences if flat is not None else None
    if rules is None:
        rules = resident.standing_rules or [] if resident is not None else []
    if prefs is None:
        prefs = resident.delivery_preferences if resident is not None else None
    if prefs is None:
        prefs = {}

    return {
        "resident": resident,
        "flat": flat,
        "standing_rules": rules,
        "delivery_preferences": prefs,
    }
