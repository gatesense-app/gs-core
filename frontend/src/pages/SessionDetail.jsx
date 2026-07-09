import { useEffect, useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { apiFetch } from '../api'
import { openSessionsSocket } from '../realtime'

const AGENT_COLOR = { gate: '#818cf8', delivery: '#34d399', intercom: '#f472b6' }
const STATUS_COLOR = {
  pending: '#64748b', auto_approved: '#22c55e', awaiting_resident: '#f59e0b',
  approved: '#22c55e', denied: '#ef4444', escalated: '#f97316', expired: '#64748b',
}

const s = {
  page: { maxWidth: 860, margin: '0 auto', padding: '32px 24px' },
  back: { fontSize: 13, color: 'var(--c-muted)', marginBottom: 24, display: 'block' },
  card: { background: 'var(--c-panel)', borderRadius: 12, border: '1px solid var(--c-border)', padding: 24, marginBottom: 24, boxShadow: 'var(--c-card-shadow)' },
  row: { display: 'flex', gap: 32, flexWrap: 'wrap' },
  kv: { marginBottom: 16 },
  key: { fontSize: 11, color: 'var(--c-muted)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 4 },
  val: { fontSize: 15, color: 'var(--c-text)', fontWeight: 500 },
  sectionTitle: { fontSize: 13, fontWeight: 600, color: 'var(--c-sub)', textTransform: 'uppercase', letterSpacing: '0.07em', marginBottom: 16 },
  badge: (status) => ({
    display: 'inline-block', padding: '3px 10px', borderRadius: 99, fontSize: 13, fontWeight: 500,
    background: STATUS_COLOR[status] + '22', color: STATUS_COLOR[status],
    border: `1px solid ${STATUS_COLOR[status]}44`,
  }),

  // Trace timeline
  timeline: { position: 'relative', paddingLeft: 28 },
  line: { position: 'absolute', left: 9, top: 8, bottom: 8, width: 2, background: 'var(--c-border)' },
  traceItem: { position: 'relative', marginBottom: 24 },
  dot: (agent) => ({
    position: 'absolute', left: -24, top: 4,
    width: 12, height: 12, borderRadius: '50%',
    background: AGENT_COLOR[agent] || 'var(--c-muted)',
    border: '2px solid var(--c-bg)',
  }),
  agentLabel: (agent) => ({
    display: 'inline-block', fontSize: 11, fontWeight: 600,
    color: AGENT_COLOR[agent] || 'var(--c-muted)',
    textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 6,
  }),
  action: { fontSize: 14, color: 'var(--c-text)', fontWeight: 500, marginBottom: 6 },
  reasoning: { fontSize: 13, color: 'var(--c-sub)', lineHeight: 1.6, marginBottom: 8 },
  tools: { display: 'flex', gap: 6, flexWrap: 'wrap' },
  toolChip: {
    fontSize: 11, padding: '2px 8px', borderRadius: 4,
    background: 'var(--c-panel-alt)', color: 'var(--c-muted)', fontFamily: 'monospace',
  },
  ts: { fontSize: 11, color: 'var(--c-muted)', marginTop: 6 },

  // Reply box
  replyBox: { display: 'flex', gap: 10, marginTop: 16 },
  replyInput: {
    flex: 1, padding: '10px 14px', borderRadius: 8,
    border: '1px solid var(--c-border)', background: 'var(--c-input-bg)',
    color: 'var(--c-text)', fontSize: 14, outline: 'none',
  },
  replyBtn: {
    padding: '10px 20px', borderRadius: 8, border: 'none',
    background: 'var(--c-btn-bg)', color: 'var(--c-btn-text)', fontSize: 14, fontWeight: 700,
  },

  // Conversation
  convItem: (speaker) => ({
    display: 'flex', justifyContent: speaker === 'resident' ? 'flex-end' : 'flex-start',
    marginBottom: 10,
  }),
  bubble: (speaker) => ({
    maxWidth: '75%', padding: '8px 14px', borderRadius: 12, fontSize: 13, lineHeight: 1.5,
    background: speaker === 'resident' ? 'var(--c-accent-2)' : speaker === 'guard' ? 'rgba(16,185,129,0.14)' : 'var(--c-panel-alt)',
    color: speaker === 'resident' ? '#fff' : 'var(--c-text)',
  }),
  speakerLabel: { fontSize: 10, color: 'var(--c-muted)', marginBottom: 4, textTransform: 'uppercase' },
}

function fmt(iso) {
  if (!iso) return ''
  return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

export default function SessionDetail() {
  const { id } = useParams()
  const [session, setSession] = useState(null)
  const [reply, setReply] = useState('')
  const [sending, setSending] = useState(false)

  async function load() {
    try {
      setSession(await apiFetch(`/sessions/${id}`))
    } catch { /* not found / not authorized */ }
  }

  useEffect(() => {
    load()
    const stop = openSessionsSocket(msg => {
      if (msg.type === 'session_update' && msg.session.session_id === id) setSession(msg.session)
    })
    const t = setInterval(load, 10000)  // fallback in case the socket drops
    return () => { stop(); clearInterval(t) }
  }, [id])

  async function sendReply(e) {
    e.preventDefault()
    if (!reply.trim()) return
    setSending(true)
    try {
      await apiFetch(`/sessions/${id}/reply`, { method: 'POST', body: { reply } })
    } catch { /* surfaced on next poll */ }
    setReply('')
    setSending(false)
    load()
  }

  if (!session) return <div style={{ padding: 40, color: 'var(--c-muted)' }}>Loading...</div>

  const isResolved = ['auto_approved', 'approved', 'denied', 'escalated', 'expired'].includes(session.status)

  return (
    <div style={s.page}>
      <Link to="/dashboard" style={s.back}>← Back to Dashboard</Link>

      {/* Session header */}
      <div style={s.card}>
        <div style={s.row}>
          <div style={s.kv}>
            <div style={s.key}>Session</div>
            <div style={{ ...s.val, fontFamily: 'monospace', fontSize: 13 }}>{session.session_id}</div>
          </div>
          <div style={s.kv}>
            <div style={s.key}>Visitor</div>
            <div style={s.val}>{session.visitor_name}</div>
          </div>
          <div style={s.kv}>
            <div style={s.key}>Flat</div>
            <div style={s.val}>{session.flat_number}</div>
          </div>
          <div style={s.kv}>
            <div style={s.key}>Purpose</div>
            <div style={s.val}>{session.purpose} — {session.purpose_detail}</div>
          </div>
          <div style={s.kv}>
            <div style={s.key}>Status</div>
            <div><span style={s.badge(session.status)}>{session.status}</span></div>
          </div>
          {session.resolved_by && (
            <div style={s.kv}>
              <div style={s.key}>Resolved by</div>
              <div style={s.val}>{session.resolved_by}</div>
            </div>
          )}
        </div>
      </div>

      {/* Decision trace timeline */}
      <div style={s.card}>
        <div style={s.sectionTitle}>Decision Trace</div>
        {session.decision_trace.length === 0 && (
          <div style={{ color: 'var(--c-muted)', fontSize: 13 }}>No trace entries yet.</div>
        )}
        <div style={s.timeline}>
          <div style={s.line} />
          {session.decision_trace.map((entry, i) => (
            <div key={i} style={s.traceItem}>
              <div style={s.dot(entry.agent)} />
              <div style={s.agentLabel(entry.agent)}>{entry.agent} agent</div>
              <div style={s.action}>{entry.action}</div>
              <div style={s.reasoning}>{entry.reasoning}</div>
              {entry.tool_calls.length > 0 && (
                <div style={s.tools}>
                  {entry.tool_calls.map(t => <span key={t} style={s.toolChip}>{t}</span>)}
                </div>
              )}
              <div style={s.ts}>{fmt(entry.timestamp)}</div>
            </div>
          ))}
        </div>
      </div>

      {/* Conversation (intercom sessions) */}
      {session.conversation_history.length > 0 && (
        <div style={s.card}>
          <div style={s.sectionTitle}>Conversation</div>
          {session.conversation_history.map((turn, i) => (
            <div key={i} style={s.convItem(turn.speaker)}>
              <div>
                <div style={s.speakerLabel}>{turn.speaker}</div>
                <div style={s.bubble(turn.speaker)}>{turn.message}</div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Resident reply input */}
      {session.status === 'awaiting_resident' && (
        <div style={s.card}>
          <div style={s.sectionTitle}>Resident Reply</div>
          <div style={{ fontSize: 13, color: 'var(--c-sub)', marginBottom: 12 }}>
            Simulate the resident's response (or guard clarification if prompted)
          </div>
          <form onSubmit={sendReply} style={s.replyBox}>
            <input
              style={s.replyInput}
              value={reply}
              onChange={e => setReply(e.target.value)}
              placeholder="Type ALLOW, DENY, or a question..."
            />
            <button style={s.replyBtn} disabled={sending}>
              {sending ? '...' : 'Send'}
            </button>
          </form>
        </div>
      )}

      {isResolved && (
        <div style={{ textAlign: 'center', color: 'var(--c-muted)', fontSize: 13, marginTop: 8 }}>
          Session resolved at {fmt(session.resolved_at)}
        </div>
      )}
    </div>
  )
}
