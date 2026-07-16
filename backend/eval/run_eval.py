"""
Score the agents against hand-labeled ground truth and write a report.

    python -m backend.eval.run_eval                 # all scenarios
    python -m backend.eval.run_eval --only gate     # scenarios whose id starts with 'gate'

Makes real Claude calls (a few per scenario), so a full run costs money and
takes a couple of minutes. It is deliberately NOT part of the pytest suite —
CI runs the deterministic tests; this is run on demand when agent behaviour or
prompts change, and the report is committed as the record.

Each scenario runs against a purpose-built society whose flats have known rules,
in a fresh session per leg (mirroring one HTTP request per leg).
"""

import argparse
import sys
from datetime import datetime, timezone

from sqlalchemy import select, text

from backend import db_models as m
from backend.deps import scoped_session, system_session
from backend.eval.scenarios import SCENARIOS
from backend.pipeline import handle_resident_reply, handle_visitor_entry

SOCIETY_NAME = "EVAL-Society"
REPORT_PATH = "docs/EVAL_REPORT.md"

_FLATS = [
    # flat,   name,            standing_rules,                                  delivery_preferences
    ("A-101", "Priya Sharma", [{"type": "always_allow", "match": "Swiggy"}],
     {"auto_log_daytime": True, "notify_after_hours": True}),
    ("A-102", "Arun Mehta", [{"type": "never_allow", "after": "21:00"}],
     {"auto_log_daytime": True, "notify_after_hours": True}),
    ("A-103", "Neha Reddy", [],
     {"auto_log_daytime": False, "notify_after_hours": True}),
    ("A-104", "Vikram Rao", [{"type": "always_allow", "match": "Amazon"}],
     {"auto_log_daytime": False, "notify_after_hours": True}),
]

# A-105 is a family flat (D3), and the reason E6-S3 exists: the agents must
# contact its *primary* resident, not whoever the database hands back.
#
# The insert order below is load-bearing. Karan is written FIRST and Meera is
# the primary — so an unordered `.first()`, which is what every tool did before
# E6-S3, returns Karan and fails the scenario. Seed them the other way round and
# the bug would pass this eval silently, which is exactly the trap this scenario
# is here to close.
_SHARED_FLAT = "A-105"
_SHARED_RESIDENTS = [
    # name,          is_primary
    ("Karan Iyer", False),
    ("Meera Iyer", True),
]
_SHARED_PRIMARY = "Meera Iyer"

_VISITORS = [
    # name, type, is_known_service, typical_hours, visit_count
    ("Swiggy", "delivery", True, {"start": "11:00", "end": "23:00"}, 45),
    ("Amazon", "delivery", True, {"start": "09:00", "end": "19:00"}, 27),
    ("Blinkit", "delivery", True, {"start": "07:00", "end": "23:00"}, 52),
    ("Raju Plumber", "service", False, {"start": "09:00", "end": "18:00"}, 12),
    ("Lakshmi (Maid)", "service", False, {"start": "07:00", "end": "11:00"}, 120),
    ("Uber", "cab", False, {"start": "06:00", "end": "23:00"}, 30),
]


def setup() -> str:
    """Recreate the eval society from scratch so runs are comparable."""
    with system_session() as db:
        db.execute(text("DELETE FROM societies WHERE name = :n"), {"n": SOCIETY_NAME})
        soc = m.Society(name=SOCIETY_NAME, address="Eval fixture")
        db.add(soc)
        db.flush()
        for flat, name, rules, prefs in _FLATS:
            db.add(m.Resident(society_id=soc.id, flat_number=flat, name=name,
                              is_primary=True, standing_rules=rules,
                              delivery_preferences=prefs))
        # Written one at a time so the physical row order is Karan-then-Meera
        # (see _SHARED_RESIDENTS): the scenario has to be able to fail.
        for name, is_primary in _SHARED_RESIDENTS:
            db.add(m.Resident(
                society_id=soc.id, flat_number=_SHARED_FLAT, name=name,
                is_primary=is_primary, standing_rules=[],
                delivery_preferences={"auto_log_daytime": False, "notify_after_hours": True},
            ))
            db.flush()
        for vn, vt, known, hours, count in _VISITORS:
            db.add(m.Visitor(society_id=soc.id, name=vn, visitor_type=vt,
                             is_known_service=known, typical_hours=hours,
                             visit_count=count, notes="Eval fixture"))
        db.flush()
        return str(soc.id)


def teardown() -> None:
    with system_session() as db:
        db.execute(text("DELETE FROM societies WHERE name = :n"), {"n": SOCIETY_NAME})


