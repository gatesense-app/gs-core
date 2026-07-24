import { useEffect, useState } from 'react'
import { apiFetch } from '../api'
import { useAuth } from '../auth'
import { ui, colors } from '../ui'

const ROLE_COLOR = {
  platform_admin: '#f472b6',
  society_admin: '#a78bfa',
  guard: '#34d399',
  resident: '#60a5fa',
}

const emptyForm = { email: '', password: '', role: 'guard', full_name: '', society_id: '' }
const PAGE_SIZE = 25

export default function Users() {
  const { user } = useAuth()
  const isPlatform = user.role === 'platform_admin'
  const [rows, setRows] = useState([])
  const [societies, setSocieties] = useState([])
  const [form, setForm] = useState(emptyForm)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [page, setPage] = useState(0)

  const pageCount = Math.max(1, Math.ceil(rows.length / PAGE_SIZE))
  const p = Math.min(page, pageCount - 1)
  const pageRows = rows.slice(p * PAGE_SIZE, p * PAGE_SIZE + PAGE_SIZE)

  // Bulk-provision resident logins
  const [wings, setWings] = useState([])
  const [prov, setProv] = useState({ society_id: '', wing_id: '', default_password: '' })
  const [provBusy, setProvBusy] = useState(false)
  const [provResult, setProvResult] = useState(null)

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }))
  const setP = (k) => (e) => setProv((p) => ({ ...p, [k]: e.target.value, ...(k === 'society_id' ? { wing_id: '' } : {}) }))

  async function load() {
    try {
      setRows(await apiFetch('/users'))
    } catch (err) {
      setError(err.message)
    }
  }
  useEffect(() => {
    load()
    if (isPlatform) apiFetch('/societies').then(setSocieties).catch(() => {})
  }, [])

  // Wings feed the provision panel's optional building filter.
  useEffect(() => {
    if (isPlatform && !prov.society_id) { setWings([]); return }
    const q = isPlatform ? `?society_id=${prov.society_id}` : ''
    apiFetch(`/wings${q}`).then(setWings).catch(() => setWings([]))
  }, [isPlatform, prov.society_id])

  async function provision(e) {
    e.preventDefault()
    setProvBusy(true)
    setError('')
    setProvResult(null)
    try {
      const body = { default_password: prov.default_password }
      if (prov.wing_id) body.wing_id = prov.wing_id
      if (isPlatform) body.society_id = prov.society_id
      const result = await apiFetch('/users/provision-residents', { method: 'POST', body })
      setProvResult(result)
      await load()
    } catch (err) {
      setError(err.message)
    } finally {
      setProvBusy(false)
    }
  }

  async function create(e) {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      const body = {
        email: form.email,
        password: form.password,
        role: form.role,
        full_name: form.full_name || null,
      }
      if (isPlatform) body.society_id = form.society_id
      await apiFetch('/users', { method: 'POST', body })
      setForm({ ...emptyForm, society_id: form.society_id })
      await load()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div style={ui.page}>
      <h1 className="page-title">Users &amp; Guards</h1>
      <div style={ui.sub}>Create logins for staff and residents.</div>

      <form style={ui.card} onSubmit={create}>
        <div style={{ ...ui.label, fontSize: 14, color: 'var(--c-text)', marginBottom: 14 }}>New user</div>
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'flex-end' }}>
          {isPlatform && (
            <div style={{ width: 180 }}>
              <label style={ui.label}>Society</label>
              <select className="select" value={form.society_id} onChange={set('society_id')} required>
                <option value="">Select…</option>
                {societies.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
              </select>
            </div>
          )}
          <div style={{ width: 140 }}>
            <label style={ui.label}>Role</label>
            <select className="select" value={form.role} onChange={set('role')}>
              <option value="guard">guard</option>
              <option value="resident">resident</option>
              <option value="society_admin">society_admin</option>
            </select>
          </div>
          <div style={{ flex: 1, minWidth: 180 }}>
            <label style={ui.label}>Email</label>
            <input className="input" type="email" value={form.email} onChange={set('email')} required placeholder="guard4@..." />
          </div>
          <div style={{ width: 150 }}>
            <label style={ui.label}>Name</label>
            <input className="input" value={form.full_name} onChange={set('full_name')} placeholder="Full name" />
          </div>
          <div style={{ width: 140 }}>
            <label style={ui.label}>Password</label>
            <input className="input" type="password" value={form.password} onChange={set('password')} required minLength={6} />
          </div>
          <button className="btn btn--primary" disabled={busy}>{busy ? 'Adding…' : 'Add'}</button>
        </div>
        {error && <div style={ui.error}>{error}</div>}
      </form>

      {/* Bulk-provision resident logins from the residents already on record */}
      <form style={ui.card} onSubmit={provision}>
        <div style={{ ...ui.label, fontSize: 14, color: 'var(--c-text)', marginBottom: 6 }}>
          Provision resident logins
        </div>
        <div style={{ ...ui.sub, marginBottom: 14 }}>
          Creates a portal login for every resident without one. They sign in with
          their <strong>phone number</strong> and the shared password below. There
          is no reset flow yet — choose a password you can share, and change it per
          account later if needed.
        </div>
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'flex-end' }}>
          {isPlatform && (
            <div style={{ width: 180 }}>
              <label style={ui.label}>Society</label>
              <select className="select" value={prov.society_id} onChange={setP('society_id')} required>
                <option value="">Select…</option>
                {societies.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
              </select>
            </div>
          )}
          <div style={{ width: 180 }}>
            <label style={ui.label}>Building (optional)</label>
            <select className="select" value={prov.wing_id} onChange={setP('wing_id')}>
              <option value="">All buildings</option>
              {wings.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
            </select>
          </div>
          <div style={{ width: 200 }}>
            <label style={ui.label}>Shared password</label>
            <input className="input" type="text" value={prov.default_password}
                   onChange={setP('default_password')} required minLength={6}
                   placeholder="Given to residents" />
          </div>
          <button className="btn btn--primary" disabled={provBusy}>
            {provBusy ? 'Provisioning…' : 'Provision logins'}
          </button>
        </div>
        {provResult && (
          <div style={{ marginTop: 14, fontSize: 13, color: colors.sub }}>
            <div style={{ color: 'var(--c-text)', fontWeight: 500 }}>
              Created {provResult.created_count} login(s); skipped {provResult.skipped_count}.
            </div>
            {provResult.skipped_count > 0 && (
              <div style={{ marginTop: 6 }}>
                {Object.entries(
                  provResult.skipped.reduce((acc, s) => {
                    acc[s.reason] = (acc[s.reason] || 0) + 1
                    return acc
                  }, {}),
                ).map(([reason, count]) => (
                  <div key={reason}>· {count} — {reason}</div>
                ))}
              </div>
            )}
          </div>
        )}
      </form>

      <div className="table-wrap">
      <table style={ui.table}>
        <thead>
          <tr>{['Email / phone', 'Name', 'Role'].map((h) => <th key={h} style={ui.th}>{h}</th>)}</tr>
        </thead>
        <tbody>
          {pageRows.map((u) => (
            <tr key={u.id}>
              <td style={{ ...ui.td, fontWeight: 500 }}>{u.email || u.phone || '—'}</td>
              <td style={{ ...ui.td, color: colors.sub }}>{u.full_name || '—'}</td>
              <td style={ui.td}>
                <span style={{ ...ui.chip, background: (ROLE_COLOR[u.role] || '#7c3aed') + '22', color: ROLE_COLOR[u.role] || '#a78bfa', border: `1px solid ${(ROLE_COLOR[u.role] || '#7c3aed')}44` }}>
                  {u.role}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      </div>

      {pageCount > 1 && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginTop: 14 }}>
          <button type="button" className="btn btn--ghost btn--sm"
                  disabled={p === 0} onClick={() => setPage(p - 1)}>← Prev</button>
          <span style={{ fontSize: 13, color: colors.muted }}>
            Page {p + 1} of {pageCount} · {rows.length} users
          </span>
          <button type="button" className="btn btn--ghost btn--sm"
                  disabled={p >= pageCount - 1} onClick={() => setPage(p + 1)}>Next →</button>
        </div>
      )}
    </div>
  )
}
