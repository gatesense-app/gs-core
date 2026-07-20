"""
Society layout — wings (E4-S1) and flats (E4-S2).

The split follows D2: a wing *declares the shape of a grid* and creates no
flats; a flat is entered one at a time with a code the admin typed. Nothing here
generates or infers a code, and nothing derives a floor from one (Q1).

Editing a wing (E4-S3), reconcile (E4-S4) and CSV import (E3) are later stories.
"""

import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select

from backend import audit
from backend import db_models as m
from backend.deps import CurrentUser, get_db, require_role
from backend.routers.common import parse_uuid, resolve_society_id
from backend.schemas import (
    FlatCreate,
    FlatResponse,
    FlatUpdate,
    ReconcileLink,
    ReconcileReport,
    TimelineEvent,
    UnmatchedResident,
    WingCreate,
    WingResponse,
    WingUpdate,
)
from backend.tools import resolve


def _now():
    return datetime.now(timezone.utc)

router = APIRouter(tags=["layout"])

_admins = require_role("platform_admin", "society_admin")


def _flat_counts(db, wing_ids: list) -> dict:
    """wing_id -> number of *live* flats. One query, not N."""
    if not wing_ids:
        return {}
    rows = db.execute(
        select(m.Flat.wing_id, func.count(m.Flat.id))
        .where(m.Flat.wing_id.in_(wing_ids), m.Flat.deleted_at.is_(None))
        .group_by(m.Flat.wing_id)
    ).all()
    return {wid: count for wid, count in rows}


def _wing_resp(w: m.Wing, flat_count: int, warnings: list[str] | None = None) -> WingResponse:
    return WingResponse(
        id=str(w.id),
        society_id=str(w.society_id),
        name=w.name,
        floors=w.floors,
        flats_per_floor=w.flats_per_floor,
        flat_count=flat_count,
        warnings=warnings or [],
    )


def _flat_resp(
    f: m.Flat,
    wing_name: str,
    warnings: list[str] | None = None,
    linked_residents: int = 0,
) -> FlatResponse:
    return FlatResponse(
        id=str(f.id),
        society_id=str(f.society_id),
        wing_id=str(f.wing_id),
        wing_name=wing_name,
        flat_number=f.flat_number,
        floor=f.floor,
        code=f.code,
        warnings=warnings or [],
        linked_residents=linked_residents,
        standing_rules=f.standing_rules,
        delivery_preferences=f.delivery_preferences,
        deleted_at=f.deleted_at,
    )


def _get_wing(db, wing_id: str) -> m.Wing:
    wing = db.get(m.Wing, parse_uuid(wing_id))
    if wing is None:  # RLS hides other societies' rows -> looks like 404
        raise HTTPException(404, "Wing not found")
    return wing


# ---------------------------------------------------------------------------
# E4-S1 — wings
# ---------------------------------------------------------------------------
@router.post("/wings", status_code=201, response_model=WingResponse)
def create_wing(body: WingCreate, user: CurrentUser = Depends(_admins), db=Depends(get_db)):
    """
    Declare a wing. Creates no flats — the grid renders empty until they are
    entered (E4-S2) or imported (E3). Floors/flats-per-floor may differ freely
    between wings in the same society.
    """
    society_id = resolve_society_id(user, body.society_id)
    name = body.name.strip()
    if not name:
        raise HTTPException(422, "Wing name is required")

    # Checked up front for a clear message; the unique constraint is the real guard.
    exists = db.execute(
        select(m.Wing.id).where(m.Wing.society_id == society_id, m.Wing.name == name)
    ).first()
    if exists:
        raise HTTPException(409, f"A wing named '{name}' already exists in this society")

    wing = m.Wing(
        society_id=society_id,
        name=name,
        floors=body.floors,
        flats_per_floor=body.flats_per_floor,
    )
    db.add(wing)
    try:
        db.flush()
    except Exception:
        # Lost a race against a concurrent create with the same name.
        raise HTTPException(409, f"A wing named '{name}' already exists in this society")
    return _wing_resp(wing, 0)


