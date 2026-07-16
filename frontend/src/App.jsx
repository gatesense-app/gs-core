import { BrowserRouter, Routes, Route, Link, Navigate, useLocation } from 'react-router-dom'
import { AuthProvider, useAuth } from './auth'
import { ROLE_HOME } from './pages/Login'
import { colors } from './ui'
import logoUrl from './assets/logo/gs-logo-horizontal.png'
import Landing from './pages/Landing'
import Login from './pages/Login'
import Societies from './pages/Societies'
import Residents from './pages/Residents'
import Users from './pages/Users'
import AdminDashboard from './pages/AdminDashboard'
import GuardKiosk from './pages/GuardKiosk'
import SessionDetail from './pages/SessionDetail'
import Portal from './pages/Portal'
import Notifications from './pages/Notifications'
import Layout from './pages/Layout'
import FlatDetail from './pages/FlatDetail'
import ImportResidents from './pages/ImportResidents'

const logoLink = { display: 'flex', alignItems: 'center' }
const logoImg = { height: 26, width: 'auto', display: 'block' }
const navLink = { fontSize: 14, color: colors.sub, textDecoration: 'none' }

// Which nav links each role sees.
const LINKS = {
  platform_admin: [['/societies', 'Societies'], ['/layout', 'Layout'], ['/residents', 'Residents'], ['/users', 'Users'], ['/dashboard', 'Sessions'], ['/notifications', 'Notifications']],
  society_admin: [['/layout', 'Layout'], ['/residents', 'Residents'], ['/users', 'Users'], ['/dashboard', 'Sessions'], ['/notifications', 'Notifications'], ['/kiosk', 'Kiosk']],
  guard: [['/kiosk', 'Guard Kiosk']],
  resident: [['/portal', 'Home']],
}

function AppNav() {
  const { user, logout } = useAuth()
  const { pathname } = useLocation()
  if (pathname === '/' || pathname === '/login') return null

  return (
    <nav className="app-nav">
      <Link to="/home" style={logoLink}><img src={logoUrl} alt="GateSense" style={logoImg} /></Link>
      {(LINKS[user?.role] || []).map(([to, label]) => (
        <Link
          key={to}
          to={to}
          aria-current={pathname === to ? 'page' : undefined}
          style={pathname === to ? { ...navLink, color: colors.text, fontWeight: 600 } : navLink}
        >{label}</Link>
      ))}
      <div className="app-nav__right">
        {user && <span className="app-nav__user">{user.email} · {user.role}</span>}
        {user && <button onClick={logout} className="btn btn--ghost btn--sm" style={{ border: 'none' }}>Sign out</button>}
      </div>
    </nav>
  )
}

function Protected({ roles, children }) {
  const { user } = useAuth()
  const loc = useLocation()
  if (!user) return <Navigate to="/login" replace state={{ from: loc.pathname }} />
  if (roles && !roles.includes(user.role)) {
    return <div style={{ maxWidth: 600, margin: '80px auto', color: colors.sub, textAlign: 'center' }}>
      You don’t have access to this page.
    </div>
  }
  return children
}

function RoleHome() {
  const { user } = useAuth()
  if (!user) return <Navigate to="/login" replace />
  return <Navigate to={ROLE_HOME[user.role] || '/login'} replace />
}

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <AppNav />
        <Routes>
          <Route path="/" element={<Landing />} />
          <Route path="/login" element={<Login />} />
          <Route path="/home" element={<RoleHome />} />
          <Route path="/societies" element={<Protected roles={['platform_admin']}><Societies /></Protected>} />
          <Route path="/layout" element={<Protected roles={['platform_admin', 'society_admin']}><Layout /></Protected>} />
          <Route path="/flat/:id" element={<Protected roles={['platform_admin', 'society_admin']}><FlatDetail /></Protected>} />
          <Route path="/import" element={<Protected roles={['platform_admin', 'society_admin']}><ImportResidents /></Protected>} />
          <Route path="/residents" element={<Protected roles={['platform_admin', 'society_admin']}><Residents /></Protected>} />
          <Route path="/users" element={<Protected roles={['platform_admin', 'society_admin']}><Users /></Protected>} />
          <Route path="/dashboard" element={<Protected roles={['platform_admin', 'society_admin']}><AdminDashboard /></Protected>} />
          <Route path="/notifications" element={<Protected roles={['platform_admin', 'society_admin']}><Notifications /></Protected>} />
          <Route path="/kiosk" element={<Protected roles={['platform_admin', 'society_admin', 'guard']}><GuardKiosk /></Protected>} />
          <Route path="/session/:id" element={<Protected><SessionDetail /></Protected>} />
          <Route path="/portal" element={<Protected roles={['resident']}><Portal /></Protected>} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  )
}
