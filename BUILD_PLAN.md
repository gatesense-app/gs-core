# GateSense — Full-Build Plan (dev branch)

Concrete, sequenced plan to take the working demo to the full product described in
`GATESENSE_PRD.md`. This is the execution reference; the PRD remains the product
source of truth. Written 2026-07-08.

## Locked decisions (this session)

| # | Decision | Choice | Impact |
|---|---|---|---|
| 1 | Backend host + deploy | **Railway** (per PRD, no AWS) | Remove AWS ECR/ECS workflows; Railway Docker service, managed Postgres, deploy-on-merge |
| 2 | Frontend structure | **Single role-gated SPA** | Keep one `frontend/` app; route-gate by JWT role; add resident view. No 3-app split, one Vercel project |
| 3 | Database | **Railway managed Postgres** | Co-located with backend; RLS enabled on every `society_id` table |
| 4 | Build cadence | **Phase-by-phase, checkpoint between phases** | One phase built, reviewed, approved before the next |

Deviations from PRD are deliberate and recorded above (single SPA instead of 3 apps;
Railway Postgres instead of Neon). Everything else follows the PRD.

## Current state vs target

**Demo has (working):** FastAPI, all 3 agents end-to-end (gate/delivery raw Claude API,
intercom LangGraph with `interrupt()`), single Vite/React SPA (Landing, AdminDashboard,
GuardKiosk, SessionDetail), GitHub Actions + Vercel wired, Alembic initialized.

**Demo lacks (the build):**
- Postgres — `session_store.py` is in-memory; all agent tools return hardcoded mock data
- Any auth — no JWT, no RBAC, no login
- Any multi-tenancy — no `society_id`, no RLS; data hardcoded to flats A-202 / B-101
- WebSocket notifications — intercom "notifies" via `print()`; replies are synchronous POSTs
- SQLAlchemy models — none exist; Alembic `versions/` is empty
- Resident app/view and auth on guard/admin
- `requirements.txt` missing `langgraph` + `httpx` (fix stranded in unmerged `chore/verify-ci` PR)
- AWS-based deploy workflows contradict the chosen Railway host

## Phase plan

Each phase: goal → key deliverables → exit criteria. Checkpoint (your review) at every `---`.

### Phase 0 — Reconcile scaffolding  *(small, unblocks everything)*
- Pull the `langgraph` + `httpx` (and add `websockets`, `python-jose[cryptography]`,
  `passlib[bcrypt]`, `slowapi`) into `requirements.txt`; verify clean-venv install
- Remove/replace AWS workflows (`staging-deploy.yml`, `prod-deploy.yml`) with a Railway
  deploy-on-merge-to-`main` workflow; keep `pr-checks.yml`; wire `dev-deploy.yml` to `dev`
- Add root `docker-compose.yml`: FastAPI + Postgres 16 for local parity
- Update `.env.example`: `DATABASE_URL`, `JWT_SECRET`, `ANTHROPIC_API_KEY`
- Update outdated model IDs in agent code to a current Claude model
- **Exit:** `docker-compose up` boots FastAPI + Postgres locally; `pr-checks` green from a clean venv

---

### Phase 1 — Foundation: DB, multi-tenancy, auth, admin CRUD  *(largest phase)*
- SQLAlchemy models, all `society_id`-scoped: `societies`, `users`, `residents`,
  `visitors`, `visitor_sessions`, `conversation_log`, `escalations`,
  `notification_delivery_log`
- First Alembic migration (`--autogenerate`) + RLS policies on every tenant table;
  request sets `app.current_society_id` session var from the JWT claim
- JWT auth: bcrypt password login route, token with `society_id` + `role` claims;
  centralized RBAC dependency applied per-route (no scattered `if role ==`)
- `platform_admin` bypasses scoping by design; all other roles strictly scoped
- Replace `session_store.py` with a Postgres-backed store
- Admin CRUD API + SPA screens: create society → residents/users/guards → standing rules;
  login screen + role-gated routing shell
- Seed script: 3 societies, 50+ residents each, varied rules + synthetic visitor history
- **Exit:** stand up all 3 demo societies with 50+ residents each via the admin UI;
  an automated RLS test proves Society A cannot read Society B's data

---

### Phase 2 — Gate Agent onto the database
- Replace `gate_tools.py` mocks with real DB queries, scoped by `society_id`
- Persist `decision_trace` and the visitor log to Postgres
- **Exit:** POST a visitor → auto-approve / auto-deny / route correctly against *seeded DB*
  rules; trace persisted and queryable

---

### Phase 3 — Delivery Agent onto the database
- Same retrofit for `delivery_tools.py`; no new concepts
- **Exit:** known daytime deliveries auto-log; unusual ones flag anomaly and route onward

---

### Phase 4 — Intercom Agent + real-time notifications  *(the headline)*
- Persist LangGraph state (Postgres checkpointer) and `conversation_log` to DB
- Build the in-app notification service: WebSocket scoped to `resident_id` (same JWT),
  polling fallback, `notification_delivery_log` (`sent`/`delivered`/`failed`)
- Async timeout timer → escalation to backup contact (same in-app transport)
- **Exit:** clarification-loop demo works end-to-end over WebSocket and is screen-recordable

---

### Phase 5 — Wire pipeline + Guard/Kiosk + Resident UI
- All three agents connected via the shared DB-backed `VisitorSession`
- Guard kiosk: add auth + society scoping; Resident view: chat-reply + standing-rules
  management, role-gated routes in the SPA
- **Exit:** a kiosk-entered visitor flows through all three agents to a resolved state,
  visible live in both the guard and resident views

---

### Phase 6 — Admin decision-trace dashboard
- Per-session trace visualization (agent, tools, reasoning, timestamps) — extends existing
  `SessionDetail`; notification-health view (`/api/admin/notification-log`)
- **Exit:** a `society_admin` opens any session and sees the full agent reasoning trail

---

### Phase 7 — Production hardening
- Rate limiting on `POST /sessions` and `/reply`, per society
- LLM/tool-call timeouts with fail-toward-human defaults
- Uniform `{error: {code, message}}` shape, no leaked internals
- Unit tests (rule match, delivery classification), integration tests (clarification loop,
  timeout/escalation), explicit RLS test; ~20-scenario eval vs. hand-labeled ground truth
- **Exit:** test suite green in CI; eval report checked in

---

### Phase 8 — Deployment & demo assets
- Live deploy: Railway (backend + Postgres), Vercel (SPA), `gatesense.in`
- README: architecture diagram, two-layer tenant isolation callout, clarification-loop
  recording, timeout/escalation example, eval summary
- (Deferred item to revisit here: stated PII/photo retention policy, PRD §15)
- **Exit:** a stranger can visit `gatesense.in`, understand it from the README, and watch
  the recorded proof points

## Still needed from you (not blocking Phase 0/1 locally)

- **Railway:** account + project; a `DATABASE_URL` (Phase 1 can run fully on local
  docker-compose Postgres first — Railway needed at Phase 8, earlier if you want a shared dev DB)
- **`chore/verify-ci` PR:** merge or close — its real content (the `langgraph` fix) gets
  absorbed in Phase 0 either way
- **`gatesense.in` DNS** — only needed at Phase 8
- **GitHub:** remove the plaintext PAT from `origin` (handoff §7 security flag); once
  `gh auth login` is done I can manage PRs/secrets directly

## Immediate next step
On your go-ahead, I start **Phase 0** on this `dev` branch and stop for review before Phase 1.
