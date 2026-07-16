# Handoff — E4-S1 / E4-S2: wings & flats

Written so a new session can start without re-deriving context.
**Task: implement E4-S1 and E4-S2 only.** Everything else in the layout epic
(reconcile, CSV, layout view, flat detail, agent contact) is later work.

## Read first

1. **`docs/USER_STORIES.md`** — the spec. E4-S1/S2 acceptance criteria, and
   decisions **D1–D6 / Q1–Q3 are already settled**. Don't relitigate them.
2. This file — state, constraints, landmines.

## Where things stand

- Branch **`dev`**, in sync with `origin/dev`. All work lands here, never `main`.
- **PR #2** (`dev` → `main`) is open, mergeable, CI green, **unmerged** — the
  merge needs a human (it triggers a production deploy).
- Tests: **72 passed / 4 skipped** — `python -m pytest backend/tests -q`.
- Agent eval: 21/21 (`docs/EVAL_REPORT.md`). Not in CI; run on demand.
- **E1 is done** (society lifecycle). E4 is the next build.

## The task

Per **D2**, flat codes are **never generated**. That splits the work in two:

**E4-S1 — declare a wing.** Name + floor count + flats-per-floor. This describes
the *shape of the grid* and **creates no flats**. Floors/flats-per-floor may
differ across wings in one society.

**E4-S2 — add a flat.** Wing + flat number + **floor**, giving
`code = "{wing}-{flat_number}"` (e.g. `A` + `101` → `A-101`). The admin types the
code; the system never invents it.

Settled decisions that shape the schema:

| | |
|---|---|
| **D1** | Flat is a real entity; `residents.flat_id` FK; keep a denormalized `flats.code` so the guard's typed string still resolves in one indexed lookup |
| **D2** | Codes are typed or imported, **never generated** |
| **Q1** | **`flats.floor` is stored, never parsed from the code** — a typed `A-101` carries no floor, and deriving it would break the first society that names flats differently |
| **Q2** | `flats_per_floor` is a **hint**: warn on mismatch, never reject. Real properties have shops on the ground floor and penthouses on top |
| **D6** | One model, called *wing/building* |

Total flats is **counted from actual flats**, never `floors × flats_per_floor` —
so the number can't lie when reality disagrees with the declared shape.

## What to build

- **`backend/db_models.py`** — `Wing` and `Flat`. Both carry `society_id`. **Add
  both to `TENANT_TABLES`** or they ship without RLS.
- **Alembic migration** — tables *plus* RLS policies. Copy the pattern from the
  initial migration (`ENABLE ROW LEVEL SECURITY` + `CREATE POLICY
  tenant_isolation` using `current_setting('app.current_society_id', true)` with
  the `app.bypass_rls` escape). A tenant table without a policy is a silent leak.
- **`residents.flat_id`** — nullable for now; **E4-S4 (reconcile)** links the
  existing free-text residents later. Don't make it required yet or you'll break
  the seed and every existing test.
- **Router + schemas** — CRUD for wings and flats. `society_admin` acts on their
  own society; `platform_admin` must name one (`resolve_society_id`).
- **Tests** — tenant scoping and role gates for every new endpoint, matching
  `test_societies.py` / `test_admin.py`.

Suggested constraints: wing name unique per society; `flats.code` unique per
society; deleting a flat with residents or visitor history is refused.

## Constraints that will bite

- **Don't break the agents.** `gate_tools`, `delivery_tools` and
  `intercom_tools` resolve residents with `Resident.flat_number == <string typed
  by the guard>`. E4-S1/S2 are **purely additive** — no agent change belongs in
  this task. The agent change is **E6-S3**, and it ships with a shared-flat eval
  scenario because the current 21 all use single-resident flats and would pass a
  regression silently.
- **Two-layer tenancy.** `society_id` always from the JWT for scoped roles; only
  a `platform_admin` may target another society, and must name it. Never trust a
  body-supplied `society_id` — `resolve_society_id()` exists for this.
- **Uniform errors.** `{error: {code, message}}` comes free via
  `backend/errors.py`; don't hand-roll shapes.
- Wing rename must **not** rewrite existing flat codes — historical
  `visitor_sessions.flat_number` has to stay meaningful.

## Environment

```powershell
.\run-local.ps1            # Postgres (docker) + migrations + backend :8000 + SPA :5173
```

- **`.env` is the single source of truth for `DATABASE_URL`** (`localhost:55432`).
  A real env var still overrides it — that's how CI and Railway work. No manual
  export needed.
- `ANTHROPIC_SSL_VERIFY=0` is set locally for the corporate TLS proxy. It must
  never be set in a deployed environment.
- Demo logins (all `password123`): `platform@gatesense.in`,
  `admin@green.gatesense.in`, `guard1@green.gatesense.in`,
  `resident@green.gatesense.in`.

## Landmines (learned the hard way this session)

- **`SESSION_HANDOFF.md` at the repo root is stale** (2026-07-02). It claims only
  `main` exists and that nothing talks to Postgres. Both are long false. Ignore
  it; it's untracked, so deleting it is a judgement call for the owner.
- **Verify by measuring, not by reading.** Two real bugs this session looked
  correct in source: a pricing button with `margin-bottom: 28px` that computed to
  `0px` (`.landing ul { margin: 0 }` at specificity (0,1,1) beats
  `.lp-plan-features` at (0,1,0)), and every route overflowing 136px at 375px
  because of the nav, not the tables. Read the rendered box.
- **Inline styles beat CSS classes.** Buttons/inputs are `.btn` / `.input`
  classes in `index.css` now — don't re-add `style={...}` on top.
- **Screenshots time out in this harness.** Verify via computed styles /
  `getBoundingClientRect`, which is more precise anyway. The headless renderer
  also freezes CSS transitions, so read settled values (`transition: none`) or
  you'll misread a mid-interpolation number.
- **Synthetic Enter doesn't activate *any* native button** here — that's the
  harness, not the app. Verify handlers with a click.
- **Ports 8000/5173 are often already taken** by the owner's `run-local` stack
  (which has `--reload`/HMR, so it already has your changes). Point a browser at
  the running server rather than fighting for the port.
- **The `origin` remote has a plaintext PAT in `.git/config`.** Never echo push
  output unredacted. It also lacks PR-write scope — `gh pr edit`/`merge` fail.

## Definition of done

- E4-S1/S2 acceptance criteria in `docs/USER_STORIES.md` met.
- New tables under RLS, with tenant-scoping + role-gate tests.
- Full suite green (`python -m pytest backend/tests -q`), frontend lints + builds.
- **The agent eval still passes 21/21** — it's the guard on flat resolution.
- Committed to `dev` and pushed.