@router.get("/wings", response_model=list[WingResponse])
def list_wings(
    society_id: str | None = None,
    user: CurrentUser = Depends(_admins),
    db=Depends(get_db),
):
    """A society's wings, each with its real flat count."""
    sid = resolve_society_id(user, society_id)
    rows = db.execute(
        select(m.Wing).where(m.Wing.society_id == parse_uuid(sid)).order_by(m.Wing.name)
    ).scalars().all()
    counts = _flat_counts(db, [w.id for w in rows])
    return [_wing_resp(w, counts.get(w.id, 0)) for w in rows]


@router.get("/wings/{wing_id}", response_model=WingResponse)
def get_wing(wing_id: str, _: CurrentUser = Depends(_admins), db=Depends(get_db)):
    wing = _get_wing(db, wing_id)
    return _wing_resp(wing, _flat_counts(db, [wing.id]).get(wing.id, 0))


# ---------------------------------------------------------------------------
# E4-S3 — edit a wing after the fact
# ---------------------------------------------------------------------------
def _declared_shape_warnings(db, wing: m.Wing) -> list[str]:
    """
    Flats that no longer fit the declared shape (Q2).

    Reducing the shape never deletes a flat, so a wing shrunk below its real
    contents keeps everything and says so. Silence here would read as "nothing
    happened" when in fact the grid now disagrees with reality.
    """
    warnings = []
    above = db.execute(
        select(func.count(m.Flat.id)).where(
            m.Flat.wing_id == wing.id, m.Flat.floor > wing.floors,
            m.Flat.deleted_at.is_(None),
        )
    ).scalar_one()
    if above:
        warnings.append(
            f"{above} flat(s) sit above the {wing.floors} floor(s) now declared. "
            f"Nothing was deleted — they are kept and still drawn."
        )
    crowded = db.execute(
        select(m.Flat.floor)
        .where(m.Flat.wing_id == wing.id, m.Flat.deleted_at.is_(None))
        .group_by(m.Flat.floor)
        .having(func.count(m.Flat.id) > wing.flats_per_floor)
    ).scalars().all()
    if crowded:
        warnings.append(
            f"{len(crowded)} floor(s) hold more than the {wing.flats_per_floor} "
            f"flat(s) per floor now declared. Kept as they are — the shape is a hint."
        )
    return warnings


@router.patch("/wings/{wing_id}", response_model=WingResponse)
def update_wing(
    wing_id: str,
    body: WingUpdate,
    _: CurrentUser = Depends(_admins),
    db=Depends(get_db),
):
    """
    Correct a wing: rename it, or change the shape of its grid.

    **A rename does not rewrite existing flat codes.** `visitor_sessions`
    records the flat string a guard typed at the time; rewriting `A-101` to
    `B-101` would silently retitle history that already happened, and the agents
    resolve residents by that same string. So existing flats keep their codes and
    only new flats use the new name — the response says how many were kept.

    Changing floors / flats-per-floor only redraws the grid: the declared shape
    is a drawing hint (Q2), never a constraint, so reducing it cannot delete a
    flat. Anything now outside the shape comes back as a warning.
    """
    wing = _get_wing(db, wing_id)
    fields = body.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(422, "Nothing to update")

    warnings: list[str] = []
    flat_count = _flat_counts(db, [wing.id]).get(wing.id, 0)

    if "name" in fields:
        new_name = fields["name"].strip()
        if not new_name:
            raise HTTPException(422, "Wing name is required")
        if new_name != wing.name:
            exists = db.execute(
                select(m.Wing.id).where(
                    m.Wing.society_id == wing.society_id,
                    m.Wing.name == new_name,
                    m.Wing.id != wing.id,
                )
            ).first()
            if exists:
                raise HTTPException(
                    409, f"A wing named '{new_name}' already exists in this society"
                )
            if flat_count:
                sample = db.execute(
                    select(m.Flat.code)
                    .where(m.Flat.wing_id == wing.id, m.Flat.deleted_at.is_(None))
                    .order_by(m.Flat.code)
                ).scalars().first()
                warnings.append(
                    f"{flat_count} existing flat(s) keep their codes (e.g. {sample}) so "
                    f"visitor history stays meaningful. Only new flats use '{new_name}'."
                )
            wing.name = new_name

    if "floors" in fields:
        wing.floors = fields["floors"]
    if "flats_per_floor" in fields:
        wing.flats_per_floor = fields["flats_per_floor"]

    try:
        db.flush()
    except Exception:
        # Lost a race against a concurrent rename to the same name.
        raise HTTPException(409, "A wing with that name already exists in this society")

    warnings += _declared_shape_warnings(db, wing)
    return _wing_resp(wing, flat_count, warnings)


