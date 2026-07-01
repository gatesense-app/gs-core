import { BrowserRouter, Routes, Route, Link } from 'react-router-dom'
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

export default function App() {
  return (
    <BrowserRouter>
      <nav style={nav}>
        <Link to="/" style={logo}>GateSense</Link>
        <Link to="/" style={navLink}>Dashboard</Link>
        <Link to="/kiosk" style={navLink}>Guard Kiosk</Link>
      </nav>
      <Routes>
        <Route path="/" element={<AdminDashboard />} />
        <Route path="/kiosk" element={<GuardKiosk />} />
        <Route path="/session/:id" element={<SessionDetail />} />
      </Routes>
    </BrowserRouter>
  )
}
