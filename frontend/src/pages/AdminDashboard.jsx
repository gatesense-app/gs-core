import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

const API = 'http://localhost:8000'

const STATUS_COLOR = {
  pending:            '#64748b',
  auto_approved:      '#22c55e',
  awaiting_resident:  '#f59e0b',
  approved:           '#22c55e',
  denied:             '#ef4444',
  escalated:          '#f97316',
  expired:            '#64748b',
}

const AGENT_COLOR = { gate: '#818cf8', delivery: '#34d399', intercom: '#f472b6' }

const s = {
  page: { padding: '32px 28px' },
  header: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 28 },
  title: { fontSize: 20, fontWeight: 700, color: 'var(--c-text)' },
  refresh: {
    padding: '7px 14px', borderRadius: 7, border: '1px solid var(--c-border)',
    background: 'transparent', color: 'var(--c-sub)', fontSize: 13,
  },
  empty: { color: 'var(--c-muted)', textAlign: 'center', marginTop: 80, fontSize: 15 },
  table: { width: '100%', borderCollapse: 'collapse' },
  th: { textAlign: 'left', fontSize: 12, color: 'var(--c-muted)', padding: '0 12px 10px', borderBottom: '1px solid var(--c-border)' },
  tr: { borderBottom: '1px solid var(--c-row-border)', cursor: 'pointer' },
  td: { padding: '14px 12px', fontSize: 14, color: 'var(--c-text)' },
  badge: (status) => ({
    display: 'inline-block', padding: '2px 9px', borderRadius: 99,
    fontSize: 12, fontWeight: 500,
    background: STATUS_COLOR[status] + '22',
    color: STATUS_COLOR[status],
    border: `1px solid ${STATUS_COLOR[status]}44`,
  }),
  agents: { display: 'flex', gap: 6, flexWrap: 'wrap' },
  agentChip: (agent) => ({
    fontSize: 11, padding: '2px 7px', borderRadius: 4,
    background: AGENT_COLOR[agent] + '22', color: AGENT_COLOR[agent],
  }),
  time: { fontSize: 12, color: '#475569' },
}

function fmt(iso) {
  if (!iso) return '—'
  return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

export default function AdminDashboard() {
  const [sessions, setSessions] = useState([])
  const [loading, setLoading] = useState(true)

  async function load() {
    try {
      const res = await fetch(`${API}/sessions`)
      setSessions((await res.json()).reverse())
    } catch { }
    setLoading(false)
  }

  useEffect(() => { load(); const t = setInterval(load, 5000); return () => clearInterval(t) }, [])

  return (
    <div style={s.page}>
      <div style={s.header}>
        <div style={s.title}>Visitor Sessions</div>
        <button style={s.refresh} onClick={load}>Refresh</button>
      </div>

      {loading && <div style={s.empty}>Loading...</div>}
      {!loading && sessions.length === 0 && (
        <div style={s.empty}>No sessions yet. <Link to="/kiosk" style={{ color: 'var(--c-accent)' }}>Submit a visitor</Link> to get started.</div>
      )}

      {sessions.length > 0 && (
        <table style={s.table}>
          <thead>
            <tr>
              {['Session', 'Visitor', 'Flat', 'Purpose', 'Agents', 'Status', 'Time'].map(h =>
                <th key={h} style={s.th}>{h}</th>
              )}
            </tr>
          </thead>
          <tbody>
            {sessions.map(sess => (
              <Link key={sess.session_id} to={`/session/${sess.session_id}`} style={{ display: 'contents' }}>
                <tr style={s.tr}>
                  <td style={{ ...s.td, fontFamily: 'monospace', color: 'var(--c-muted)', fontSize: 12 }}>
                    {sess.session_id}
                  </td>
                  <td style={{ ...s.td, color: 'var(--c-text)', fontWeight: 500 }}>{sess.visitor_name}</td>
                  <td style={s.td}>{sess.flat_number}</td>
                  <td style={{ ...s.td, color: 'var(--c-sub)' }}>{sess.purpose}</td>
                  <td style={s.td}>
                    <div style={s.agents}>
                      {[...new Set(sess.decision_trace.map(t => t.agent))].map(a =>
                        <span key={a} style={s.agentChip(a)}>{a}</span>
                      )}
                    </div>
                  </td>
                  <td style={s.td}><span style={s.badge(sess.status)}>{sess.status}</span></td>
                  <td style={{ ...s.td, ...s.time }}>{fmt(sess.entry_time)}</td>
                </tr>
              </Link>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
