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

export default function Users() {
  const { user } = useAuth()
  const isPlatform = user.role === 'platform_admin'
  const [rows, setRows] = useState([])
  const [societies, setSocieties] = useState([])
  const [form, setForm] = useState(emptyForm)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }))

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
      <div style={ui.h1}>Users &amp; Guards</div>
      <div style={ui.sub}>Create logins for staff and residents.</div>

      <form style={ui.card} onSubmit={create}>
        <div style={{ ...ui.label, fontSize: 14, color: '#e2e8f0', marginBottom: 14 }}>New user</div>
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'flex-end' }}>
          {isPlatform && (
            <div style={{ width: 180 }}>
              <label style={ui.label}>Society</label>
              <select style={{ ...ui.input, marginBottom: 0 }} value={form.society_id} onChange={set('society_id')} required>
                <option value="">Select…</option>
                {societies.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
              </select>
            </div>
          )}
          <div style={{ width: 140 }}>
            <label style={ui.label}>Role</label>
            <select style={{ ...ui.input, marginBottom: 0 }} value={form.role} onChange={set('role')}>
              <option value="guard">guard</option>
              <option value="resident">resident</option>
              <option value="society_admin">society_admin</option>
            </select>
          </div>
          <div style={{ flex: 1, minWidth: 180 }}>
            <label style={ui.label}>Email</label>
            <input style={{ ...ui.input, marginBottom: 0 }} type="email" value={form.email} onChange={set('email')} required placeholder="guard4@..." />
          </div>
          <div style={{ width: 150 }}>
            <label style={ui.label}>Name</label>
            <input style={{ ...ui.input, marginBottom: 0 }} value={form.full_name} onChange={set('full_name')} placeholder="Full name" />
          </div>
          <div style={{ width: 140 }}>
            <label style={ui.label}>Password</label>
            <input style={{ ...ui.input, marginBottom: 0 }} type="password" value={form.password} onChange={set('password')} required minLength={6} />
          </div>
          <button style={ui.btn} disabled={busy}>{busy ? 'Adding…' : 'Add'}</button>
        </div>
        {error && <div style={ui.error}>{error}</div>}
      </form>

      <table style={ui.table}>
        <thead>
          <tr>{['Email', 'Name', 'Role'].map((h) => <th key={h} style={ui.th}>{h}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((u) => (
            <tr key={u.id}>
              <td style={{ ...ui.td, fontWeight: 500 }}>{u.email}</td>
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
  )
}
