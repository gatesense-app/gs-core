# User stories — society setup & flat layout

Requirements for society onboarding, bulk resident import, and a clickable
building/flat layout. Written before implementation so the decisions surface
first — several of these collide with choices already baked into the system.

Roles referenced: `platform_admin`, `society_admin`, `guard`, `resident`.

---

## Where we already are (verified against the running code, not assumed)

| Requirement | Status |
|---|---|
| Multiple society admins; any society admin can add another | ✅ **already works** — see E2-S1 |
| Platform admin adds a society | ⚠️ works, but an admin is **mandatory** at creation |
| Platform admin allocates an admin *at any time* | ❌ not possible — only at creation |
| Platform admin modifies a society | ❌ no `PATCH /societies/{id}` exists |
| CSV upload of residents | ❌ nothing |
| Buildings / wings / floors / flats | ❌ **no model exists at all** |

Three facts from the current code that shape everything below:

1. **A flat is not a thing.** `residents.flat_number` is free text (`String(32)`,
   e.g. `"A-101"`), typed by hand. There is no Building/Wing/Flat table. The
   layout feature is what turns a flat into a first-class entity.
2. **The agents look residents up by that string** — `Resident.flat_number == flat_number`
   in `gate_tools`, `delivery_tools` and `intercom_tools`. The guard also types
   the flat free-hand at the kiosk. Anything that changes flat identity must keep
   these working.
3. **One resident per flat is assumed.** Those lookups all use `.first()`. This
   requirement says a flat detail page shows "the details of the residents"
   (plural) — so this assumption has to be confronted, not worked around. See
   **D3**.

---

## Decisions needed before build (D1–D6)

These are choices, not tasks. Each blocks stories below.

### D1 — Does a Flat become a real entity? *(blocks E4, E5, E6)*
**Recommend: yes.** `buildings` → `flats`, with `residents.flat_id` FK. Keep a
denormalized `flats.code` (`"A-101"`) so the agents keep resolving the guard's
typed string with one indexed lookup and no prompt changes.
Alternative (layout is only a drawing, residents stay on free text) is cheaper
but leaves flat identity unenforced — two residents can still sit on `A-101` and
`A101` and nothing notices.

### D2 — How are flat codes generated? *(blocks E4)*
"Wing A, 10 floors, 4 flats/floor" must produce codes. Proposal:
`{wing}-{floor}{index:02d}` → `A-101 … A-104, A-201 …`. Needs answers on:
ground floor (`0` or `G`?), skipped floors (13th?), flats per floor that vary
*within* a wing, and whether admins can rename an individual flat.

### D3 — Can a flat have several residents? *(blocks E6, touches the agents)*
The layout page implies yes (a family). Today `.first()` silently picks one, so
a notification could reach the wrong person. If yes: pick a **primary contact**
per flat, or notify all. This changes agent behaviour and needs its own eval
scenario.

### D4 — What happens to residents already on free-text flats? *(blocks E4)*
Seeded societies have 60 residents on `A-101`-style strings. On introducing a
layout: auto-match by code, leave unmatched ones flagged, or block layout
creation until they reconcile?

### D5 — "Landing page" means which page?
The requirement says the layout appears "on the landing page". `/` today is the
**public marketing page**. Resident names and flat occupancy must never be
public. **Assumption: this means the authenticated admin home.** Flagging
loudly — if it really means the public page, that's a privacy no.

### D6 — Is a wing a "building" or a "wing"?
The requirement uses both. Proposal: one model, `buildings`, with a `name` free
enough to hold `"A"`, `"Palm Block"`, or `"Tower 1"`. Avoid modelling both.

---

## E1 — Society lifecycle (platform admin)

### E1-S1 — Create a society without an admin
> **As a** platform admin, **I want** to create a society without naming an
> admin, **so that** I can onboard the property before I know who runs it.

Today `POST /societies` **requires** `admin_email` + `admin_password`, so a
society cannot exist adminless.

**Acceptance**
- Given I am a platform admin, when I create a society with only a name and
  address, then it is created and appears in the societies list.
- Admin details become optional; when supplied, behaviour is unchanged (society
  + admin created together) so nothing existing breaks.
- A society with no admin is visibly marked as such in the list.
- Only a platform admin may create a society (a society admin gets `403`).

### E1-S2 — Allocate an admin to an existing society at any time
> **As a** platform admin, **I want** to add a society admin to any society
> whenever I choose, **so that** onboarding isn't a one-shot.

