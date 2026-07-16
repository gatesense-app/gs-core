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

// `contentType` / `responseType` exist for the CSV import (E3): it posts a raw
// text/csv body and downloads a text/csv template, so JSON isn't universal here.
// Both default to JSON, so every existing caller is unaffected.
export async function apiFetch(
  path,
  { method = 'GET', body, auth = true, contentType = 'application/json', responseType = 'json' } = {},
) {
  const headers = { 'Content-Type': contentType }
  if (auth) {
    const a = readAuth()
    if (a?.token) headers.Authorization = `Bearer ${a.token}`
  }
  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers,
    // A raw (non-JSON) body is already a string — stringifying it again would
    // wrap the whole CSV in quotes and escape every newline.
    body: body != null ? (contentType === 'application/json' ? JSON.stringify(body) : body) : undefined,
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
  return responseType === 'text' ? res.text() : res.json()
}
