import { useCallback, useEffect, useState } from 'react'
import { apiFetch } from '../api'
import { openSessionsSocket } from '../realtime'

const STATUS_COLOR = {
  pending: '#64748b', auto_approved: '#22c55e', awaiting_resident: '#f59e0b',
  approved: '#22c55e', denied: '#ef4444', escalated: '#f97316', expired: '#64748b',
}

const s = {
  page: { maxWidth: 780, margin: '0 auto', padding: '32px 24px' },
  h1: { fontSize: 22, fontWeight: 700, color: 'var(--c-text)' },
  flat: { fontSize: 13, color: 'var(--c-muted)', marginTop: 4, marginBottom: 28 },
  card: {
    background: 'var(--c-panel)', border: '1px solid var(--c-border)', borderRadius: 12,
    padding: 20, marginBottom: 20, boxShadow: 'var(--c-card-shadow)',
  },
  liveCard: {
    background: 'var(--c-panel)', border: '1px solid var(--c-accent-border)', borderRadius: 12,
    padding: 20, marginBottom: 20, boxShadow: '0 8px 24px -14px var(--c-accent)',
  },
  sectionTitle: {
    fontSize: 12, fontWeight: 700, color: 'var(--c-sub)', textTransform: 'uppercase',
    letterSpacing: '0.07em', marginBottom: 14,
  },
  visitor: { fontSize: 17, fontWeight: 700, color: 'var(--c-text)' },
  purpose: { fontSize: 13, color: 'var(--c-sub)', marginTop: 2, marginBottom: 14 },
  badge: (st) => ({
    display: 'inline-block', padding: '2px 9px', borderRadius: 99, fontSize: 12, fontWeight: 500,
    background: (STATUS_COLOR[st] || '#64748b') + '22',
    color: STATUS_COLOR[st] || '#64748b',
    border: `1px solid ${(STATUS_COLOR[st] || '#64748b')}44`,
  }),
  bubbleRow: (who) => ({
    display: 'flex', justifyContent: who === 'resident' ? 'flex-end' : 'flex-start', marginBottom: 8,
  }),
  bubble: (who) => ({
    maxWidth: '78%', padding: '8px 13px', borderRadius: 12, fontSize: 13, lineHeight: 1.5,
    whiteSpace: 'pre-wrap',
    background: who === 'resident' ? 'var(--c-accent-2)'
      : who === 'guard' ? 'rgba(16,185,129,0.14)' : 'var(--c-panel-alt)',
    color: who === 'resident' ? '#fff' : 'var(--c-text)',
  }),
  who: { fontSize: 10, color: 'var(--c-muted)', textTransform: 'uppercase', marginBottom: 3 },
  replyRow: { display: 'flex', gap: 8, marginTop: 14 },
  input: {
    flex: 1, padding: '10px 13px', borderRadius: 8, border: '1px solid var(--c-border)',
    background: 'var(--c-input-bg)', color: 'var(--c-text)', fontSize: 14, outline: 'none',
  },
  btn: {
    padding: '10px 18px', borderRadius: 8, border: 'none', background: 'var(--c-btn-bg)',
    color: 'var(--c-btn-text)', fontSize: 14, fontWeight: 700,
  },
  quickRow: { display: 'flex', gap: 8, marginTop: 10 },
  allow: {
    padding: '8px 16px', borderRadius: 8, border: '1px solid rgba(34,197,94,0.45)',
    background: 'rgba(34,197,94,0.12)', color: '#15803d', fontSize: 13, fontWeight: 700,
  },
  deny: {
    padding: '8px 16px', borderRadius: 8, border: '1px solid rgba(239,68,68,0.45)',
    background: 'rgba(239,68,68,0.12)', color: '#b91c1c', fontSize: 13, fontWeight: 700,
  },
  // rules
  label: { display: 'block', fontSize: 13, color: 'var(--c-sub)', marginBottom: 6 },
  chips: { display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 10 },
  chip: {
    display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 12, padding: '4px 10px',
    borderRadius: 99, background: 'var(--c-accent-bg)', color: 'var(--c-accent-soft)',
    border: '1px solid var(--c-accent-border)',
  },
  x: { cursor: 'pointer', fontWeight: 700, lineHeight: 1, opacity: 0.7 },
  addRow: { display: 'flex', gap: 8, marginBottom: 18 },
  check: { display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, color: 'var(--c-text)', marginBottom: 10 },
  time: {
    padding: '7px 10px', borderRadius: 8, border: '1px solid var(--c-border)',
    background: 'var(--c-input-bg)', color: 'var(--c-text)', fontSize: 13, outline: 'none',
  },
  row: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 0', borderBottom: '1px solid var(--c-row-border)' },
  muted: { fontSize: 13, color: 'var(--c-muted)' },
  saved: { fontSize: 12, color: 'var(--c-ok)', marginLeft: 10 },
  err: { fontSize: 13, color: 'var(--c-error)', marginTop: 8 },
}

