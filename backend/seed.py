"""
Seed 3 demo societies with 60 residents each, varied standing rules, and
synthetic visitor history. Idempotent — truncates the tenant tables first.

    python -m backend.seed

All demo accounts share the password below (demo only).
"""

import random
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from backend import db_models as m
from backend.deps import system_session
from backend.security import hash_password

DEMO_PASSWORD = "password123"

_FIRST = [
    "Priya", "Arun", "Vikram", "Neha", "Rahul", "Anjali", "Karan", "Sneha",
    "Rohan", "Divya", "Amit", "Pooja", "Sanjay", "Meera", "Vivek", "Kavya",
]
_LAST = [
    "Sharma", "Mehta", "Nair", "Reddy", "Iyer", "Gupta", "Patel", "Rao",
    "Verma", "Joshi", "Kulkarni", "Menon",
]
_SERVICES = ["Swiggy", "Zomato", "Amazon", "Blinkit", "Flipkart"]

_SOCIETIES = [
    ("Green Meadows", "MG Road, Bengaluru", "green"),
    ("Palm Grove Residency", "Baner, Pune", "palm"),
    ("Lake View Towers", "Powai, Mumbai", "lake"),
]

_KNOWN_VISITORS = [
    # name, type, is_known_service, typical_hours, visit_count
    ("Swiggy", "delivery", True, {"start": "11:00", "end": "22:00"}, 45),
    ("Zomato", "delivery", True, {"start": "11:00", "end": "23:00"}, 38),
    ("Amazon", "delivery", True, {"start": "09:00", "end": "19:00"}, 27),
    ("Blinkit", "delivery", True, {"start": "07:00", "end": "23:00"}, 52),
    ("Raju Plumber", "service", False, {"start": "09:00", "end": "18:00"}, 12),
    ("Lakshmi (Maid)", "service", False, {"start": "07:00", "end": "11:00"}, 120),
    ("Uber", "cab", False, {"start": "06:00", "end": "23:00"}, 30),
    ("Rapido", "cab", False, {"start": "06:00", "end": "23:00"}, 15),
]


def _standing_rules(rng: random.Random) -> list[dict]:
    rules: list[dict] = []
    if rng.random() < 0.4:
        rules.append({"type": "always_allow", "match": rng.choice(_SERVICES)})
    if rng.random() < 0.3:
        rules.append({"type": "never_allow", "after": rng.choice(["21:00", "22:00", "23:00"])})
    return rules


def _delivery_prefs(rng: random.Random) -> dict:
    return {
        "auto_log_daytime": rng.random() < 0.7,
        "notify_after_hours": rng.random() < 0.6,
    }


def seed() -> None:
    rng = random.Random(42)
    now = datetime.now(timezone.utc)

    with system_session() as db:
        db.execute(
            text(
                "TRUNCATE societies, residents, users, visitors, visitor_sessions, "
                "conversation_log, escalations, notification_delivery_log "
                "RESTART IDENTITY CASCADE"
            )
        )

        db.add(
            m.User(
                society_id=None,
                email="platform@gatesense.in",
                password_hash=hash_password(DEMO_PASSWORD),
                role="platform_admin",
                full_name="Platform Operator",
            )
        )

        for name, address, slug in _SOCIETIES:
            society = m.Society(name=name, address=address)
            db.add(society)
            db.flush()

            db.add(
                m.User(
                    society_id=society.id,
                    email=f"admin@{slug}.gatesense.in",
                    password_hash=hash_password(DEMO_PASSWORD),
                    role="society_admin",
                    full_name=f"{name} Admin",
                )
            )
            for g in range(1, 4):
                db.add(
                    m.User(
                        society_id=society.id,
                        email=f"guard{g}@{slug}.gatesense.in",
                        password_hash=hash_password(DEMO_PASSWORD),
                        role="guard",
                        full_name=f"{name} Guard {g}",
                    )
                )

            first_resident = None
            for block in ("A", "B", "C"):
                for flat in range(101, 121):  # 20 x 3 blocks = 60 residents
                    resident = m.Resident(
                        society_id=society.id,
                        flat_number=f"{block}-{flat}",
                        name=f"{rng.choice(_FIRST)} {rng.choice(_LAST)}",
                        phone=f"+9198{rng.randint(10000000, 99999999)}",
                        standing_rules=_standing_rules(rng),
                        delivery_preferences=_delivery_prefs(rng),
                    )
                    db.add(resident)
                    if first_resident is None:
                        first_resident = resident

            db.flush()  # populate resident ids

            # One resident-login user per society (linked to the first flat).
            db.add(
                m.User(
                    society_id=society.id,
                    email=f"resident@{slug}.gatesense.in",
                    password_hash=hash_password(DEMO_PASSWORD),
                    role="resident",
                    full_name=first_resident.name,
                    resident_id=first_resident.id,
                )
            )

            for vn, vt, known_svc, hours, vc in _KNOWN_VISITORS:
                db.add(
                    m.Visitor(
                        society_id=society.id,
                        name=vn,
                        visitor_type=vt,
                        is_known_service=known_svc,
                        typical_hours=hours,
                        visit_count=vc,
                        last_visit_at=now - timedelta(days=rng.randint(0, 5)),
                        notes="Seeded known visitor",
                    )
                )

    print("Seed complete.")
    print(f"  3 societies x 60 residents, 3 guards + 1 admin + 1 resident login each.")
    print(f"  Demo password (all accounts): {DEMO_PASSWORD}")
    print("  platform_admin: platform@gatesense.in")
    print("  society_admin:  admin@green.gatesense.in / admin@palm.gatesense.in / admin@lake.gatesense.in")


if __name__ == "__main__":
    seed()
