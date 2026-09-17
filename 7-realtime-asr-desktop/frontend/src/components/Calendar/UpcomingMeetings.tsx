'use client'

import { useEffect, useMemo, useState } from 'react'
import { useRouter } from 'next/navigation'
import { invoke } from '@tauri-apps/api/core'
import { toast } from 'sonner'
import {
  CalendarDays,
  Clock,
  ExternalLink,
  Link as LinkIcon,
  Loader2,
  MapPin,
  Mic,
  Notebook,
  RefreshCw,
  Users,
  Video,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useAuth } from '@/contexts/AuthContext'
import {
  listCalendarEvents,
  listOutlookCalendarEvents,
  type CalendarEvent,
} from '@/services/integrationService'
import { useIntegrationStatus } from '@/hooks/useIntegrationStatus'
import { storageService, type Meeting } from '@/services/storageService'

/** Meeting whose `created_at` falls within ±MATCH_WINDOW_MS of an event start. */
const MATCH_WINDOW_MS = 2 * 60 * 60 * 1000 // 2 hours either side

interface MeetingWithTimestamp extends Meeting {
  created_at?: string
}

/** Format a Date as YYYY-MM-DD in local time, used as a stable group key. */
function dateKey(d: Date): string {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

/** "오늘" / "내일" / "D-3" / "D+5" / weekday for distant days. */
function dayBadge(eventDate: Date, now: Date): { label: string; tone: 'today' | 'soon' | 'past' | 'future' } {
  const a = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
  const b = new Date(eventDate.getFullYear(), eventDate.getMonth(), eventDate.getDate()).getTime()
  const diffDays = Math.round((b - a) / (24 * 60 * 60 * 1000))
  if (diffDays === 0) return { label: '오늘', tone: 'today' }
  if (diffDays === 1) return { label: '내일', tone: 'soon' }
  if (diffDays === -1) return { label: '어제', tone: 'past' }
  if (diffDays > 0) return { label: `D-${diffDays}`, tone: diffDays <= 3 ? 'soon' : 'future' }
  return { label: `D+${Math.abs(diffDays)}`, tone: 'past' }
}

function formatTimeRange(ev: CalendarEvent): string {
  if (ev.all_day) return '종일'
  const start = new Date(ev.start)
  const end = ev.end ? new Date(ev.end) : null
  const fmt = (d: Date) =>
    d.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', hour12: false })
  return end ? `${fmt(start)} – ${fmt(end)}` : fmt(start)
}

function dayHeading(dateStr: string, now: Date): string {
  const [y, m, d] = dateStr.split('-').map(Number)
  const target = new Date(y, m - 1, d)
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const diffDays = Math.round((target.getTime() - today.getTime()) / (24 * 60 * 60 * 1000))
  if (diffDays === 0) return `오늘 · ${target.toLocaleDateString('ko-KR', { month: 'long', day: 'numeric', weekday: 'short' })}`
  if (diffDays === 1) return `내일 · ${target.toLocaleDateString('ko-KR', { month: 'long', day: 'numeric', weekday: 'short' })}`
  if (diffDays === -1) return `어제 · ${target.toLocaleDateString('ko-KR', { month: 'long', day: 'numeric', weekday: 'short' })}`
  return target.toLocaleDateString('ko-KR', { month: 'long', day: 'numeric', weekday: 'long' })
}

/**
 * Pick the meeting whose `created_at` is closest to the event's start time,
 * within MATCH_WINDOW_MS. Heuristic, not authoritative — meetings only have
 * created_at, not a scheduled-for field, so a meeting created right around
 * the calendar event's start time is the strongest signal we have.
 */
function findMatchingMeeting(
  ev: CalendarEvent,
  meetings: MeetingWithTimestamp[],
): MeetingWithTimestamp | null {
  if (ev.all_day) return null
  const evStart = new Date(ev.start).getTime()
  if (Number.isNaN(evStart)) return null

  let best: { meeting: MeetingWithTimestamp; delta: number } | null = null
  for (const m of meetings) {
    if (!m.created_at) continue
    const mStart = new Date(m.created_at).getTime()
    if (Number.isNaN(mStart)) continue
    const delta = Math.abs(mStart - evStart)
    if (delta > MATCH_WINDOW_MS) continue
    if (!best || delta < best.delta) {
      best = { meeting: m, delta }
    }
  }
  return best?.meeting ?? null
}

const DAY_BADGE_CLASS: Record<'today' | 'soon' | 'past' | 'future', string> = {
  today: 'bg-blue-100 text-blue-700 ring-1 ring-blue-200',
  soon: 'bg-amber-100 text-amber-700 ring-1 ring-amber-200',
  past: 'bg-gray-100 text-gray-600 ring-1 ring-gray-200',
  future: 'bg-gray-50 text-gray-600 ring-1 ring-gray-200',
}

export function UpcomingMeetings() {
  const router = useRouter()
  const { isAuthenticated } = useAuth()
  const {
    status: googleStatus,
    isLoading: isLoadingGoogleStatus,
    refresh: refreshGoogleStatus,
  } = useIntegrationStatus('google_calendar')
  const {
    status: outlookStatus,
    isLoading: isLoadingOutlookStatus,
    refresh: refreshOutlookStatus,
  } = useIntegrationStatus('outlook_calendar')

  const [events, setEvents] = useState<CalendarEvent[]>([])
  const [meetings, setMeetings] = useState<MeetingWithTimestamp[]>([])
  const [isLoadingEvents, setIsLoadingEvents] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [now, setNow] = useState<Date>(() => new Date())

  // Refresh "now" every minute so D-day badges roll over without a hard
  // reload when the user leaves the app open.
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 60_000)
    return () => clearInterval(t)
  }, [])

  const isGoogleConnected = googleStatus?.connected === true
  const isOutlookConnected = outlookStatus?.connected === true
  const isAnyConnected = isGoogleConnected || isOutlookConnected
  const isLoadingAnyStatus = isLoadingGoogleStatus || isLoadingOutlookStatus

  const loadEvents = async () => {
    if (!isAnyConnected) return
    setIsLoadingEvents(true)
    setError(null)
    try {
      // Window: from start of today through 30 days forward. Past days are not
      // listed on the home screen — only today and upcoming.
      const todayStart = new Date()
      todayStart.setHours(0, 0, 0, 0)
      const future = new Date()
      future.setDate(future.getDate() + 30)
      const params = {
        time_min: todayStart.toISOString(),
        time_max: future.toISOString(),
        max_results: 100,
      }

      // Fetch from each connected source in parallel; merge whatever succeeds.
      // A partial failure (e.g., Google 200 + Outlook 500) still shows the
      // events that came back, with the "새로고침 실패" pill flagging the
      // failed source via the error message.
      const sources: Promise<CalendarEvent[]>[] = []
      if (isGoogleConnected) {
        sources.push(listCalendarEvents(params).then((r) => r.events))
      }
      if (isOutlookConnected) {
        sources.push(listOutlookCalendarEvents(params).then((r) => r.events))
      }
      const results = await Promise.allSettled(sources)

      const merged: CalendarEvent[] = []
      const failures: string[] = []
      for (const r of results) {
        if (r.status === 'fulfilled') {
          merged.push(...r.value)
        } else {
          failures.push((r.reason as any)?.message || 'load_failed')
        }
      }
      setEvents(merged)

      if (failures.length > 0) {
        setError(failures[0])
        // Token revocation on either side — re-poll status so the UI shows
        // the disconnected card.
        if (failures.some((f) => f === 'reconnect_required')) {
          await Promise.all([refreshGoogleStatus(), refreshOutlookStatus()])
        }
      }
    } catch (e: any) {
      // Should not happen with allSettled, but keep a safety net.
      setError(e?.message || 'load_failed')
    } finally {
      setIsLoadingEvents(false)
    }
  }

  // Load events whenever any connection state flips on. Triggers also when the
  // second calendar connects mid-session so its events get pulled in.
  useEffect(() => {
    if (!isAuthenticated) return
    if (!isAnyConnected) {
      setEvents([])
      return
    }
    loadEvents()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAuthenticated, isGoogleConnected, isOutlookConnected])

  useEffect(() => {
    if (!isAuthenticated) return
    storageService
      .getMeetings()
      .then((m) => setMeetings(m as MeetingWithTimestamp[]))
      .catch(() => setMeetings([]))
  }, [isAuthenticated])

  // Index events by local date so the calendar skeleton can look up O(1).
  const eventsByDay = useMemo(() => {
    const m = new Map<string, CalendarEvent[]>()
    for (const ev of events) {
      if (!ev.start) continue
      const d = new Date(ev.start)
      if (Number.isNaN(d.getTime())) continue
      const key = dateKey(d)
      const list = m.get(key) || []
      list.push(ev)
      m.set(key, list)
    }
    // Sort each day's events chronologically (all-day first, then by start).
    for (const [, list] of m) {
      list.sort((a, b) => {
        if (a.all_day !== b.all_day) return a.all_day ? -1 : 1
        return new Date(a.start).getTime() - new Date(b.start).getTime()
      })
    }
    return m
  }, [events])

  // Always-visible calendar skeleton: today + next 13 days (2 weeks).
  // We re-derive whenever `now` ticks so the window rolls forward at midnight
  // without a manual reload.
  const calendarDays = useMemo(() => {
    const days: string[] = []
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
    for (let i = 0; i < 14; i++) {
      const d = new Date(today.getFullYear(), today.getMonth(), today.getDate() + i)
      days.push(dateKey(d))
    }
    return days
  }, [now])

  if (!isAuthenticated) return null

  return (
    <div className="flex h-full flex-col bg-gray-50">
      <div className="mx-auto w-full max-w-3xl flex-1 overflow-y-auto px-6 py-8">
        <div className="mb-6 flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-semibold text-gray-900">다가오는 회의</h1>
            <p className="mt-1 text-sm text-gray-500">
              연결된 캘린더에서 가져온 일정과, 이미 녹음된 회의록을 함께 표시합니다.
            </p>
          </div>
          {isAnyConnected && (
            <div className="flex items-center gap-2">
              {error && error !== 'reconnect_required' && (
                <span
                  className="text-xs text-amber-700"
                  title={`일정 새로고침 실패: ${error}`}
                >
                  새로고침 실패
                </span>
              )}
              <Button
                variant="outline"
                size="sm"
                onClick={loadEvents}
                disabled={isLoadingEvents}
                title="새로고침"
              >
                {isLoadingEvents ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <RefreshCw className="h-4 w-4" />
                )}
              </Button>
            </div>
          )}
        </div>

        {!isLoadingAnyStatus && !isAnyConnected && (
          <div className="rounded-xl border border-dashed border-gray-300 bg-white p-8 text-center">
            <CalendarDays className="mx-auto h-10 w-10 text-gray-300" />
            <h2 className="mt-3 text-base font-semibold text-gray-900">
              연결된 캘린더가 없어요
            </h2>
            <p className="mx-auto mt-1 max-w-md text-sm text-gray-600">
              설정에서 Google 또는 Outlook 캘린더를 연결하면 다가오는 회의가 여기 표시되고, 지난 회의는
              자동으로 녹음된 회의록과 연결됩니다.
            </p>
            <Button className="mt-4" onClick={() => router.push('/settings')}>
              <LinkIcon className="mr-2 h-4 w-4" />
              설정에서 연결하기
            </Button>
          </div>
        )}

        {/* `reconnect_required` is the only error that requires user action;
            other failures (http_500, network blips) are shown as a small
            "새로고침 실패" pill next to the refresh button so the calendar
            itself stays visible. */}
        {isAnyConnected && error === 'reconnect_required' && (
          <div className="mb-4 rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
            캘린더 권한이 만료되었거나 취소되었어요. 설정에서 다시 연결해 주세요.
          </div>
        )}

        {/* Initial spinner while we wait for the very first response. After
            that the calendar skeleton is always visible. */}
        {isAnyConnected && isLoadingEvents && events.length === 0 && (
          <div className="flex items-center justify-center py-16 text-gray-400">
            <Loader2 className="h-5 w-5 animate-spin" />
          </div>
        )}

        {isAnyConnected && !(isLoadingEvents && events.length === 0) && (
          <div className="space-y-6">
            {/* Always-visible 2-week skeleton starting today. Empty days render
                a placeholder so the calendar feels continuous. */}
            {calendarDays.map((day) => (
              <DaySection
                key={day}
                day={day}
                events={eventsByDay.get(day) ?? []}
                now={now}
                meetings={meetings}
                onOpenMeeting={(id) => router.push(`/meeting-details?id=${id}`)}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

interface DaySectionProps {
  day: string
  events: CalendarEvent[]
  now: Date
  meetings: MeetingWithTimestamp[]
  onOpenMeeting: (meetingId: string) => void
}

/** One day's slot in the always-on calendar. Renders the day heading plus
 *  either the event cards or a subtle "일정 없음" placeholder. */
function DaySection({ day, events, now, meetings, onOpenMeeting }: DaySectionProps) {
  return (
    <div>
      <div className="mb-2 px-1 text-xs font-semibold uppercase tracking-wide text-gray-500">
        {dayHeading(day, now)}
      </div>
      {events.length === 0 ? (
        <div className="rounded-lg border border-dashed border-gray-200 bg-white px-4 py-3 text-xs text-gray-400">
          일정 없음
        </div>
      ) : (
        <div className="space-y-2">
          {events.map((ev) => (
            <EventRow
              key={ev.id}
              event={ev}
              now={now}
              match={findMatchingMeeting(ev, meetings)}
              onOpenMeeting={onOpenMeeting}
            />
          ))}
        </div>
      )}
    </div>
  )
}

interface EventRowProps {
  event: CalendarEvent
  now: Date
  match: MeetingWithTimestamp | null
  onOpenMeeting: (meetingId: string) => void
}

function EventRow({ event, now, match, onOpenMeeting }: EventRowProps) {
  const startDate = new Date(event.start)
  const badge = dayBadge(startDate, now)
  const startTs = startDate.getTime()
  const isPast = !event.all_day && startTs < now.getTime()
  const meetLink = event.hangout_link

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4 transition-shadow hover:shadow-sm">
      <div className="flex items-start gap-3">
        <span
          className={`shrink-0 rounded-md px-2 py-0.5 text-xs font-semibold ${DAY_BADGE_CLASS[badge.tone]}`}
        >
          {badge.label}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <h3 className="truncate text-sm font-semibold text-gray-900">
              {event.title || '(제목 없음)'}
            </h3>
            {event.status === 'cancelled' && (
              <span className="rounded bg-gray-100 px-1.5 py-0.5 text-[10px] text-gray-500">
                취소됨
              </span>
            )}
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-gray-600">
            <span className="inline-flex items-center gap-1">
              <Clock className="h-3 w-3" />
              {formatTimeRange(event)}
            </span>
            {event.location && (
              <span className="inline-flex items-center gap-1">
                <MapPin className="h-3 w-3" />
                {event.location}
              </span>
            )}
            {event.attendees && event.attendees.length > 0 && (
              <span className="inline-flex items-center gap-1">
                <Users className="h-3 w-3" />
                {event.attendees.length}명
              </span>
            )}
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {match && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => onOpenMeeting(match.id)}
              title={`회의록: ${match.title}`}
            >
              <Notebook className="mr-1 h-3.5 w-3.5" />
              회의록
            </Button>
          )}
          {!match && isPast && (
            <span className="text-[10px] text-gray-400">기록 없음</span>
          )}
          {meetLink && !isPast && (
            <button
              type="button"
              onClick={() => {
                invoke('open_external_url', { url: meetLink }).catch(() => {
                  toast.error('브라우저를 열지 못했습니다. 잠시 후 다시 시도해주세요.')
                })
              }}
              className="inline-flex items-center gap-1 rounded-md bg-[#1a73e8] px-2.5 py-1 text-xs font-medium text-white hover:bg-[#1666d6]"
            >
              <Video className="h-3.5 w-3.5" />
              참여
            </button>
          )}
          {!meetLink && !isPast && !match && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                // Send the user straight to the recording page with the calendar
                // event's title pre-filled. The recording page reads `?title=`
                // when seeding a fresh session.
                const params = new URLSearchParams()
                if (event.title) params.set('title', event.title)
                window.location.href = `/record${params.toString() ? `?${params}` : ''}`
              }}
              title="이 회의 녹음 시작"
            >
              <Mic className="mr-1 h-3.5 w-3.5" />
              녹음
            </Button>
          )}
          {event.html_link && (
            <button
              type="button"
              onClick={() => {
                invoke('open_external_url', { url: event.html_link! }).catch(() => {
                  toast.error('브라우저를 열지 못했습니다. 잠시 후 다시 시도해주세요.')
                })
              }}
              className="rounded-md p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600"
              title="캘린더에서 열기"
            >
              <ExternalLink className="h-3.5 w-3.5" />
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
