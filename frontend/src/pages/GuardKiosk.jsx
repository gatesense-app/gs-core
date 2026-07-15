import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { apiFetch } from '../api'

// Look/feel for inputs and the button comes from .input / .btn in index.css,
// so they get hover, focus rings, disabled and 44px touch targets.
const s = {
  page: { maxWidth: 480, margin: '60px auto', padding: '0 20px' },
  sub: { fontSize: 14, color: 'var(--c-muted)', marginBottom: 32 },
  label: { display: 'block', fontSize: 13, color: 'var(--c-sub)', marginBottom: 6 },
  gap: { marginBottom: 18 },
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
      <h1 className="page-title" style={{ marginBottom: 6 }}>Guard Kiosk</h1>
      <div style={s.sub}>Log a visitor at the gate</div>
      <form onSubmit={submit}>
        <label style={s.label} htmlFor="k-name">Visitor name</label>
        <input id="k-name" className="input" style={s.gap} value={form.visitor_name} onChange={set('visitor_name')} required placeholder="e.g. Raju / Swiggy delivery" />

        <label style={s.label} htmlFor="k-flat">Flat number</label>
        <input id="k-flat" className="input" style={s.gap} value={form.flat_number} onChange={set('flat_number')} required placeholder="e.g. A-202" />

        <label style={s.label} htmlFor="k-purpose">Purpose</label>
        <select id="k-purpose" className="select" style={s.gap} value={form.purpose} onChange={set('purpose')}>
          {['guest', 'delivery', 'service', 'cab', 'other'].map(p =>
            <option key={p} value={p}>{p}</option>
          )}
        </select>

        <label style={s.label} htmlFor="k-detail">Details</label>
        <input id="k-detail" className="input" style={s.gap} value={form.purpose_detail} onChange={set('purpose_detail')} required placeholder="e.g. Blinkit grocery delivery" />

        <button className="btn btn--primary btn--block" disabled={loading}>
          {loading ? 'Processing...' : 'Submit Visitor'}
        </button>
        {error && <div style={s.error} role="alert">{error}</div>}
      </form>
    </div>
  )
}