function fmt(iso) {
  if (!iso) return ''
  return new Date(iso).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

// standing_rules is a list of dicts; the UI edits the two shapes the agents read:
//   {type:'always_allow', match:'Swiggy'} and {type:'never_allow', after:'21:00'}
function rulesToForm(rules = []) {
  return {
    alwaysAllow: rules.filter(r => r.type === 'always_allow' && r.match).map(r => r.match),
    neverAfter: (rules.find(r => r.type === 'never_allow') || {}).after || '',
  }
}
function formToRules({ alwaysAllow, neverAfter }) {
  const out = alwaysAllow.map(match => ({ type: 'always_allow', match }))
  if (neverAfter) out.push({ type: 'never_allow', after: neverAfter })
  return out
}

export default function Portal() {
  const [me, setMe] = useState(null)
  const [sessions, setSessions] = useState([])
  const [form, setForm] = useState({ alwaysAllow: [], neverAfter: '' })
  const [prefs, setPrefs] = useState({})
  const [newRule, setNewRule] = useState('')
  const [reply, setReply] = useState({})
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState('')

  const loadSessions = useCallback(async () => {
    try { setSessions(await apiFetch('/portal/sessions')) } catch { /* surfaced on next poll */ }
  }, [])

  useEffect(() => {
    (async () => {
      try {
        const profile = await apiFetch('/portal/me')
        setMe(profile)
        setForm(rulesToForm(profile.standing_rules))
        setPrefs(profile.delivery_preferences || {})
      } catch (e) { setError(e.message) }
    })()
    loadSessions()
    const stop = openSessionsSocket(msg => {
      // The backend only sends this resident their own flat's sessions.
      if (msg.type === 'session_update') {
        setSessions(prev => {
          const i = prev.findIndex(x => x.session_id === msg.session.session_id)
          if (i === -1) return [msg.session, ...prev]
          const next = [...prev]; next[i] = msg.session; return next
        })
      }
    })
    const t = setInterval(loadSessions, 15000)  // fallback if the socket drops
    return () => { stop(); clearInterval(t) }
  }, [loadSessions])

  async function send(id, text) {
    if (!text.trim()) return
    setError('')
    try {
      const updated = await apiFetch(`/sessions/${id}/reply`, { method: 'POST', body: { reply: text } })
      setSessions(prev => prev.map(x => (x.session_id === id ? updated : x)))
      setReply(r => ({ ...r, [id]: '' }))
    } catch (e) { setError(e.message) }
  }

  async function saveRules() {
    setSaving(true); setSaved(false); setError('')
    try {
      const updated = await apiFetch('/portal/rules', {
        method: 'PATCH',
        body: { standing_rules: formToRules(form), delivery_preferences: prefs },
      })
      setMe(updated)
      setForm(rulesToForm(updated.standing_rules))
      setPrefs(updated.delivery_preferences || {})
      setSaved(true)
    } catch (e) { setError(e.message) }
    setSaving(false)
  }

  function addRule() {
    const v = newRule.trim()
    if (!v || form.alwaysAllow.includes(v)) return
    setForm(f => ({ ...f, alwaysAllow: [...f.alwaysAllow, v] }))
    setNewRule('')
  }

  if (!me && !error) return <div style={{ padding: 40, color: 'var(--c-muted)' }}>Loading...</div>

  const awaiting = sessions.filter(x => x.status === 'awaiting_resident')
  const recent = sessions.filter(x => x.status !== 'awaiting_resident').slice(0, 10)

  return (
    <div style={s.page}>
      <div style={s.h1}>Hi{me?.name ? `, ${me.name.split(' ')[0]}` : ''}</div>
      <div style={s.flat}>{me ? `Flat ${me.flat_number}` : ''}</div>
      {error && <div style={s.err}>{error}</div>}

      {/* Visitors waiting on this resident */}
      {awaiting.length === 0 && (
        <div style={s.card}>
          <div style={s.sectionTitle}>At your gate</div>
          <div style={s.muted}>No one is waiting right now. You&apos;ll see visitors here the moment they arrive.</div>
        </div>
      )}
      {awaiting.map(sess => (
        <div key={sess.session_id} style={s.liveCard}>
          <div style={s.sectionTitle}>Waiting at your gate</div>
          <div style={s.visitor}>{sess.visitor_name}</div>
          <div style={s.purpose}>{sess.purpose} — {sess.purpose_detail}</div>

          {(sess.conversation_history || []).map((turn, i) => (
            <div key={i} style={s.bubbleRow(turn.speaker)}>
              <div>
                <div style={s.who}>{turn.speaker}</div>
                <div style={s.bubble(turn.speaker)}>{turn.message}</div>
              </div>
            </div>
          ))}

          <form onSubmit={e => { e.preventDefault(); send(sess.session_id, reply[sess.session_id] || '') }} style={s.replyRow}>
            <input
              style={s.input}
              value={reply[sess.session_id] || ''}
              onChange={e => setReply(r => ({ ...r, [sess.session_id]: e.target.value }))}
              placeholder="Reply, or ask a question..."
            />
            <button style={s.btn}>Send</button>
          </form>
          <div style={s.quickRow}>
            <button style={s.allow} onClick={() => send(sess.session_id, 'ALLOW')}>Allow</button>
            <button style={s.deny} onClick={() => send(sess.session_id, 'DENY')}>Deny</button>
          </div>
        </div>
      ))}

      {/* Standing rules */}
      <div style={s.card}>
        <div style={s.sectionTitle}>Standing rules</div>

        <label style={s.label}>Always allow these visitors</label>
        <div style={s.chips}>
          {form.alwaysAllow.length === 0 && <span style={s.muted}>None yet</span>}
          {form.alwaysAllow.map(r => (
            <span key={r} style={s.chip}>
              {r}
              <span
                style={s.x}
                role="button"
                tabIndex={0}
                aria-label={`Remove ${r}`}
                onClick={() => setForm(f => ({ ...f, alwaysAllow: f.alwaysAllow.filter(x => x !== r) }))}
              >×</span>
            </span>
          ))}
        </div>
        <div style={s.addRow}>
          <input
            style={s.input}
            value={newRule}
            onChange={e => setNewRule(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); addRule() } }}
            placeholder="e.g. Swiggy"
          />
          <button type="button" style={s.btn} onClick={addRule}>Add</button>
        </div>

        <label style={s.label}>Never allow visitors after</label>
        <div style={s.addRow}>
          <input
            type="time"
            style={s.time}
            value={form.neverAfter}
            onChange={e => setForm(f => ({ ...f, neverAfter: e.target.value }))}
          />
          {form.neverAfter && (
            <button type="button" style={{ ...s.btn, background: 'transparent', color: 'var(--c-sub)', border: '1px solid var(--c-border)' }}
              onClick={() => setForm(f => ({ ...f, neverAfter: '' }))}>Clear</button>
          )}
        </div>

        <div style={s.sectionTitle}>Deliveries</div>
        <label style={s.check}>
          <input
            type="checkbox"
            checked={!!prefs.auto_log_daytime}
            onChange={e => setPrefs(p => ({ ...p, auto_log_daytime: e.target.checked }))}
          />
          Auto-approve routine daytime deliveries
        </label>
        <label style={s.check}>
          <input
            type="checkbox"
            checked={!!prefs.notify_after_hours}
            onChange={e => setPrefs(p => ({ ...p, notify_after_hours: e.target.checked }))}
          />
          Always ask me about after-hours deliveries
        </label>

        <div style={{ marginTop: 16 }}>
          <button style={s.btn} onClick={saveRules} disabled={saving}>
            {saving ? 'Saving...' : 'Save rules'}
          </button>
          {saved && <span style={s.saved}>Saved</span>}
        </div>
      </div>

      {/* Recent visitors */}
      <div style={s.card}>
        <div style={s.sectionTitle}>Recent visitors</div>
        {recent.length === 0 && <div style={s.muted}>No visitors yet.</div>}
        {recent.map(sess => (
          <div key={sess.session_id} style={s.row}>
            <div>
              <div style={{ fontSize: 14, color: 'var(--c-text)', fontWeight: 500 }}>{sess.visitor_name}</div>
              <div style={s.muted}>{sess.purpose} · {fmt(sess.entry_time)}</div>
            </div>
            <span style={s.badge(sess.status)}>{sess.status}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
