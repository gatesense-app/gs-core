// Single place the frontend talks to the backend. Base URL is env-configurable
// (VITE_API_URL) so the same build works locally and on Railway.
export const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000'

const STORAGE_KEY = 'gs_auth'

export function readAuth() {
  const raw = localStorage.getItem(STORAGE_KEY)
  return raw ? JSON.parse(raw) : null
}

export function writeAuth(auth) {
  if (auth) localStorage.setItem(STORAGE_KEY, JSON.stringify(auth))
  else localStorage.removeItem(STORAGE_KEY)
}

export async function apiFetch(path, { method = 'GET', body, auth = true } = {}) {
  const headers = { 'Content-Type': 'application/json' }
  if (auth) {
    const a = readAuth()
    if (a?.token) headers.Authorization = `Bearer ${a.token}`
  }
  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers,
    body: body != null ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) {
    // The API returns a uniform {error: {code, message}}; fall back to older
    // shapes (and plain text) so a proxy/error page still surfaces something.
    let message
    let code
    try {
      const j = await res.json()
      message = j.error?.message ?? j.detail ?? JSON.stringify(j)
      code = j.error?.code
    } catch {
      message = await res.text()
    }
    const err = new Error(typeof message === 'string' ? message : JSON.stringify(message))
    err.status = res.status
    err.code = code
    throw err
  }
  if (res.status === 204) return null
  return res.json()
}
