import { useEffect, useState } from 'react'
import { apiFetch } from '../api'
import { useAuth } from '../auth'
import { ui, colors } from '../ui'

function ruleLabel(r) {
  if (r.type === 'always_allow') return `Allow ${r.match}`
  if (r.type === 'never_allow') return `Deny after ${r.after}`
  return JSON.stringify(r)
}

function RulesEditor({ initial, onSave, onCancel, busy }) {
  const [rules, setRules] = useState(initial || [])
  const [type, setType] = useState('always_allow')
  const [value, setValue] = useState('')

  function add() {
    const v = value.trim()
    if (!v) return
    setRules((rs) => [...rs, type === 'always_allow' ? { type, match: v } : { type: 'never_allow', after: v }])
    setValue('')
  }

  return (
    <div>
      <div style={{ marginBottom: 10 }}>
        {rules.length === 0 && <span style={{ color: colors.muted, fontSize: 13 }}>No rules yet.</span>}
        {rules.map((r, i) => (
          <span key={i} style={ui.chip}>
            {ruleLabel(r)}
            {/* Real button: as a bare <span onClick> this was unreachable by
                keyboard entirely — no focus, no Enter. */}
            <button
              type="button"
              className="chip-x"
              aria-label={`Remove rule: ${ruleLabel(r)}`}
              onClick={() => setRules((rs) => rs.filter((_, j) => j !== i))}
            >×</button>
          </span>
        ))}
      </div>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 12 }}>
        <select className="select" style={{ width: 170 }} value={type} onChange={(e) => setType(e.target.value)}>
          <option value="always_allow">Always allow</option>
          <option value="never_allow">Never allow after</option>
        </select>
        <input
          className="input"
          style={{ flex: 1 }}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder={type === 'always_allow' ? 'e.g. Swiggy' : 'e.g. 21:00'}
        />
        <button type="button" className="btn btn--ghost" onClick={add}>Add</button>
      </div>
      <button className="btn btn--primary" disabled={busy} onClick={() => onSave(rules)}>{busy ? 'Saving…' : 'Save rules'}</button>
      <button type="button" className="btn btn--ghost" style={{ marginLeft: 8 }} onClick={onCancel}>Cancel</button>
    </div>
  )
}

const emptyForm = { flat_number: '', name: '', phone: '', society_id: '' }

export default function Residents() {
  const { user } = useAuth()
  const isPlatform = user.role === 'platform_admin'
  const [rows, setRows] = useState([])
  const [societies, setSocieties] = useState([])
  const [form, setForm] = useState(emptyForm)
  const [editing, setEditing] = useState(null) // resident id
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }))

  async function load() {
    try {
      setRows(await apiFetch('/residents'))
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
      const body = { flat_number: form.flat_number, name: form.name, phone: form.phone || null }
      if (isPlatform) body.society_id = form.society_id
      await apiFetch('/residents', { method: 'POST', body })
      setForm(emptyForm)
      await load()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  async function saveRules(id, rules) {
    setBusy(true)
    setError('')
    try {
      await apiFetch(`/residents/${id}`, { method: 'PATCH', body: { standing_rules: rules } })
      setEditing(null)
      await load()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div style={ui.page}>
      <h1 className="page-title">Residents</h1>
      <div style={ui.sub}>{rows.length} residents. Manage flats and standing rules.</div>

      <form style={ui.card} onSubmit={create}>
        <div style={{ ...ui.label, fontSize: 14, color: 'var(--c-text)', marginBottom: 14 }}>New resident</div>
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'flex-end' }}>
          {isPlatform && (
            <div style={{ width: 200 }}>
              <label style={ui.label}>Society</label>
              <select className="select" value={form.society_id} onChange={set('society_id')} required>
                <option value="">Select…</option>
                {societies.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
              </select>
            </div>
          )}
          <div style={{ width: 120 }}>
            <label style={ui.label}>Flat</label>
            <input className="input" value={form.flat_number} onChange={set('flat_number')} required placeholder="A-101" />
          </div>
          <div style={{ flex: 1, minWidth: 160 }}>
            <label style={ui.label}>Name</label>
            <input className="input" value={form.name} onChange={set('name')} required placeholder="Priya Sharma" />
          </div>
          <div style={{ width: 160 }}>
            <label style={ui.label}>Phone</label>
            <input className="input" value={form.phone} onChange={set('phone')} placeholder="+91…" />
          </div>
          <button className="btn btn--primary" disabled={busy}>{busy ? 'Adding…' : 'Add'}</button>
        </div>
        {error && <div style={ui.error}>{error}</div>}
      </form>

      <table style={ui.table}>
        <thead>
          <tr>{['Flat', 'Name', 'Phone', 'Standing rules', ''].map((h) => <th key={h} style={ui.th}>{h}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id}>
              <td style={{ ...ui.td, fontFamily: 'monospace', color: colors.sub }}>{r.flat_number}</td>
              <td style={{ ...ui.td, fontWeight: 500 }}>{r.name}</td>
              <td style={{ ...ui.td, color: colors.sub }}>{r.phone || '—'}</td>
              <td style={ui.td}>
                {editing === r.id ? (
                  <RulesEditor
                    initial={r.standing_rules}
                    busy={busy}
                    onCancel={() => setEditing(null)}
                    onSave={(rules) => saveRules(r.id, rules)}
                  />
                ) : (
                  r.standing_rules?.length
                    ? r.standing_rules.map((rule, i) => <span key={i} style={ui.chip}>{ruleLabel(rule)}</span>)
                    : <span style={{ color: colors.muted }}>—</span>
                )}
              </td>
              <td style={ui.td}>
                {editing !== r.id && (
                  <button className="btn btn--ghost" onClick={() => setEditing(r.id)}>Edit rules</button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
