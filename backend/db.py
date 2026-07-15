"""
SQLAlchemy engine, session factory, and declarative Base.

A single engine/DATABASE_URL is used everywhere. Tenant isolation is NOT done
by connecting as different roles — it's done per-request via `SET ROLE app_rls`
plus a `app.current_society_id` GUC that the Postgres RLS policies filter on.
See backend/deps.py.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from backend.config import DATABASE_URL

engine = create_engine(DATABASE_URL, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()
