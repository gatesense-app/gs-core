import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { apiFetch } from '../api'
import { useAuth } from '../auth'
import { ui, colors } from '../ui'

// E5 — Layout view, plus the E4-S1/S2 management that feeds it: declare a
// building, then enter its flats. Admin picks a wing and sees its floors and
// flats laid out spatially, one floor per row. Each flat links to /flat/:id.
//
// Creation lives here rather than on a separate screen because E4-S1's whole
// point is "add a wing and it is drawn as an empty grid" — you make it and watch
// it appear. Per D2 a flat code is never generated: the admin types the number
// and the server composes {wing}-{number}.
//
// This is a STATIC directory: occupancy is fetched on load, not streamed. The
// E5-S2 "live status over WebSocket?" open question is resolved as "static for
// now" — no realtime here on purpose. (See realtime.js; unused.)

// Match residents onto flats by (society_id, code). A flat carries no resident
// count, so we derive both occupancy and the contact from /residents.
// platform_admin's /residents spans societies, hence society_id is part of the key.
function occKey(societyId, code) {
  return `${societyId}::${code}`
}

// The cell is a container, not the link itself: it holds a link *and* a remove
// button, and a <button> nested inside an <a> is invalid and unreachable by
// keyboard. The link fills the cell; the button sits in its corner.
const flatCell = {
  position: 'relative', flex: '0 0 auto', width: 124, minHeight: 56,
  borderRadius: 10, boxSizing: 'border-box', border: '1px solid var(--c-border)',
}
const cellLink = {
  display: 'flex', flexDirection: 'column', gap: 4, justifyContent: 'center',
  height: '100%', padding: '8px 10px', borderRadius: 10,
  textDecoration: 'none', boxSizing: 'border-box',
}
const flatState = {
  occupied: { background: 'var(--c-accent-bg)', borderColor: 'var(--c-accent-border)', color: 'var(--c-ok)' },
  // Tenant-occupied flats read differently at a glance (amber). The colour is
  // backed by the cell's title text (see below), so it isn't carried by hue alone.
  tenant: { background: '#f59e0b1f', borderColor: '#f59e0b66', color: 'var(--c-ok)' },
  vacant: { background: 'transparent', color: 'var(--c-muted)' },
}
// Names are longer than "Occupied" and vary wildly; clip rather than let one
// long name stretch a floor into a horizontal scroll. The full name is in the
// cell's title, and the flat detail page has it in full.
const clip = { overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }

function Flat({ flat, contact, occupied, onDelete }) {
  // The primary contact is who the gate actually calls (E6-S3), which is more
  // use on a grid than a yes/no. Every flat with residents has exactly one —
  // the DB enforces at most one, and ensure_primary appoints one on every write
  // path — so "no contact" means nobody lives here. `occupied` still guards the
  // gap: were a flat ever to hold residents with nobody flagged, it must not be
  // labelled Vacant, which would be a lie about an occupied home.
  const label = contact || (occupied ? 'Occupied' : 'Vacant')
  const filled = Boolean(contact || occupied)
  const isTenant = filled && flat.occupancy === 'tenant'
  const state = !filled ? flatState.vacant : isTenant ? flatState.tenant : flatState.occupied
  const title = contact
    ? `Flat ${flat.code} — primary contact ${contact}${isTenant ? ' (tenant-occupied)' : ''}`
    : `Flat ${flat.code} — ${label}`
  return (
    <div style={{ ...flatCell, ...state }}>
      <Link to={`/flat/${flat.id}`} style={cellLink} title={title}>
        <span style={{ fontFamily: 'monospace', fontSize: 14, fontWeight: 600, color: 'var(--c-text)', paddingRight: 14 }}>{flat.code}</span>
        {/* State is never colour-alone: a shape marker + a text label carry it too. */}
        <span style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 11, minWidth: 0 }}>
          <span aria-hidden="true" style={{ flex: '0 0 auto' }}>{filled ? '●' : '○'}</span>
          <span style={clip}>{label}</span>
        </span>
      </Link>
      {/* Asks rather than deletes: the confirm names the flat outside the cell,
          where there is room to say what is about to happen. */}
      <button
        type="button"
        className="chip-x"
        aria-label={`Delete flat ${flat.code}`}
        title={`Delete flat ${flat.code}`}
        style={{ position: 'absolute', top: 4, right: 4 }}
        onClick={() => onDelete(flat)}
      >×</button>
    </div>
  )
}