@router.delete("/wings/{wing_id}", status_code=204)
def delete_wing(wing_id: str, _: CurrentUser = Depends(_admins), db=Depends(get_db)):
    """
    Remove a wing declared by mistake. Refused once it has flats — the CASCADE
    would take occupied flats with it, which is not a thing to do silently.
    """
    wing = _get_wing(db, wing_id)
    count = _flat_counts(db, [wing.id]).get(wing.id, 0)
    if count:
        raise HTTPException(
            409,
            f"Wing '{wing.name}' still has {count} flat(s). Delete them first.",
        )
    db.delete(wing)
    db.flush()


# ---------------------------------------------------------------------------
# E4-S4 — reconcile free-text residents onto flats (D4)
# ---------------------------------------------------------------------------
def _normalize(code: str) -> str:
    """`A-101`, `A 101` and `a101` are the same flat to a human. Nothing else is."""
    return re.sub(r"[^a-z0-9]", "", code.lower())


def _build_report(db, society_id) -> ReconcileReport:
    flats = db.execute(
        select(m.Flat).where(
            m.Flat.society_id == society_id, m.Flat.deleted_at.is_(None))
    ).scalars().all()
    residents = db.execute(
        select(m.Resident).where(
            m.Resident.society_id == society_id, m.Resident.deleted_at.is_(None))
    ).scalars().all()

    # Normalized index, used only to *suggest*. Codes are unique per society, but
    # `A-101` and `A101` can both exist — an ambiguous key suggests nothing.
    by_norm: dict[str, list[m.Flat]] = {}
    for f in flats:
        by_norm.setdefault(_normalize(f.code), []).append(f)

    unmatched = []
    linked = 0
    for r in residents:
        if r.flat_id is not None:
            linked += 1
            continue
        candidates = by_norm.get(_normalize(r.flat_number), [])
        suggestion = candidates[0] if len(candidates) == 1 else None
        unmatched.append(UnmatchedResident(
            resident_id=str(r.id),
            name=r.name,
            flat_number=r.flat_number,
            suggested_flat_id=str(suggestion.id) if suggestion else None,
            suggested_code=suggestion.code if suggestion else None,
        ))

    return ReconcileReport(
        society_id=str(society_id),
        flat_count=len(flats),
        linked=linked,
        unmatched_count=len(unmatched),
        unmatched=unmatched,
    )


@router.get("/reconcile", response_model=ReconcileReport)
def reconcile_report(
    society_id: str | None = None,
    user: CurrentUser = Depends(_admins),
    db=Depends(get_db),
):
    """
    Who is linked, and who still needs a human. Read-only — changes nothing.

    Everyone unmatched is listed: a resident is never dropped just because the
    layout doesn't describe them yet.
    """
    return _build_report(db, parse_uuid(resolve_society_id(user, society_id)))


