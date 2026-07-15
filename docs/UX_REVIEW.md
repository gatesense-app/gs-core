# UX review — GateSense app

Review of the authenticated SPA (kiosk, dashboard, session detail, resident
portal, admin CRUD). The marketing Landing page is excluded — it is responsive,
has real hover/focus states and semantic headings, and is in good shape. **Every
finding below is about the product UI, which did not get the same treatment.**

Ranked by severity. Each item says what it is, where, why it matters *here*, and
the fix. Line numbers are from the commit this review was written against.

## Status

**Fixed** — #2 (focus rings), #3 (chip button), #4 (semantic headings), #5
(hover/focus/disabled states), #6 (44px touch targets), #10 (autocomplete), #11
(input labels, via aria-label), plus #9 in part (primary/secondary/ghost tiers
now exist and are applied; Allow leads in the portal) and #16
(prefers-reduced-motion). Verified in a browser: a real Tab press produces a
navy focus ring, the chip remove is a real `<button>` exposed to the a11y tree
with a 44px hit area, and `:disabled` dims to 0.45 with `cursor: not-allowed`.

**Fixed (second pass)** — #1 (responsive), #8 (DOM nesting), #15 (session id
truncated). Measured at 375px: every route overflowed the page by 136–198px
before; all now measure **0**, verified again at 768 and desktop.

The dominant cause was not the tables — it was the **nav**: a no-wrap flex row
whose email span alone was 183px, which pushed *every* route sideways, including
the kiosk (just a form). Tables were the second layer, now contained.

**Still open** — #7 (Deny confirmation), #12 (error placement / empty-vs-failed),
#13 (no animation on live updates), #14 (markdown in trace), #17 (skip link),
#18 (static title).

---

## Context that drives severity

Two things about who actually uses this:

- **A guard uses this standing at a gate, on a phone or a small kiosk**, with a
  visitor waiting in front of them. Anything slow, small, or ambiguous costs a
  real person standing in the sun.
- **A resident uses the portal in ~10 seconds**, one-handed, to answer "is this
  person allowed in?" — often while doing something else.

Neither of those users is sitting at a 1280px desktop, which is the only width
this UI currently works at.

---

## 🔴 Critical

### 1. The app is not responsive at all
`frontend/src/index.css` — **zero media queries**. Landing.css has them; the app
has none. Every table (`AdminDashboard`, `Notifications`, `Users`, `Residents`,
`Societies`) is a fixed `<table>` with 6–7 columns, and the nav is a
`display:flex` row with `gap:22` and no wrap. At 375px a `society_admin` has
5 nav links + their email + Sign out in that row.

**Why it matters:** the guard kiosk is the most likely mobile surface in the
product, and the resident portal is a phone-first experience by definition. This
is the single biggest gap between "works on my machine" and "works at a gate."

**Fix:** stack table rows into cards under ~768px (or make the table wrapper
`overflow-x:auto` as a stopgap), collapse the nav, and test at 375px.

### 2. Focus rings are removed and never replaced
`ui.js:26`, `GuardKiosk.jsx:8`, `Portal.jsx:48`, `Portal.jsx:76`,
`SessionDetail.jsx:70` — every input sets `outline: 'none'` with no
`:focus-visible` replacement (impossible via inline styles anyway).

**Why it matters:** a keyboard user cannot see where they are. WCAG 2.4.7
failure, and the skill's #1 listed anti-pattern.

**Fix:** move inputs/buttons to CSS classes and add
`:focus-visible { outline: 2px solid var(--c-navy); outline-offset: 2px }`.
Navy reads on both white and turquoise.

### 3. The chip remove button can be focused but not activated
`Portal.jsx:233-239` — a `<span role="button" tabIndex={0}>` with `onClick` and
**no `onKeyDown`**.

**Why it matters:** a keyboard user can Tab to "Remove Swiggy", press Enter, and
nothing happens. It advertises itself as a button and then isn't one. This is
worse than an unfocusable element.

**Fix:** make it a real `<button type="button">`. The native element brings
Enter/Space, focus, and semantics for free.

### 4. No semantic headings anywhere in the app
`grep '<h[1-6]'` across the app pages returns **nothing** — every title
("Visitor Sessions", "Hi, Neha", "Notification health") is a styled `<div>`.

**Why it matters:** screen-reader users navigate by heading. With none, the whole
app is one undifferentiated blob and there is no way to skim.

**Fix:** one `<h1>` per page, `<h2>` per card section. Purely a tag change; the
styles already exist.

---

## 🟠 High

### 5. Buttons have no hover, focus, or disabled states
No `:hover` exists anywhere in `index.css`; all buttons are inline-styled, which
cannot express pseudo-classes.

- **Disabled looks identical to enabled.** Six buttons set `disabled` (e.g.
  `GuardKiosk.jsx:72`, `Portal.jsx:287`, `SessionDetail.jsx:277`) but keep full
  turquoise saturation *and* `cursor: pointer`. During a submit — which takes
  **several seconds** because it's calling Claude — the button looks clickable
  and does nothing. The label changes to "Processing…", which is the only clue.
- **Nothing responds to hover**, so the UI feels dead.

**Fix:** CSS classes with `:hover` (darken ~8%), `:active`, `:focus-visible`, and
`:disabled { opacity:.45; cursor:not-allowed }`.

