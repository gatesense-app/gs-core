"""Pydantic request/response schemas for the admin + auth API."""

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, EmailStr, Field, model_validator

Role = Literal["platform_admin", "society_admin", "guard", "resident"]


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: Role
    society_id: Optional[str] = None
    full_name: Optional[str] = None


class MeResponse(BaseModel):
    user_id: str
    role: Role
    society_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Societies
# ---------------------------------------------------------------------------
class SocietyCreate(BaseModel):
    """
    The admin is optional: a society can be onboarded before anyone knows who
    will run it, and an admin allocated later (POST /users with
    role=society_admin). Supplying admin details still creates both at once.
    """

    name: str
    address: Optional[str] = None
    admin_email: Optional[EmailStr] = None
    admin_password: Optional[str] = Field(default=None, min_length=6)
    admin_name: Optional[str] = None

    @model_validator(mode="after")
    def _admin_is_all_or_nothing(self):
        # Half an admin is a silent failure: an email with no password would
        # create a society whose "admin" can never sign in.
        if bool(self.admin_email) != bool(self.admin_password):
            raise ValueError(
                "admin_email and admin_password must be provided together, "
                "or both omitted to create a society without an admin"
            )
        return self


class SocietyUpdate(BaseModel):
    """Only the society's own details; never its residents, users or sessions."""

    name: Optional[str] = None
    address: Optional[str] = None


class SocietyResponse(BaseModel):
    id: str
    name: str
    address: Optional[str] = None
    created_at: Optional[datetime] = None
    # Lets the UI flag a society that nobody can administer yet.
    admin_count: int = 0
    # Counted from actual flats, never floors * flats_per_floor (E4-S1 / Q2), so
    # the number can't lie when reality disagrees with the declared shape.
    flat_count: int = 0


# ---------------------------------------------------------------------------
# Layout: wings + flats (E4-S1 / E4-S2)
# ---------------------------------------------------------------------------
class WingCreate(BaseModel):
    """Declares the shape of a grid. Creates no flats (D2)."""

    name: str = Field(min_length=1, max_length=64)
    floors: int = Field(ge=1)
    flats_per_floor: int = Field(ge=1)
    society_id: Optional[str] = None  # platform_admin only


class WingUpdate(BaseModel):
    """
    Correct a wing after the fact (E4-S3) — a typo shouldn't force a rebuild.

    Renaming never rewrites existing flat codes, and changing the shape only
    redraws the grid; neither touches a flat. See the router for why.
    """

    name: Optional[str] = Field(default=None, min_length=1, max_length=64)
    floors: Optional[int] = Field(default=None, ge=1)
    flats_per_floor: Optional[int] = Field(default=None, ge=1)


class WingResponse(BaseModel):
    id: str
    society_id: str
    name: str
    floors: int
    flats_per_floor: int
    # Actual flats entered so far — the grid renders empty until they are.
    flat_count: int = 0
    # E4-S3 / Q2: what an edit left alone but the admin should know about —
    # kept codes after a rename, flats outside a reduced shape. Never a rejection.
    warnings: list[str] = Field(default_factory=list)


class FlatCreate(BaseModel):
    """
    The admin types the number; the system never invents it (D2).

    `floor` is given, not parsed from the number (Q1).
    """

    wing_id: str
    flat_number: str = Field(min_length=1, max_length=32)
    floor: int


class FlatResponse(BaseModel):
    id: str
    society_id: str
    wing_id: str
    wing_name: str
    flat_number: str
    floor: int
    code: str
    # Q2: the declared shape is a hint. Exceeding it warns and saves.
    warnings: list[str] = Field(default_factory=list)
    # E4-S4: free-text residents this flat adopted on creation.
    linked_residents: int = 0
    # E6-S3: rules for the door. null means "not set" — the primary contact's
    # own rules apply — which is different from [] meaning "no rules".
    standing_rules: Optional[list[dict[str, Any]]] = None
    delivery_preferences: Optional[dict[str, Any]] = None


class FlatUpdate(BaseModel):
    """
    Correct a flat: its number, its floor, or the rules that apply at its door.

    `standing_rules` / `delivery_preferences` override what its residents hold
    individually (E6-S3); sending null clears the override and hands the door
    back to the primary contact's own. Unset fields are left alone — the router
    reads `exclude_unset`, so "not sent" and "sent as null" mean different things.
    """

    # Changing this changes the flat's code, which is its identity. See the router.
    flat_number: Optional[str] = Field(default=None, min_length=1, max_length=32)
    floor: Optional[int] = None
    standing_rules: Optional[list[dict[str, Any]]] = None
    delivery_preferences: Optional[dict[str, Any]] = None


