import { BrowserRouter, Routes, Route, Link, useLocation } from 'react-router-dom'
import Landing from './pages/Landing'
import AdminDashboard from './pages/AdminDashboard'
import GuardKiosk from './pages/GuardKiosk'
import SessionDetail from './pages/SessionDetail'

const nav = {
  display: 'flex', alignItems: 'center', gap: 24,
  padding: '14px 28px', borderBottom: '1px solid #1e2130',
  background: '#0a0c12',
}
const logo = { fontWeight: 700, fontSize: 18, color: '#a78bfa', letterSpacing: '-0.5px' }
const navLink = { fontSize: 14, color: '#94a3b8' }

function AppNav() {
  const { pathname } = useLocation()
  if (pathname === '/') return null

  return (
    <nav style={nav}>
      <Link to="/" style={logo}>GateSense</Link>
      <Link to="/dashboard" style={navLink}>Dashboard</Link>
      <Link to="/kiosk" style={navLink}>Guard Kiosk</Link>
    </nav>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <AppNav />
      <Routes>
        <Route path="/" element={<Landing />} />
        <Route path="/dashboard" element={<AdminDashboard />} />
        <Route path="/kiosk" element={<GuardKiosk />} />
        <Route path="/session/:id" element={<SessionDetail />} />
      </Routes>
    </BrowserRouter>
  )
}
