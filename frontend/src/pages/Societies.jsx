import { useEffect, useState } from 'react'
import { apiFetch } from '../api'
import { ui } from '../ui'

const empty = { name: '', address: '', admin_email: '', admin_password: '', admin_name: '' }

export default function Societies() {
  const [rows, setRows] = useState([])
  const [form, setForm] = useState(empty)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }))

  async function load() {
    try {
      setRows(await apiFetch('/societies'))
    } catch (err) {
      setError(err.message)
    }
  }
  useEffect(() => { load() }, [])

  async function create(e) {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      await apiFetch('/societies', { method: 'POST', body: form })
      setForm(empty)
      await load()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div style={ui.page}>
      <div style={ui.h1}>Societies</div>
      <div style={ui.sub}>Onboard a society and create its administrator.</div>

      <form style={ui.card} onSubmit={create}>
        <div style={{ ...ui.label, fontSize: 14, color: '#e2e8f0', marginBottom: 14 }}>New society</div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
          <div>
            <label style={ui.label}>Society name</label>
            <input style={ui.input} value={form.name} onChange={set('name')} required placeholder="Green Meadows" />
          </div>
          <div>
            <label style={ui.label}>Address</label>
            <input style={ui.input} value={form.address} onChange={set('address')} placeholder="MG Road, Bengaluru" />
          </div>
          <div>
            <label style={ui.label}>Admin name</label>
            <input style={ui.input} value={form.admin_name} onChange={set('admin_name')} placeholder="Site Manager" />
          </div>
          <div>
            <label style={ui.label}>Admin email</label>
            <input style={ui.input} type="email" value={form.admin_email} onChange={set('admin_email')} required placeholder="admin@..." />
          </div>
          <div>
            <label style={ui.label}>Admin password</label>
            <input style={ui.input} type="password" value={form.admin_password} onChange={set('admin_password')} required minLength={6} />
          </div>
        </div>
        <button style={ui.btn} disabled={busy}>{busy ? 'Creating…' : 'Create society'}</button>
        {error && <div style={ui.error}>{error}</div>}
      </form>

      <table style={ui.table}>
        <thead>
          <tr>{['Name', 'Address'].map((h) => <th key={h} style={ui.th}>{h}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((s) => (
            <tr key={s.id}>
              <td style={{ ...ui.td, fontWeight: 500 }}>{s.name}</td>
              <td style={{ ...ui.td, color: '#94a3b8' }}>{s.address || '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
