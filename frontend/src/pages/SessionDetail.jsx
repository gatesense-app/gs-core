import { useEffect, useState } from 'react'
import { useParams, Link } from 'react-router-dom'

const API = 'http://localhost:8000'

const AGENT_COLOR = { gate: '#818cf8', delivery: '#34d399', intercom: '#f472b6' }
const STATUS_COLOR = {
  pending: '#64748b', auto_approved: '#22c55e', awaiting_resident: '#f59e0b',
  approved: '#22c55e', denied: '#ef4444', escalated: '#f97316', expired: '#64748b',
}

const s = {
  page: { maxWidth: 860, margin: '0 auto', padding: '32px 24px' },
  back: { fontSize: 13, color: '#64748b', marginBottom: 24, display: 'block' },
  card: { background: '#131620', borderRadius: 12, border: '1px solid #1e2130', padding: 24, marginBottom: 24 },
  row: { display: 'flex', gap: 32, flexWrap: 'wrap' },
  kv: { marginBottom: 16 },
  key: { fontSize: 11, color: '#475569', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 4 },
  val: { fontSize: 15, color: '#e2e8f0', fontWeight: 500 },
  sectionTitle: { fontSize: 13, fontWeight: 600, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.07em', marginBottom: 16 },
  badge: (status) => ({
    display: 'inline-block', padding: '3px 10px', borderRadius: 99, fontSize: 13, fontWeight: 500,
    background: STATUS_COLOR[status] + '22', color: STATUS_COLOR[status],
    border: `1px solid ${STATUS_COLOR[status]}44`,
  }),

  // Trace timeline
  timeline: { position: 'relative', paddingLeft: 28 },
  line: { position: 'absolute', left: 9, top: 8, bottom: 8, width: 2, background: '#1e2130' },
  traceItem: { position: 'relative', marginBottom: 24 },
  dot: (agent) => ({
    position: 'absolute', left: -24, top: 4,
    width: 12, height: 12, borderRadius: '50%',
    background: AGENT_COLOR[agent] || '#475569',
    border: '2px solid #0f1117',
  }),
  agentLabel: (agent) => ({
    display: 'inline-block', fontSize: 11, fontWeight: 600,
    color: AGENT_COLOR[agent] || '#64748b',
    textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 6,
  }),
  action: { fontSize: 14, color: '#f1f5f9', fontWeight: 500, marginBottom: 6 },
  reasoning: { fontSize: 13, color: '#94a3b8', lineHeight: 1.6, marginBottom: 8 },
  tools: { display: 'flex', gap: 6, flexWrap: 'wrap' },
  toolChip: {
    fontSize: 11, padding: '2px 8px', borderRadius: 4,
    background: '#1e2130', color: '#64748b', fontFamily: 'monospace',
  },
  ts: { fontSize: 11, color: '#334155', marginTop: 6 },

  // Reply box
  replyBox: { display: 'flex', gap: 10, marginTop: 16 },
  replyInput: {
    flex: 1, padding: '10px 14px', borderRadius: 8,
    border: '1px solid #1e2130', background: '#0f1117',
    color: '#e2e8f0', fontSize: 14, outline: 'none',
  },
  replyBtn: {
    padding: '10px 20px', borderRadius: 8, border: 'none',
    background: '#7c3aed', color: '#fff', fontSize: 14, fontWeight: 600,
  },

  // Conversation
  convItem: (speaker) => ({
    display: 'flex', justifyContent: speaker === 'resident' ? 'flex-end' : 'flex-start',
    marginBottom: 10,
  }),
  bubble: (speaker) => ({
    maxWidth: '75%', padding: '8px 14px', borderRadius: 12, fontSize: 13, lineHeight: 1.5,
    background: speaker === 'resident' ? '#7c3aed' : speaker === 'agent' ? '#1e2130' : '#0f2a1a',
    color: speaker === 'resident' ? '#fff' : '#e2e8f0',
  }),
  speakerLabel: { fontSize: 10, color: '#475569', marginBottom: 4, textTransform: 'uppercase' },
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
    const res = await fetch(`${API}/sessions/${id}`)
    if (res.ok) setSession(await res.json())
  }

  useEffect(() => {
    load()
    const t = setInterval(load, 3000)
    return () => clearInterval(t)
  }, [id])

  async function sendReply(e) {
    e.preventDefault()
    if (!reply.trim()) return
    setSending(true)
    await fetch(`${API}/sessions/${id}/reply`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reply }),
    })
    setReply('')
    setSending(false)
    load()
  }

  if (!session) return <div style={{ padding: 40, color: '#475569' }}>Loading...</div>

  const isResolved = ['auto_approved', 'approved', 'denied', 'escalated', 'expired'].includes(session.status)

  return (
    <div style={s.page}>
      <Link to="/" style={s.back}>← Back to Dashboard</Link>

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
          <div style={{ color: '#475569', fontSize: 13 }}>No trace entries yet.</div>
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
          <div style={{ fontSize: 13, color: '#64748b', marginBottom: 12 }}>
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
        <div style={{ textAlign: 'center', color: '#475569', fontSize: 13, marginTop: 8 }}>
          Session resolved at {fmt(session.resolved_at)}
        </div>
      )}
    </div>
  )
}
