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
    standing_rules: Optional[list[dict[str, Any]]] = None
    delivery_preferences: Optional[dict[str, Any]] = None


class ResidentResponse(BaseModel):
    id: str
    society_id: str
    flat_number: str
    name: str
    phone: Optional[str] = None
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
