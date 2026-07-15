"""
Central runtime configuration for the GateSense backend.

Keeps cross-cutting settings (currently just the Claude model id) in one place
instead of duplicated across the three agent modules.
"""

import os

from dotenv import load_dotenv

# Load .env here, before any os.getenv() below, so a local .env is the single
# source of truth for every entry point that imports this module (the API, the
# test suite, and alembic via migrations/env.py). load_dotenv does NOT override
# variables already set in the real environment, so precedence stays:
#   real env (Docker / Railway / CI)  >  .env  >  the defaults below.
load_dotenv()

# Current-generation Sonnet — good balance of reasoning and cost for the
# classification / short-drafting workloads these agents run. Override with the
# ANTHROPIC_MODEL env var (e.g. `claude-opus-4-8`) for higher-stakes reasoning.
#
# NOTE: on this model family adaptive thinking is ON when the `thinking` param
# is omitted, and thinking tokens count against `max_tokens`. The agents run
# short, tool-driven calls (some with max_tokens as low as 10), so they pass
# `thinking={"type": "disabled"}` explicitly to keep the fast, no-thinking
# behaviour the prompts were tuned for.
MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5")

# A hung Claude call would otherwise hold a visitor at the gate indefinitely.
# On timeout the pipeline falls back to a human rather than guessing.
LLM_TIMEOUT_SECONDS = float(os.getenv("LLM_TIMEOUT_SECONDS", "45"))
LLM_MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", "2"))

# ---------------------------------------------------------------------------
# Rate limits (per society) on the endpoints that trigger Claude calls.
# Generous enough for a real gate; tight enough that a retry loop can't run up
# the API bill or starve other tenants. See backend/ratelimit.py.
# ---------------------------------------------------------------------------
RATE_LIMIT_WINDOW_SECONDS = float(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))
RATE_LIMIT_SESSIONS = int(os.getenv("RATE_LIMIT_SESSIONS", "30"))  # visitor entries / window
RATE_LIMIT_REPLIES = int(os.getenv("RATE_LIMIT_REPLIES", "60"))    # replies / window

# ---------------------------------------------------------------------------
# Resident reply timeout -> escalation (backend/timeouts.py)
# ---------------------------------------------------------------------------
# How long a visitor may wait on a silent resident before the session escalates
# to the backup contact (or the guard's default policy if no backup is set).
RESIDENT_TIMEOUT_MINUTES = int(os.getenv("RESIDENT_TIMEOUT_MINUTES", "10"))
TIMEOUT_SWEEP_SECONDS = float(os.getenv("TIMEOUT_SWEEP_SECONDS", "60"))
# The sweeper runs in the API process; disable it for tests/one-off scripts.
TIMEOUT_SWEEPER_ENABLED = os.getenv("TIMEOUT_SWEEPER_ENABLED", "1").strip().lower() not in {
    "0", "false", "no", "off",
}

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
# Default targets the local docker-compose Postgres, which is published on 55432
# to avoid clashing with a locally-installed Postgres on 5432. In Docker/Railway
# DATABASE_URL is always set explicitly and wins over this.
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://gatesense:gatesense@localhost:55432/gatesense",
)

# Non-superuser role the app SET ROLEs into so Postgres RLS is actually
# enforced (a superuser connection bypasses RLS). Created in the initial
# migration. See backend/deps.py:scoped_session.
APP_DB_ROLE = os.getenv("APP_DB_ROLE", "app_rls")

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------
# "development" locally; set APP_ENV=production on Railway. Guards below refuse
# to boot with insecure dev defaults in production.
APP_ENV = os.getenv("APP_ENV", "development").strip().lower()
IS_PRODUCTION = APP_ENV == "production"

# ---------------------------------------------------------------------------
# Auth (JWT)
# ---------------------------------------------------------------------------
_DEV_JWT_SECRET = "dev-insecure-secret-change-in-prod"
JWT_SECRET = os.getenv("JWT_SECRET", _DEV_JWT_SECRET)
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_TTL_MINUTES = int(os.getenv("ACCESS_TOKEN_TTL_MINUTES", "720"))  # 12h

if IS_PRODUCTION and JWT_SECRET == _DEV_JWT_SECRET:
    # Shipping the dev secret would let anyone mint a platform_admin token for
    # any society. Refuse to start rather than serve traffic that can be forged.
    raise RuntimeError(
        "JWT_SECRET is still the development default while APP_ENV=production. "
        "Set a strong random JWT_SECRET (e.g. `openssl rand -hex 32`) before deploying."
    )

# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------
# The SPA is served from a different origin in production (Vercel /
# gatesense.in), so the deployed origins must be configurable. Comma-separated.
CORS_ORIGINS = [
    o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",") if o.strip()
]
