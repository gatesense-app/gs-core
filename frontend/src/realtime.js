// Live session feed over WebSocket. The backend pushes {type, session} messages
// whenever a session is created or changes, so the dashboard / detail views update
// without polling. Auto-reconnects; returns a cleanup function.
import { API_BASE, readAuth } from './api'

export function openSessionsSocket(onUpdate) {
  const a = readAuth()
  if (!a?.token) return () => {}

  // http(s)://host -> ws(s)://host. Browsers can't set headers on a WS handshake,
  // so the JWT rides as a query param (the backend validates it there).
  const wsBase = API_BASE.replace(/^http/, 'ws')
  const url = `${wsBase}/ws/sessions?token=${encodeURIComponent(a.token)}`

  let ws
  let closed = false
  let retry

  function connect() {
    ws = new WebSocket(url)
    ws.onmessage = (e) => {
      try { onUpdate(JSON.parse(e.data)) } catch { /* ignore malformed frames */ }
    }
    ws.onclose = () => {
      if (!closed) retry = setTimeout(connect, 2000)  // reconnect with backoff
    }
    ws.onerror = () => { try { ws.close() } catch { /* no-op */ } }
  }
  connect()

  return () => {
    closed = true
    clearTimeout(retry)
    if (ws) { try { ws.close() } catch { /* no-op */ } }
  }
}
