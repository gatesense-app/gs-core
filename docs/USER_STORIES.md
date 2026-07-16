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

## Decisions (settled)

| # | Question | Decision |
|---|---|---|
| **D1** | Is a Flat a real entity? | **Yes** — `wings` → `flats`, `residents.flat_id` FK, denormalized `flats.code` so the guard's typed string still resolves |
| **D2** | How are flat codes made? | **Never auto-generated.** `code = "{wing}-{flat_number}"`, entered manually in the UI or supplied by CSV |
| **D3** | Several residents per flat? | **Yes** |
| **D4** | Existing free-text flats? | **Reconcile** them onto generated/entered flats |
| **D5** | Which "landing page"? | **The authenticated admin home** — never the public marketing page |
| **D6** | Wing or building? | **One model**, referred to as *wing/building* |

### What D2 changes (this is the big one)

The original requirement gives a wing a **floor count** and **flats per floor**,
which reads like "generate the grid". D2 says codes are **never** generated —
they're typed or imported. Those two only reconcile one way:

> The wing's floors × flats-per-floor describes the **shape of the grid**.
> The flats that occupy it are **entered**, not derived.

Consequences, in order of importance:

1. **A flat must carry its floor explicitly.** If `A-101` is typed by hand, the
   system has no way to know it belongs on floor 1 — unless we parse the code,
   which only works if every society names flats the same way (`A-1201` on floor
   12? `A-G3` on the ground floor?). Parsing is a guess; storing is a fact.
   **→ `flats.floor` is required, and CSV needs a `floor` column.** See **Q1**.
2. **Declared shape vs actual flats can disagree.** A wing saying 10 floors × 4
   is 40 slots; an import could bring 43, or none on floor 7. The declared
   numbers become **the grid to draw and a total to check against**, not a
   constraint that silently rejects reality. See **Q2**.
3. **CSV is the bulk path, the UI is for one-offs.** Nobody hand-types 500 flats;
   without generation, import stops being a convenience and becomes the primary
   way a society gets set up. That raises E3's priority.

### Follow-ups from D2/D3 (settled)

| # | Question | Decision |
|---|---|---|
| **Q1** | Where does a flat's floor come from? | **Stored, never parsed** — `flats.floor` is explicit; CSV carries a `floor` column and the UI asks for it |
| **Q2** | Is `flats_per_floor` a rule or a hint? | **A hint** — draw the grid, warn on mismatch, never reject |
| **Q3** | Who does the intercom agent contact? | **A primary contact per flat**, defaulting to the first imported |

Why each matters:

- **Q1** — a typed `A-101` carries no floor. Deriving it would need every society
  to name flats identically (`A-1201` on floor 12? `A-G3` on the ground?), so a
  single differently-named society would silently mis-place its whole layout.
  Storing it makes the grid a fact rather than a guess.
- **Q2** — a declared 10 × 4 is a drawing aid, not a truth. Real properties have
  a shop on the ground floor and a penthouse on top; the system warns and draws
  what actually exists.
- **Q3** — this is the one that can change a live gate decision. See **E6-S3**.

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
- A resident who exists already is updated, not duplicated. **Settled:** the
  natural key is **(society_id, code, name)**, case-insensitive on name. Flat
  alone can't be the key once D3 lets a flat hold several people; the name is
  what tells them apart. Re-importing the same person updates their phone /
  primary flag rather than creating a second row.
- Only `society_admin`/`platform_admin` may import; a guard or resident gets `403`.
- Nothing in the file can override tenancy: a `society_id` column is ignored.

**Proposed columns** (per **D2**, the file carries wing + flat number, and per
**Q1** the floor too — without it a flat can't be placed on the grid):

```
wing, flat_number, floor, resident_name, phone, is_primary_contact (opt)
```

- `code` is composed as `{wing}-{flat_number}` — the file states the parts, the
  system never invents them.
- `floor` is required (**Q1**) — a typed code carries no floor, and the layout
  can't place a flat without one.
- **Several rows may share a flat** (D3): three rows with wing `A`, flat `101`
  create one flat with three residents. `is_primary_contact` marks who the
  intercom agent talks to; absent it, **the first row for that flat wins**
  (**Q3**). Two rows both claiming primary for one flat is a validation error.
- A `floor` that contradicts an existing flat's floor is a validation error, not
  a silent overwrite.
- An unknown `wing` is an error, not an implicit create — otherwise a typo
  (`"a"` vs `"A"`) silently spawns a phantom wing.
- Flats that don't exist yet **are** created by the import (this is the bulk
  path — see D2 note 3).
- **Settled:** `standing_rules` / `delivery_preferences` are **not** importable.
  They're JSON, awkward in a CSV cell, and now live on the flat (E6-S3) — the UI
  and portal set them. The import establishes occupancy; rules are a separate,
  deliberate edit.

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

## E4 — Society layout: wings/buildings, floors, flats

### E4-S1 — Define a wing/building
> **As a** society admin, **I want** to add a wing with its floors and flats per
> floor, **so that** the system knows the shape of the property.

Per **D2** this **declares the grid** — it does **not** create flats.

**Acceptance**
- Given my society, when I add a wing with a **name**, **floor count** and
  **flats per floor**, then it is saved and drawn as an empty grid.
