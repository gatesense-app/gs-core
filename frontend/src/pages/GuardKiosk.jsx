import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { apiFetch } from '../api'

const field = {
  width: '100%', padding: '10px 14px', borderRadius: 8,
  border: '1px solid var(--c-border)', background: 'var(--c-input-bg)',
  color: 'var(--c-text)', fontSize: 14, marginBottom: 18, outline: 'none',
  boxSizing: 'border-box',
}
const s = {
  page: { maxWidth: 480, margin: '60px auto', padding: '0 20px' },
  heading: { fontSize: 22, fontWeight: 700, color: 'var(--c-text)', marginBottom: 6 },
  sub: { fontSize: 14, color: 'var(--c-muted)', marginBottom: 32 },
  label: { display: 'block', fontSize: 13, color: 'var(--c-sub)', marginBottom: 6 },
  input: field,
  select: field,
  btn: {
    width: '100%', padding: '12px', borderRadius: 8,
    background: 'var(--c-btn-bg)',
    border: 'none', color: 'var(--c-btn-text)', fontSize: 15, fontWeight: 700,
    boxShadow: '0 6px 16px -8px var(--c-accent)',
  },
  error: { color: 'var(--c-error)', fontSize: 13, marginTop: 12 },
}

export default function GuardKiosk() {
  const nav = useNavigate()
  const [form, setForm] = useState({
    visitor_name: '', flat_number: '',
    purpose: 'guest', purpose_detail: '',
  })
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const set = (k) => (e) => setForm(f => ({ ...f, [k]: e.target.value }))

  async function submit(e) {
    e.preventDefault()
    setLoading(true); setError('')
    try {
      const session = await apiFetch('/sessions', { method: 'POST', body: form })
      nav(`/session/${session.session_id}`)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={s.page}>
      <div style={s.heading}>Guard Kiosk</div>
      <div style={s.sub}>Log a visitor at the gate</div>
      <form onSubmit={submit}>
        <label style={s.label}>Visitor name</label>
        <input style={s.input} value={form.visitor_name} onChange={set('visitor_name')} required placeholder="e.g. Raju / Swiggy delivery" />

        <label style={s.label}>Flat number</label>
        <input style={s.input} value={form.flat_number} onChange={set('flat_number')} required placeholder="e.g. A-202" />

        <label style={s.label}>Purpose</label>
        <select style={s.select} value={form.purpose} onChange={set('purpose')}>
          {['guest', 'delivery', 'service', 'cab', 'other'].map(p =>
            <option key={p} value={p}>{p}</option>
          )}
        </select>

        <label style={s.label}>Details</label>
        <input style={s.input} value={form.purpose_detail} onChange={set('purpose_detail')} required placeholder="e.g. Blinkit grocery delivery" />

        <button style={s.btn} disabled={loading}>
          {loading ? 'Processing...' : 'Submit Visitor'}
        </button>
        {error && <div style={s.error}>{error}</div>}
      </form>
    </div>
  )
}