# ---------------------------------------------------------------------------
# Reconcile free-text residents onto flats (E4-S4 / D4)
# ---------------------------------------------------------------------------
class UnmatchedResident(BaseModel):
    """
    A resident whose free-text flat_number matches no flat code.

    Listed for a human to resolve — never dropped, and never auto-linked on a
    guess. `suggested_*` is a hint for the UI (D2: the system doesn't invent).
    """

    resident_id: str
    name: str
    flat_number: str
    suggested_flat_id: Optional[str] = None
    suggested_code: Optional[str] = None


class ReconcileReport(BaseModel):
    society_id: str
    flat_count: int
    linked: int
    unmatched_count: int
    unmatched: list[UnmatchedResident] = Field(default_factory=list)


class ReconcileLink(BaseModel):
    """Manual resolution of one resident the exact-match pass couldn't place."""

    resident_id: str
    flat_id: str


# ---------------------------------------------------------------------------
# CSV import (E3)
# ---------------------------------------------------------------------------
class ImportRowError(BaseModel):
    """One rejected row, pinned to its file line and offending column."""

    row: int
    column: Optional[str] = None
    message: str


class ImportReport(BaseModel):
    """
    What an import did, or (dry run) would do.

    `committed` is the honest bit: true only when rows were actually written.
    A preview, or a commit that hit any row error, leaves it false.
    """

    dry_run: bool
    committed: bool
    total_rows: int
    residents_to_create: int
    residents_to_update: int
    # Residents not named in the file, already sitting on a code the import
    # creates: a new flat adopts them (D4) rather than orphaning them.
    residents_to_link: int = 0
    flats_to_create: int
    rejected_rows: int
    errors: list[ImportRowError] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Residents
# ---------------------------------------------------------------------------
class ResidentCreate(BaseModel):
    flat_number: str
    name: str
    phone: Optional[str] = None
    standing_rules: list[dict[str, Any]] = Field(default_factory=list)
    delivery_preferences: dict[str, Any] = Field(default_factory=dict)
    # platform_admin must supply this; society_admin's is taken from their JWT.
    society_id: Optional[str] = None


class ResidentUpdate(BaseModel):
    flat_number: Optional[str] = None
    name: Optional[str] = None
    phone: Optional[str] = None
    # E6-S3: set true to make this resident the flat's contact. There is no
    # "demote" — a flat always needs someone, so promote another instead.
    is_primary: Optional[bool] = None
    standing_rules: Optional[list[dict[str, Any]]] = None
    delivery_preferences: Optional[dict[str, Any]] = None


class ResidentResponse(BaseModel):
    id: str
    society_id: str
    flat_number: str
    name: str
    phone: Optional[str] = None
    # The one the agents contact for this flat (Q3).
    is_primary: bool = False
    standing_rules: list[dict[str, Any]] = Field(default_factory=list)
    delivery_preferences: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Resident portal (self-service — always scoped to the caller's own flat)
# ---------------------------------------------------------------------------
class PortalMeResponse(BaseModel):
    resident_id: str
    flat_number: str
    name: str
    phone: Optional[str] = None
    standing_rules: list[dict[str, Any]] = Field(default_factory=list)
    delivery_preferences: dict[str, Any] = Field(default_factory=dict)


class PortalRulesUpdate(BaseModel):
    """A resident may edit only their own rules/preferences — never their flat."""

    standing_rules: Optional[list[dict[str, Any]]] = None
    delivery_preferences: Optional[dict[str, Any]] = None


# ---------------------------------------------------------------------------
# Users (guards / residents / society admins)
# ---------------------------------------------------------------------------
class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6)
    role: Literal["society_admin", "guard", "resident"]
    full_name: Optional[str] = None
    resident_id: Optional[str] = None
    society_id: Optional[str] = None  # platform_admin only


class UserResponse(BaseModel):
    id: str
    email: str
    role: Role
    full_name: Optional[str] = None
    society_id: Optional[str] = None
    is_active: bool = True


# ---------------------------------------------------------------------------
# Visitors (known + history)
# ---------------------------------------------------------------------------
class VisitorCreate(BaseModel):
    name: str
    flat_number: Optional[str] = None
    visitor_type: Optional[str] = None
    phone: Optional[str] = None
    is_known_service: bool = False
    visit_count: int = 0
    typical_hours: Optional[dict[str, Any]] = None
    notes: Optional[str] = None
    society_id: Optional[str] = None  # platform_admin only


class VisitorResponse(BaseModel):
    id: str
    society_id: str
    name: str
    flat_number: Optional[str] = None
    visitor_type: Optional[str] = None
    is_known_service: bool = False
    visit_count: int = 0
    notes: Optional[str] = None