const emptyWing = { name: '', floors: '', flats_per_floor: '' }
const emptyFlat = { flat_number: '', floor: '' }

export default function Layout() {
  const { user } = useAuth()
  const isPlatform = user.role === 'platform_admin'

  const [societies, setSocieties] = useState([])
  const [societyId, setSocietyId] = useState('')
  const [wings, setWings] = useState([])
  const [wingId, setWingId] = useState('')
  const [flats, setFlats] = useState([])
  const [occupied, setOccupied] = useState(() => new Set())
  const [contacts, setContacts] = useState(() => new Map())
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  // Management (E4-S1/S2)
  const [wingForm, setWingForm] = useState(emptyWing)
  const [editForm, setEditForm] = useState(emptyWing)
  const [flatForm, setFlatForm] = useState(emptyFlat)
  const [showAddWing, setShowAddWing] = useState(false)
  const [showEditWing, setShowEditWing] = useState(false)
  const [showAddFlat, setShowAddFlat] = useState(false)
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState([])   // Q2 warnings / adoption feedback
  const [confirmWing, setConfirmWing] = useState(false)
  const [confirmFlat, setConfirmFlat] = useState(null)
  const [confirmLink, setConfirmLink] = useState(null)  // prior deleted flat found on add

  // society_admin's society comes from the JWT; platform_admin must name one.
  const sq = isPlatform ? societyId : ''
  const wingQuery = isPlatform ? `?society_id=${societyId}` : ''

  // platform_admin has no society in their JWT — they must pick one first.
  useEffect(() => {
    if (isPlatform) apiFetch('/societies').then(setSocieties).catch(() => {})
  }, [isPlatform])

  const loadWings = useCallback(async () => {
    if (isPlatform && !societyId) {
      setWings([])
      return
    }
    try {
      setWings(await apiFetch(`/wings${wingQuery}`))
    } catch (err) {
      setError(err.message)
    }
  }, [isPlatform, societyId, wingQuery])

  const loadFlats = useCallback(async (wid) => {
    if (!wid) {
      setFlats([])
      setOccupied(new Set())
      setContacts(new Map())
      return
    }
    setLoading(true)
    try {
      const [flatRows, residents] = await Promise.all([
        apiFetch(`/flats?wing_id=${wid}${isPlatform ? `&society_id=${sq}` : ''}`),
        apiFetch('/residents'),
      ])
      setFlats(flatRows)
      setOccupied(new Set(residents.map((r) => occKey(r.society_id, r.flat_number))))
      setContacts(new Map(
        residents.filter((r) => r.is_primary)
          .map((r) => [occKey(r.society_id, r.flat_number), r.name]),
      ))
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [isPlatform, sq])

  // Reset down the chain when the society changes.
  useEffect(() => {
    setError('')
    setWingId('')
    setFlats([])
    setNotice([])
    loadWings()
  }, [loadWings])

  useEffect(() => {
    setNotice([])
    loadFlats(wingId)
  }, [wingId, loadFlats])

  async function addWing(e) {
    e.preventDefault()
    setBusy(true)
    setError('')
    setNotice([])
    try {
      const body = {
        name: wingForm.name.trim(),
        floors: Number(wingForm.floors),
        flats_per_floor: Number(wingForm.flats_per_floor),
      }
      if (isPlatform) body.society_id = societyId
      const created = await apiFetch('/wings', { method: 'POST', body })
      setWingForm(emptyWing)
      setShowAddWing(false)
      await loadWings()
      // E4-S1: the new building is drawn immediately — as an empty grid, because
      // declaring a wing creates no flats (D2).
      setWingId(created.id)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  function startEditWing() {
    setEditForm({
      name: wing?.name ?? '',
      floors: String(wing?.floors ?? ''),
      flats_per_floor: String(wing?.flats_per_floor ?? ''),
    })
    setShowEditWing(true)
    setShowAddFlat(false)
    setNotice([])
  }

  async function saveWing(e) {
    e.preventDefault()
    setBusy(true)
    setError('')
    setNotice([])
    try {
      const updated = await apiFetch(`/wings/${wingId}`, {
        method: 'PATCH',
        body: {
          name: editForm.name.trim(),
          floors: Number(editForm.floors),
          flats_per_floor: Number(editForm.flats_per_floor),
        },
      })
      setShowEditWing(false)
      // E4-S3: what the edit deliberately left alone — kept codes after a
      // rename, flats now outside a reduced shape. Never a rejection.
      setNotice(updated.warnings || [])
      await loadWings()
      await loadFlats(wingId)   // the grid redraws; the flats don't move
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  async function addFlat(e) {
    e.preventDefault()
    const flat_number = flatForm.flat_number.trim()
    setBusy(true)
    setError('')
    setNotice([])
    try {
      // A flat with this code may have been deleted before. If so, ask whether to
      // adopt its history rather than silently starting a fresh, blank flat.
      const prior = await apiFetch(
        `/flats/prior-deleted?wing_id=${wingId}&flat_number=${encodeURIComponent(flat_number)}`,
      )
      if (prior.exists) {
        setConfirmLink({ prior, floor: Number(flatForm.floor), flat_number })
        setBusy(false)
        return
      }
      await postFlat(flat_number, Number(flatForm.floor), false)
    } catch (err) {
      setError(err.message)
      setBusy(false)
    }
  }

  // The actual create, shared by the plain path and the "link its history" choice.
  async function postFlat(flat_number, floor, link_prior) {
    setBusy(true)
    setError('')
    try {
      const created = await apiFetch('/flats', {
        method: 'POST',
        body: { wing_id: wingId, flat_number, floor, link_prior },
      })
      setFlatForm({ ...emptyFlat, floor: flatForm.floor })  // keep the floor for the next one
      setConfirmLink(null)
      // Q2: the declared shape is only a hint, so the server saves and warns.
      // Surfacing that is the whole point — a silent warning is no warning.
      const msgs = [...(created.warnings || [])]
      if (created.linked_residents > 0) {
        msgs.push(`Linked ${created.linked_residents} existing resident(s) already on ${created.code}.`)
      }
      if (link_prior) {
        msgs.push(`The previously deleted ${created.code}'s history now appears on this flat's page.`)
      }
      setNotice(msgs)
      await loadFlats(wingId)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  async function deleteFlat() {
    setBusy(true)
    setError('')
    setNotice([])
    try {
      await apiFetch(`/flats/${confirmFlat.id}`, { method: 'DELETE' })
      setConfirmFlat(null)
      await loadFlats(wingId)
    } catch (err) {
      // Soft delete rarely fails, but surface any reason verbatim rather than
      // swallow it.
      setError(err.message)
      setConfirmFlat(null)
    } finally {
      setBusy(false)
    }
  }

  async function deleteWing() {
    setBusy(true)
    setError('')
    try {
      await apiFetch(`/wings/${wingId}`, { method: 'DELETE' })
      setConfirmWing(false)
      setWingId('')
      await loadWings()
    } catch (err) {
      setError(err.message)   // refused if it still has flats
      setConfirmWing(false)
    } finally {
      setBusy(false)
    }
  }

  // Group flats into rows, one floor per row, highest floor at the top.
  const floors = useMemo(() => {
    const byFloor = new Map()
    for (const f of flats) {
      if (!byFloor.has(f.floor)) byFloor.set(f.floor, [])
      byFloor.get(f.floor).push(f)
    }
    return [...byFloor.keys()].sort((a, b) => b - a).map((floor) => ({
      floor,
      flats: byFloor.get(floor).sort((a, b) => (a.flat_number > b.flat_number ? 1 : -1)),
    }))
  }, [flats])

  const occCount = useMemo(
    () => flats.filter((f) => occupied.has(occKey(f.society_id, f.code))).length,
    [flats, occupied],
  )

  const needsSociety = isPlatform && !societyId
  const noWings = !needsSociety && !error && wings.length === 0
  const wing = wings.find((w) => w.id === wingId)
  const set = (setter, k) => (e) => setter((f) => ({ ...f, [k]: e.target.value }))

  return (
    <div style={ui.page}>
      <h1 className="page-title">Layout</h1>
      <div style={ui.sub}>Declare a building, enter its flats, and see them laid out.</div>

      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'flex-end', marginBottom: 20 }}>
        {isPlatform && (
          <div style={{ width: 220 }}>
            <label style={ui.label}>Society</label>
            <select className="select" value={societyId} onChange={(e) => setSocietyId(e.target.value)}>
              <option value="">Select…</option>
              {societies.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
          </div>
        )}
        {!needsSociety && wings.length > 0 && (
          <div style={{ width: 220 }}>
            <label style={ui.label}>Building (wing)</label>
            <select className="select" value={wingId} onChange={(e) => setWingId(e.target.value)}>
              <option value="">Select…</option>
              {wings.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
            </select>
          </div>
        )}
        {!needsSociety && (
          <>
            <button type="button" className="btn btn--ghost" onClick={() => setShowAddWing((v) => !v)}>
              {showAddWing ? 'Cancel' : 'Add building'}
            </button>
            <Link to="/import" className="btn btn--ghost" style={{ textDecoration: 'none' }}>
              Import residents (CSV)
            </Link>
          </>
        )}
      </div>

      {error && <div style={ui.error}>{error}</div>}

      {needsSociety && (
        <div style={{ ...ui.sub, marginTop: 4 }}>Select a society to view its buildings.</div>
      )}

      {showAddWing && (
        <form style={ui.card} onSubmit={addWing}>
          <div style={{ ...ui.label, fontSize: 14, color: colors.text, marginBottom: 4 }}>New building</div>
          <div style={{ fontSize: 13, color: colors.muted, marginBottom: 14 }}>
            Floors and flats-per-floor describe the shape of the grid — they’re a hint for
            drawing it, not a rule, and they create no flats. You add those next.
          </div>
          <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'flex-end' }}>
            <div style={{ width: 160 }}>
              <label style={ui.label}>Name</label>
              <input className="input" value={wingForm.name} onChange={set(setWingForm, 'name')}
                     required placeholder="A" />
            </div>
            <div style={{ width: 110 }}>
              <label style={ui.label}>Floors</label>
              <input className="input" type="number" min="1" value={wingForm.floors}
                     onChange={set(setWingForm, 'floors')} required placeholder="10" />
            </div>
            <div style={{ width: 130 }}>
              <label style={ui.label}>Flats / floor</label>
              <input className="input" type="number" min="1" value={wingForm.flats_per_floor}
                     onChange={set(setWingForm, 'flats_per_floor')} required placeholder="4" />
            </div>
            <button className="btn btn--primary" disabled={busy}>{busy ? 'Adding…' : 'Add building'}</button>
          </div>
        </form>
      )}

      {noWings && !showAddWing && (
        <div style={ui.card}>
          <div style={{ fontWeight: 600, color: colors.text, marginBottom: 6 }}>No buildings yet</div>
          <div style={{ fontSize: 14, color: colors.sub, marginBottom: 14 }}>
            A building is a wing with a name, a floor count and flats per floor. Add one and it
            appears here as an empty grid, ready for its flats.
          </div>
          <button type="button" className="btn btn--primary" onClick={() => setShowAddWing(true)}>
            Add your first building
          </button>
        </div>
      )}

      {wingId && (
        <>
          <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'center', marginBottom: 14 }}>
            <div style={{ ...ui.sub, marginBottom: 0 }}>
              {flats.length} flats · {occCount} occupied · {flats.length - occCount} vacant
              {wing && <span style={{ color: colors.muted }}>
                {' '}· declared {wing.floors} floors × {wing.flats_per_floor}
              </span>}
            </div>
            <button type="button" className="btn btn--ghost btn--sm" onClick={() => setShowAddFlat((v) => !v)}>
              {showAddFlat ? 'Cancel' : 'Add flat'}
            </button>
            <button type="button" className="btn btn--ghost btn--sm"
                    onClick={() => (showEditWing ? setShowEditWing(false) : startEditWing())}>
              {showEditWing ? 'Cancel' : 'Edit building'}
            </button>
            {/* Deleting stays available for a wing declared entirely by mistake;
                the server refuses once it has flats. */}
            {flats.length === 0 && !confirmWing && (
              <button type="button" className="btn btn--ghost btn--sm" onClick={() => setConfirmWing(true)}>
                Delete building
              </button>
            )}
            {flats.length === 0 && confirmWing && (
              <span style={{ display: 'inline-flex', gap: 8, alignItems: 'center' }}>
                <span style={{ fontSize: 13, color: colors.sub }}>Delete this building?</span>
                <button type="button" className="btn btn--sm" disabled={busy} onClick={deleteWing}>Yes, delete</button>
                <button type="button" className="btn btn--ghost btn--sm" onClick={() => setConfirmWing(false)}>No</button>
              </span>
            )}
          </div>

          {showEditWing && (
            <form style={ui.card} onSubmit={saveWing}>
              <div style={{ ...ui.label, fontSize: 14, color: colors.text, marginBottom: 4 }}>
                Edit {wing?.name}
              </div>
              <div style={{ fontSize: 13, color: colors.muted, marginBottom: 14 }}>
                Renaming is safe: existing flats keep their codes, so a visitor logged at{' '}
                <code>{wing?.name}-101</code> still means that flat. Only new flats use the new
                name. Changing floors or flats-per-floor just redraws the grid — reducing it
                never deletes a flat.
              </div>
              <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'flex-end' }}>
                <div style={{ width: 160 }}>
                  <label style={ui.label}>Name</label>
                  <input className="input" value={editForm.name}
                         onChange={set(setEditForm, 'name')} required />
                </div>
                <div style={{ width: 110 }}>
                  <label style={ui.label}>Floors</label>
                  <input className="input" type="number" min="1" value={editForm.floors}
                         onChange={set(setEditForm, 'floors')} required />
                </div>
                <div style={{ width: 130 }}>
                  <label style={ui.label}>Flats / floor</label>
                  <input className="input" type="number" min="1" value={editForm.flats_per_floor}
                         onChange={set(setEditForm, 'flats_per_floor')} required />
                </div>
                <button className="btn btn--primary" disabled={busy}>{busy ? 'Saving…' : 'Save changes'}</button>
              </div>
            </form>
          )}

          {showAddFlat && (
            <form style={ui.card} onSubmit={addFlat}>
              <div style={{ ...ui.label, fontSize: 14, color: colors.text, marginBottom: 4 }}>
                New flat in {wing?.name}
              </div>
              <div style={{ fontSize: 13, color: colors.muted, marginBottom: 14 }}>
                Type the number as it’s painted on the door — the code becomes{' '}
                <code>{wing?.name}-{flatForm.flat_number || '101'}</code>. The floor is stored,
                never guessed from the number.
              </div>
              <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'flex-end' }}>
                <div style={{ width: 160 }}>
                  <label style={ui.label}>Flat number</label>
                  <input className="input" value={flatForm.flat_number}
                         onChange={set(setFlatForm, 'flat_number')} required placeholder="101" />
                </div>
                <div style={{ width: 110 }}>
                  <label style={ui.label}>Floor</label>
                  <input className="input" type="number" value={flatForm.floor}
                         onChange={set(setFlatForm, 'floor')} required placeholder="1" />
                </div>
                <button className="btn btn--primary" disabled={busy}>{busy ? 'Adding…' : 'Add flat'}</button>
              </div>
            </form>
          )}

          {confirmFlat && (
            <div style={{ ...ui.card, padding: 14, display: 'flex', gap: 10,
                          alignItems: 'center', flexWrap: 'wrap' }}>
              <span style={{ fontSize: 14, color: colors.text }}>
                Delete flat <code>{confirmFlat.code}</code>?
              </span>
              <span style={{ fontSize: 13, color: colors.muted }}>
                Its residents go with it. Nothing is lost — the flat and its history
                stay on record and can be viewed from the flat page.
              </span>
              <button type="button" className="btn btn--sm" disabled={busy} onClick={deleteFlat}>
                {busy ? 'Deleting…' : 'Yes, delete'}
              </button>
              <button type="button" className="btn btn--ghost btn--sm"
                      onClick={() => setConfirmFlat(null)}>Cancel</button>
            </div>
          )}

          {confirmLink && (
            <div style={{ ...ui.card, padding: 14, display: 'flex', gap: 10,
                          alignItems: 'center', flexWrap: 'wrap',
                          borderColor: 'var(--c-accent-border)' }}>
              <span style={{ fontSize: 14, color: colors.text }}>
                A flat <code>{confirmLink.prior.code}</code> was deleted here before
                {confirmLink.prior.resident_count > 0 &&
                  ` (with ${confirmLink.prior.resident_count} resident(s))`}.
              </span>
              <span style={{ fontSize: 13, color: colors.muted }}>
                Link its history to this new flat, so its past residents and events
                show on the flat's timeline? The new flat is still new — nothing is
                un-deleted.
              </span>
              <button type="button" className="btn btn--sm" disabled={busy}
                      onClick={() => postFlat(confirmLink.flat_number, confirmLink.floor, true)}>
                {busy ? 'Creating…' : 'Link history & create'}
              </button>
              <button type="button" className="btn btn--ghost btn--sm" disabled={busy}
                      onClick={() => postFlat(confirmLink.flat_number, confirmLink.floor, false)}>
                Create without history
              </button>
              <button type="button" className="btn btn--ghost btn--sm" disabled={busy}
                      onClick={() => setConfirmLink(null)}>Cancel</button>
            </div>
          )}

          {notice.length > 0 && (
            <div style={{ ...ui.card, padding: 14, borderColor: 'var(--c-accent-border)' }}>
              {notice.map((n, i) => (
                <div key={i} style={{ fontSize: 13, color: colors.sub }}>{n}</div>
              ))}
            </div>
          )}
        </>
      )}

      {wingId && !loading && flats.length > 0 && (
        /* Wide floors scroll inside their own container so the page body never
           scrolls sideways at 375px (mirrors the .table-wrap pattern). */
        <div className="table-wrap">
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10, minWidth: 'min-content' }}>
            {floors.map(({ floor, flats: row }) => (
              <div key={floor} style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                <div
                  style={{
                    flex: '0 0 auto', width: 64, fontSize: 12, color: colors.muted,
                    fontWeight: 600, textAlign: 'right',
                  }}
                >
                  Floor {floor}
                </div>
                <div style={{ display: 'flex', gap: 8 }}>
                  {row.map((f) => (
                    <Flat
                      key={f.id}
                      flat={f}
                      contact={contacts.get(occKey(f.society_id, f.code))}
                      occupied={occupied.has(occKey(f.society_id, f.code))}
                      onDelete={(target) => { setError(''); setConfirmFlat(target) }}
                    />
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {wingId && loading && <div style={ui.sub}>Loading…</div>}
      {wingId && !loading && !error && flats.length === 0 && (
        <div style={ui.sub}>
          This building has no flats yet — it’s an empty grid until you add them.
        </div>
      )}
    </div>
  )
}
