import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../auth'
import { ui, colors } from '../ui'

export const ROLE_HOME = {
  platform_admin: '/societies',
  society_admin: '/residents',
  guard: '/kiosk',
  resident: '/portal',
}

export default function Login() {
  const { login } = useAuth()
  const nav = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  async function submit(e) {
    e.preventDefault()
    setLoading(true)
    setError('')
    try {
      const authed = await login(email.trim(), password)
      nav(ROLE_HOME[authed.role] || '/', { replace: true })
    } catch (err) {
      setError(err.status === 401 ? 'Invalid email or password' : err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={ui.narrow}>
      <h1 className="page-title" style={{ letterSpacing: '-0.5px', marginBottom: 6 }}>
        <span style={{ color: colors.accentLight }}>GateSense</span> sign in
      </h1>
      <div style={ui.sub}>Society visitor management</div>
      <form onSubmit={submit}>
        <label style={ui.label} htmlFor="login-email">Email</label>
        <input
          id="login-email"
          className="input"
          style={ui.fieldGap}
          type="email"
          name="email"
          autoComplete="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
          placeholder="admin@green.gatesense.in"
          autoFocus
        />
        <label style={ui.label} htmlFor="login-password">Password</label>
        <input
          id="login-password"
          className="input"
          style={ui.fieldGap}
          type="password"
          name="password"
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
          placeholder="••••••••"
        />
        <button className="btn btn--primary btn--block" disabled={loading}>
          {loading ? 'Signing in…' : 'Sign in'}
        </button>
        {error && <div style={ui.error}>{error}</div>}
      </form>
      <div style={{ ...ui.sub, marginTop: 24, fontSize: 12 }}>
        Demo: platform@gatesense.in · admin@green.gatesense.in · guard1@green.gatesense.in — password123
      </div>
    </div>
  )
}
