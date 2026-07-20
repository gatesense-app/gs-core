"""
Bulk resident import endpoints (E3).

The CSV arrives as the raw request body (Content-Type: text/csv), not multipart:
it needs no extra dependency, and it lets us cap the number of bytes we read
*before* pulling the whole thing into memory — a 2M-row file must not take the
API down. All the parsing/validation rules live in backend/csv_import.py; this
module is just transport, auth, and the preview/commit switch.
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse

from backend import csv_import
from backend.deps import CurrentUser, get_db, require_role
from backend.routers.common import resolve_society_id
from backend.schemas import ImportReport

router = APIRouter(prefix="/import", tags=["import"])

_admins = require_role("platform_admin", "society_admin")


async def _read_capped(request: Request) -> bytes:
    """
    Pull the body a chunk at a time, refusing once it passes the byte cap.

    Content-Length can lie, so the running total is the real guard; the header
    check just rejects an honest oversize upload before a single chunk is read.
    """
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > csv_import.MAX_BYTES:
        raise HTTPException(413, f"File too large (limit {csv_import.MAX_BYTES} bytes).")

    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > csv_import.MAX_BYTES:
            raise HTTPException(413, f"File too large (limit {csv_import.MAX_BYTES} bytes).")
    return bytes(body)


@router.get("/residents/template", response_class=PlainTextResponse)
def residents_template(_: CurrentUser = Depends(_admins)):
    """The documented header plus a couple of example rows, to fill in and upload."""
    return PlainTextResponse(
        csv_import.TEMPLATE,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=residents-template.csv"},
    )


@router.post("/residents", response_model=ImportReport)
async def import_residents(
    request: Request,
    dry_run: bool = True,
    society_id: str | None = None,
    user: CurrentUser = Depends(_admins),
    db=Depends(get_db),
):
    """
    Preview (default) or commit a resident CSV.

    `dry_run=true` validates and reports what would happen, writing nothing —
    the UI shows create/update/reject counts and the reasons, and the admin can
    cancel. `dry_run=false` runs the identical validation and commits in this
    request's single transaction, but only if no row was rejected: the import is
    all-or-nothing, so a bad row 250 never leaves 249 half-imported residents.
    """
    sid = resolve_society_id(user, society_id)
    raw = await _read_capped(request)

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(400, "File is not valid UTF-8 text. Export it as a CSV.")

    try:
        rows = csv_import.parse(text)
    except csv_import.ImportError_ as exc:
        raise HTTPException(400, str(exc))

    result = csv_import.validate(db, sid, rows)
    errors = result["errors"]
    counts = result["counts"]

    committed = False
    if not dry_run and not errors:
        csv_import.apply_plan(db, sid, result["plan"], user=user)
        committed = True

    return ImportReport(
        dry_run=dry_run,
        committed=committed,
        total_rows=counts["total_rows"],
        residents_to_create=counts["residents_to_create"],
        residents_to_update=counts["residents_to_update"],
        residents_to_link=counts["residents_to_link"],
        flats_to_create=counts["flats_to_create"],
        rejected_rows=counts["rejected_rows"],
        errors=errors,
    )
