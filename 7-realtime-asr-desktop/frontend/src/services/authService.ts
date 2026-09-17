import { fetch } from '@tauri-apps/plugin-http'

const BASE_URL = 'https://api.example.com/api/v1'

export interface AuthTokens {
  access: string
  refresh: string
}

export interface UserInfo {
  id: number
  email: string
  username: string
  first_name: string
  last_name: string
}

export async function login(email: string, password: string): Promise<AuthTokens> {
  const res = await fetch(`${BASE_URL}/auth/token/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  })

  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    console.error('[authService] login failed', res.status, JSON.stringify(data))
    if (res.status >= 500) throw new Error('서버 연결이 불안정합니다.')
    throw new Error('회원 정보가 잘못되었습니다.')
  }

  return res.json()
}

export async function refreshToken(refresh: string): Promise<{ access: string }> {
  const res = await fetch(`${BASE_URL}/auth/token/refresh/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh }),
  })

  if (!res.ok) throw new Error('Token refresh failed')
  return res.json()
}

export async function verifyToken(access: string): Promise<boolean> {
  const res = await fetch(`${BASE_URL}/auth/token/verify/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ token: access }),
  })
  return res.ok
}

export async function logout(refresh: string): Promise<void> {
  await fetch(`${BASE_URL}/auth/logout/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh }),
  }).catch(() => {})
}

export async function getCurrentUser(access: string): Promise<UserInfo> {
  const res = await fetch(`${BASE_URL}/auth/me/`, {
    headers: { Authorization: `Bearer ${access}` },
  })
  if (!res.ok) throw new Error('Failed to fetch user')
  return res.json()
}

export type Tier = 'free' | 'subscription' | 'team'

export interface BillingInfo {
  tier: {
    profile: Tier
    effective: Tier
    source: 'profile' | 'team'
  }
  billing: {
    status: 'active' | 'inactive'
    is_paid: boolean
    is_team_plan: boolean
  }
  current_team: { uuid: string; name: string; tier: Tier } | null
}

export async function getBillingInfo(access: string): Promise<BillingInfo> {
  const res = await fetch(`${BASE_URL}/auth/billing/me/`, {
    headers: { Authorization: `Bearer ${access}` },
  })
  if (!res.ok) throw new Error('Failed to fetch billing info')
  return res.json()
}
