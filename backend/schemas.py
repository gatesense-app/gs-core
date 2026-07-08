"""Pydantic request/response schemas for the admin + auth API."""

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, EmailStr, Field

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
    name: str
    address: Optional[str] = None
    admin_email: EmailStr
    admin_password: str = Field(min_length=6)
    admin_name: Optional[str] = None


class SocietyResponse(BaseModel):
    id: str
    name: str
    address: Optional[str] = None
    created_at: Optional[datetime] = None


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