@router.post("/reconcile/run", response_model=ReconcileReport)
def reconcile_run(
    society_id: str | None = None,
    user: CurrentUser = Depends(_admins),
    db=Depends(get_db),
):
    """
    Link every resident whose flat_number is exactly a flat code.

    Idempotent, and the safety net for residents added before their flat existed
    (flat creation already adopts the ones present at the time). Anything left
    over comes back in `unmatched` for manual resolution.
    """
    sid = parse_uuid(resolve_society_id(user, society_id))
    live_flats = db.execute(
        select(m.Flat).where(m.Flat.society_id == sid, m.Flat.deleted_at.is_(None))
    ).scalars().all()
    for flat in live_flats:
        resolve.link_exact_matches(db, sid, flat)
    return _build_report(db, sid)


@router.post("/reconcile/link", response_model=ReconcileReport)
def reconcile_link(
    body: ReconcileLink,
    user: CurrentUser = Depends(_admins),
    db=Depends(get_db),
):
    """
    Resolve one resident by hand — the `A101` vs `A-101` case the exact pass
    can't take on its own.

    This also rewrites the resident's `flat_number` to the flat's code. Until
    E6-S3 the agents resolve by that typed string, so linking `A101` to `A-101`
    while leaving the string alone would satisfy the FK and still leave the
    resident unreachable to a guard typing the code on the door — exactly the
    orphaning this story exists to prevent. History is untouched:
    `visitor_sessions.flat_number` is a snapshot of what was typed at the time.
    """
    resident = db.get(m.Resident, parse_uuid(body.resident_id))
    if resident is None:  # RLS hides other societies' rows -> looks like 404
        raise HTTPException(404, "Resident not found")
    flat = db.get(m.Flat, parse_uuid(body.flat_id))
    if flat is None or flat.deleted_at is not None:
        raise HTTPException(404, "Flat not found")
    if resident.deleted_at is not None:
        raise HTTPException(404, "Resident not found")
    if resident.society_id != flat.society_id:
        # Unreachable via RLS for a scoped role; a platform_admin bypasses it.
        raise HTTPException(400, "Resident and flat belong to different societies")

    # The primary slot is keyed on flat_number, so a resident who was primary of
    # "A101" cannot carry the flag onto "A-101" if someone already holds it
    # there — that trips the unique index. Release first, re-settle both doors
    # after: the one being left must not lose its contact either.
    old_flat_number = resident.flat_number
    resolve.release_primary(db, resident)
    resident.flat_id = flat.id
    resident.flat_number = flat.code
    db.flush()
    resolve.ensure_primary(db, resident.society_id, old_flat_number)
    resolve.ensure_primary(db, resident.society_id, flat.code)

    return _build_report(db, resident.society_id)


# ---------------------------------------------------------------------------
# E4-S2 — flats
# ---------------------------------------------------------------------------
def _shape_warnings(db, wing: m.Wing, floor: int, exclude_flat_id=None) -> list[str]:
    """
    Q2: the declared shape is a hint, never a rule. Ground-floor shops and
    penthouses are normal, so we say something and save anyway.
    """
    warnings = []
    if floor > wing.floors:
        warnings.append(
            f"Floor {floor} is above the {wing.floors} floor(s) declared for wing "
            f"'{wing.name}'. Saved anyway."
        )
    # Count the flat's *neighbours*, so the "+1" below is this flat joining them.
    # On a create it isn't inserted yet; on an edit it already is, so it has to
    # be excluded or it would count itself twice.
    q = select(func.count(m.Flat.id)).where(
        m.Flat.wing_id == wing.id, m.Flat.floor == floor, m.Flat.deleted_at.is_(None))
    if exclude_flat_id is not None:
        q = q.where(m.Flat.id != exclude_flat_id)
    on_floor = db.execute(q).scalar_one()
    if on_floor >= wing.flats_per_floor:
        warnings.append(
            f"Floor {floor} now has {on_floor + 1} flats; wing '{wing.name}' declares "
            f"{wing.flats_per_floor} per floor. Saved anyway."
        )
    return warnings


