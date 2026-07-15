# Data retention & PII

Deferred from PRD §15 and stated here as the intended policy. It records what
the system holds today, what the retention rules should be, and — honestly —
which of those rules are **not yet enforced in code**.

## What GateSense stores

| Data | Where | Personal? |
|---|---|---|
| Resident name, flat, phone | `residents` | Yes |
| Backup contact link | `residents.backup_contact_id` | Yes |
| Standing rules, delivery preferences | `residents` | Reveals habits |
| Visitor name, purpose, entry time | `visitor_sessions` | Yes — about a non-user |
| Known-visitor history, visit counts, typical hours | `visitors` | Yes |
| Agent reasoning + tool calls | `visitor_sessions.decision_trace` | Contains the above |
| Resident/guard messages | `conversation_log`, `visitor_sessions.conversation_history` | Yes |
| Notification delivery records | `notification_delivery_log` | Links resident ↔ session |
| Escalations | `escalations` | Yes |
| Login email, bcrypt hash, role | `users` | Yes |
| In-flight intercom graph state | `checkpoints*` (LangGraph-owned) | Yes — mirrors the conversation |

**No photos.** The PRD contemplated visitor photo capture; it is not built, and
nothing in the schema stores images. Adding it would need its own retention and
consent decision — a face is more sensitive than a name, and a visitor never
agreed to anything.

**Visitors are not users.** The most sensitive records here describe people who
never signed up: a courier's visit pattern, a guest's arrival at a specific flat
at a specific hour. That asymmetry drives the policy below.

## Third parties

Visitor name, flat, purpose, resident name, and the resident's messages are sent
to **Anthropic's API** as agent prompts, because that is what the agents reason
over. Nothing else leaves the deployment. Per Anthropic's API terms, inputs are
not used to train models.

Minimization already in place: agent tools return only the caller's society's
rows, and the model never receives a `society_id` or picks the tenant — that
comes from the request's JWT.

## Intended retention

| Data | Retention | Rationale |
|---|---|---|
| `visitor_sessions` + `decision_trace` | **90 days**, then delete | Matches the Starter plan's stated trace history; long enough to audit a dispute |
| `conversation_log`, `conversation_history` | **90 days** | Same lifecycle as its session |
| `notification_delivery_log` | **30 days** | Operational health only |
| `escalations` | **1 year** | Security-relevant; reviewed by the committee |
| `checkpoints*` | Until the session resolves; purge with its session | Only needed while a conversation is in flight |
| `visitors` aggregates | **1 year** after last visit | Powers "known visitor" |
| `residents`, `users` | Life of the tenancy; delete ≤30 days after a society leaves | |

Longer retention on a paid plan is a pricing decision, not a technical one; it
should still be bounded and stated.

## Not yet enforced (be honest about this)

- **No retention job exists.** Nothing expires today; rows live until the
  society row is deleted (`ON DELETE CASCADE` removes its data).
- **No resident-facing export or erasure.** A resident cannot download or delete
  their history from the portal.
- **No consent surface for visitors**, who are the least-consenting party here.

Closing these needs: a scheduled purge honouring the table above, an
export/erasure endpoint, and gate signage disclosing that entries are logged.

## Deleting a society

`DELETE FROM societies WHERE id = …` cascades to residents, users, visitors,
sessions, conversations, escalations, and notifications — the tenant's data is
removed in one step.

Two caveats, stated rather than hidden:

- **LangGraph's `checkpoints*` tables do not cascade.** They are keyed by session
  id with no foreign key to `societies`, so deleting a society leaves any
  in-flight conversation state behind. A purge job must clear checkpoints for
  the deleted sessions too.
- Backups must age out per the schedule above, or the deletion is only partial.
