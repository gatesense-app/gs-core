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
    let detail
    try {
      const j = await res.json()
      detail = j.detail ?? JSON.stringify(j)
    } catch {
      detail = await res.text()
    }
    const err = new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
    err.status = res.status
    throw err
  }
  if (res.status === 204) return null
  return res.json()
}
