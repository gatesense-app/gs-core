"""
GateSense API — FastAPI entry point.

Endpoints:
  POST /sessions              — guard submits a visitor entry
  POST /sessions/{id}/reply   — resident (or guard) submits a reply
  GET  /sessions/{id}         — fetch session state + decision_trace
  GET  /sessions              — list all sessions (admin dashboard feed)
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backend import session_store
from backend.pipeline import handle_visitor_entry, handle_resident_reply

app = FastAPI(title="GateSense", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


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
@app.post("/sessions", status_code=201)
def create_session(body: VisitorEntryRequest):
    """
    Guard submits a new visitor. Runs the Gate Agent (and Delivery Agent
    if needed), then either resolves immediately or starts the intercom flow.
    """
    session = handle_visitor_entry(
        visitor_name=body.visitor_name,
        flat_number=body.flat_number,
        purpose=body.purpose,
        purpose_detail=body.purpose_detail,
    )
    return session.model_dump()


@app.post("/sessions/{session_id}/reply")
def submit_reply(session_id: str, body: ReplyRequest):
    """
    Resident or guard submits a reply to the intercom agent.
    Call this repeatedly until response.status == 'resolved'.
    """
    session = session_store.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.status not in ("awaiting_resident",):
        raise HTTPException(
            status_code=400,
            detail=f"Session is not awaiting a reply (status={session.status})",
        )

    updated = handle_resident_reply(session_id, body.reply)
    return updated.model_dump()


@app.get("/sessions/{session_id}")
def get_session(session_id: str):
    """Fetch a single session with its full decision_trace."""
    session = session_store.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return session.model_dump()


@app.get("/sessions")
def list_sessions():
    """List all sessions — used by the admin dashboard."""
    return [s.model_dump() for s in session_store.all_sessions()]
