import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { apiFetch } from '../api'

const STATUS_COLOR = { sent: '#22c55e', delivered: '#22c55e', failed: '#ef4444' }

const s = {
  page: { padding: '32px 28px' },
  header: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6, gap: 16 },
  sub: { fontSize: 13, color: 'var(--c-muted)', marginBottom: 24 },
  stats: { display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 24 },
  stat: {
    border: '1px solid var(--c-border)', borderRadius: 10, padding: '14px 18px',
    background: 'var(--c-panel)', minWidth: 120, boxShadow: 'var(--c-card-shadow)',
  },
  statNum: { fontSize: 22, fontWeight: 800, color: 'var(--c-text)' },
  statLabel: {
    fontSize: 11, color: 'var(--c-muted)', textTransform: 'uppercase',
    letterSpacing: '0.06em', marginTop: 2,
  },
  table: { width: '100%', borderCollapse: 'collapse' },
  th: {
    textAlign: 'left', fontSize: 12, color: 'var(--c-muted)',
    padding: '0 12px 10px', borderBottom: '1px solid var(--c-border)',
  },
  td: { padding: '13px 12px', fontSize: 14, color: 'var(--c-text)', borderBottom: '1px solid var(--c-row-border)' },
  muted: { color: 'var(--c-muted)', fontSize: 13 },
  badge: (st) => ({
    display: 'inline-block', padding: '2px 9px', borderRadius: 99, fontSize: 12, fontWeight: 500,
    background: (STATUS_COLOR[st] || '#64748b') + '22',
    color: STATUS_COLOR[st] || '#64748b',
    border: `1px solid ${(STATUS_COLOR[st] || '#64748b')}44`,
  }),
  empty: { color: 'var(--c-muted)', textAlign: 'center', marginTop: 60, fontSize: 15 },
  link: { color: 'var(--c-link)', fontWeight: 600 },
}

function fmt(iso) {
  if (!iso) return '—'
  return new Date(iso).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

export default function Notifications() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  async function load() {
    try {
      setData(await apiFetch('/admin/notification-log'))
      setError('')
    } catch (e) { setError(e.message) }
    setLoading(false)
  }

  useEffect(() => { load() }, [])

  if (loading) return <div style={{ padding: 40, color: 'var(--c-muted)' }}>Loading...</div>

  const summary = data?.summary || {}
  const rows = data?.notifications || []
  const failed = summary.failed || 0

  return (
    <div style={s.page}>
      <div style={s.header}>
        <h1 className="page-title">Notification health</h1>
        <button className="btn btn--ghost" onClick={load}>Refresh</button>
      </div>
      <div style={s.sub}>Every message the intercom agent sent to a resident, and whether it landed.</div>

      {error && <div style={{ color: 'var(--c-error)', fontSize: 13, marginBottom: 16 }}>{error}</div>}

      <div style={s.stats}>
        <div style={s.stat}>
          <div style={s.statNum}>{data?.total ?? 0}</div>
          <div style={s.statLabel}>Total sent</div>
        </div>
        {Object.entries(summary).map(([st, n]) => (
          <div key={st} style={s.stat}>
            <div style={{ ...s.statNum, color: STATUS_COLOR[st] || 'var(--c-text)' }}>{n}</div>
            <div style={s.statLabel}>{st}</div>
          </div>
        ))}
        {failed === 0 && rows.length > 0 && (
          <div style={s.stat}>
            <div style={{ ...s.statNum, color: '#22c55e' }}>100%</div>
            <div style={s.statLabel}>Delivered</div>
          </div>
        )}
      </div>

      {rows.length === 0 && (
        <div style={s.empty}>
          No notifications yet. They appear when the intercom agent contacts a resident.
        </div>
      )}

      {rows.length > 0 && (
        <table style={s.table}>
          <thead>
            <tr>
              {['Resident', 'Flat', 'Visitor', 'Channel', 'Status', 'Sent'].map(h => (
                <th key={h} style={s.th}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map(n => (
              <tr key={n.id}>
                <td style={s.td}>{n.resident_name || <span style={s.muted}>—</span>}</td>
                <td style={s.td}>{n.flat_number || <span style={s.muted}>—</span>}</td>
                <td style={s.td}>
                  {n.session_id
                    ? <Link to={`/session/${n.session_id}`} style={s.link}>{n.visitor_name || 'View session'}</Link>
                    : <span style={s.muted}>—</span>}
                </td>
                <td style={{ ...s.td, ...s.muted }}>{n.channel}</td>
                <td style={s.td}><span style={s.badge(n.status)}>{n.status}</span></td>
                <td style={{ ...s.td, ...s.muted }}>{fmt(n.created_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
