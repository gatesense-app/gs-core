import { useEffect, useState } from 'react'
import { apiFetch } from '../api'
import { ui } from '../ui'

const empty = { name: '', address: '', admin_email: '', admin_password: '', admin_name: '' }
const emptyAdmin = { email: '', password: '', full_name: '' }

// Blank admin fields must be OMITTED, not sent as "": the API validates
// admin_email as an email address, so "" would 422 rather than mean "no admin".
function createPayload(form) {
  const body = { name: form.name.trim(), address: form.address.trim() || null }
  if (form.admin_email.trim()) {
    body.admin_email = form.admin_email.trim()
    body.admin_password = form.admin_password
    if (form.admin_name.trim()) body.admin_name = form.admin_name.trim()
  }
  return body
}

const s = {
  hint: { fontSize: 12, color: 'var(--c-muted)', marginTop: -6, marginBottom: 14 },
  legend: { ...ui.label, fontSize: 13, color: 'var(--c-text)', fontWeight: 600, marginTop: 8, marginBottom: 10 },
  // The create form collapses so the societies table is what you land on.
  // <summary> is the always-visible header/toggle; it's keyboard-operable natively.
  summary: {
    cursor: 'pointer', fontSize: 14, fontWeight: 600, color: 'var(--c-text)',
    display: 'flex', alignItems: 'center', gap: 8, userSelect: 'none',
  },
  summaryHint: { fontWeight: 400, fontSize: 13, color: 'var(--c-muted)' },
  // Status is never colour-only: the chip always carries its word.
  noAdmin: {
    display: 'inline-block', padding: '2px 9px', borderRadius: 99, fontSize: 12, fontWeight: 600,
    background: 'rgba(249,115,22,0.14)', color: '#b45309', border: '1px solid rgba(249,115,22,0.4)',
  },
  adminCount: { fontSize: 13, color: 'var(--c-sub)' },
  actions: { display: 'flex', gap: 8, flexWrap: 'wrap' },
  inlineForm: { display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' },
}

export default function Societies() {
  const [rows, setRows] = useState([])
  const [form, setForm] = useState(empty)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [editing, setEditing] = useState(null)      // society id being renamed
  const [editForm, setEditForm] = useState({ name: '', address: '' })
  const [addingAdmin, setAddingAdmin] = useState(null)  // society id gaining an admin
  const [adminForm, setAdminForm] = useState(emptyAdmin)

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
    setBusy(true); setError('')
    try {
      await apiFetch('/societies', { method: 'POST', body: createPayload(form) })
      setForm(empty)
      await load()
    } catch (err) { setError(err.message) } finally { setBusy(false) }
  }

  async function saveEdit(id) {
    setBusy(true); setError('')
    try {
      await apiFetch(`/societies/${id}`, {
        method: 'PATCH',
        body: { name: editForm.name.trim(), address: editForm.address.trim() || null },
      })
      setEditing(null)
      await load()
    } catch (err) { setError(err.message) } finally { setBusy(false) }
  }

  async function togglePhonePrivacy(soc) {
    setBusy(true); setError('')
    try {
      await apiFetch(`/societies/${soc.id}`, {
        method: 'PATCH',
        body: { hide_resident_phones: !soc.hide_resident_phones },
      })
      await load()
    } catch (err) { setError(err.message) } finally { setBusy(false) }
  }

  async function saveAdmin(societyId) {
    setBusy(true); setError('')
    try {
      // No dedicated endpoint needed: a platform admin may target any society.
      await apiFetch('/users', {
        method: 'POST',
        body: {
          email: adminForm.email.trim(),
          password: adminForm.password,
          role: 'society_admin',
          full_name: adminForm.full_name.trim() || null,
          society_id: societyId,
        },
      })
      setAddingAdmin(null)
      setAdminForm(emptyAdmin)
      await load()
    } catch (err) { setError(err.message) } finally { setBusy(false) }
  }

  return (
    <div style={ui.page}>
      <h1 className="page-title">Societies</h1>
      <div style={ui.sub}>Onboard a society now; its administrator can be allocated at any time.</div>

      <details style={ui.card}>
        <summary style={s.summary}>
          <span className="disclosure" aria-hidden="true" style={{ fontSize: 12, display: 'inline-block' }}>▸</span>
          New society
          <span style={s.summaryHint}>— add a society and, optionally, its first admin</span>
        </summary>
        <form style={{ marginTop: 16 }} onSubmit={create}>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
          <div>
            <label style={ui.label} htmlFor="soc-name">Society name</label>
            <input id="soc-name" className="input" style={ui.fieldGap} value={form.name} onChange={set('name')} required placeholder="Green Meadows" />
          </div>
          <div>
            <label style={ui.label} htmlFor="soc-addr">Address</label>
            <input id="soc-addr" className="input" style={ui.fieldGap} value={form.address} onChange={set('address')} placeholder="MG Road, Bengaluru" />
          </div>
        </div>

        <div style={s.legend}>Administrator <span style={{ fontWeight: 400, color: 'var(--c-muted)' }}>— optional</span></div>
        <div style={s.hint}>
          Leave blank to onboard the society now and allocate an admin later. Email and password go together.
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
          <div>
            <label style={ui.label} htmlFor="soc-admin-name">Admin name</label>
            <input id="soc-admin-name" className="input" style={ui.fieldGap} value={form.admin_name} onChange={set('admin_name')} placeholder="Site Manager" />
          </div>
          <div>
            <label style={ui.label} htmlFor="soc-admin-email">Admin email</label>
            <input id="soc-admin-email" className="input" style={ui.fieldGap} type="email" value={form.admin_email} onChange={set('admin_email')} placeholder="admin@…" />
          </div>
          <div>
            <label style={ui.label} htmlFor="soc-admin-pw">Admin password</label>
            <input
              id="soc-admin-pw" className="input" style={ui.fieldGap} type="password"
              value={form.admin_password} onChange={set('admin_password')}
              // Only required once an email is given — the API enforces the same pairing.
              required={!!form.admin_email.trim()}
              minLength={6}
              autoComplete="new-password"
            />
          </div>
        </div>
        <button className="btn btn--primary" disabled={busy}>{busy ? 'Creating…' : 'Create society'}</button>
        {error && <div style={ui.error} role="alert">{error}</div>}
        </form>
      </details>

      <div className="table-wrap">
        <table style={ui.table}>
          <thead>
            <tr>{['Name', 'Address', 'Admins', 'Resident phones', ''].map((h) => <th key={h} style={ui.th}>{h}</th>)}</tr>
          </thead>
          <tbody>
            {rows.map((soc) => (
              <tr key={soc.id}>
                {editing === soc.id ? (
                  <>
                    <td style={ui.td}>
                      <input className="input" aria-label="Society name" value={editForm.name}
                        onChange={(e) => setEditForm((f) => ({ ...f, name: e.target.value }))} />
                    </td>
                    <td style={ui.td}>
                      <input className="input" aria-label="Address" value={editForm.address}
                        onChange={(e) => setEditForm((f) => ({ ...f, address: e.target.value }))} />
                    </td>
                    <td style={ui.td} />
                    <td style={ui.td} />
                    <td style={ui.td}>
                      <div style={s.actions}>
                        <button className="btn btn--primary btn--sm" disabled={busy} onClick={() => saveEdit(soc.id)}>Save</button>
                        <button className="btn btn--ghost btn--sm" onClick={() => setEditing(null)}>Cancel</button>
                      </div>
                    </td>
                  </>
                ) : (
                  <>
                    <td style={{ ...ui.td, fontWeight: 500 }}>{soc.name}</td>
                    <td style={{ ...ui.td, color: 'var(--c-muted)' }}>{soc.address || '—'}</td>
                    <td style={ui.td}>
                      {soc.admin_count > 0
                        ? <span style={s.adminCount}>{soc.admin_count}</span>
                        : <span style={s.noAdmin}>No admin</span>}
                    </td>
                    <td style={ui.td}>
                      <button className="btn btn--ghost btn--sm" disabled={busy}
                              title="Masking hides all but the last 4 digits of resident phones from staff"
                              onClick={() => togglePhonePrivacy(soc)}>
                        {soc.hide_resident_phones ? 'Masked ✓' : 'Shown'}
                      </button>
                    </td>
                    <td style={ui.td}>
                      <div style={s.actions}>
                        <button className="btn btn--ghost btn--sm" onClick={() => {
                          setEditing(soc.id)
                          setEditForm({ name: soc.name, address: soc.address || '' })
                        }}>Edit</button>
                        <button className="btn btn--ghost btn--sm" onClick={() => {
                          setAddingAdmin(soc.id)
                          setAdminForm(emptyAdmin)
                        }}>Add admin</button>
                      </div>

                      {addingAdmin === soc.id && (
                        <form
                          style={{ ...s.inlineForm, marginTop: 12 }}
                          onSubmit={(e) => { e.preventDefault(); saveAdmin(soc.id) }}
                        >
                          <input className="input" style={{ width: 190 }} type="email" required
                            aria-label={`Admin email for ${soc.name}`} placeholder="admin@…"
                            value={adminForm.email}
                            onChange={(e) => setAdminForm((f) => ({ ...f, email: e.target.value }))} />
                          <input className="input" style={{ width: 150 }} type="password" required minLength={6}
                            aria-label={`Admin password for ${soc.name}`} placeholder="password"
                            autoComplete="new-password"
                            value={adminForm.password}
                            onChange={(e) => setAdminForm((f) => ({ ...f, password: e.target.value }))} />
                          <input className="input" style={{ width: 150 }}
                            aria-label={`Admin name for ${soc.name}`} placeholder="Name (optional)"
                            value={adminForm.full_name}
                            onChange={(e) => setAdminForm((f) => ({ ...f, full_name: e.target.value }))} />
                          <button className="btn btn--primary btn--sm" disabled={busy}>{busy ? 'Adding…' : 'Add'}</button>
                          <button type="button" className="btn btn--ghost btn--sm" onClick={() => setAddingAdmin(null)}>Cancel</button>
                        </form>
                      )}
                    </td>
                  </>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
