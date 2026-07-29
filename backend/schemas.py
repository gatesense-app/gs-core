"""Pydantic request/response schemas for the admin + auth API."""

from datetime import date, datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, EmailStr, Field, model_validator

Role = Literal["platform_admin", "society_admin", "guard", "resident"]


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
class LoginRequest(BaseModel):
    # An email (admins/guards) or a phone (provisioned residents). Kept a plain
    # str, not EmailStr, so a phone number isn't rejected before we can look it up.
    # The field name stays `email` to avoid a breaking client rename.
    email: str
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
    # Privacy toggle: mask resident mobile numbers in admin-facing responses.
    hide_resident_phones: Optional[bool] = None


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
    # When true, resident phones are masked (last 4) for staff.
    hide_resident_phones: bool = False


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
    # When a flat with this code was soft-deleted before, the admin may choose to
    # link the new flat to it so the old flat's history surfaces on the new
    # timeline. Defaults off, so an ordinary create is unchanged and a CSV import
    # (which builds Flat rows directly) never trips this.
    link_prior: bool = False


class PriorFlat(BaseModel):
    """A soft-deleted flat that shares a to-be-created flat's code."""

    exists: bool = False
    flat_id: Optional[str] = None
    code: Optional[str] = None
    deleted_at: Optional[datetime] = None
    resident_count: int = 0


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
    # 'owner' or 'tenant' — who occupies the flat. Drives the grid colour and which
    # role the gate reaches.
    occupancy: str = "owner"
    # Soft delete: set once the flat is deleted. Lists never return a deleted
    # flat, but its detail page stays reachable to view the timeline.
    deleted_at: Optional[datetime] = None


class TimelineEvent(BaseModel):
    """One entry on a flat's history (audit trail)."""

    id: str
    action: str
    summary: str
    actor_email: Optional[str] = None
    detail: Optional[dict[str, Any]] = None
    created_at: Optional[datetime] = None


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
    # 'owner' or 'tenant'. Re-elects the gate's contact from the matching role.
    occupancy: Optional[Literal["owner", "tenant"]] = None


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
    # 'owner' or 'tenant'. If omitted the router assigns it: the first resident on
    # a flat is its owner, everyone added after is a tenant.
    role: Optional[Literal["owner", "tenant"]] = None
    # platform_admin must supply this; society_admin's is taken from their JWT.
    society_id: Optional[str] = None


class ResidentUpdate(BaseModel):
    flat_number: Optional[str] = None
    name: Optional[str] = None
    phone: Optional[str] = None
    # E6-S3: set true to make this resident the flat's contact. There is no
    # "demote" — a flat always needs someone, so promote another instead.
    is_primary: Optional[bool] = None
    # Re-label this resident owner/tenant; may re-elect the flat's contact.
    role: Optional[Literal["owner", "tenant"]] = None
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
    # 'owner' or 'tenant' — a stable label, distinct from is_primary.
    role: str = "owner"
    # Set for a tenant: the tenancy agreement they belong to.
    tenancy_id: Optional[str] = None
    standing_rules: list[dict[str, Any]] = Field(default_factory=list)
    delivery_preferences: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Tenancies (a tenant-occupied flat's agreement + its tenants)
# ---------------------------------------------------------------------------
class TenancyCreate(BaseModel):
    """Start a tenancy on a tenant-occupied flat. Dates are optional."""

    start_date: Optional[date] = None
    end_date: Optional[date] = None


class TenancyRenew(BaseModel):
    """Renew (clone) the active tenancy with fresh dates."""

    start_date: Optional[date] = None
    end_date: Optional[date] = None


class TenantCreate(BaseModel):
    """Add a tenant to the active tenancy. First tenant becomes the contact."""

    name: str = Field(min_length=1)
    phone: Optional[str] = None
    standing_rules: list[dict[str, Any]] = Field(default_factory=list)
    delivery_preferences: dict[str, Any] = Field(default_factory=dict)


class TenancyResponse(BaseModel):
    id: str
    flat_id: str
    flat_code: str
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    ended_at: Optional[datetime] = None
    # Derived: 'active', 'ended', or 'expired' (active but past its end date).
    status: str = "active"
    prior_tenancy_id: Optional[str] = None
    tenants: list[ResidentResponse] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Vehicles + parking (per flat)
# ---------------------------------------------------------------------------
class VehicleCreate(BaseModel):
    registration_number: str = Field(min_length=1, max_length=20)
    vehicle_type: Literal["two_wheeler", "four_wheeler"]
    # Primary owner as per the RC book (free text, may differ from residents).
    owner_name: str = Field(min_length=1, max_length=200)
    # Optional: one of the flat's parking numbers to assign this vehicle to.
    parking_slot_id: Optional[str] = None


class VehicleUpdate(BaseModel):
    registration_number: Optional[str] = Field(default=None, min_length=1, max_length=20)
    vehicle_type: Optional[Literal["two_wheeler", "four_wheeler"]] = None
    owner_name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    # Send a slot id to (re)assign, or null to clear the assignment. Unset leaves
    # it alone — the router reads exclude_unset, so "not sent" ≠ "sent as null".
    parking_slot_id: Optional[str] = None


class VehicleResponse(BaseModel):
    id: str
    society_id: str
    flat_id: str
    flat_code: str
    registration_number: str
    vehicle_type: str
    owner_name: str
    # The assigned parking slot, if any, with its number resolved for display.
    parking_slot_id: Optional[str] = None
    parking_number: Optional[str] = None


class ParkingCreate(BaseModel):
    parking_number: str = Field(min_length=1, max_length=32)


class ParkingResponse(BaseModel):
    id: str
    society_id: str
    flat_id: str
    flat_code: str
    parking_number: str


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
    # Phone-only resident logins have no email.
    email: Optional[str] = None
    phone: Optional[str] = None
    role: Role
    full_name: Optional[str] = None
    society_id: Optional[str] = None
    is_active: bool = True


# ---------------------------------------------------------------------------
# Bulk-provision resident logins from imported residents
# ---------------------------------------------------------------------------
class ProvisionRequest(BaseModel):
    # A shared default password every provisioned resident logs in with. Admin's
    # choice (pilot-grade — there is no reset flow yet).
    default_password: str = Field(min_length=6)
    wing_id: Optional[str] = None       # narrow to one building; all wings if omitted
    society_id: Optional[str] = None    # platform_admin only


class ProvisionedRow(BaseModel):
    resident_id: str
    name: str
    flat_number: str
    phone: str


class SkippedRow(BaseModel):
    name: str
    flat_number: str
    reason: str


class ProvisionResult(BaseModel):
    created_count: int
    skipped_count: int
    created: list[ProvisionedRow] = Field(default_factory=list)
    skipped: list[SkippedRow] = Field(default_factory=list)


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
