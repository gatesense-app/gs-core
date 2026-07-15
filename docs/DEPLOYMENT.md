# Deployment runbook

Backend + Postgres on **Railway**, SPA on **Vercel**, domain **gatesense.in**.

These steps need account access and secrets, so they are run by a maintainer —
not automated here. Everything the code needs to *be* deployable is already in
the repo (`backend/Dockerfile`, `frontend/vercel.json`, env-driven config, and
the workflows in `.github/workflows/`).

---

## 0. Before you start

| You need | Why |
|---|---|
| Railway account + project | backend container + managed Postgres |
| Vercel account + project (root: `frontend`) | the SPA |
| DNS access for `gatesense.in` | custom domains |
| An `ANTHROPIC_API_KEY` | the agents |

Generate a real JWT secret — the app **refuses to boot** in production with the
dev default:

```bash
openssl rand -hex 32
```

---

## 1. Railway — Postgres

1. Create the project → **New → Database → PostgreSQL**.
2. Copy the connection string it generates (`DATABASE_URL`).

RLS needs the `app_rls` role, which the initial migration creates. Railway's
default user must be able to `CREATE ROLE` — the managed Postgres user can.

## 2. Railway — backend

1. **New → GitHub Repo** → this repo. Set the Dockerfile path to
   `backend/Dockerfile` and the build context to the repo root.
2. Set variables:

   | Variable | Value |
   |---|---|
   | `DATABASE_URL` | reference the Postgres service's variable |
   | `ANTHROPIC_API_KEY` | your key |
   | `JWT_SECRET` | the value from step 0 |
   | `APP_ENV` | `production` (the image defaults to this; set it explicitly anyway) |
   | `CORS_ORIGINS` | `https://gatesense.in,https://www.gatesense.in` (add the Vercel preview URL while testing) |
   | `ANTHROPIC_MODEL` | *(optional)* defaults to `claude-sonnet-5` |
   | `LLM_TIMEOUT_SECONDS` | *(optional)* defaults to `45` |
   | `RESIDENT_TIMEOUT_MINUTES` | *(optional)* defaults to `10` — how long a visitor waits on a silent resident before escalating to their backup contact |

   Do **not** set `ANTHROPIC_SSL_VERIFY`. It disables TLS verification and exists
   only for local dev behind an intercepting proxy.

3. Do not set `PORT` — Railway injects it and the image binds `${PORT:-8000}`.
4. Release command (so schema changes ship with the code):

   ```
   alembic upgrade head
   ```

5. Deploy, then confirm: `https://<service>.up.railway.app/docs` loads.

> **Rate limits are per-process.** The limiter holds buckets in memory, so with
> more than one replica each process allows the full limit. Keep the backend at
> one instance, or move the buckets to Redis first (`backend/ratelimit.py`).

> **The timeout sweeper runs in the API process** (`backend/timeouts.py`). With
> multiple replicas each would sweep, so a session could be escalated twice.
> The sweep is idempotent on status (only `awaiting_resident` is eligible), but
> take a lock — or move it to a single worker — before scaling out.
> `TIMEOUT_SWEEPER_ENABLED=0` disables it.

LangGraph creates its own `checkpoints*` tables on first boot (see
`backend/checkpointer.py`). They hold in-flight conversation state, are keyed by
session id, and — unlike the application tables — are **not** under RLS. Include
them in backups; a lost checkpoint strands any conversation in flight.

## 3. Vercel — SPA

1. **New Project** → this repo → **Root Directory: `frontend`**. `vercel.json`
   supplies the framework, build command, and the SPA rewrite (without it,
   refreshing `/dashboard` would 404).
2. Environment variable:

   | Variable | Value |
   |---|---|
   | `VITE_API_URL` | `https://<service>.up.railway.app` (no trailing slash) |

   It must be **https** — the WebSocket URL is derived from it, and a `ws://`
   socket from an https page is blocked as mixed content.
3. Deploy.

## 4. Domain

1. Vercel → project → **Domains** → add `gatesense.in` and `www.gatesense.in`;
   create the DNS records it shows.
2. Add the same origins to the backend's `CORS_ORIGINS` and redeploy it.

## 5. Seed the first society

The seed script is demo data (3 societies, 60 flats each, shared password) —
fine for a demo, **not** for a real society.

```bash
DATABASE_URL='<railway url>' python -m backend.seed
```

For a real tenant, create the society and its admin through the API as a
`platform_admin` instead (`POST /societies`), then let that admin add residents,
guards and resident logins.

## 6. Verify

- [ ] `/docs` loads on Railway
- [ ] The site loads on `gatesense.in`
- [ ] Sign in works (no CORS errors in the console)
- [ ] A kiosk submission returns a decision (agents can reach Anthropic)
- [ ] The resident portal updates **live** (WebSocket connected, `wss://`)
- [ ] Refreshing `/dashboard` does not 404 (SPA rewrite)
- [ ] A deliberately bad request returns `{"error":{"code":…,"message":…}}` and no traceback

## CI/CD

| Workflow | Trigger | Does |
|---|---|---|
| `pr-checks.yml` | PRs to `main`, pushes to `dev` | backend tests, frontend lint + build, Vercel preview (PRs only) |
| `deploy.yml` | push to `main` | migrations, then Railway + Vercel production deploy |
| `dev-deploy.yml` | manual | deploy `dev` to a staging service |

Repo secrets required by the deploy workflows: `RAILWAY_TOKEN`,
`PROD_DATABASE_URL`, `VERCEL_TOKEN`, `VERCEL_ORG_ID`, `VERCEL_PROJECT_ID`.

The agent eval is **not** in CI (real Claude calls, non-deterministic). Run it
when prompts or agent behaviour change and commit the report:

```bash
python -m backend.eval.run_eval
```

---

## Security checklist before going live

- [ ] `JWT_SECRET` is a real random value (the app won't boot otherwise)
- [ ] `ANTHROPIC_SSL_VERIFY` is **unset** in production
- [ ] `CORS_ORIGINS` lists only origins you control — not `*`
- [ ] `.env` is not committed (it is gitignored; verify with `git ls-files .env`)
- [ ] The `origin` remote has no plaintext token in `.git/config` — if a PAT was
      ever embedded there or pushed, **rotate it**
- [ ] Demo seed accounts (`password123`) are not present in a real deployment
- [ ] Backups enabled on the Railway Postgres
