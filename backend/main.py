"""
GateSense API — FastAPI entry point.

Endpoints:
  POST /sessions              — guard submits a visitor entry
  POST /sessions/{id}/reply   — resident (or guard) submits a reply
  GET  /sessions/{id}         — fetch session state + decision_trace
  GET  /sessions              — list all sessions (admin dashboard feed)
"""

import asyncio
import sys
from contextlib import asynccontextmanager

import jwt
from fastapi import Depends, FastAPI, HTTPException, Query, WebSocket
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import select
from starlette.websockets import WebSocketDisconnect

# Agents print Claude output (and arrows) to stdout. Windows consoles default to
# cp1252, so force UTF-8 here to keep a stray non-ASCII log line from 500-ing a
# request. (No-op where stdout is already UTF-8, e.g. Linux/Docker.)
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

from backend import db_models as m
from backend.deps import (
    CurrentUser,
    get_db,
    require_role,
    resolve_resident_for_user,
    scoped_session,
)
from backend.pipeline import handle_resident_reply, handle_visitor_entry, serialize
from backend.realtime import manager
from backend.routers import auth, portal, residents, societies, users, visitors
from backend.routers.common import parse_uuid
from backend.security import decode_access_token


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Capture the running loop so sync request handlers can push WebSocket
    # updates via manager.publish() (see backend/realtime.py).
    manager.bind_loop(asyncio.get_running_loop())
    yield


app = FastAPI(title="GateSense", version="0.1.0", lifespan=lifespan)

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
app.include_router(portal.router)  # resident self-service (Phase 5)


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
_viewer = require_role("guard", "society_admin", "platform_admin")  # society-wide read
_replier = require_role("guard", "society_admin", "resident")       # who can reply
# Residents may read a single session, but only for their own flat (see _assert_flat_access).
_session_reader = require_role("guard", "society_admin", "platform_admin", "resident")


def _assert_flat_access(db, user: CurrentUser, row: m.VisitorSession) -> None:
    """
    RLS scopes to the society; this narrows a resident to their own flat.

    Without it, any resident could read or answer a neighbour's visitor. Raises
    404 rather than 403 so we don't confirm the session exists to someone who
    isn't allowed to know.
    """
    if user.role != "resident":
        return
    resident = resolve_resident_for_user(db, user)
    if resident is None or resident.flat_number != row.flat_number:
        raise HTTPException(status_code=404, detail="Session not found")


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
    data = serialize(row)
    manager.publish(user.society_id, {"type": "session_update", "session": data})
    return data


@app.post("/sessions/{session_id}/reply")
def submit_reply(session_id: str, body: ReplyRequest, user: CurrentUser = Depends(_replier), db=Depends(get_db)):
    """Resident (or guard) submits a reply to the intercom agent."""
    row = db.get(m.VisitorSession, parse_uuid(session_id))
    if row is None:  # RLS hides other societies' sessions -> looks like 404
        raise HTTPException(status_code=404, detail="Session not found")
    _assert_flat_access(db, user, row)  # a resident may only answer their own flat
    if row.status != "awaiting_resident":
        raise HTTPException(status_code=400, detail=f"Session is not awaiting a reply (status={row.status})")
    data = serialize(handle_resident_reply(db, row, body.reply))
    manager.publish(user.society_id, {"type": "session_update", "session": data})
    return data


@app.get("/sessions/{session_id}")
def get_session(session_id: str, user: CurrentUser = Depends(_session_reader), db=Depends(get_db)):
    """Fetch a single session with its full decision_trace (residents: own flat only)."""
    row = db.get(m.VisitorSession, parse_uuid(session_id))
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    _assert_flat_access(db, user, row)
    return serialize(row)


@app.get("/sessions")
def list_sessions(user: CurrentUser = Depends(_viewer), db=Depends(get_db)):
    """List this society's sessions — used by the admin dashboard."""
    rows = db.execute(
        select(m.VisitorSession).order_by(m.VisitorSession.entry_time.desc())
    ).scalars().all()
    return [serialize(r) for r in rows]


def _resident_flat(user_id: str, society_id: str) -> str | None:
    """Blocking lookup of a resident's flat — run off the event loop."""
    with scoped_session(society_id) as db:
        resident = resolve_resident_for_user(db, CurrentUser(user_id, society_id, "resident"))
        return resident.flat_number if resident else None


# ---------------------------------------------------------------------------
# WebSocket: live session updates for the dashboard / session detail / portal.
# Browsers can't send Authorization headers on a WebSocket, so the JWT is
# passed as a query param (?token=...). Staff are bucketed by society,
# platform_admins receive every society, and residents are bucketed by flat so
# they only ever hear about their own visitors.
# ---------------------------------------------------------------------------
@app.websocket("/ws/sessions")
async def ws_sessions(ws: WebSocket, token: str | None = Query(default=None)):
    if not token:
        await ws.close(code=1008)
        return
    try:
        claims = decode_access_token(token)
    except jwt.PyJWTError:
        await ws.close(code=1008)
        return
    role = claims.get("role")
    if role not in ("guard", "society_admin", "platform_admin", "resident"):
        await ws.close(code=1008)
        return

    society_id = claims.get("sid")
    flat_number = None
    if role == "resident":
        # A resident with no linked flat has nothing to subscribe to.
        flat_number = await run_in_threadpool(_resident_flat, claims["sub"], society_id)
        if not flat_number:
            await ws.close(code=1008)
            return

    await manager.connect(ws, society_id, flat_number)
    try:
        while True:
            await ws.receive_text()  # client sends nothing meaningful; keep-alive
    except WebSocketDisconnect:
        manager.disconnect(ws, society_id, flat_number)
    except Exception:
        manager.disconnect(ws, society_id, flat_number)