@router.post("/flats", status_code=201, response_model=FlatResponse)
def create_flat(body: FlatCreate, user: CurrentUser = Depends(_admins), db=Depends(get_db)):
    """
    Add a flat to a wing: `code = "{wing}-{flat_number}"` from the number the
    admin typed. The society comes from the wing, not the body — the wing was
    already resolved through RLS, so it can't point outside the caller's tenant.
    """
    wing = _get_wing(db, body.wing_id)
    flat_number = body.flat_number.strip()
    if not flat_number:
        raise HTTPException(422, "Flat number is required")
    code = f"{wing.name}-{flat_number}"

    # Only a *live* flat blocks the code. A soft-deleted A-101 leaves the code
    # free to be created again — a fresh flat with its own history.
    exists = db.execute(
        select(m.Flat.id).where(
            m.Flat.society_id == wing.society_id, m.Flat.code == code,
            m.Flat.deleted_at.is_(None))
    ).first()
    if exists:
        raise HTTPException(409, f"Flat '{code}' already exists in this society")

    # Read the floor's occupancy before inserting, so the count is of the others.
    warnings = _shape_warnings(db, wing, body.floor)

    flat = m.Flat(
        society_id=wing.society_id,
        wing_id=wing.id,
        flat_number=flat_number,
        floor=body.floor,
        code=code,
    )
    db.add(flat)
    try:
        db.flush()
    except Exception:
        raise HTTPException(409, f"Flat '{code}' already exists in this society")

    # D4: introducing a layout must not orphan anyone who was already here.
    linked = resolve.link_exact_matches(db, wing.society_id, flat)

    summary = f"Flat {code} added on floor {body.floor}"
    if linked:
        summary += f", adopting {linked} existing resident(s)"
    audit.record(
        db, society_id=wing.society_id, user=user, action="flat_created",
        summary=summary, entity_type=audit.FLAT, entity_id=flat.id,
        flat_id=flat.id, flat_code=code,
        detail={"floor": body.floor, "linked_residents": linked},
    )
    return _flat_resp(flat, wing.name, warnings, linked)


@router.get("/flats", response_model=list[FlatResponse])
def list_flats(
    wing_id: str | None = None,
    society_id: str | None = None,
    user: CurrentUser = Depends(_admins),
    db=Depends(get_db),
):
    """This society's flats, newest floor-first order; optionally one wing's."""
    sid = resolve_society_id(user, society_id)
    q = (
        select(m.Flat, m.Wing.name)
        .join(m.Wing, m.Flat.wing_id == m.Wing.id)
        .where(m.Flat.society_id == parse_uuid(sid), m.Flat.deleted_at.is_(None))
        .order_by(m.Wing.name, m.Flat.floor, m.Flat.flat_number)
    )
    if wing_id:
        q = q.where(m.Flat.wing_id == parse_uuid(wing_id))
    return [_flat_resp(f, wing_name) for f, wing_name in db.execute(q).all()]


@router.get("/flats/{flat_id}", response_model=FlatResponse)
def get_flat(flat_id: str, _: CurrentUser = Depends(_admins), db=Depends(get_db)):
    flat = db.get(m.Flat, parse_uuid(flat_id))
    if flat is None:
        raise HTTPException(404, "Flat not found")
    return _flat_resp(flat, db.get(m.Wing, flat.wing_id).name)


