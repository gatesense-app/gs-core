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
# Auth (JWT)
# ---------------------------------------------------------------------------
JWT_SECRET = os.getenv("JWT_SECRET", "dev-insecure-secret-change-in-prod")
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_TTL_MINUTES = int(os.getenv("ACCESS_TOKEN_TTL_MINUTES", "720"))  # 12h
