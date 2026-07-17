import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { apiFetch } from '../api'
import { useAuth } from '../auth'
import { ui, colors } from '../ui'

// E3 — bulk resident import. The realistic setup path: 300 flats aren't hand-typed.
//
// Preview then commit, because the API is preview-first: the same upload is
// validated with dry_run=true (writes nothing) so the admin sees what would be
// created/updated/rejected and why, and can cancel. Committing re-validates and
// is all-or-nothing — one bad row leaves nothing behind.
//
// The wings must already exist: an unknown wing is a row error, never an
// implicit create, so a typo can't spawn a phantom building. Flats, though, are
// created by the import — that's the bulk path.

function download(name, text) {
  const url = URL.createObjectURL(new Blob([text], { type: 'text/csv' }))
  const a = document.createElement('a')
  a.href = url
  a.download = name
  a.click()
  URL.revokeObjectURL(url)
}

export default function ImportResidents() {
  const { user } = useAuth()
  const isPlatform = user.role === 'platform_admin'

  const [societies, setSocieties] = useState([])
  const [societyId, setSocietyId] = useState('')
  const [csv, setCsv] = useState('')
  const [fileName, setFileName] = useState('')
  const [report, setReport] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [done, setDone] = useState(false)

  useEffect(() => {
    if (isPlatform) apiFetch('/societies').then(setSocieties).catch(() => {})
  }, [isPlatform])

  const needsSociety = isPlatform && !societyId
  const q = (dry) => `/import/residents?dry_run=${dry}${isPlatform ? `&society_id=${societyId}` : ''}`

  async function pickFile(e) {
    const file = e.target.files?.[0]
    if (!file) return
    setFileName(file.name)
    setReport(null)
    setDone(false)
    setError('')
    setCsv(await file.text())
  }

  async function send(dry) {
    setBusy(true)
    setError('')
    try {
      // Raw text/csv body — the API caps the bytes it reads, so an enormous file
      // is refused rather than swallowed.
      const rep = await apiFetch(q(dry), { method: 'POST', body: csv, contentType: 'text/csv' })
      setReport(rep)
      setDone(rep.committed)
    } catch (err) {
      setError(err.message)   // empty file, bad header, non-CSV, too large
      setReport(null)
    } finally {
      setBusy(false)
    }
  }

  async function getTemplate() {
    try {
      download('residents-template.csv',
        await apiFetch('/import/residents/template', { responseType: 'text' }))
    } catch (err) {
      setError(err.message)
    }
  }

  const clean = report && report.rejected_rows === 0
  const total = report ? report.residents_to_create + report.residents_to_update : 0

  return (
    <div style={ui.page}>
      <h1 className="page-title">Import residents</h1>
      <div style={ui.sub}>
        Upload a CSV of residents. Nothing is written until you confirm.{' '}
        <Link to="/layout" style={{ color: colors.accentLight }}>Buildings must exist first</Link>.
      </div>

      <div style={ui.card}>
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'flex-end' }}>
          {isPlatform && (
            <div style={{ width: 220 }}>
              <label style={ui.label}>Society</label>
              <select className="select" value={societyId} onChange={(e) => setSocietyId(e.target.value)}>
                <option value="">Select…</option>
                {societies.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
              </select>
            </div>
          )}
          <div style={{ flex: 1, minWidth: 220 }}>
            <label style={ui.label}>CSV file</label>
            <input className="input" type="file" accept=".csv,text/csv" onChange={pickFile} />
          </div>
          <button type="button" className="btn btn--ghost" onClick={getTemplate}>Download template</button>
        </div>

        <div style={{ fontSize: 13, color: colors.muted, marginTop: 14 }}>
          Columns: <code>wing, flat_number, floor, resident_name, phone, is_primary_contact</code>.
          Several rows may share a flat — that’s a household. Mark one{' '}
          <code>is_primary_contact</code> to say who the gate calls; otherwise the first row for
          that flat wins.
        </div>

        {csv && !done && (
          <div style={{ display: 'flex', gap: 8, marginTop: 16, alignItems: 'center', flexWrap: 'wrap' }}>
            <button type="button" className="btn btn--primary" disabled={busy || needsSociety}
                    onClick={() => send(true)}>
              {busy ? 'Checking…' : 'Preview'}
            </button>
            {report && clean && (
              <button type="button" className="btn" disabled={busy} onClick={() => send(false)}>
                Import {total} resident{total === 1 ? '' : 's'}
              </button>
            )}
            <span style={{ fontSize: 13, color: colors.muted }}>{fileName}</span>
            {needsSociety && <span style={{ fontSize: 13, color: colors.muted }}>Pick a society first.</span>}
          </div>
        )}

        {error && <div style={ui.error}>{error}</div>}
      </div>

      {report && (
        <div style={ui.card}>
          <div style={{ ...ui.label, fontSize: 14, color: colors.text, marginBottom: 12 }}>
            {report.committed
              ? 'Imported'
              : clean ? 'Ready to import — nothing written yet' : 'Rejected — nothing written'}
          </div>

          <div style={{ display: 'flex', gap: 28, flexWrap: 'wrap', marginBottom: 4 }}>
            {[
              ['Rows read', report.total_rows],
              ['Residents created', report.residents_to_create],
              ['Residents updated', report.residents_to_update],
              // Not in the file, but already living at a code it creates — the
              // new flat adopts them instead of orphaning them.
              ['Residents adopted', report.residents_to_link],
              ['Flats created', report.flats_to_create],
              ['Rows rejected', report.rejected_rows],
            ].map(([k, v]) => (
              <div key={k}>
                <div style={{ fontSize: 11, color: colors.muted, textTransform: 'uppercase', letterSpacing: '0.05em' }}>{k}</div>
                <div style={{ fontSize: 18, fontWeight: 600, color: colors.text }}>{v}</div>
              </div>
            ))}
          </div>

          {report.committed && (
            <div style={{ fontSize: 13, color: colors.ok, marginTop: 12 }}>
              Done. <Link to="/layout" style={{ color: colors.accentLight }}>See the layout</Link>.
            </div>
          )}

          {!report.committed && clean && (
            <div style={{ fontSize: 13, color: colors.sub, marginTop: 12 }}>
              Every row is valid. Nothing has been written — press Import to commit.
            </div>
          )}

          {report.errors?.length > 0 && (
            <>
              <div style={{ fontSize: 13, color: colors.sub, margin: '18px 0 8px' }}>
                The whole file is rejected until these are fixed — a bad row never leaves a
                half-imported list.
              </div>
              <div className="table-wrap">
                <table style={ui.table}>
                  <thead>
                    <tr>{['Row', 'Column', 'Problem'].map((h) => <th key={h} style={ui.th}>{h}</th>)}</tr>
                  </thead>
                  <tbody>
                    {report.errors.map((e, i) => (
                      <tr key={i}>
                        <td style={{ ...ui.td, fontFamily: 'monospace', color: colors.sub }}>{e.row}</td>
                        <td style={{ ...ui.td, fontFamily: 'monospace', color: colors.sub }}>{e.column || '—'}</td>
                        <td style={ui.td}>{e.message}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  )
}
