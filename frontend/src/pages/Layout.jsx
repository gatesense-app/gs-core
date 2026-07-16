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
// count, so we build a set of occupied keys from /residents. platform_admin's
// /residents spans societies, hence society_id is part of the key.
function occKey(societyId, code) {
  return `${societyId}::${code}`
}

const flatCell = {
  display: 'flex', flexDirection: 'column', gap: 4, justifyContent: 'center',
  flex: '0 0 auto', width: 84, minHeight: 56, padding: '8px 10px',
  borderRadius: 10, textDecoration: 'none', boxSizing: 'border-box',
  border: '1px solid var(--c-border)',
}
const flatState = {
  occupied: { background: 'var(--c-accent-bg)', borderColor: 'var(--c-accent-border)', color: 'var(--c-ok)' },
  vacant: { background: 'transparent', color: 'var(--c-muted)' },
}

function Flat({ flat, occupied }) {
  const label = occupied ? 'Occupied' : 'Vacant'
  return (
    <Link
      to={`/flat/${flat.id}`}
      style={{ ...flatCell, ...(occupied ? flatState.occupied : flatState.vacant) }}
      title={`Flat ${flat.code} — ${label}`}
    >
      <span style={{ fontFamily: 'monospace', fontSize: 14, fontWeight: 600, color: 'var(--c-text)' }}>{flat.code}</span>
      {/* State is never colour-alone: a shape marker + a text label carry it too. */}
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 11 }}>
        <span aria-hidden="true">{occupied ? '●' : '○'}</span>
        {label}
      </span>
    </Link>
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
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  // Management (E4-S1/S2)
  const [wingForm, setWingForm] = useState(emptyWing)
  const [flatForm, setFlatForm] = useState(emptyFlat)
  const [showAddWing, setShowAddWing] = useState(false)
  const [showAddFlat, setShowAddFlat] = useState(false)
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState([])   // Q2 warnings / adoption feedback
  const [confirmWing, setConfirmWing] = useState(false)

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

  async function addFlat(e) {
    e.preventDefault()
    setBusy(true)
    setError('')
    setNotice([])
    try {
      const created = await apiFetch('/flats', {
        method: 'POST',
        body: {
          wing_id: wingId,
          flat_number: flatForm.flat_number.trim(),
          floor: Number(flatForm.floor),
        },
      })
      setFlatForm({ ...emptyFlat, floor: flatForm.floor })  // keep the floor for the next one
      // Q2: the declared shape is only a hint, so the server saves and warns.
      // Surfacing that is the whole point — a silent warning is no warning.
      const msgs = [...(created.warnings || [])]
      if (created.linked_residents > 0) {
        msgs.push(`Linked ${created.linked_residents} existing resident(s) already on ${created.code}.`)
      }
      setNotice(msgs)
      await loadFlats(wingId)
    } catch (err) {
      setError(err.message)
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
            {/* No PATCH /wings yet (E4-S3), so deleting is the only way to undo a
                typo'd name. The server refuses once the wing has flats. */}
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
                    <Flat key={f.id} flat={f} occupied={occupied.has(occKey(f.society_id, f.code))} />
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
