import { fetch } from '@tauri-apps/plugin-http'

const BASE_URL = 'https://api.example.com/api/v1'

// Cloud-side representation of a backed-up meeting. The shape mirrors what
// the Django `meetings` app (`apps/meetings/serializers.py`) emits.

export interface CloudMeetingSummary {
  uuid: string
  client_meeting_id: string
  title: string
  started_at: string | null
  duration_seconds: number | null
  detected_language: string
  target_language: string
  team_uuid: string | null
  team_name: string | null
  owner_email: string
  owner_name: string
  created_at: string
  updated_at: string
}

export interface CloudMeetingDetail extends CloudMeetingSummary {
  transcript_segments: unknown[]
  summary: unknown
}

export interface MeetingUploadPayload {
  client_meeting_id: string
  title: string
  started_at?: string | null
  duration_seconds?: number | null
  detected_language?: string
  target_language?: string
  transcript_segments: unknown[]
  summary: unknown
  // Empty string / null = unshare. UUID of one of the user's teams = share.
  // Server validates membership and silently falls back to null on a stale
  // mismatch, so we don't have to.
  team_uuid?: string | null
}

async function readError(res: Response, fallback: string): Promise<string> {
  const data = await res.json().catch(() => null)
  if (!data || typeof data !== 'object') return fallback
  if (typeof (data as { error?: unknown }).error === 'string') {
    return (data as { error: string }).error
  }
  const messages = Object.values(data).flat().filter(Boolean)
  return messages.length ? messages.join(', ') : fallback
}

export async function listCloudMeetings(
  access: string,
): Promise<CloudMeetingSummary[]> {
  const res = await fetch(`${BASE_URL}/meetings/`, {
    headers: { Authorization: `Bearer ${access}` },
  })
  if (!res.ok) throw new Error(await readError(res, '백업 목록을 불러오지 못했습니다'))
  return res.json()
}

export async function listTeamMeetings(
  access: string,
  teamUuid: string,
): Promise<CloudMeetingSummary[]> {
  const res = await fetch(`${BASE_URL}/meetings/team/${teamUuid}/`, {
    headers: { Authorization: `Bearer ${access}` },
  })
  if (!res.ok) throw new Error(await readError(res, '팀 회의 목록을 불러오지 못했습니다'))
  return res.json()
}

export async function getCloudMeeting(
  access: string,
  uuid: string,
): Promise<CloudMeetingDetail> {
  const res = await fetch(`${BASE_URL}/meetings/${uuid}/`, {
    headers: { Authorization: `Bearer ${access}` },
  })
  if (!res.ok) throw new Error(await readError(res, '백업을 불러오지 못했습니다'))
  return res.json()
}

// Upserts on (user, client_meeting_id) — re-uploading the same local meeting
// replaces the prior cloud snapshot in place rather than producing duplicates,
// which is the behavior the manual "백업" button needs.
export async function uploadMeeting(
  access: string,
  payload: MeetingUploadPayload,
): Promise<CloudMeetingDetail> {
  const res = await fetch(`${BASE_URL}/meetings/`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${access}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  })
  if (!res.ok) throw new Error(await readError(res, '백업에 실패했습니다'))
  return res.json()
}

export async function deleteCloudMeeting(
  access: string,
  uuid: string,
): Promise<void> {
  const res = await fetch(`${BASE_URL}/meetings/${uuid}/`, {
    method: 'DELETE',
    headers: { Authorization: `Bearer ${access}` },
  })
  if (!res.ok) throw new Error(await readError(res, '백업 삭제에 실패했습니다'))
}