- Floor count and flats-per-floor may **differ across wings** in the same society.
- No flats are created by this step; the grid renders empty until flats are
  entered (E4-S2) or imported (E3).
- The society shows **total flats across all wings** — counted from actual flats,
  not from `floors × flats_per_floor`, so the number never lies (**Q2**).
- Both `society_admin` (own society) and `platform_admin` (any) can do this.
- Wing names are unique within a society (they form part of every flat code).

### E4-S2 — Add a flat to a wing
> **As a** society admin, **I want** to add a flat by typing its number, **so
> that** the code matches what's actually painted on the door.

**Acceptance**
- Given a wing, when I enter a **flat number** and its **floor**, then a flat is
  created with `code = "{wing}-{flat_number}"` (e.g. wing `A` + `101` → `A-101`).
- The code is **never generated or inferred** — I typed it.
- Flat codes are unique within a society; a duplicate is rejected with a clear
  message.
- The flat appears on the layout at the floor I gave it (**Q1** — floor is
  stored, never inferred from the code).
- Entering more flats on a floor than the wing declares **warns and saves**
  (**Q2** — the declared shape is a hint).

### E4-S3 — Edit a wing after the fact
> **As a** society admin, **I want** to correct a wing, **so that** a typo
> doesn't force a rebuild.

**Acceptance**
- Renaming a wing is safe and does **not** rewrite existing flat codes — history
  (`visitor_sessions.flat_number`) must stay meaningful. A renamed wing's *new*
  flats use the new name; existing codes are immutable once visitors exist.
- Changing floors/flats-per-floor only redraws the grid.
- **Reducing** the declared shape never deletes flats. Deleting a *flat* is
  refused (or needs explicit confirmation) when it has residents or visitor
  history — silently removing an occupied flat is unacceptable.

### E4-S4 — Reconcile existing free-text flats *(see D4)*
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

### E6-S3 — The intercom agent contacts the right person *(from D3)*
> **As a** resident sharing a flat with my family, **I want** the gate to contact
> the right one of us, **so that** a visitor isn't left waiting on someone who
> isn't there.

D3 says a flat can hold several residents. Today `gate_tools`, `delivery_tools`
and `intercom_tools` all resolve a resident with `.first()` on `flat_number` —
whoever the database happens to return. With one resident per flat that was
invisible; with a family it means **notifying an arbitrary person**.

**Acceptance**
- Given a flat with several residents, when a visitor arrives, then the agent
  contacts the flat's **primary contact** — deterministically, never "whichever
  row the database returned first".
- **Exactly one primary contact per flat** is enforced; the first resident
  imported/added for a flat becomes primary by default (**Q3**), and an admin can
  change it from the flat page.
- A flat whose primary contact is removed promotes another deterministically —
  a flat with residents is never left uncontactable.
- Standing rules and delivery preferences are resolved **per flat**, not per
  resident — otherwise two residents could hold contradictory rules for the same
  door. **Settled:** `flats.standing_rules` / `flats.delivery_preferences` were
  added and win when set, falling back to the primary contact's own when not.
  They are **nullable on purpose**: `NULL` means "not set → fall back", which is
  a different statement from `[]` meaning "explicitly no rules". A `[]` default
  would have made a society's first reconcile silently overrule every resident's
  real rules — a gate behaviour change delivered by a migration. The fallback is
  also what keeps unreconciled residents (`flat_id IS NULL`) working.
- The escalation chain still works. **Settled:** the backup contact is now
  another resident of the same flat — the household, in the flat's deterministic
  order — and `residents.backup_contact_id` is dropped. A flat with nobody else
  behind the door still falls through to the guard's default policy. The
  `escalate_to_backup_contact` tool keeps its name: the agents' tool names are
  part of their prompt contract, and only the lookup changed.
- **The eval gains a shared-flat scenario** asserting the primary contact is the
  one notified. Today's 21 scenarios all use single-resident flats, so a
  regression to `.first()` would pass them silently — the eval is the only thing
  standing between this change and a wrong-person notification.

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

With D1–D6 settled, the shape is:

1. **E1** (society lifecycle: create without an admin, allocate later, `PATCH`)
   \+ **E2-S1 regression test**. No schema risk, closes the "at any given time"
   gaps. **Independent — can start now.**
2. **E4-S1/S2** — `wings` + `flats` schema (with RLS), manual entry, and
   `residents.flat_id`. The foundation for everything after.
3. **E4-S4 reconcile** (D4) — link the existing free-text residents before
   anything depends on `flat_id`.
4. **E6-S3 + eval scenario** — the agent contact change from D3. Do this *with*
   the schema, not after: it's the only item here that can change a live gate
   decision, and today's eval wouldn't catch a regression.
5. **E3 (CSV)** — the real setup path now that codes aren't generated.
6. **E5** (layout view), then **E6-S1/S2** (flat detail).

All decisions (D1–D6) and follow-ups (Q1–Q3) are settled, so nothing here is
blocked on an answer.

The one to keep honest is **step 4**: E6-S3 is the only item that can change what
happens at a real gate. Everything else is additive — new tables, new screens,
new endpoints — and can't break a decision that's already working. Ship the
shared-flat eval scenario *with* it, not after.