**Acceptance**
- Given a society with no admin, when I add one, then they can sign in and
  administer only that society.
- I can add an admin to a society that already has one (multiple allowed).
- The new admin lands in the target society, never mine — `society_id` comes
  from the request path/body **validated against my platform role**, never from
  a society admin's input.
- Duplicate email returns `409` with the uniform error shape.

### E1-S3 — Modify a society
> **As a** platform admin, **I want** to edit a society's name and address,
> **so that** I can fix mistakes and reflect renames.

No `PATCH /societies/{id}` exists today.

**Acceptance**
- Given a society, when I change its name/address, then the change persists and
  shows everywhere it's displayed.
- A society admin **cannot** edit their society (platform admin only) — or, if
  the product wants that, it's a separate explicit decision.
- Editing a society never touches its residents, users or sessions.
- RLS still applies: a platform admin acts with `bypass_rls`; nobody else can
  reach another tenant's society row.

---

## E2 — Society admins

### E2-S1 — Any society admin can add another ✅ *already works*
> **As a** society admin, **I want** to add another society admin, **so that**
> I'm not a single point of failure.

**Verified live**: a `society_admin` `POST /users` with `role: "society_admin"`
returned `201`, scoped to their own society. `resolve_society_id()` forces the
caller's society, so they cannot plant an admin in another tenant. The Users
screen already offers `society_admin` in its role dropdown.

**Remaining work is confirmation, not construction:**
- Add a regression test asserting a society admin can create a society admin
  **in their own society only**, and that a supplied foreign `society_id` is
  ignored.
- Confirm the UI wording makes it discoverable.

### E2-S2 — See who administers a society
> **As a** society admin, **I want** to see the other admins, **so that** I know
> who has control.

**Acceptance**
- Given several admins, when I open Users, then I can tell admins from guards
  and residents at a glance (the role chip already does this).
- A platform admin can see admins per society.
- **Open:** can an admin remove/deactivate another admin? Guard against removing
  the last one — leaving a society adminless should be impossible or explicit.

---

## E3 — Bulk resident import (CSV)

### E3-S1 — Upload residents via CSV
> **As a** society admin (or platform admin), **I want** to upload a CSV of
> residents, **so that** I don't hand-type 300 flats.

**Acceptance**
- Given a CSV with a documented header, when I upload it, then residents are
  created in my society (platform admin: in a society they name).
- A downloadable template/example is offered next to the upload.
- The file is validated **before** anything is written: I see how many rows will
  be created/updated/rejected, and why, and can cancel.
- Import is **all-or-nothing per upload** (one transaction) — a bad row 250
  never leaves 249 half-imported residents.
- Errors report the **row number and the offending column**, not "invalid input".
- A resident who exists already (same flat + name, or a chosen key) is updated,
  not duplicated — **Open:** what is the natural key? Flat alone is not unique
  once D3 says a flat can hold several people.
- Only `society_admin`/`platform_admin` may import; a guard or resident gets `403`.
- Nothing in the file can override tenancy: a `society_id` column is ignored.

**Proposed columns:** `flat_number, name, phone, backup_contact_flat (opt),
standing_rules (opt), delivery_preferences (opt)`.
**Open:** are rules/preferences in scope for import, given they're JSON?

### E3-S2 — CSV rejects unsafe/malformed input
> **As a** society admin, **I want** a bad file to fail loudly, **so that** I
> don't silently corrupt the resident list.

**Acceptance**
- Non-CSV, wrong headers, empty file → clear, actionable error.
- A size/row cap exists (uploading a 2M-row file must not take the API down).
- Fields are treated as **data, never formulas** — a cell starting `=`, `+`, `-`
  or `@` is neutralised so exports can't become spreadsheet injection.
- Encoding (UTF-8/BOM) and stray whitespace handled; `A-101 ` == `A-101`.

---

## E4 — Society layout: buildings, floors, flats

### E4-S1 — Define a building/wing
> **As a** society admin, **I want** to add a building with its floors and flats
> per floor, **so that** the system reflects the real property.

**Acceptance**
- Given my society, when I add a building with a **name**, **floor count**, and
  **flats per floor**, then its flats are generated with codes per **D2**.
- Floor count and flats-per-floor may **differ across buildings** in the same
  society.
- The society shows **total flats across all wings**, derived — never typed.
- Both `society_admin` (own society) and `platform_admin` (any) can do this.
- Building names are unique within a society.

### E4-S2 — Edit a building after the fact
> **As a** society admin, **I want** to correct a building, **so that** a typo
> doesn't force a rebuild.

