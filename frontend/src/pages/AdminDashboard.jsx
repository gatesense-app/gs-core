import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { apiFetch } from '../api'
import { openSessionsSocket } from '../realtime'

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
  header: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 28, gap: 16 },
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
  time: { fontSize: 12, color: 'var(--c-muted)' },
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
      setSessions(await apiFetch('/sessions'))  // backend returns newest-first
    } catch { }
    setLoading(false)
  }

  // Insert or replace a session pushed over the WebSocket (newest first).
  function upsert(sess) {
    setSessions(prev => {
      const idx = prev.findIndex(x => x.session_id === sess.session_id)
      if (idx === -1) return [sess, ...prev]
      const next = [...prev]
      next[idx] = sess
      return next
    })
  }

  useEffect(() => {
    load()
    const stop = openSessionsSocket(msg => { if (msg.type === 'session_update') upsert(msg.session) })
    const t = setInterval(load, 15000)  // fallback in case the socket drops
    return () => { stop(); clearInterval(t) }
  }, [])

  return (
    <div style={s.page}>
      <div style={s.header}>
        <h1 className="page-title">Visitor Sessions</h1>
        <button className="btn btn--ghost" onClick={load}>Refresh</button>
      </div>

      {loading && <div style={s.empty}>Loading...</div>}
      {!loading && sessions.length === 0 && (
        <div style={s.empty}>No sessions yet. <Link to="/kiosk" style={{ color: 'var(--c-link)', fontWeight: 600 }}>Submit a visitor</Link> to get started.</div>
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
