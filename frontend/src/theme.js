// Light/dark theme via a data-theme attribute on <html>, persisted in
// localStorage. Light is the default (matches the marketing landing page).
const KEY = 'gs_theme'

export function getTheme() {
  return localStorage.getItem(KEY) || 'light'
}

export function applyTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme)
  localStorage.setItem(KEY, theme)
}

export function initTheme() {
  applyTheme(getTheme())
}

export function toggleTheme() {
  const next = getTheme() === 'dark' ? 'light' : 'dark'
  applyTheme(next)
  return next
}
