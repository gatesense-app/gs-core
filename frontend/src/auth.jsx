import { createContext, useContext, useState } from 'react'
import { apiFetch, readAuth, writeAuth } from './api'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(() => readAuth())

  async function login(email, password) {
    const data = await apiFetch('/auth/login', {
      method: 'POST',
      auth: false,
      body: { email, password },
    })
    const authed = {
      token: data.access_token,
      role: data.role,
      society_id: data.society_id,
      full_name: data.full_name,
      email,
    }
    writeAuth(authed)
    setUser(authed)
    return authed
  }

  function logout() {
    writeAuth(null)
    setUser(null)
  }

  return (
    <AuthContext.Provider value={{ user, login, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  return useContext(AuthContext)
}