**Acceptance**
- Renaming a building is safe.
- **Adding** floors/flats generates the new flats only; existing flats and their
  residents are untouched.
- **Reducing** floors/flats is refused (or requires explicit confirmation) when
  the flats being removed have residents or visitor history. Deleting occupied
  flats silently is unacceptable.
- **Open:** does renaming a wing rewrite every flat code — and therefore every
  historical `visitor_sessions.flat_number`? Recommend codes are immutable once
  visitors exist.

### E4-S3 — Reconcile existing free-text flats *(see D4)*
> **As a** platform admin, **I want** existing residents matched to generated
> flats, **so that** introducing a layout doesn't orphan anyone.

**Acceptance**
- On layout creation, residents whose `flat_number` matches a generated code are
  linked automatically.
- Non-matching residents are listed for manual resolution — never dropped.
- The agents keep working throughout: a guard typing `A-101` still resolves.

---

## E5 — Layout view

### E5-S1 — Pick a building and see its flats
> **As a** society/platform admin, **I want** to select a wing and see its
> layout, **so that** I can navigate the property visually.

**Acceptance**
- Given a society with buildings, when I open the layout (**authenticated admin
  page — D5**) and pick a building, then I see floors and flats laid out
  spatially (floor per row).
- Each flat is **clickable** and shows its code.
- A flat's state is legible at a glance — e.g. occupied vs vacant — **and never
  by colour alone** (this codebase's existing rule).
- Empty state: a society with no buildings explains how to add one.
- Works on a phone: no page-level horizontal scroll (an existing invariant).
- Flats are keyboard reachable, not click-only.
- A society admin sees only their society's buildings (RLS + role).

### E5-S2 — Layout at scale
> **As an** admin of a large society, **I want** the layout to stay usable at
> 500+ flats, **so that** it's not a wall of squares.

**Acceptance**
- 20 floors × 8 flats renders without jank.
- **Open:** does the layout need occupancy/visitor status live on it (WebSocket),
  or is it a static directory? Live status is a much bigger build.

---

## E6 — Flat detail

### E6-S1 — Open a flat and see its residents
> **As an** admin, **I want** to click a flat and see who lives there, **so that**
> I can answer "who is in A-101?" without searching.

**Acceptance**
- Given a flat, when I click it, then I navigate to a detail page showing every
  resident (**plural — D3**): name, phone, standing rules, delivery preferences.
- A vacant flat says so, and offers to add a resident.
- Recent visitor sessions for that flat are shown (data already exists).
- Deep-linkable: the URL can be shared/refreshed (an existing SPA invariant).
- A society admin cannot open another society's flat (`404`, not `403` — matching
  how we already avoid confirming existence).
- **Resident PII is admin-only.** A guard must not browse resident phone numbers
  through this page; residents must not see neighbours. Decide guard access
  explicitly.

### E6-S2 — Manage residents from the flat
> **As an** admin, **I want** to add/edit/remove a resident on the flat page,
> **so that** I don't go elsewhere to fix an occupancy.

**Acceptance**
- Add/edit/remove a resident in place.
- Removing the last resident marks the flat vacant, not deleted.
- Changes are reflected immediately in the layout view.

---

## Cross-cutting (applies to every story)

- **Tenancy**: `society_id` always from the JWT for scoped roles; only a
  platform admin may target another society, and must name it. New tables get
  **RLS policies** like every other tenant table — the existing two-layer model.
- **Errors**: uniform `{error: {code, message}}`; no internals leaked.
- **Audit**: creating/renaming buildings and importing residents change what the
  agents decide. Consider recording who did it.
- **Tests**: every new endpoint gets tenant-scoping and role-gate tests, matching
  the existing suite.
- **Agents must not regress**: the eval (`docs/EVAL_REPORT.md`) is the guard —
  re-run it after any change to flat resolution.

---

## Suggested sequencing

1. **E1** (society lifecycle) + **E2-S1 test** — small, no schema risk, closes
   the "at any given time" gaps.
2. **D1–D4 decisions**, then **E4-S1/S3** (schema + generation + reconcile) —
   the foundation everything else needs.
3. **E3** (CSV) — depends on whether flats must pre-exist (D1).
4. **E5**, then **E6**.

E1 is genuinely independent and could start now. Everything from E3 onward hangs
on **D1** (is a flat an entity?) and **D3** (can it hold several residents?) —
those two are worth deciding first, because they're the ones that reach back into
the agents.
