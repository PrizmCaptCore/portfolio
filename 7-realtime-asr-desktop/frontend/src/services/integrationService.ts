import { authedFetch } from './apiClient'

export type IntegrationProvider =
  | 'slack'
  | 'notion'
  | 'google_calendar'
  | 'gmail'
  | 'outlook_mail'
  | 'outlook_calendar'
  | 'teams'

export interface IntegrationStatus {
  connected: boolean
  workspace?: string
  connected_at?: string
  last_used_at?: string
  scope?: string
}

export interface SlackChannel {
  id: string
  name: string
  is_private: boolean
}

export interface SlackChannelsResponse {
  channels: SlackChannel[]
  next_cursor: string
}

export interface NotionSearchItem {
  id: string
  object: 'page' | 'database'
  title: string
  url: string
  last_edited_time: string
}

export interface NotionSearchResponse {
  results: NotionSearchItem[]
  next_cursor: string
  has_more: boolean
}

export interface ConnectResponse {
  authorize_url: string
}

export class IntegrationError extends Error {
  constructor(public code: string, public httpStatus: number) {
    super(code)
  }
}

async function parseOrThrow(res: Response): Promise<any> {
  if (res.ok) return res.status === 204 ? null : res.json()
  const data = await res.json().catch(() => ({}))
  throw new IntegrationError(data?.detail || `http_${res.status}`, res.status)
}

export async function getStatus(
  provider: IntegrationProvider,
): Promise<IntegrationStatus> {
  const res = await authedFetch(`/integrations/${provider}/status/`)
  return parseOrThrow(res)
}

export async function startConnect(
  provider: IntegrationProvider,
): Promise<ConnectResponse> {
  const res = await authedFetch(`/integrations/${provider}/connect/`)
  return parseOrThrow(res)
}

export async function disconnect(
  provider: IntegrationProvider,
): Promise<void> {
  const res = await authedFetch(`/integrations/${provider}/disconnect/`, {
    method: 'DELETE',
  })
  await parseOrThrow(res)
}

export async function listSlackChannels(
  cursor = '',
): Promise<SlackChannelsResponse> {
  const qs = cursor ? `?cursor=${encodeURIComponent(cursor)}` : ''
  const res = await authedFetch(`/integrations/slack/channels/${qs}`)
  return parseOrThrow(res)
}

export async function sendToSlack(
  channel: string,
  markdown: string,
): Promise<void> {
  const res = await authedFetch(`/integrations/slack/send/`, {
    method: 'POST',
    body: JSON.stringify({ channel, markdown }),
  })
  await parseOrThrow(res)
}

export async function searchNotion(
  params: { q?: string; type?: 'page' | 'database'; cursor?: string } = {},
): Promise<NotionSearchResponse> {
  const qs = new URLSearchParams()
  if (params.q) qs.set('q', params.q)
  if (params.type) qs.set('type', params.type)
  if (params.cursor) qs.set('cursor', params.cursor)
  const suffix = qs.toString() ? `?${qs}` : ''
  const res = await authedFetch(`/integrations/notion/search/${suffix}`)
  return parseOrThrow(res)
}

export async function sendToNotion(
  params: {
    page_id: string
    markdown: string
    mode?: 'append' | 'create'
    title?: string
    object?: 'page' | 'database'
  },
): Promise<void> {
  const res = await authedFetch(`/integrations/notion/send/`, {
    method: 'POST',
    body: JSON.stringify({ mode: 'append', object: 'page', ...params }),
  })
  await parseOrThrow(res)
}

// ── Google Calendar ──────────────────────────────────────────────────────

export interface CalendarAttendee {
  email: string
  name: string
  response: string
  self: boolean
}

export interface CalendarEvent {
  id: string
  title: string
  /** RFC3339 datetime for timed events, or YYYY-MM-DD for all-day. */
  start: string
  end: string
  all_day: boolean
  location: string
  description: string
  html_link: string
  /** Google Meet URL when present. */
  hangout_link: string
  attendees: CalendarAttendee[]
  organizer_email: string
  status: string
}

export interface CalendarEventsResponse {
  events: CalendarEvent[]
}

export async function listCalendarEvents(
  params: { time_min?: string; time_max?: string; max_results?: number } = {},
): Promise<CalendarEventsResponse> {
  const qs = new URLSearchParams()
  if (params.time_min) qs.set('time_min', params.time_min)
  if (params.time_max) qs.set('time_max', params.time_max)
  if (params.max_results != null) qs.set('max_results', String(params.max_results))
  const suffix = qs.toString() ? `?${qs}` : ''
  const res = await authedFetch(`/integrations/google_calendar/events/${suffix}`)
  return parseOrThrow(res)
}

// ── Gmail (send only) ────────────────────────────────────────────────────

export interface SendGmailParams {
  to: string[]
  subject: string
  body: string
  cc?: string[]
  bcc?: string[]
}

export async function sendGmail(params: SendGmailParams): Promise<void> {
  const res = await authedFetch(`/integrations/gmail/send/`, {
    method: 'POST',
    body: JSON.stringify(params),
  })
  await parseOrThrow(res)
}

// ── Outlook Mail (send only) ─────────────────────────────────────────────
// Same shape as Gmail — the gateway maps both to Microsoft Graph /sendMail
// or Gmail API behind the scenes. Frontend can reuse SendGmailParams.

export type SendOutlookMailParams = SendGmailParams

export async function sendOutlookMail(params: SendOutlookMailParams): Promise<void> {
  const res = await authedFetch(`/integrations/outlook_mail/send/`, {
    method: 'POST',
    body: JSON.stringify(params),
  })
  await parseOrThrow(res)
}

// ── Outlook Calendar ─────────────────────────────────────────────────────
// Same response shape as Google Calendar — gateway returns the unified
// CalendarEvent[] regardless of provider. Frontend can merge sources.

export async function listOutlookCalendarEvents(
  params: { time_min?: string; time_max?: string; max_results?: number } = {},
): Promise<CalendarEventsResponse> {
  const qs = new URLSearchParams()
  if (params.time_min) qs.set('time_min', params.time_min)
  if (params.time_max) qs.set('time_max', params.time_max)
  if (params.max_results != null) qs.set('max_results', String(params.max_results))
  const suffix = qs.toString() ? `?${qs}` : ''
  const res = await authedFetch(`/integrations/outlook_calendar/events/${suffix}`)
  return parseOrThrow(res)
}

// ── Microsoft Teams ──────────────────────────────────────────────────────
// Mirrors Slack: list channels (= teams + channels in MS Graph), post markdown.

export interface TeamsChannel {
  id: string
  name: string
  /** team_id is required to scope `send/` calls — Teams channels live under teams */
  team_id: string
  team_name: string
}

export interface TeamsChannelsResponse {
  channels: TeamsChannel[]
  next_cursor: string
}

export async function listTeamsChannels(
  cursor = '',
): Promise<TeamsChannelsResponse> {
  const qs = cursor ? `?cursor=${encodeURIComponent(cursor)}` : ''
  const res = await authedFetch(`/integrations/teams/channels/${qs}`)
  return parseOrThrow(res)
}

export async function sendToTeams(
  team_id: string,
  channel_id: string,
  markdown: string,
): Promise<void> {
  const res = await authedFetch(`/integrations/teams/send/`, {
    method: 'POST',
    body: JSON.stringify({ team_id, channel_id, markdown }),
  })
  await parseOrThrow(res)
}