### 6. Touch targets are below the 44px minimum
`ui.btn` is `padding:'10px 18px'` at 14px → ~37px tall. Portal's Allow/Deny
(`Portal.jsx`, `padding:'8px 16px'`, 13px) → ~32px. Apple HIG says 44×44,
Material says 48×48.

**Why it matters:** Allow/Deny is *the* decision in the product, made one-handed
in seconds. It is currently one of the smallest targets on the page, and the two
opposite-consequence buttons sit 8px apart.

**Fix:** `min-height:44px` on buttons; increase the gap between Allow and Deny.

### 7. Deny has no confirmation and no undo
`grep 'confirm('` → nothing. Tapping Deny (a ~32px target) instantly refuses a
visitor. There is no undo, and the session resolves.

**Why it matters:** a mis-tap turns a legitimate guest away, and the resident
cannot take it back. Asymmetric consequences deserve asymmetric friction.

**Fix:** confirm Deny (not Allow), or offer a brief undo toast. At minimum,
separate it from Allow spatially.

### 8. Invalid DOM nesting in the sessions table
`AdminDashboard.jsx:86` — `<Link>` renders an `<a>` wrapping `<tr>` inside
`<tbody>`, with `display:contents` to hide the damage. React logs a hydration
error on every render (visible in the console today).

**Why it matters:** it works by accident. `display:contents` on an `<a>` has
historically removed it from the a11y tree in some browsers, so the row may not
be announced as a link at all.

**Fix:** drop the `<Link>`; put `onClick`/`onKeyDown` on the `<tr>`, or a real
link inside the first `<td>`.

---

## 🟡 Medium

### 9. Turquoise is doing too much work
`Submit Visitor`, `Add`, `Send`, `Save rules`, `Refresh` are all the same
turquoise shout. The resident portal has five competing buttons: turquoise Send +
green Allow + red Deny + turquoise Add + turquoise Save.

**Why it matters:** if everything is primary, nothing is. In the portal the user
has one job — Allow or Deny — and those aren't the loudest things on screen.

**Fix:** one primary per view. Add a `secondary` (white + navy border) and
`ghost` tier; demote Add/Refresh/Send. In the portal make **Allow** the primary.

### 10. No password-manager support on login
`Login.jsx` — no `autoComplete` on either field, no `name` attributes.

**Fix:** `autoComplete="email"` / `autoComplete="current-password"`.

### 11. Inputs rely on placeholders in two places
`SessionDetail.jsx` reply box and `Portal.jsx` chip input have placeholders but
no visible label. (`GuardKiosk` does this correctly.)

**Why it matters:** the placeholder disappears on focus, and placeholder-only
labelling fails WCAG 3.3.2.

### 12. Errors are inconsistent and can be missed
`Portal.jsx` renders one shared error at the top of the page; if a reply fails
while you're at the standing-rules section, you won't see it. `AdminDashboard`
swallows load errors entirely (`catch { }`) and just shows an empty table — so
"the backend is down" and "no visitors yet" look identical.

**Fix:** put errors next to the action; distinguish empty from failed.

### 13. Nothing animates
No transitions anywhere in the app (the theme transition was removed with dark
mode). Rows appear instantly when a WebSocket pushes an update — the marquee
feature of the product happens with no visual cue at all.

**Fix:** a 150–200ms fade/highlight on a newly-arrived session. This is the one
place motion would carry real meaning, and it's a cheap win for the demo.

---

## 🟢 Low / polish

14. **Raw markdown in the trace** — the Delivery agent's reasoning renders
    `**Decision:**` literally (`SessionDetail`). Strip or render it.
15. **Session ids shown raw** — full UUIDs in the dashboard's first column earn
    their width poorly; truncate to 8 chars with the full value on hover.
16. **`prefers-reduced-motion`** is unhandled (relevant once #13 lands).
17. **Skip-link** exists on Landing but not in the app.
18. **`<title>` is static** ("GateSense") on every route.

---

## What's already good (not everything needs fixing)

- **Empty states are genuinely helpful** — the portal's "No one is waiting right
  now. You'll see visitors here the moment they arrive." tells the user what will
  happen, not just that there's nothing. `AdminDashboard`'s empty state links to
  the kiosk.
- **Status is never conveyed by colour alone** — every badge pairs colour with
  the status word, so it survives colourblindness and greyscale.
- **Contrast on the core pairings is strong** — navy on white 17.8:1, navy on
  turquoise 9.6:1, both well past AA.
- **Live updates work without a refresh**, with polling as a fallback.
- **Destructive/decision actions are semantically coloured** (green/red), not
  brand-coloured.
- **The kiosk form labels every field** properly.

---

## Suggested order

1. **#2, #3, #4** — accessibility defects, cheap, no design debate.
2. **#1** — responsive; the biggest real-world gap (a guard is on a phone).
3. **#5, #6, #8** — button states, touch targets, the DOM bug. #5 and #6 land
   together with the CSS-class refactor.
4. **#7, #9** — Deny confirmation and the primary-action hierarchy.
5. The rest as polish; **#13** is worth doing before any demo recording.

Items #2, #5, #6 all depend on the same structural change: move buttons and
inputs from inline styles to CSS classes in `index.css`. That refactor unblocks
hover/focus/disabled in one pass and is the highest-leverage single change here.
