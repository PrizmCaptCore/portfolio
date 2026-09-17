import { fetch } from '@tauri-apps/plugin-http'

const BASE_URL = 'https://api.example.com/api/v1'

export type TeamRole = 'admin' | 'member'

export interface Team {
  uuid: string
  name: string
  tier: string
  max_seats: number
  member_count: number
  my_role: TeamRole | null
  logo_url: string | null
  created_at: string
}

export interface TeamMember {
  id: number
  user_email: string
  user_uuid: string
  user_name: string
  role: TeamRole
  joined_at: string
  avatar_url: string | null
  level: string | null
}

export interface InvitationResult {
  email: string
  role: TeamRole
  status: string
  expires_at: string
}

export const TEAM_ROLE_LABELS: Record<TeamRole, string> = {
  admin: '관리자',
  member: '멤버',
}

// Convert backend `{error: "..."}` payload (or DRF field-error dict) into a
// flat error message string, falling back to a generic line if the response
// doesn't follow either shape.
async function readError(res: Response, fallback: string): Promise<string> {
  const data = await res.json().catch(() => null)
  if (!data || typeof data !== 'object') return fallback
  if (typeof (data as { error?: unknown }).error === 'string') {
    return (data as { error: string }).error
  }
  const messages = Object.values(data).flat().filter(Boolean)
  return messages.length ? messages.join(', ') : fallback
}

export async function listTeams(access: string): Promise<Team[]> {
  const res = await fetch(`${BASE_URL}/teams/`, {
    headers: { Authorization: `Bearer ${access}` },
  })
  if (!res.ok) throw new Error(await readError(res, '팀 목록을 불러오지 못했습니다'))
  return res.json()
}

export async function listMembers(
  access: string,
  teamUuid: string,
): Promise<TeamMember[]> {
  const res = await fetch(`${BASE_URL}/teams/${teamUuid}/members/`, {
    headers: { Authorization: `Bearer ${access}` },
  })
  if (!res.ok) throw new Error(await readError(res, '팀원 목록을 불러오지 못했습니다'))
  return res.json()
}

export async function inviteMember(
  access: string,
  teamUuid: string,
  email: string,
  role: TeamRole,
): Promise<{ message: string; invitation: InvitationResult }> {
  const res = await fetch(`${BASE_URL}/teams/${teamUuid}/invite/`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${access}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ email, role }),
  })
  if (!res.ok) throw new Error(await readError(res, '초대를 보내지 못했습니다'))
  return res.json()
}

export async function changeMemberRole(
  access: string,
  teamUuid: string,
  membershipId: number,
  role: TeamRole,
): Promise<{ message: string; membership: TeamMember }> {
  const res = await fetch(
    `${BASE_URL}/teams/${teamUuid}/members/${membershipId}/role/`,
    {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${access}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ role }),
    },
  )
  if (!res.ok) throw new Error(await readError(res, '권한을 변경하지 못했습니다'))
  return res.json()
}

export async function removeMember(
  access: string,
  teamUuid: string,
  membershipId: number,
): Promise<void> {
  const res = await fetch(
    `${BASE_URL}/teams/${teamUuid}/members/${membershipId}/remove/`,
    {
      method: 'POST',
      headers: { Authorization: `Bearer ${access}` },
    },
  )
  if (!res.ok) throw new Error(await readError(res, '팀원을 제거하지 못했습니다'))
}
