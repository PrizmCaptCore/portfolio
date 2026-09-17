/**
 * Shared HTTP client with automatic JWT refresh.
 *
 * Every service module should call `authedFetch` instead of raw `fetch`.
 * On 401 it transparently refreshes the access token (once), retries the
 * request, and persists the new token pair to the Tauri store. If the
 * refresh itself fails the user is forcibly logged out via Tauri event.
 *
 * Concurrent 401s are coalesced — only one refresh request fires.
 */

import { fetch } from '@tauri-apps/plugin-http'
import { load } from '@tauri-apps/plugin-store'
import { emit } from '@tauri-apps/api/event'

const BASE_URL = 'https://api.example.com/api/v1'

const STORE_FILE = 'auth.json'
const KEY_ACCESS = 'access_token'
const KEY_REFRESH = 'refresh_token'

export const AUTH_LOGOUT_EVENT = 'auth-logout-required'
export const AUTH_TOKEN_REFRESHED_EVENT = 'auth-token-refreshed'

// Refresh proactively when the access token has this much life left or less.
// A 30-minute TTL with a 60-second window means the token is still comfortably
// valid if the refresh fails and the call has to fall back to the 401-retry
// path, but we almost never let an expired token leave the client.
const EXPIRY_SKEW_SECONDS = 60

// ── token helpers ────────────────────────────────────────────────────────

// Decode the `exp` (seconds-since-epoch) claim from a JWT without verifying
// the signature — we only need it to decide when to preemptively refresh.
// Returns `null` if the token is malformed or missing `exp`.
export function jwtExpSeconds(token: string): number | null {
  const parts = token.split('.')
  if (parts.length !== 3) return null
  try {
    const b64 = parts[1].replace(/-/g, '+').replace(/_/g, '/')
    const padded = b64 + '='.repeat((4 - (b64.length % 4)) % 4)
    const payload = JSON.parse(atob(padded)) as { exp?: unknown }
    return typeof payload.exp === 'number' ? payload.exp : null
  } catch {
    return null
  }
}

function isExpiringSoon(token: string, skewSeconds = EXPIRY_SKEW_SECONDS): boolean {
  const exp = jwtExpSeconds(token)
  if (exp === null) return false // unknown shape → don't spuriously refresh
  return exp * 1000 - Date.now() <= skewSeconds * 1000
}

async function getTokens(): Promise<{ access: string | null; refresh: string | null }> {
  const store = await load(STORE_FILE, { autoSave: true, defaults: {} })
  return {
    access: await store.get<string>(KEY_ACCESS) ?? null,
    refresh: await store.get<string>(KEY_REFRESH) ?? null,
  }
}

async function persistTokens(access: string, refresh?: string): Promise<void> {
  const store = await load(STORE_FILE, { autoSave: true, defaults: {} })
  await store.set(KEY_ACCESS, access)
  if (refresh) {
    await store.set(KEY_REFRESH, refresh)
  }
}

// ── single-flight refresh ────────────────────────────────────────────────

let inflightRefresh: Promise<string> | null = null

async function doRefresh(refreshToken: string): Promise<string> {
  const res = await fetch(`${BASE_URL}/auth/token/refresh/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh: refreshToken }),
  })

  if (!res.ok) {
    throw new Error('refresh_failed')
  }

  const data = await res.json() as { access: string; refresh?: string }
  await persistTokens(data.access, data.refresh)
  await emit(AUTH_TOKEN_REFRESHED_EVENT, { access: data.access })
  return data.access
}

export async function refreshAccessToken(): Promise<string> {
  if (inflightRefresh) return inflightRefresh

  const { refresh } = await getTokens()
  if (!refresh) {
    await emit(AUTH_LOGOUT_EVENT, {})
    throw new Error('no_refresh_token')
  }

  inflightRefresh = doRefresh(refresh).finally(() => {
    inflightRefresh = null
  })

  try {
    return await inflightRefresh
  } catch {
    await emit(AUTH_LOGOUT_EVENT, {})
    throw new Error('refresh_failed')
  }
}

/**
 * Refresh the access token if it will expire within `skewSeconds`.
 * Returns the current valid token. Safe to call from timers or focus
 * handlers; coalesces with any in-flight refresh.
 */
export async function ensureFreshAccessToken(
  skewSeconds = EXPIRY_SKEW_SECONDS,
): Promise<string | null> {
  const { access } = await getTokens()
  if (!access) return null
  if (!isExpiringSoon(access, skewSeconds)) return access
  try {
    return await refreshAccessToken()
  } catch {
    return null
  }
}

// ── public API ───────────────────────────────────────────────────────────

export { BASE_URL }

/**
 * `fetch` wrapper that injects `Authorization: Bearer` and retries once
 * on 401 after refreshing the access token.
 */
export async function authedFetch(
  path: string,
  init: RequestInit = {},
): Promise<Response> {
  const url = path.startsWith('http') ? path : `${BASE_URL}${path}`

  const attempt = async (accessToken: string) => {
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      ...((init.headers as Record<string, string>) ?? {}),
      Authorization: `Bearer ${accessToken}`,
    }
    return fetch(url, { ...init, headers })
  }

  const { access } = await getTokens()
  if (!access) {
    await emit(AUTH_LOGOUT_EVENT, {})
    throw new Error('no_access_token')
  }

  // Preemptive refresh: if the token is about to expire, swap it before the
  // request leaves the client so Rust call sites reading from disk also see
  // the fresh token. On failure we still try the request — the 401 fallback
  // below will surface the real error.
  let working = access
  if (isExpiringSoon(access)) {
    try {
      working = await refreshAccessToken()
    } catch {
      working = access
    }
  }

  let res = await attempt(working)

  if (res.status === 401) {
    const newAccess = await refreshAccessToken()
    res = await attempt(newAccess)
  }

  return res
}