def _run_one(society_id: str, sc: dict) -> dict:
    """Run one scenario; return its result row."""
    with scoped_session(society_id) as db:
        row = handle_visitor_entry(
            db, society_id, sc["visitor"], sc["flat"], sc["purpose"], sc["detail"])
        session_id = row.id
        status = row.status
        agents = [t["agent"] for t in (row.decision_trace or [])]

    # Each reply is its own request in production -> its own session here.
    for reply in sc.get("replies", []):
        with scoped_session(society_id) as db:
            row = db.get(m.VisitorSession, session_id)
            if row.status != "awaiting_resident":
                break  # already resolved; further replies aren't accepted
            row = handle_resident_reply(db, row, reply)
            status = row.status
            agents = [t["agent"] for t in (row.decision_trace or [])]

    escalated = False
    if sc.get("expect_escalation"):
        with scoped_session(society_id) as db:
            escalated = db.execute(
                select(m.Escalation).where(m.Escalation.session_id == session_id)
            ).scalars().first() is not None

    # Who did we actually wake up? The status label can be right while the wrong
    # person is holding the phone, so a shared flat has to assert the name too
    # (E6-S3).
    notified = None
    if sc.get("expect_notified"):
        with scoped_session(society_id) as db:
            notified = db.execute(
                select(m.Resident.name)
                .join(m.NotificationDeliveryLog,
                      m.NotificationDeliveryLog.resident_id == m.Resident.id)
                .where(m.NotificationDeliveryLog.session_id == session_id)
            ).scalars().first()

    passed = status == sc["expected"]
    if sc.get("expect_escalation") and not escalated:
        passed = False
    if sc.get("expect_notified") and notified != sc["expect_notified"]:
        passed = False

    return {
        "id": sc["id"],
        "why": sc["why"],
        "expected": sc["expected"],
        "actual": status,
        "agents": agents,
        "escalation_expected": bool(sc.get("expect_escalation")),
        "escalation_found": escalated,
        "notified_expected": sc.get("expect_notified"),
        "notified_actual": notified,
        "passed": passed,
    }


def _in_daytime_window() -> bool:
    return 7 <= datetime.now().hour < 23


def main() -> int:
    ap = argparse.ArgumentParser(description="Run the GateSense agent eval.")
    ap.add_argument("--only", help="only scenarios whose id starts with this prefix")
    args = ap.parse_args()

    scenarios = [s for s in SCENARIOS if not args.only or s["id"].startswith(args.only)]

    results, skipped = [], []
    society_id = setup()
    started = datetime.now(timezone.utc)
    try:
        for sc in scenarios:
            if sc.get("daytime_only") and not _in_daytime_window():
                skipped.append({"id": sc["id"], "reason": "outside the 07:00-23:00 delivery window"})
                print(f"[skip] {sc['id']} (outside delivery window)")
                continue
            res = _run_one(society_id, sc)
            results.append(res)
            mark = "PASS" if res["passed"] else "FAIL"
            print(f"[{mark}] {res['id']}: expected={res['expected']} actual={res['actual']}")
    finally:
        teardown()

    passed = sum(1 for r in results if r["passed"])
    total = len(results)
    accuracy = (passed / total * 100) if total else 0.0
    _write_report(results, skipped, started, passed, total, accuracy)

    print(f"\n{passed}/{total} passed ({accuracy:.0f}%). Report: {REPORT_PATH}")
    return 0 if passed == total else 1


def _write_report(results, skipped, started, passed, total, accuracy) -> None:
    lines = [
        "# GateSense agent eval",
        "",
        "Scores the three agents against hand-labeled ground truth "
        "(`backend/eval/scenarios.py`). The label is the **status the session should "
        "end in** — what a resident actually cares about — not the model's wording.",
        "",
        "Regenerate with:",
        "",
        "```bash",
        "python -m backend.eval.run_eval",
        "```",
        "",
        f"- **Run:** {started.isoformat(timespec='seconds')}",
        f"- **Result:** {passed}/{total} passed ({accuracy:.0f}%)",
        "",
        "| Scenario | Expected | Actual | Agents | Result |",
        "|---|---|---|---|---|",
    ]
    for r in results:
        agents = " → ".join(dict.fromkeys(r["agents"])) or "—"
        lines.append(
            f"| `{r['id']}` | {r['expected']} | {r['actual']} | {agents} | "
            f"{'✅' if r['passed'] else '❌'} |"
        )

    if skipped:
        lines += ["", "### Skipped", ""]
        for s in skipped:
            lines.append(f"- `{s['id']}` — {s['reason']}")

    failures = [r for r in results if not r["passed"]]
    if failures:
        lines += ["", "### Failures", ""]
        for r in failures:
            lines.append(f"- **`{r['id']}`** — {r['why']}")
            lines.append(f"  - expected `{r['expected']}`, got `{r['actual']}`")
            if r["escalation_expected"] and not r["escalation_found"]:
                lines.append("  - expected an escalation row, none was recorded")
            if r["notified_expected"] and r["notified_actual"] != r["notified_expected"]:
                lines.append(
                    f"  - expected `{r['notified_expected']}` to be notified, "
                    f"got `{r['notified_actual']}`"
                )

    lines += [
        "",
        "### What each scenario checks",
        "",
    ]
    for r in results:
        lines.append(f"- **`{r['id']}`** — {r['why']}")

    lines += [
        "",
        "### Notes",
        "",
        "- Scenarios marked `daytime_only` depend on the flat's typical delivery",
        "  window (07:00–23:00) and are skipped outside it rather than failed.",
        "- The eval is not part of the pytest/CI suite: it makes real Claude calls.",
        "  CI runs the deterministic tests; this is run when prompts or agent",
        "  behaviour change, and the report is committed as the record.",
        "",
    ]
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


if __name__ == "__main__":
    sys.exit(main())