def _recode_flat(db, flat: m.Flat, wing: m.Wing, new_number: str) -> list[str]:
    """
    Retype a flat's number, taking its household with it.

    The code is the flat's identity: `residents.flat_number` matches it and the
    agents resolve residents by that exact string, so the household is moved with
    the code or the gate stops finding them. `visitor_sessions.flat_number` is
    NOT rewritten — it records what a guard actually typed at the time, and a
    record you can edit afterwards isn't a record. The cost is that past sessions
    keep a code this flat no longer answers to; that's returned as a warning
    rather than done quietly.
    """
    old_code = flat.code
    new_code = f"{wing.name}-{new_number}"
    if new_code == old_code:
        return []

    clash = db.execute(
        select(m.Flat.id).where(
            m.Flat.society_id == flat.society_id,
            m.Flat.code == new_code,
            m.Flat.id != flat.id,
            m.Flat.deleted_at.is_(None),
        )
    ).first()
    if clash:
        raise HTTPException(409, f"Flat '{new_code}' already exists in this society")

    warnings = []
    history = db.execute(
        select(func.count(m.VisitorSession.id)).where(
            m.VisitorSession.society_id == flat.society_id,
            m.VisitorSession.flat_number == old_code,
        )
    ).scalar_one()
    if history:
        warnings.append(
            f"{history} past visitor session(s) recorded '{old_code}'. They keep that "
            f"code as a record of what was typed, so they no longer match this flat."
        )

    movers = resolve.flat_residents(db, flat.society_id, old_code)
    was_primary = next((r for r in movers if r.is_primary), None)

    # Release before moving: the primary slot is unique per (society, flat_number),
    # so carrying a flag onto a code someone already holds it for would trip the
    # index mid-statement.
    for r in movers:
        r.is_primary = False
    db.flush()
    for r in movers:
        r.flat_number = new_code
    flat.flat_number = new_number
    flat.code = new_code
    db.flush()

    if movers:
        warnings.append(
            f"{len(movers)} resident(s) moved to '{new_code}' so the gate still finds them."
        )

    # Settle both doors. If the destination already had a flagged contact — free
    # text residents can live on a code before a flat does — they keep it, and
    # this is a merge worth saying out loud. Otherwise restore whoever held it.
    if was_primary is not None and not resolve.has_primary(db, flat.society_id, new_code):
        resolve.claim_primary(db, was_primary)
    else:
        settled = resolve.ensure_primary(db, flat.society_id, new_code)
        if was_primary is not None and settled is not None and settled.id != was_primary.id:
            warnings.append(
                f"'{new_code}' already had residents; {settled.name} stays the primary contact."
            )
    resolve.ensure_primary(db, flat.society_id, old_code)

    # Anyone already living on the new code but never linked to a flat (D4).
    resolve.link_exact_matches(db, flat.society_id, flat)
    return warnings


@router.patch("/flats/{flat_id}", response_model=FlatResponse)
def update_flat(
    flat_id: str,
    body: FlatUpdate,
    user: CurrentUser = Depends(_admins),
    db=Depends(get_db),
):
    """
    Correct a flat — its number, its floor, or the rules at its door.

    `floor` is inert: it is stored, never inferred from the code (Q1), and
    nothing resolves on it, so changing it only moves the flat on the grid.

    `flat_number` changes the code, which is the flat's identity — see
    `_recode_flat` for what moves with it and what deliberately doesn't.

    Rules override whatever the residents hold individually (E6-S3): two people
    behind one door can't contradict each other about who gets in. Sending null
    clears the override and hands the door back to its primary contact's own.
    """
    flat = db.get(m.Flat, parse_uuid(flat_id))
    if flat is None or flat.deleted_at is not None:  # RLS/soft-delete -> 404
        raise HTTPException(404, "Flat not found")

    fields = body.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(422, "Nothing to update")

    wing = db.get(m.Wing, flat.wing_id)
    warnings: list[str] = []
    events: list[tuple] = []  # (action, summary, detail) recorded after the flush
    old_floor, old_code = flat.floor, flat.code

    if "floor" in fields:
        if fields["floor"] is None:
            raise HTTPException(422, "Floor is required")
        if fields["floor"] != old_floor:
            flat.floor = fields["floor"]
            events.append(("flat_floor_changed",
                           f"Floor changed from {old_floor} to {flat.floor}",
                           {"from": old_floor, "to": flat.floor}))

    if "flat_number" in fields:
        new_number = (fields["flat_number"] or "").strip()
        if not new_number:
            raise HTTPException(422, "Flat number is required")
        warnings += _recode_flat(db, flat, wing, new_number)
        if flat.code != old_code:
            events.append(("flat_renamed",
                           f"Renumbered from {old_code} to {flat.code}",
                           {"from": old_code, "to": flat.code}))

    if "standing_rules" in fields or "delivery_preferences" in fields:
        for key in ("standing_rules", "delivery_preferences"):
            if key in fields:
                setattr(flat, key, fields[key])
        events.append(("flat_rules_changed", "Door rules updated", None))

    try:
        db.flush()
    except Exception:
        raise HTTPException(409, "That flat code already exists in this society")

    for action, summary, detail in events:
        audit.record(
            db, society_id=flat.society_id, user=user, action=action,
            summary=summary, entity_type=audit.FLAT, entity_id=flat.id,
            flat_id=flat.id, flat_code=flat.code, detail=detail,
        )

    # Q2: the declared shape is a hint, so a moved flat warns rather than refuses.
    warnings += _shape_warnings(db, wing, flat.floor, exclude_flat_id=flat.id)
    return _flat_resp(flat, wing.name, warnings)


