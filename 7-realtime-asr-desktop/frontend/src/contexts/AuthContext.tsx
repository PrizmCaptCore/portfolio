'use client'

import React, { createContext, useContext, useEffect, useState, useCallback } from 'react'
import { load } from '@tauri-apps/plugin-store'
import { listen } from '@tauri-apps/api/event'
import * as authService from '@/services/authService'
import type { UserInfo, BillingInfo, Tier } from '@/services/authService'
import {
  AUTH_LOGOUT_EVENT,
  AUTH_TOKEN_REFRESHED_EVENT,
  ensureFreshAccessToken,
} from '@/services/apiClient'

const STORE_FILE = 'auth.json'
const KEY_ACCESS = 'access_token'
const KEY_REFRESH = 'refresh_token'

interface AuthContextType {
  isAuthenticated: boolean
  isLoading: boolean
  isBillingLoading: boolean
  user: UserInfo | null
  accessToken: string | null
  billing: BillingInfo | null
  isPaid: boolean
  isTeamPlan: boolean
  effectiveTier: Tier
  login: (email: string, password: string) => Promise<void>
  logout: () => Promise<void>
}

const AuthContext = createContext<AuthContextType | undefined>(undefined)

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [isAuthenticated, setIsAuthenticated] = useState(false)
  const [isLoading, setIsLoading] = useState(true)
  const [isBillingLoading, setIsBillingLoading] = useState(false)
  const [user, setUser] = useState<UserInfo | null>(null)
  const [accessToken, setAccessToken] = useState<string | null>(null)
  const [billing, setBilling] = useState<BillingInfo | null>(null)

  // On mount: restore tokens from store and validate
  useEffect(() => {
    const restore = async () => {
      try {
        const store = await load(STORE_FILE, { autoSave: true, defaults: {} })
        const access = await store.get<string>(KEY_ACCESS)
        const refresh = await store.get<string>(KEY_REFRESH)

        if (!access || !refresh) {
          setIsLoading(false)
          return
        }

        // Try to verify the access token
        const valid = await authService.verifyToken(access)
        if (valid) {
          setAccessToken(access)
          setIsAuthenticated(true)
          authService.getCurrentUser(access).then(setUser).catch(() => {})
          setIsBillingLoading(true)
          authService.getBillingInfo(access).then(setBilling).catch(() => {}).finally(() => setIsBillingLoading(false))
        } else {
          // Try to refresh
          try {
            const { access: newAccess } = await authService.refreshToken(refresh)
            await store.set(KEY_ACCESS, newAccess)
            setAccessToken(newAccess)
            setIsAuthenticated(true)
            authService.getCurrentUser(newAccess).then(setUser).catch(() => {})
            setIsBillingLoading(true)
            authService.getBillingInfo(newAccess).then(setBilling).catch(() => {}).finally(() => setIsBillingLoading(false))
          } catch {
            // Refresh failed — clear stored tokens
            await store.delete(KEY_ACCESS)
            await store.delete(KEY_REFRESH)
          }
        }
      } catch (e) {
        console.error('[AuthContext] Failed to restore session:', e)
      } finally {
        setIsLoading(false)
      }
    }

    restore()
  }, [])

  const login = useCallback(async (email: string, password: string) => {
    const tokens = await authService.login(email, password)
    const store = await load(STORE_FILE, { autoSave: true, defaults: {} })
    await store.set(KEY_ACCESS, tokens.access)
    await store.set(KEY_REFRESH, tokens.refresh)
    setAccessToken(tokens.access)
    setIsAuthenticated(true)
    authService.getCurrentUser(tokens.access).then(setUser).catch(() => {})
    setIsBillingLoading(true)
    authService.getBillingInfo(tokens.access).then(setBilling).catch(() => {}).finally(() => setIsBillingLoading(false))
  }, [])

  const logout = useCallback(async () => {
    try {
      const store = await load(STORE_FILE, { autoSave: true, defaults: {} })
      const refresh = await store.get<string>(KEY_REFRESH)
      if (refresh) await authService.logout(refresh)
      await store.delete(KEY_ACCESS)
      await store.delete(KEY_REFRESH)
    } catch (e) {
      console.error('[AuthContext] Logout error:', e)
    } finally {
      setAccessToken(null)
      setIsAuthenticated(false)
      setUser(null)
      setBilling(null)
      setIsBillingLoading(false)
    }
  }, [])

  // Listen for apiClient events: forced logout + token refresh
  useEffect(() => {
    const unlistenLogout = listen(AUTH_LOGOUT_EVENT, () => {
      console.warn('[AuthContext] Forced logout — refresh token expired or invalid')
      logout()
    })
    const unlistenRefresh = listen<{ access: string }>(AUTH_TOKEN_REFRESHED_EVENT, (e) => {
      setAccessToken(e.payload.access)
    })
    return () => {
      unlistenLogout.then((fn) => fn())
      unlistenRefresh.then((fn) => fn())
    }
  }, [logout])

  // Keep the on-disk access token fresh while the app is open — Rust call
  // sites (transcription polling, translation warmup, etc.) read tokens
  // straight from disk each request, so a stale disk copy turns into 401s
  // even if the frontend hasn't fired a fetch recently.
  //
  // Two triggers:
  //   - A 4-minute interval as a steady heartbeat. Short enough that laptop
  //     sleep/wake reliably hits a tick within seconds of resuming, and well
  //     under the 30-minute TTL so a single missed tick isn't catastrophic.
  //   - `window.focus` so bringing the app forward after idling immediately
  //     guarantees a valid token before the user's first action lands.
  useEffect(() => {
    if (!isAuthenticated) return
    // Background timer uses a wider 5-minute skew than the per-request
    // default (60s) so that, under a 30-minute TTL, we refresh once we're
    // within the last ~17% of the token's life even if the user hasn't
    // made a call. The tighter 60s skew in authedFetch keeps inflight
    // requests from ever carrying a near-expired token.
    const check = () => { void ensureFreshAccessToken(5 * 60) }
    check()
    const interval = window.setInterval(check, 4 * 60 * 1000)
    window.addEventListener('focus', check)
    return () => {
      window.clearInterval(interval)
      window.removeEventListener('focus', check)
    }
  }, [isAuthenticated])

  const isPaid = billing?.billing.is_paid ?? false
  const isTeamPlan = billing?.billing.is_team_plan ?? false
  const effectiveTier: Tier = billing?.tier.effective ?? 'free'

  return (
    <AuthContext.Provider value={{ isAuthenticated, isLoading, isBillingLoading, user, accessToken, billing, isPaid, isTeamPlan, effectiveTier, login, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
