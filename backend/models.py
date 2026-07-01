"""
Shared data models for the GateSense pipeline.

VisitorSession is the single object that flows through all three agents.
Each agent appends TraceEntry records to decision_trace, giving you a
full audit log of every check, tool call, and reasoning step.
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field
import uuid


class TraceEntry(BaseModel):
    agent: str                          # "gate" | "delivery" | "intercom"
    action: str                         # human-readable action name
    reasoning: str                      # why this action was taken
    tool_calls: list[str] = []          # names of tools invoked
    timestamp: str = Field(
        default_factory=lambda: datetime.utcnow().isoformat()
    )


class VisitorSession(BaseModel):
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])

    # Visitor info (from gate kiosk)
    visitor_name: str
    flat_number: str
    purpose: str
    purpose_detail: str

    # State machine
    status: str = "pending"             # pending | auto_approved | awaiting_resident
                                        # | approved | denied | escalated | expired

    # Who resolved it and how
    resolved_by: Optional[str] = None   # "agent" | "resident" | "guard_default" | "backup_contact" | "timeout"
    resolved_at: Optional[str] = None

    # The audit trail — every agent appends here
    decision_trace: list[TraceEntry] = []

    # Conversation log (populated by intercom agent)
    conversation_history: list[dict] = []

    # Timestamps
    entry_time: str = Field(
        default_factory=lambda: datetime.utcnow().isoformat()
    )

    def add_trace(self, agent: str, action: str, reasoning: str, tool_calls: list[str] = []):
        self.decision_trace.append(TraceEntry(
            agent=agent,
            action=action,
            reasoning=reasoning,
            tool_calls=tool_calls,
        ))

    def resolve(self, status: str, resolved_by: str):
        self.status = status
        self.resolved_by = resolved_by
        self.resolved_at = datetime.utcnow().isoformat()