@router.delete("/flats/{flat_id}", status_code=204)
def delete_flat(flat_id: str, user: CurrentUser = Depends(_admins), db=Depends(get_db)):
    """
    Soft-delete a flat, cascading to its residents.

    Nothing is truly removed: the flat and its residents keep their rows (and
    their whole timeline) and are simply marked deleted, so a flat with residents
    or visitor history *can* now be deleted — the old refusal existed only because
    a hard delete lost that history. resolve.py filters deleted rows, so the gate
    stops seeing the flat and its people at once. The code is freed for re-use.
    """
    flat = db.get(m.Flat, parse_uuid(flat_id))
    if flat is None or flat.deleted_at is not None:
        raise HTTPException(404, "Flat not found")

    now = _now()
    # Cascade to the flat's live residents — the household goes with the door.
    residents = resolve.flat_residents(db, flat.society_id, flat.code)
    for r in residents:
        r.deleted_at = now
        r.is_primary = False  # free the primary slot even though it's soft-deleted
    flat.deleted_at = now
    db.flush()

    for r in residents:
        audit.record(
            db, society_id=flat.society_id, user=user, action="resident_deleted",
            summary=f"{r.name} removed (flat {flat.code} deleted)",
            entity_type=audit.RESIDENT, entity_id=r.id,
            flat_id=flat.id, flat_code=flat.code,
        )
    audit.record(
        db, society_id=flat.society_id, user=user, action="flat_deleted",
        summary=f"Flat {flat.code} deleted"
        + (f", with {len(residents)} resident(s)" if residents else ""),
        entity_type=audit.FLAT, entity_id=flat.id,
        flat_id=flat.id, flat_code=flat.code,
        detail={"residents_removed": len(residents)},
    )


@router.get("/flats/{flat_id}/timeline", response_model=list[TimelineEvent])
def flat_timeline(flat_id: str, _: CurrentUser = Depends(_admins), db=Depends(get_db)):
    """
    The history of a flat and its residents — created, renamed, moved, rules
    changed, residents added/edited/made-primary/removed — newest first.

    Reachable for a soft-deleted flat too: seeing why and when a flat went away
    is the whole point of keeping it.
    """
    flat = db.get(m.Flat, parse_uuid(flat_id))
    if flat is None:
        raise HTTPException(404, "Flat not found")
    rows = db.execute(
        select(m.LayoutEvent)
        .where(m.LayoutEvent.flat_id == flat.id)
        .order_by(m.LayoutEvent.created_at.desc(), m.LayoutEvent.id.desc())
    ).scalars().all()
    return [
        TimelineEvent(
            id=str(e.id), action=e.action, summary=e.summary,
            actor_email=e.actor_email, detail=e.detail, created_at=e.created_at,
        )
        for e in rows
    ]
