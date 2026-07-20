# GateSense agent eval

Scores the three agents against hand-labeled ground truth (`backend/eval/scenarios.py`). The label is the **status the session should end in** — what a resident actually cares about — not the model's wording.

Regenerate with:

```bash
python -m backend.eval.run_eval
```

- **Run:** 2026-07-20T05:29:17+00:00
- **Result:** 23/23 passed (100%)

| Scenario | Expected | Actual | Agents | Result |
|---|---|---|---|---|
| `gate-01` | auto_approved | auto_approved | gate | ✅ |
| `gate-02` | auto_approved | auto_approved | gate | ✅ |
| `gate-03` | awaiting_resident | awaiting_resident | gate → intercom | ✅ |
| `gate-04` | awaiting_resident | awaiting_resident | gate → intercom | ✅ |
| `gate-05` | awaiting_resident | awaiting_resident | gate → delivery → intercom | ✅ |
| `gate-06` | awaiting_resident | awaiting_resident | gate → intercom | ✅ |
| `gate-07` | awaiting_resident | awaiting_resident | gate → delivery → intercom | ✅ |
| `gate-08` | auto_approved | auto_approved | gate | ✅ |
| `deliv-01` | awaiting_resident | awaiting_resident | gate → delivery → intercom | ✅ |
| `deliv-02` | awaiting_resident | awaiting_resident | gate → delivery → intercom | ✅ |
| `deliv-03` | auto_approved | auto_approved | gate → delivery | ✅ |
| `deliv-04` | awaiting_resident | awaiting_resident | gate → delivery → intercom | ✅ |
| `deliv-05` | auto_approved | auto_approved | gate → delivery | ✅ |
| `icom-01` | approved | approved | gate → intercom | ✅ |
| `icom-02` | denied | denied | gate → intercom | ✅ |
| `icom-03` | approved | approved | gate → intercom | ✅ |
| `icom-04` | denied | denied | gate → intercom | ✅ |
| `icom-05` | awaiting_resident | awaiting_resident | gate → intercom | ✅ |
| `icom-06` | approved | approved | gate → intercom | ✅ |
| `icom-07` | escalated | escalated | gate → delivery → intercom | ✅ |
| `icom-08` | denied | denied | gate → intercom | ✅ |
| `share-01` | awaiting_resident | awaiting_resident | gate → intercom | ✅ |
| `share-02` | approved | approved | gate → intercom | ✅ |

### What each scenario checks

- **`gate-01`** — A standing always_allow rule matches the visitor exactly -> let them in, no resident needed.
- **`gate-02`** — Rule matching should be case-insensitive; 'swiggy' is the same rule.
- **`gate-03`** — Unknown guest, no rule covers it -> must ask the resident, never guess.
- **`gate-04`** — A known person (not a service) with no rule still needs resident confirmation.
- **`gate-05`** — A rule for one flat must not leak to another flat.
- **`gate-06`** — Cabs are not covered by any rule -> resident decides.
- **`gate-07`** — A-104's always_allow names Amazon, not Zomato; with auto-logging off the resident must decide.
- **`gate-08`** — always_allow on A-104 is Amazon -> exact match auto-approves.
- **`deliv-01`** — Unknown local courier -> anomaly, must not auto-approve.
- **`deliv-02`** — Known service but the resident opted OUT of auto-logging -> ask them.
- **`deliv-03`** — Known service + resident opted IN to daytime auto-logging -> clear it.
- **`deliv-04`** — A vague 'courier' with no brand is not a known service.
- **`deliv-05`** — auto_log_daytime is a blanket opt-in: on A-101 any known service in-window clears even though the always_allow rule names a different brand.
- **`icom-01`** — A plain ALLOW approves entry.
- **`icom-02`** — A plain DENY refuses entry.
- **`icom-03`** — Natural-language yes should be read as approval, not just the literal word.
- **`icom-04`** — Natural-language refusal should be read as a denial.
- **`icom-05`** — A question is not a decision -> stay open, don't resolve.
- **`icom-06`** — Full clarification loop: question -> guard answers -> resident approves.
- **`icom-07`** — Deferring to the guard escalates rather than approving.
- **`icom-08`** — Clarification then refusal must end denied, not approved.
- **`share-01`** — A flat with a family must notify its primary contact (Meera), not whichever resident the database returned first (Karan). This is the only scenario that fails on a regression to an unordered .first().
- **`share-02`** — The primary contact answers for the whole flat: her reply resolves the visit without asking anyone else in the household.

### Notes

- Scenarios marked `daytime_only` depend on the flat's typical delivery
  window (07:00–23:00) and are skipped outside it rather than failed.
- The eval is not part of the pytest/CI suite: it makes real Claude calls.
  CI runs the deterministic tests; this is run when prompts or agent
  behaviour change, and the report is committed as the record.
