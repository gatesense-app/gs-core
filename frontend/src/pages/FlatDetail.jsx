import { useEffect, useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { apiFetch } from '../api'
import { useAuth } from '../auth'
import { ui, colors } from '../ui'

// E6-S1/S2 — flat detail + manage residents (add / edit / remove / set primary).
//
// Route is /flat/:id, admin-only (App.jsx gates it to platform_admin /
// society_admin). Resident PII is admin-only, so this page never adds
// guard/resident access.
//
// Deep-linkable: everything is (re)fetched on mount, so a refresh or a shared
// link rebuilds the whole page. The separate layout view (Layout.jsx) also
// refetches on mount, so the add/edit/remove/primary changes made here show up
// there the next time it loads — no shared state to keep in sync.

const STATUS_COLOR = {
  pending: '#64748b', auto_approved: '#22c55e', awaiting_resident: '#f59e0b',
  approved: '#22c55e', denied: '#ef4444', escalated: '#f97316', expired: '#64748b',
}

const s = {
  page: { maxWidth: 860, margin: '0 auto', padding: '32px 24px' },
  back: { fontSize: 13, color: 'var(--c-muted)', marginBottom: 24, display: 'block' },
  card: { background: 'var(--c-panel)', borderRadius: 12, border: '1px solid var(--c-border)', padding: 24, marginBottom: 24, boxShadow: 'var(--c-card-shadow)' },
  row: { display: 'flex', gap: 32, flexWrap: 'wrap' },
  kv: { marginBottom: 16 },
  key: { fontSize: 11, color: 'var(--c-muted)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 4 },
  val: { fontSize: 15, color: 'var(--c-text)', fontWeight: 500 },
  resRow: {
    display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between',
    gap: 16, padding: '14px 0', borderBottom: '1px solid var(--c-row-border)', flexWrap: 'wrap',
  },
  resName: { fontSize: 15, color: 'var(--c-text)', fontWeight: 600 },
  resPhone: { fontSize: 13, color: 'var(--c-sub)', marginTop: 2 },
  actions: { display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' },
  primaryBadge: {
    display: 'inline-block', padding: '2px 9px', borderRadius: 99, fontSize: 11, fontWeight: 600,
    background: 'var(--c-accent-bg)', color: 'var(--c-accent-soft)',
    border: '1px solid var(--c-accent-border)', marginLeft: 8,
  },
  roleBadge: (role) => ({
    display: 'inline-block', padding: '2px 9px', borderRadius: 99, fontSize: 11, fontWeight: 600,
    marginLeft: 8,
    background: role === 'tenant' ? '#f59e0b22' : '#3b82f622',
    color: role === 'tenant' ? '#b45309' : '#1d4ed8',
    border: `1px solid ${role === 'tenant' ? '#f59e0b55' : '#3b82f655'}`,
  }),
  expiredTag: {
    display: 'inline-block', marginLeft: 8, padding: '1px 8px', borderRadius: 99,
    fontSize: 11, fontWeight: 600, background: '#ef444422', color: '#b91c1c',
    border: '1px solid #ef444455',
  },
  toggle: (active) => ({
    padding: '4px 12px', fontSize: 13, fontWeight: 600, cursor: 'pointer',
    border: '1px solid var(--c-border)',
    background: active ? 'var(--c-accent-bg)' : 'transparent',
    color: active ? 'var(--c-accent-soft)' : 'var(--c-muted)',
  }),
  statusBadge: (status) => ({
    display: 'inline-block', padding: '2px 9px', borderRadius: 99, fontSize: 12, fontWeight: 500,
    background: (STATUS_COLOR[status] || '#64748b') + '22', color: STATUS_COLOR[status] || '#64748b',
    border: `1px solid ${STATUS_COLOR[status] || '#64748b'}44`,
  }),
  sessRow: {
    display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between',
    gap: 16, padding: '10px 0', borderBottom: '1px solid var(--c-row-border)',
  },
  none: { fontSize: 13, color: 'var(--c-muted)' },
  editForm: { display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'flex-end', marginTop: 8 },
}

function ruleLabel(r) {
  if (r.type === 'always_allow') return `Allow ${r.match}`
  if (r.type === 'never_allow') return r.after ? `Deny after ${r.after}` : `Deny ${r.match}`
  return JSON.stringify(r)
}

function fmt(iso) {
  if (!iso) return ''
  return new Date(iso).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' })
}

function tenancyDates(t) {
  if (t.start_date && t.end_date) return `${t.start_date} → ${t.end_date}`
  if (t.start_date) return `From ${t.start_date}`
  if (t.end_date) return `Until ${t.end_date}`
  return 'No dates set'
}

// A quiet dot colour per kind of event, so the timeline scans at a glance —
// paired with the text summary, never colour alone.
const EVENT_DOT = {
  flat_created: '#22c55e', resident_added: '#22c55e',
  flat_renamed: '#3b82f6', flat_floor_changed: '#3b82f6',
  flat_rules_changed: '#3b82f6', resident_edited: '#3b82f6',
  flat_occupancy_changed: '#f59e0b', resident_role_changed: '#f59e0b',
  tenancy_started: '#0ea5e9', tenancy_renewed: '#0ea5e9', tenancy_ended: '#ef4444',
  resident_primary_set: '#a855f7', flat_linked: '#a855f7',
  flat_deleted: '#ef4444', resident_deleted: '#ef4444',
}

export default function FlatDetail() {
  const { id } = useParams()
  const { user } = useAuth()
  const isPlatform = user?.role === 'platform_admin'

  const [flat, setFlat] = useState(null)
  const [notFound, setNotFound] = useState(false)
  const [residents, setResidents] = useState([])
  const [tenancies, setTenancies] = useState([])
  const [sessions, setSessions] = useState([])
  const [timeline, setTimeline] = useState([])
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  // Tenant section forms
  const [tStart, setTStart] = useState('')
  const [tEnd, setTEnd] = useState('')
  const [tenantName, setTenantName] = useState('')
  const [tenantPhone, setTenantPhone] = useState('')
  const [renewing, setRenewing] = useState(false)
  const [renewStart, setRenewStart] = useState('')
  const [renewEnd, setRenewEnd] = useState('')
  const [confirmEnd, setConfirmEnd] = useState(false)

  // Add-resident form
  const [addName, setAddName] = useState('')
  const [addPhone, setAddPhone] = useState('')
  // Edit-in-place: resident id being edited, plus its working values
  const [editId, setEditId] = useState(null)
  const [editName, setEditName] = useState('')
  const [editPhone, setEditPhone] = useState('')
  // Remove confirmation: resident id awaiting a confirmed delete
  const [confirmId, setConfirmId] = useState(null)
  // Edit the flat itself (number / floor), plus what the server left alone
  const [editFlat, setEditFlat] = useState(false)
  const [flatNumber, setFlatNumber] = useState('')
  const [flatFloor, setFlatFloor] = useState('')
  const [notice, setNotice] = useState([])

  async function load() {
    setError('')
    try {
      const f = await apiFetch(`/flats/${id}`)
      setFlat(f)
      // /residents and /sessions span all societies for a platform_admin, so we
      // always also match on society_id — never surface another tenant's rows.
      const [allResidents, allSessions] = await Promise.all([
        apiFetch('/residents').catch(() => []),
        apiFetch('/sessions').catch(() => []),
      ])
      setResidents(
        allResidents.filter(
          (r) => r.flat_number === f.code && r.society_id === f.society_id,
        ),
      )
      setSessions(
        allSessions
          .filter((v) => v.flat_number === f.code)
          .sort((a, b) => new Date(b.entry_time || 0) - new Date(a.entry_time || 0)),
      )
      // Tenancy agreements (active + past) for a tenant-occupied flat.
      setTenancies(await apiFetch(`/flats/${id}/tenancies`).catch(() => []))
      // The audit trail — every change to this flat and its residents, newest
      // first. Reachable even for a soft-deleted flat.
      setTimeline(await apiFetch(`/flats/${id}/timeline`).catch(() => []))
    } catch (err) {
      if (err.status === 404) setNotFound(true)  // don't confirm existence
      else setError(err.message)
    }
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id])

  function startEditFlat() {
    setFlatNumber(flat.flat_number)
    setFlatFloor(String(flat.floor))
    setEditFlat(true)
    setNotice([])
  }

  async function saveFlat(e) {
    e.preventDefault()
    setBusy(true)
    setError('')
    setNotice([])
    try {
      const updated = await apiFetch(`/flats/${id}`, {
        method: 'PATCH',
        body: { flat_number: flatNumber.trim(), floor: Number(flatFloor) },
      })
      setEditFlat(false)
      // What the edit deliberately left alone: history keeping the old code, a
      // merged household's contact, a floor now outside the declared shape.
      setNotice(updated.warnings || [])
      await load()
    } catch (err) {
      setError(err.message)   // e.g. that code already exists
    } finally {
      setBusy(false)
    }
  }

  async function setOccupancy(value) {
    if (!flat || flat.occupancy === value) return
    setBusy(true)
    setError('')
    setNotice([])
    try {
      await apiFetch(`/flats/${id}`, { method: 'PATCH', body: { occupancy: value } })
      await load()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  // Wraps a tenancy mutation with busy/error handling and a reload.
  async function tenancyAction(fn) {
    setBusy(true)
    setError('')
    try {
      await fn()
      await load()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  function startTenancy(e) {
    e.preventDefault()
    tenancyAction(async () => {
      await apiFetch(`/flats/${id}/tenancies`, {
        method: 'POST',
        body: { start_date: tStart || null, end_date: tEnd || null },
      })
      setTStart(''); setTEnd('')
    })
  }

  function addTenant(e, tenancyId) {
    e.preventDefault()
    if (!tenantName.trim()) return
    tenancyAction(async () => {
      await apiFetch(`/tenancies/${tenancyId}/tenants`, {
        method: 'POST',
        body: { name: tenantName.trim(), phone: tenantPhone.trim() || null },
      })
      setTenantName(''); setTenantPhone('')
    })
  }

  function renewTenancy(e, tenancyId) {
    e.preventDefault()
    tenancyAction(async () => {
      await apiFetch(`/tenancies/${tenancyId}/renew`, {
        method: 'POST',
        body: { start_date: renewStart || null, end_date: renewEnd || null },
      })
      setRenewing(false); setRenewStart(''); setRenewEnd('')
    })
  }

  function endTenancy(tenancyId) {
    tenancyAction(async () => {
      await apiFetch(`/tenancies/${tenancyId}/end`, { method: 'POST' })
      setConfirmEnd(false)
    })
  }

  async function addResident(e) {
    e.preventDefault()
    if (!addName.trim()) return
    setBusy(true)
    setError('')
    try {
      const body = { flat_number: flat.code, name: addName.trim(), phone: addPhone.trim() || null }
      if (isPlatform) body.society_id = flat.society_id
      await apiFetch('/residents', { method: 'POST', body })
      setAddName('')
      setAddPhone('')
      await load()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  function startEdit(r) {
    setEditId(r.id)
    setEditName(r.name)
    setEditPhone(r.phone || '')
    setConfirmId(null)
  }

  async function saveEdit(e) {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      await apiFetch(`/residents/${editId}`, {
        method: 'PATCH',
        body: { name: editName.trim(), phone: editPhone.trim() || null },
      })
      setEditId(null)
      await load()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  async function makePrimary(r) {
    setBusy(true)
    setError('')
    try {
      // The server demotes the incumbent. There is no "demote": is_primary:false
      // is a 422, so we only ever offer "make primary" on the others.
      await apiFetch(`/residents/${r.id}`, { method: 'PATCH', body: { is_primary: true } })
      await load()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  async function removeResident(r) {
    // Real onClick handler (not a synthetic Enter): the test harness does not
    // activate a button via a synthetic Enter key.
    setBusy(true)
    setError('')
    try {
      await apiFetch(`/residents/${r.id}`, { method: 'DELETE' })
      setConfirmId(null)
      await load()  // removing the last resident falls through to the vacant state
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  if (notFound) {
    return (
      <div style={s.page}>
        <Link to="/layout" style={s.back}>← Back to Layout</Link>
        <div style={s.card}>
          <h1 className="page-title">Flat not found</h1>
          <div style={s.none}>This flat doesn’t exist, or you don’t have access to it.</div>
        </div>
      </div>
    )
  }

  if (!flat) return <div style={{ padding: 40, color: 'var(--c-muted)' }}>Loading…</div>

  const primary = residents.find((r) => r.is_primary) || null
  // The residents section shows the flat's owners/household; tenants live in the
  // Tenant section, managed through the tenancy agreement.
  const owners = residents.filter((r) => r.role !== 'tenant')
  const activeTenancy = tenancies.find((t) => t.status !== 'ended') || null
  const pastTenancies = tenancies.filter((t) => t.status === 'ended')

  // The door's *effective* rules — what the gate actually reads. The flat's own
  // win when set (non-null); otherwise they fall back, field-independently, to
  // the primary resident's. null means "unset"; [] / {} are real answers.
  const effRules =
    flat.standing_rules != null ? flat.standing_rules : (primary?.standing_rules || [])
  const effPrefs =
    flat.delivery_preferences != null
      ? flat.delivery_preferences
      : (primary?.delivery_preferences || {})
  const prefEntries = Object.entries(effPrefs || {})

  return (
    <div style={s.page}>
      <Link to="/layout" style={s.back}>← Back to Layout</Link>

      {flat.deleted_at && (
        <div style={{ ...s.card, padding: 14, borderColor: '#ef4444',
                      background: 'rgba(239,68,68,0.08)' }}>
          <span style={{ fontSize: 14, color: 'var(--c-text)', fontWeight: 600 }}>
            This flat was deleted
          </span>
          <span style={{ fontSize: 13, color: colors.sub }}> · {fmt(flat.deleted_at)}. </span>
          <span style={{ fontSize: 13, color: colors.sub }}>
            Its residents and history are kept below for the record.
          </span>
        </div>
      )}

      {/* Flat header */}
      <div style={s.card}>
        <h1 className="page-title">Flat {flat.code}</h1>
        <div style={s.row}>
          <div style={s.kv}>
            <div style={s.key}>Wing</div>
            <div style={s.val}>{flat.wing_name}</div>
          </div>
          <div style={s.kv}>
            <div style={s.key}>Flat number</div>
            <div style={s.val}>{flat.flat_number}</div>
          </div>
          <div style={s.kv}>
            <div style={s.key}>Floor</div>
            <div style={s.val}>{flat.floor}</div>
          </div>
          <div style={s.kv}>
            <div style={s.key}>Occupancy</div>
            <div style={{ display: 'inline-flex', borderRadius: 8, overflow: 'hidden', marginTop: 2 }}>
              <button type="button" style={{ ...s.toggle(flat.occupancy === 'owner'), borderRadius: 0 }}
                      disabled={busy || !!flat.deleted_at} onClick={() => setOccupancy('owner')}>
                Owner
              </button>
              <button type="button" style={{ ...s.toggle(flat.occupancy === 'tenant'), borderRadius: 0, borderLeft: 'none' }}
                      disabled={busy || !!flat.deleted_at} onClick={() => setOccupancy('tenant')}>
                Tenant
              </button>
            </div>
          </div>
        </div>
        <div style={{ fontSize: 13, color: 'var(--c-muted)', marginBottom: 14 }}>
          {flat.occupancy === 'tenant'
            ? 'Occupied by a tenant — the gate contacts a tenant of this flat.'
            : 'Owner-occupied — the gate contacts the owner.'}
        </div>

        {!editFlat ? (
          <button type="button" className="btn btn--ghost btn--sm" onClick={startEditFlat}>
            Edit flat
          </button>
        ) : (
          <form onSubmit={saveFlat}>
            <div style={{ fontSize: 13, color: 'var(--c-muted)', marginBottom: 12 }}>
              Retyping the number changes this flat’s code to{' '}
              <code>{flat.wing_name}-{flatNumber || flat.flat_number}</code> and moves its
              residents with it, so the gate still finds them. Past visitor sessions keep the
              old code — they record what was actually typed at the time.
            </div>
            <div style={s.editForm}>
              <div style={{ width: 140 }}>
                <label style={ui.label}>Flat number</label>
                <input className="input" value={flatNumber}
                       onChange={(e) => setFlatNumber(e.target.value)} required />
              </div>
              <div style={{ width: 110 }}>
                <label style={ui.label}>Floor</label>
                <input className="input" type="number" value={flatFloor}
                       onChange={(e) => setFlatFloor(e.target.value)} required />
              </div>
              <button className="btn btn--primary btn--sm" disabled={busy}>
                {busy ? 'Saving…' : 'Save flat'}
              </button>
              <button type="button" className="btn btn--ghost btn--sm"
                      onClick={() => setEditFlat(false)}>Cancel</button>
            </div>
          </form>
        )}

        {notice.length > 0 && (
          <div style={{ marginTop: 14 }}>
            {notice.map((n, i) => (
              <div key={i} style={{ fontSize: 13, color: colors.sub }}>{n}</div>
            ))}
          </div>
        )}
      </div>

      {/* Residents (owners / household) */}
      <div style={s.card}>
        <h2 className="section-title">Residents</h2>
        {owners.length === 0 ? (
          <div style={{ ...s.none, marginBottom: 4 }}>
            No residents yet. Add the flat's owner/household below.
          </div>
        ) : (
          owners.map((r) => (
            <div key={r.id} style={s.resRow}>
              {editId === r.id ? (
                <form onSubmit={saveEdit} style={{ ...s.editForm, marginTop: 0, flex: 1 }}>
                  <div style={{ flex: 1, minWidth: 160 }}>
                    <label style={ui.label}>Name</label>
                    <input className="input" value={editName} onChange={(e) => setEditName(e.target.value)} required />
                  </div>
                  <div style={{ width: 160 }}>
                    <label style={ui.label}>Phone</label>
                    <input className="input" value={editPhone} onChange={(e) => setEditPhone(e.target.value)} placeholder="+91…" />
                  </div>
                  <button className="btn btn--primary btn--sm" disabled={busy}>{busy ? 'Saving…' : 'Save'}</button>
                  <button type="button" className="btn btn--ghost btn--sm" onClick={() => setEditId(null)}>Cancel</button>
                </form>
              ) : (
                <>
                  <div>
                    <div style={s.resName}>
                      {r.name}
                      <span style={s.roleBadge('owner')}>Owner</span>
                      {r.is_primary && <span style={s.primaryBadge}>Primary contact</span>}
                    </div>
                    <div style={s.resPhone}>{r.phone || 'No phone'}</div>
                  </div>
                  <div style={s.actions}>
                    {!r.is_primary && (
                      <button type="button" className="btn btn--ghost btn--sm" disabled={busy} onClick={() => makePrimary(r)}>
                        Make primary
                      </button>
                    )}
                    <button type="button" className="btn btn--ghost btn--sm" onClick={() => startEdit(r)}>Edit</button>
                    {confirmId === r.id ? (
                      <>
                        <span style={{ fontSize: 13, color: colors.error }}>Remove {r.name}?</span>
                        <button type="button" className="btn btn--ghost btn--sm" disabled={busy} onClick={() => removeResident(r)}>
                          Confirm remove
                        </button>
                        <button type="button" className="btn btn--ghost btn--sm" onClick={() => setConfirmId(null)}>Cancel</button>
                      </>
                    ) : (
                      <button type="button" className="btn btn--ghost btn--sm" onClick={() => { setConfirmId(r.id); setEditId(null) }}>
                        Remove
                      </button>
                    )}
                  </div>
                </>
              )}
            </div>
          ))
        )}

        {/* Add resident */}
        <form onSubmit={addResident} style={s.editForm}>
          <div style={{ flex: 1, minWidth: 160 }}>
            <label style={ui.label}>Add resident</label>
            <input className="input" value={addName} onChange={(e) => setAddName(e.target.value)} placeholder="Name" required />
          </div>
          <div style={{ width: 160 }}>
            <label style={ui.label}>Phone</label>
            <input className="input" value={addPhone} onChange={(e) => setAddPhone(e.target.value)} placeholder="+91…" />
          </div>
          <button className="btn btn--primary" disabled={busy}>{busy ? 'Adding…' : 'Add resident'}</button>
        </form>
        {error && <div style={ui.error}>{error}</div>}
      </div>

      {/* Tenants (only when tenant-occupied) */}
      {flat.occupancy === 'tenant' && !flat.deleted_at && (
        <div style={s.card}>
          <h2 className="section-title">Tenants</h2>
          {!activeTenancy ? (
            <>
              <div style={{ ...s.none, marginBottom: 10 }}>
                This flat is tenant-occupied. Start a tenancy to add tenants — the
                primary tenant becomes the contact the gate reaches.
              </div>
              <form onSubmit={startTenancy} style={s.editForm}>
                <div style={{ width: 160 }}>
                  <label style={ui.label}>Start date (optional)</label>
                  <input className="input" type="date" value={tStart} onChange={(e) => setTStart(e.target.value)} />
                </div>
                <div style={{ width: 160 }}>
                  <label style={ui.label}>End date (optional)</label>
                  <input className="input" type="date" value={tEnd} onChange={(e) => setTEnd(e.target.value)} />
                </div>
                <button className="btn btn--primary btn--sm" disabled={busy}>
                  {busy ? 'Starting…' : 'Start tenancy'}
                </button>
              </form>
            </>
          ) : (
            <>
              <div style={{ fontSize: 13, color: colors.sub, marginBottom: 4 }}>
                {tenancyDates(activeTenancy)}
                {activeTenancy.status === 'expired' && (
                  <span style={s.expiredTag}>past end date</span>
                )}
              </div>

              {activeTenancy.tenants.length === 0 ? (
                <div style={{ ...s.none, marginBottom: 4 }}>
                  No tenants yet — add the first one below (they become the contact).
                </div>
              ) : (
                activeTenancy.tenants.map((r) => (
                  <div key={r.id} style={s.resRow}>
                    <div>
                      <div style={s.resName}>
                        {r.name}
                        <span style={s.roleBadge('tenant')}>Tenant</span>
                        {r.is_primary && <span style={s.primaryBadge}>Primary contact</span>}
                      </div>
                      <div style={s.resPhone}>{r.phone || 'No phone'}</div>
                    </div>
                    <div style={s.actions}>
                      {!r.is_primary && (
                        <button type="button" className="btn btn--ghost btn--sm" disabled={busy} onClick={() => makePrimary(r)}>
                          Make primary
                        </button>
                      )}
                      {confirmId === r.id ? (
                        <>
                          <span style={{ fontSize: 13, color: colors.error }}>Remove {r.name}?</span>
                          <button type="button" className="btn btn--ghost btn--sm" disabled={busy} onClick={() => removeResident(r)}>
                            Confirm remove
                          </button>
                          <button type="button" className="btn btn--ghost btn--sm" onClick={() => setConfirmId(null)}>Cancel</button>
                        </>
                      ) : (
                        <button type="button" className="btn btn--ghost btn--sm" onClick={() => setConfirmId(r.id)}>
                          Remove
                        </button>
                      )}
                    </div>
                  </div>
                ))
              )}

              {/* Add tenant */}
              <form onSubmit={(e) => addTenant(e, activeTenancy.id)} style={s.editForm}>
                <div style={{ flex: 1, minWidth: 160 }}>
                  <label style={ui.label}>Add tenant</label>
                  <input className="input" value={tenantName} onChange={(e) => setTenantName(e.target.value)} placeholder="Name" required />
                </div>
                <div style={{ width: 160 }}>
                  <label style={ui.label}>Phone</label>
                  <input className="input" value={tenantPhone} onChange={(e) => setTenantPhone(e.target.value)} placeholder="+91…" />
                </div>
                <button className="btn btn--primary btn--sm" disabled={busy}>{busy ? 'Adding…' : 'Add tenant'}</button>
              </form>

              {/* Renew / End */}
              <div style={{ display: 'flex', gap: 8, marginTop: 16, flexWrap: 'wrap', alignItems: 'flex-end' }}>
                {renewing ? (
                  <form onSubmit={(e) => renewTenancy(e, activeTenancy.id)} style={{ ...s.editForm, marginTop: 0 }}>
                    <div style={{ width: 160 }}>
                      <label style={ui.label}>New start (optional)</label>
                      <input className="input" type="date" value={renewStart} onChange={(e) => setRenewStart(e.target.value)} />
                    </div>
                    <div style={{ width: 160 }}>
                      <label style={ui.label}>New end (optional)</label>
                      <input className="input" type="date" value={renewEnd} onChange={(e) => setRenewEnd(e.target.value)} />
                    </div>
                    <button className="btn btn--primary btn--sm" disabled={busy}>{busy ? 'Renewing…' : 'Confirm renewal'}</button>
                    <button type="button" className="btn btn--ghost btn--sm" onClick={() => setRenewing(false)}>Cancel</button>
                  </form>
                ) : confirmEnd ? (
                  <>
                    <span style={{ fontSize: 13, color: colors.text }}>
                      End this tenancy? Its tenants are removed and the flat reverts to owner-occupied.
                    </span>
                    <button type="button" className="btn btn--sm" disabled={busy} onClick={() => endTenancy(activeTenancy.id)}>
                      {busy ? 'Ending…' : 'Yes, end tenancy'}
                    </button>
                    <button type="button" className="btn btn--ghost btn--sm" onClick={() => setConfirmEnd(false)}>Cancel</button>
                  </>
                ) : (
                  <>
                    <button type="button" className="btn btn--ghost btn--sm" onClick={() => setRenewing(true)}>
                      Renew (clone with new dates)
                    </button>
                    <button type="button" className="btn btn--ghost btn--sm" onClick={() => setConfirmEnd(true)}>
                      End tenancy
                    </button>
                  </>
                )}
              </div>
            </>
          )}

          {pastTenancies.length > 0 && (
            <div style={{ marginTop: 20 }}>
              <div style={{ ...s.key, marginBottom: 6 }}>Previous tenancies</div>
              {pastTenancies.map((t) => (
                <div key={t.id} style={{ fontSize: 13, color: colors.sub, padding: '4px 0' }}>
                  {tenancyDates(t)} — {t.tenants.map((x) => x.name).join(', ') || 'no tenants'}
                  {' '}(ended {fmt(t.ended_at)})
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* The door's effective rules — what the gate actually enforces */}
      <div style={s.card}>
        <h2 className="section-title">Door rules</h2>
        <div style={{ ...s.none, marginBottom: 12 }}>
          What the gate enforces at this door: the flat’s own rules where set, otherwise
          {primary ? ` ${primary.name}’s (the primary contact’s).` : ' the primary contact’s.'}
        </div>
        <div style={s.kv}>
          <div style={s.key}>Standing rules</div>
          <div>
            {effRules.length
              ? effRules.map((rule, i) => <span key={i} style={ui.chip}>{ruleLabel(rule)}</span>)
              : <span style={s.none}>No standing rules.</span>}
          </div>
        </div>
        <div style={s.kv}>
          <div style={s.key}>Delivery preferences</div>
          <div>
            {prefEntries.length
              ? prefEntries.map(([k, v]) => (
                  <span key={k} style={ui.chip}>{k}: {typeof v === 'object' ? JSON.stringify(v) : String(v)}</span>
                ))
              : <span style={s.none}>No delivery preferences.</span>}
          </div>
        </div>
      </div>

      {/* Recent visitor sessions for this flat */}
      <div style={s.card}>
        <h2 className="section-title">Recent visitors</h2>
        {sessions.length === 0 ? (
          <div style={s.none}>No visitor sessions for this flat yet.</div>
        ) : (
          sessions.slice(0, 8).map((v) => (
            <div key={v.session_id} style={s.sessRow}>
              <div>
                <div style={{ ...s.val, fontWeight: 500 }}>
                  <Link to={`/session/${v.session_id}`} style={{ color: 'var(--c-accent)' }}>
                    {v.visitor_name || 'Visitor'}
                  </Link>
                </div>
                <div style={s.resPhone}>{v.purpose}{v.entry_time ? ` · ${fmt(v.entry_time)}` : ''}</div>
              </div>
              <span style={s.statusBadge(v.status)}>{v.status}</span>
            </div>
          ))
        )}
      </div>

      {/* History — the audit trail of edits and deletes on this flat */}
      <div style={s.card}>
        <h2 className="section-title">History</h2>
        {timeline.length === 0 ? (
          <div style={s.none}>No changes recorded yet.</div>
        ) : (
          <div>
            {timeline.map((e) => (
              <div key={e.id} style={{ display: 'flex', gap: 12, padding: '10px 0',
                                       borderBottom: '1px solid var(--c-row-border)' }}>
                <span aria-hidden="true" style={{
                  flex: '0 0 auto', width: 8, height: 8, borderRadius: 99, marginTop: 6,
                  background: EVENT_DOT[e.action] || 'var(--c-muted)',
                }} />
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontSize: 14, color: 'var(--c-text)' }}>{e.summary}</div>
                  <div style={s.resPhone}>
                    {fmt(e.created_at)}
                    {e.actor_email ? ` · ${e.actor_email}` : ' · system'}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
