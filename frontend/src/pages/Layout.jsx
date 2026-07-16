import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { apiFetch } from '../api'
import { useAuth } from '../auth'
import { ui, colors } from '../ui'

// E5 — Layout view. Admin picks a wing (building) and sees its floors and flats
// laid out spatially, one floor per row. Each flat links to /flat/:id.
//
// This is a STATIC directory: occupancy is fetched once on load, not streamed.
// The E5-S2 "live status over WebSocket?" open question is resolved as
// "static for now" — no realtime here on purpose. (See realtime.js; unused.)

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

  // platform_admin has no society in their JWT — they must pick one first.
  useEffect(() => {
    if (isPlatform) apiFetch('/societies').then(setSocieties).catch(() => {})
  }, [isPlatform])

  // Load wings whenever the effective society changes. society_admin omits
  // society_id (taken from JWT); platform_admin must pass it.
  useEffect(() => {
    if (isPlatform && !societyId) {
      setWings([])
      setWingId('')
      return
    }
    let cancelled = false
    setError('')
    setWingId('')
    setFlats([])
    const q = isPlatform ? `?society_id=${societyId}` : ''
    apiFetch(`/wings${q}`)
      .then((rows) => { if (!cancelled) setWings(rows) })
      .catch((err) => { if (!cancelled) setError(err.message) })
    return () => { cancelled = true }
  }, [isPlatform, societyId])

  // Load the picked wing's flats + occupancy together.
  useEffect(() => {
    if (!wingId) {
      setFlats([])
      setOccupied(new Set())
      return
    }
    let cancelled = false
    setLoading(true)
    setError('')
    const sq = isPlatform ? `&society_id=${societyId}` : ''
    Promise.all([
      apiFetch(`/flats?wing_id=${wingId}${sq}`),
      apiFetch('/residents'),
    ])
      .then(([flatRows, residents]) => {
        if (cancelled) return
        const set = new Set(residents.map((r) => occKey(r.society_id, r.flat_number)))
        setFlats(flatRows)
        setOccupied(set)
      })
      .catch((err) => { if (!cancelled) setError(err.message) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [wingId, isPlatform, societyId])

  // Group flats into rows, one floor per row, highest floor at the top.
  const floors = useMemo(() => {
    const byFloor = new Map()
    for (const f of flats) {
      if (!byFloor.has(f.floor)) byFloor.set(f.floor, [])
      byFloor.get(f.floor).push(f)
    }
    const sortedFloors = [...byFloor.keys()].sort((a, b) => b - a)
    return sortedFloors.map((floor) => ({
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

  return (
    <div style={ui.page}>
      <h1 className="page-title">Layout</h1>
      <div style={ui.sub}>Pick a building to see its floors and flats.</div>

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
      </div>

      {error && <div style={ui.error}>{error}</div>}

      {needsSociety && (
        <div style={{ ...ui.sub, marginTop: 4 }}>Select a society to view its buildings.</div>
      )}

      {noWings && (
        <div style={ui.card}>
          <div style={{ fontWeight: 600, color: colors.text, marginBottom: 6 }}>No buildings yet</div>
          <div style={{ fontSize: 14, color: colors.sub }}>
            This society has no wings. Add one through wing &amp; flat management
            (creation lives in the API), then it will appear here to lay out.
          </div>
        </div>
      )}

      {wingId && !loading && flats.length > 0 && (
        <>
          <div style={{ ...ui.sub, marginBottom: 14 }}>
            {flats.length} flats · {occCount} occupied · {flats.length - occCount} vacant
          </div>
          {/* Wide floors scroll inside their own container so the page body never
              scrolls sideways at 375px (mirrors the .table-wrap pattern). */}
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
        </>
      )}

      {wingId && loading && <div style={ui.sub}>Loading…</div>}
      {wingId && !loading && !error && flats.length === 0 && (
        <div style={ui.sub}>This building has no flats yet.</div>
      )}
    </div>
  )
}
