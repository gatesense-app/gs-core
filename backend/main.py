"""
GateSense API — FastAPI entry point.

Endpoints:
  POST /sessions              — guard submits a visitor entry
  POST /sessions/{id}/reply   — resident (or guard) submits a reply
  GET  /sessions/{id}         — fetch session state + decision_trace
  GET  /sessions              — list all sessions (admin dashboard feed)
"""

import sys

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import select

# Agents print Claude output (and arrows) to stdout. Windows consoles default to
# cp1252, so force UTF-8 here to keep a stray non-ASCII log line from 500-ing a
# request. (No-op where stdout is already UTF-8, e.g. Linux/Docker.)
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

from backend import db_models as m
from backend.deps import CurrentUser, get_db, require_role
from backend.pipeline import handle_resident_reply, handle_visitor_entry, serialize
from backend.routers import auth, residents, societies, users, visitors
from backend.routers.common import parse_uuid

app = FastAPI(title="GateSense", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Admin + auth API (Phase 1)
app.include_router(auth.router)
app.include_router(societies.router)
app.include_router(residents.router)
app.include_router(users.router)
app.include_router(visitors.router)


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------
class VisitorEntryRequest(BaseModel):
    visitor_name: str
    flat_number: str
    purpose: str           # delivery | guest | service | cab | other
    purpose_detail: str    # free text from guard


class ReplyRequest(BaseModel):
    reply: str             # resident's or guard's reply text


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
# Role gates for the visitor pipeline. society_id always comes from the JWT.
_kiosk = require_role("guard", "society_admin")           # who can submit visitors
_viewer = require_role("guard", "society_admin", "platform_admin")  # who can read
_replier = require_role("guard", "society_admin", "resident")       # who can reply


@app.post("/sessions", status_code=201)
def create_session(body: VisitorEntryRequest, user: CurrentUser = Depends(_kiosk), db=Depends(get_db)):
    """
    Guard submits a new visitor. Runs the Gate Agent (and Delivery Agent
    if needed) against this society's data, then resolves or starts intercom.
    """
    row = handle_visitor_entry(
        db, user.society_id,
        body.visitor_name, body.flat_number, body.purpose, body.purpose_detail,
    )
    return serialize(row)


@app.post("/sessions/{session_id}/reply")
def submit_reply(session_id: str, body: ReplyRequest, user: CurrentUser = Depends(_replier), db=Depends(get_db)):
    """Resident (or guard) submits a reply to the intercom agent."""
    row = db.get(m.VisitorSession, parse_uuid(session_id))
    if row is None:  # RLS hides other societies' sessions -> looks like 404
        raise HTTPException(status_code=404, detail="Session not found")
    if row.status != "awaiting_resident":
        raise HTTPException(status_code=400, detail=f"Session is not awaiting a reply (status={row.status})")
    return serialize(handle_resident_reply(db, row, body.reply))


@app.get("/sessions/{session_id}")
def get_session(session_id: str, user: CurrentUser = Depends(_viewer), db=Depends(get_db)):
    """Fetch a single session with its full decision_trace."""
    row = db.get(m.VisitorSession, parse_uuid(session_id))
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return serialize(row)


@app.get("/sessions")
def list_sessions(user: CurrentUser = Depends(_viewer), db=Depends(get_db)):
    """List this society's sessions — used by the admin dashboard."""
    rows = db.execute(
        select(m.VisitorSession).order_by(m.VisitorSession.entry_time.desc())
    ).scalars().all()
    return [serialize(r) for r in rows]
