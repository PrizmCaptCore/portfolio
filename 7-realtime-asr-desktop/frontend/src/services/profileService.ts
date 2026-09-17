import { fetch } from '@tauri-apps/plugin-http'

const BASE_URL = 'https://api.example.com/api/v1'

export type JobRole =
  | 'researcher'
  | 'doctor'
  | 'professor'
  | 'biz_dev'
  | 'investment'
  | 'engineer'
  | 'student'
  | 'other'

export type Industry =
  | 'bio_pharma'
  | 'medical'
  | 'ai_it'
  | 'manufacturing'
  | 'finance'
  | 'startup'
  | 'other'

export type Position = 'junior' | 'senior' | 'executive'

export type ProfileTier =
  | 'free'
  | 'b2c_relay'
  | 'b2c_relay_assistant'
  | 'b2c_relay_complete'
  | 'b2b_relay'
  | 'b2b_relay_assistant'
  | 'b2b_relay_complete'

export interface Profile {
  name: string
  email: string
  level: string | null
  tier: ProfileTier
  language: string
  usage_purpose: string | null
  difficulty: string | null
  job_role: JobRole | null
  industry: Industry | null
  position: Position | null
  current_team_uuid: string | null
  current_team_name: string | null
  avatar_url: string | null
}

export interface ProfileTeam {
  uuid: string
  name: string
}

export interface ProfileChoice {
  value: string
  label: string
}

export interface ProfileResponse {
  profile: Profile
  teams: ProfileTeam[]
  choices: {
    languages: ProfileChoice[]
    levels: ProfileChoice[]
  }
}

// Subset of fields the client is allowed to PATCH. `email` and `tier` are
// server-managed; `level` is set via assessment so we do not surface it here.
export interface ProfileUpdate {
  name?: string
  language?: string
  job_role?: JobRole | null
  industry?: Industry | null
  position?: Position | null
  selected_team_uuid?: string | null
}

export const JOB_ROLE_LABELS: Record<JobRole, string> = {
  researcher: '연구원',
  doctor: '의사',
  professor: '교수',
  biz_dev: '사업개발',
  investment: '투자',
  engineer: '엔지니어',
  student: '학생',
  other: '기타',
}

export const INDUSTRY_LABELS: Record<Industry, string> = {
  bio_pharma: '바이오 / 제약',
  medical: '의료',
  ai_it: 'AI / IT',
  manufacturing: '제조 / 공학',
  finance: '금융',
  startup: '스타트업',
  other: '기타',
}

export const POSITION_LABELS: Record<Position, string> = {
  junior: '주니어 (사원-대리)',
  senior: '시니어 (과장-부장)',
  executive: '임원 (이사급 이상)',
}

export const TIER_LABELS: Record<ProfileTier, string> = {
  free: 'Free',
  b2c_relay: 'B2C Relay',
  b2c_relay_assistant: 'B2C Relay Assistant',
  b2c_relay_complete: 'B2C Relay Complete',
  b2b_relay: 'B2B Relay',
  b2b_relay_assistant: 'B2B Relay Assistant',
  b2b_relay_complete: 'B2B Relay Complete',
}

export async function getProfile(access: string): Promise<ProfileResponse> {
  const res = await fetch(`${BASE_URL}/users/profile/`, {
    headers: { Authorization: `Bearer ${access}` },
  })
  if (!res.ok) throw new Error('Failed to fetch profile')
  return res.json()
}

export async function updateProfile(
  access: string,
  patch: ProfileUpdate,
): Promise<ProfileResponse> {
  const res = await fetch(`${BASE_URL}/users/profile/`, {
    method: 'PATCH',
    headers: {
      Authorization: `Bearer ${access}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(patch),
  })
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    throw new Error(
      typeof data === 'object' && data
        ? Object.values(data).flat().join(', ') || '프로필 저장에 실패했습니다.'
        : '프로필 저장에 실패했습니다.',
    )
  }
  return res.json()
}

// Avatar requires multipart/form-data; the rest of the PATCH fields can ride
// along on the same request.
export async function updateProfileWithAvatar(
  access: string,
  patch: ProfileUpdate,
  avatar: File,
): Promise<ProfileResponse> {
  const form = new FormData()
  form.append('avatar', avatar)
  for (const [key, value] of Object.entries(patch)) {
    if (value === undefined) continue
    form.append(key, value === null ? '' : String(value))
  }

  const res = await fetch(`${BASE_URL}/users/profile/`, {
    method: 'PATCH',
    headers: { Authorization: `Bearer ${access}` },
    body: form,
  })
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    throw new Error(
      typeof data === 'object' && data
        ? Object.values(data).flat().join(', ') || '프로필 저장에 실패했습니다.'
        : '프로필 저장에 실패했습니다.',
    )
  }
  return res.json()
}
