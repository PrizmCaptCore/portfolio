'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { invoke } from '@tauri-apps/api/core'
import {
  CloudDownload,
  Eye,
  Loader2,
  RefreshCw,
  Trash2,
  Users,
} from 'lucide-react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogTitle,
} from '@/components/ui/dialog'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { VisuallyHidden } from '@/components/ui/visually-hidden'
import { useSidebar } from '@/components/Sidebar/SidebarProvider'
import { useAuth } from '@/contexts/AuthContext'
import {
  deleteCloudMeeting,
  getCloudMeeting,
  listCloudMeetings,
  listTeamMeetings,
  type CloudMeetingDetail,
  type CloudMeetingSummary,
} from '@/services/meetingsService'
import { listTeams, type Team } from '@/services/teamsService'

interface BackupsSectionProps {
  accessToken: string | null
}

/**
 * Profile-page section that lists the user's cloud-backed meetings, lets them
 * preview a snapshot, restore it back into local sqlite, or delete it.
 *
 * Two tabs:
 *  - "내 회의" — meetings the caller uploaded (their own backups, regardless
 *    of whether they're shared with a team)
 *  - "팀 회의" — meetings shared into one of the caller's teams. Sub-tabbed
 *    per team. Shows owner info; restore is allowed for everyone, delete is
 *    only allowed for the owner or a team admin.
 */
export function BackupsSection({ accessToken }: BackupsSectionProps) {
  const { user } = useAuth()
  const [tab, setTab] = useState<'mine' | 'team'>('mine')

  if (!accessToken) return null

  return (
    <section className="space-y-4 rounded-lg border border-gray-200 bg-white p-6">
      <div className="flex items-center gap-2">
        <CloudDownload className="h-5 w-5 text-gray-700" />
        <h2 className="text-lg font-semibold text-gray-900">내 백업</h2>
      </div>

      <Tabs value={tab} onValueChange={(v) => setTab(v as 'mine' | 'team')}>
        <TabsList>
          <TabsTrigger value="mine">내 회의</TabsTrigger>
          <TabsTrigger value="team">팀 회의</TabsTrigger>
        </TabsList>
        <TabsContent value="mine" className="mt-4">
          <MyBackupsTab
            accessToken={accessToken}
            currentUserEmail={user?.email}
          />
        </TabsContent>
        <TabsContent value="team" className="mt-4">
          <TeamBackupsTab
            accessToken={accessToken}
            currentUserEmail={user?.email}
          />
        </TabsContent>
      </Tabs>
    </section>
  )
}

// ────────────────────────────────────────────────────────────────────────────
// "내 회의" tab — own backups
// ────────────────────────────────────────────────────────────────────────────

interface TabBaseProps {
  accessToken: string
  currentUserEmail: string | undefined
}

function MyBackupsTab({ accessToken, currentUserEmail }: TabBaseProps) {
  const [items, setItems] = useState<CloudMeetingSummary[] | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Stable identity — BackupTable's effect re-runs whenever `fetcher` changes,
  // so an inline arrow would loop forever.
  const fetcher = useCallback(
    () => listCloudMeetings(accessToken),
    [accessToken],
  )

  return (
    <BackupTable
      items={items}
      setItems={setItems}
      isLoading={isLoading}
      setIsLoading={setIsLoading}
      error={error}
      setError={setError}
      fetcher={fetcher}
      accessToken={accessToken}
      currentUserEmail={currentUserEmail}
      emptyMessage="아직 백업한 회의가 없습니다. 회의 상세 화면의 '백업' 버튼으로 업로드할 수 있어요."
      showOwner={false}
    />
  )
}

// ────────────────────────────────────────────────────────────────────────────
// "팀 회의" tab — meetings shared into one of the user's teams
// ────────────────────────────────────────────────────────────────────────────

function TeamBackupsTab({ accessToken, currentUserEmail }: TabBaseProps) {
  const [teams, setTeams] = useState<Team[] | null>(null)
  const [teamsError, setTeamsError] = useState<string | null>(null)
  const [selectedUuid, setSelectedUuid] = useState<string | null>(null)

  const [items, setItems] = useState<CloudMeetingSummary[] | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // First pass: discover the user's teams to populate the team picker.
  useEffect(() => {
    let cancelled = false
    listTeams(accessToken)
      .then((list) => {
        if (cancelled) return
        setTeams(list)
        setSelectedUuid((prev) => {
          if (prev && list.some((t) => t.uuid === prev)) return prev
          return list[0]?.uuid ?? null
        })
        if (list.length === 0) setIsLoading(false)
      })
      .catch((err) => {
        if (!cancelled) {
          setTeamsError(err instanceof Error ? err.message : String(err))
          setIsLoading(false)
        }
      })
    return () => {
      cancelled = true
    }
  }, [accessToken])

  const myTeam = useMemo(
    () => teams?.find((t) => t.uuid === selectedUuid) ?? null,
    [teams, selectedUuid],
  )

  const fetcher = useMemo(() => {
    if (!selectedUuid) return null
    return () => listTeamMeetings(accessToken, selectedUuid)
  }, [accessToken, selectedUuid])

  if (teamsError) {
    return <p className="text-sm text-red-600">{teamsError}</p>
  }

  if (teams && teams.length === 0) {
    return (
      <p className="text-sm text-gray-500">
        소속된 팀이 없습니다. 팀에 초대받으면 이 영역에 공유 회의가 보여요.
      </p>
    )
  }

  return (
    <div className="space-y-3">
      {teams && teams.length > 1 ? (
        <div className="flex flex-wrap gap-2">
          {teams.map((team) => {
            const isActive = team.uuid === selectedUuid
            return (
              <button
                key={team.uuid}
                type="button"
                onClick={() => setSelectedUuid(team.uuid)}
                className={`rounded-full border px-3 py-1 text-xs transition-colors ${
                  isActive
                    ? 'border-blue-300 bg-blue-50 text-blue-700'
                    : 'border-gray-200 bg-white text-gray-700 hover:bg-gray-50'
                }`}
              >
                {team.name}
              </button>
            )
          })}
        </div>
      ) : null}

      {fetcher ? (
        <BackupTable
          items={items}
          setItems={setItems}
          isLoading={isLoading}
          setIsLoading={setIsLoading}
          error={error}
          setError={setError}
          fetcher={fetcher}
          accessToken={accessToken}
          currentUserEmail={currentUserEmail}
          isTeamAdmin={myTeam?.my_role === 'admin'}
          emptyMessage="이 팀에 공유된 회의가 아직 없습니다."
          showOwner={true}
        />
      ) : null}
    </div>
  )
}

// ────────────────────────────────────────────────────────────────────────────
// Shared table — handles list, view, restore, delete for either source
// ────────────────────────────────────────────────────────────────────────────

interface BackupTableProps {
  items: CloudMeetingSummary[] | null
  setItems: (
    next:
      | CloudMeetingSummary[]
      | null
      | ((prev: CloudMeetingSummary[] | null) => CloudMeetingSummary[] | null),
  ) => void
  isLoading: boolean
  setIsLoading: (v: boolean) => void
  error: string | null
  setError: (v: string | null) => void
  fetcher: () => Promise<CloudMeetingSummary[]>
  accessToken: string
  currentUserEmail: string | undefined
  isTeamAdmin?: boolean
  emptyMessage: string
  showOwner: boolean
}

function BackupTable({
  items,
  setItems,
  isLoading,
  setIsLoading,
  error,
  setError,
  fetcher,
  accessToken,
  currentUserEmail,
  isTeamAdmin = false,
  emptyMessage,
  showOwner,
}: BackupTableProps) {
  // Sidebar refetch lets the restored meeting show up in the left-pane
  // meeting list without forcing the user to refresh the app. The provider
  // is mounted at the app shell, so this hook is safe wherever the section
  // renders.
  const { refetchMeetings } = useSidebar()

  const [pendingUuid, setPendingUuid] = useState<string | null>(null)
  const [viewing, setViewing] = useState<CloudMeetingDetail | null>(null)
  const [isFetchingDetail, setIsFetchingDetail] = useState(false)
  const [viewOpen, setViewOpen] = useState(false)

  // Re-fetch whenever the underlying fetcher changes (i.e. caller switched
  // teams or tabs). Resetting items first avoids flashing stale data from the
  // previous fetcher.
  useEffect(() => {
    let cancelled = false
    setItems(null)
    setIsLoading(true)
    setError(null)
    fetcher()
      .then((list) => {
        if (!cancelled) setItems(list)
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : String(err))
        }
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false)
      })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fetcher])

  const refresh = async () => {
    setIsLoading(true)
    setError(null)
    try {
      const list = await fetcher()
      setItems(list)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setIsLoading(false)
    }
  }

  const handleView = async (item: CloudMeetingSummary) => {
    setIsFetchingDetail(true)
    setViewOpen(true)
    setViewing(null)
    try {
      const detail = await getCloudMeeting(accessToken, item.uuid)
      setViewing(detail)
    } catch (err) {
      toast.error('백업을 불러오지 못했습니다', {
        description: err instanceof Error ? err.message : String(err),
      })
      setViewOpen(false)
    } finally {
      setIsFetchingDetail(false)
    }
  }

  const handleRestore = async (item: CloudMeetingSummary) => {
    setPendingUuid(item.uuid)
    try {
      const detail = await getCloudMeeting(accessToken, item.uuid)
      await invoke('api_restore_cloud_meeting', {
        meetingId: detail.client_meeting_id,
        title: detail.title,
        startedAt: detail.started_at,
        transcriptSegments: detail.transcript_segments,
        summary: detail.summary,
      })
      // Refresh the sidebar's cached meeting list so the restored row shows
      // up immediately. Without this, the sidebar keeps the stale list it
      // fetched on mount until the user navigates somewhere that re-triggers
      // the fetch.
      await refetchMeetings()
      toast.success('회의를 로컬에 복원했습니다', {
        description: '왼쪽 사이드바 회의록 목록에서 확인하세요',
      })
    } catch (err) {
      toast.error('복원에 실패했습니다', {
        description: err instanceof Error ? err.message : String(err),
      })
    } finally {
      setPendingUuid(null)
    }
  }

  const handleDelete = async (item: CloudMeetingSummary) => {
    if (
      !window.confirm(
        `'${item.title}' 백업을 삭제하시겠습니까? 클라우드 데이터가 영구 삭제됩니다.`,
      )
    ) {
      return
    }
    setPendingUuid(item.uuid)
    try {
      await deleteCloudMeeting(accessToken, item.uuid)
      setItems((prev) =>
        prev ? prev.filter((i) => i.uuid !== item.uuid) : prev,
      )
      toast.success('백업을 삭제했습니다')
    } catch (err) {
      toast.error('백업 삭제에 실패했습니다', {
        description: err instanceof Error ? err.message : String(err),
      })
    } finally {
      setPendingUuid(null)
    }
  }

  return (
    <>
      <div className="mb-3 flex justify-end">
        <Button
          variant="outline"
          size="sm"
          onClick={refresh}
          disabled={isLoading}
          title="새로고침"
        >
          <RefreshCw
            className={`h-4 w-4 ${isLoading ? 'animate-spin' : ''}`}
          />
          <span className="hidden sm:inline">새로고침</span>
        </Button>
      </div>

      {isLoading && items === null ? (
        <div className="flex items-center justify-center py-8 text-gray-400">
          <Loader2 className="h-5 w-5 animate-spin" />
        </div>
      ) : error ? (
        <p className="text-sm text-red-600">{error}</p>
      ) : !items || items.length === 0 ? (
        <p className="text-sm text-gray-500">{emptyMessage}</p>
      ) : (
        <div className="overflow-hidden rounded-md border border-gray-200">
          <table className="w-full table-fixed text-sm">
            {/* Fixed column widths so the action buttons stay on-screen even
                when titles are long; the title cell soaks up the remaining
                space and truncates. */}
            <colgroup>
              <col />
              {showOwner ? <col className="w-[140px]" /> : null}
              <col className="w-[160px]" />
              <col className="w-[88px]" />
              <col className="w-[200px]" />
            </colgroup>
            <thead className="bg-gray-50 text-left text-xs uppercase tracking-wide text-gray-500">
              <tr>
                <th className="px-3 py-2 font-medium">제목</th>
                {showOwner ? (
                  <th className="px-3 py-2 font-medium">공유자</th>
                ) : null}
                <th className="px-3 py-2 font-medium">백업일</th>
                <th className="px-3 py-2 font-medium">길이</th>
                <th className="px-3 py-2" />
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {items.map((item) => (
                <BackupRow
                  key={item.uuid}
                  item={item}
                  pending={pendingUuid === item.uuid}
                  showOwner={showOwner}
                  canDelete={
                    item.owner_email === currentUserEmail || isTeamAdmin
                  }
                  onView={() => handleView(item)}
                  onRestore={() => handleRestore(item)}
                  onDelete={() => handleDelete(item)}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}

      <ViewBackupDialog
        open={viewOpen}
        onOpenChange={(o) => {
          setViewOpen(o)
          if (!o) setViewing(null)
        }}
        isLoading={isFetchingDetail}
        detail={viewing}
      />
    </>
  )
}

// ────────────────────────────────────────────────────────────────────────────
// Row + view dialog
// ────────────────────────────────────────────────────────────────────────────

interface BackupRowProps {
  item: CloudMeetingSummary
  pending: boolean
  showOwner: boolean
  canDelete: boolean
  onView: () => void
  onRestore: () => void
  onDelete: () => void
}

function BackupRow({
  item,
  pending,
  showOwner,
  canDelete,
  onView,
  onRestore,
  onDelete,
}: BackupRowProps) {
  return (
    <tr className="bg-white">
      <td className="px-3 py-2.5">
        <div className="flex items-center gap-1.5 min-w-0">
          <span className="min-w-0 flex-1 truncate font-medium text-gray-900">
            {item.title || '(제목 없음)'}
          </span>
          {item.team_uuid ? (
            <span
              title={`'${item.team_name}' 팀 공유`}
              className="inline-flex shrink-0 items-center gap-0.5 rounded-full bg-amber-50 px-1.5 py-0.5 text-[10px] font-medium text-amber-700"
            >
              <Users className="h-2.5 w-2.5 shrink-0" />
              <span className="max-w-[4ch] truncate">{item.team_name}</span>
            </span>
          ) : null}
        </div>
        {item.detected_language || item.target_language ? (
          <div className="mt-0.5 truncate text-xs text-gray-500">
            {item.detected_language || '—'} → {item.target_language || '—'}
          </div>
        ) : null}
      </td>
      {showOwner ? (
        <td className="px-3 py-2.5 whitespace-nowrap">
          <div className="text-xs font-medium text-gray-700">
            {item.owner_name}
          </div>
          <div className="text-[10px] text-gray-400 truncate max-w-[140px]">
            {item.owner_email}
          </div>
        </td>
      ) : null}
      <td className="px-3 py-2.5 whitespace-nowrap text-xs text-gray-500">
        {formatDate(item.created_at)}
      </td>
      <td className="px-3 py-2.5 whitespace-nowrap text-xs text-gray-500">
        {formatDuration(item.duration_seconds)}
      </td>
      <td className="px-3 py-2.5 whitespace-nowrap text-right">
        <div className="inline-flex items-center gap-1">
          <button
            type="button"
            onClick={onView}
            disabled={pending}
            className="inline-flex h-8 items-center gap-1 rounded-md px-2 text-xs text-gray-700 transition-colors hover:bg-gray-100 disabled:opacity-50"
            title="내용 보기"
          >
            <Eye className="h-3.5 w-3.5" />
            <span>보기</span>
          </button>
          <button
            type="button"
            onClick={onRestore}
            disabled={pending}
            className="inline-flex h-8 items-center gap-1 rounded-md px-2 text-xs text-blue-700 transition-colors hover:bg-blue-50 disabled:opacity-50"
            title="로컬로 복원"
          >
            {pending ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <CloudDownload className="h-3.5 w-3.5" />
            )}
            <span>복원</span>
          </button>
          {canDelete ? (
            <button
              type="button"
              onClick={onDelete}
              disabled={pending}
              className="inline-flex h-8 items-center gap-1 rounded-md px-2 text-xs text-red-600 transition-colors hover:bg-red-50 disabled:opacity-50"
              title="백업 삭제"
            >
              <Trash2 className="h-3.5 w-3.5" />
            </button>
          ) : null}
        </div>
      </td>
    </tr>
  )
}

interface ViewBackupDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  isLoading: boolean
  detail: CloudMeetingDetail | null
}

function ViewBackupDialog({
  open,
  onOpenChange,
  isLoading,
  detail,
}: ViewBackupDialogProps) {
  const segments = useMemo(() => {
    if (!detail) return []
    return Array.isArray(detail.transcript_segments)
      ? detail.transcript_segments
      : []
  }, [detail])

  const summaryDisplay = useMemo(() => {
    if (!detail) return null
    const s = detail.summary
    if (!s) return null
    if (typeof s === 'string') return s
    if (typeof s === 'object' && s !== null) {
      const obj = s as Record<string, unknown>
      if (typeof obj.markdown === 'string') return obj.markdown
    }
    try {
      return JSON.stringify(s, null, 2)
    } catch {
      return null
    }
  }, [detail])

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl max-h-[80vh] overflow-y-auto">
        <VisuallyHidden>
          <DialogTitle>백업 미리보기</DialogTitle>
        </VisuallyHidden>
        {isLoading ? (
          <div className="flex items-center justify-center py-16 text-gray-400">
            <Loader2 className="h-6 w-6 animate-spin" />
          </div>
        ) : !detail ? (
          <p className="py-8 text-center text-sm text-gray-500">
            데이터를 불러오지 못했습니다.
          </p>
        ) : (
          <div className="space-y-5 pb-2">
            <div>
              <h3 className="text-lg font-semibold text-gray-900">
                {detail.title}
              </h3>
              <div className="mt-1 text-xs text-gray-500">
                {formatDate(detail.created_at)} ·{' '}
                {formatDuration(detail.duration_seconds)} ·{' '}
                {detail.detected_language || '—'} →{' '}
                {detail.target_language || '—'}
                {detail.team_name ? <> · 팀: {detail.team_name}</> : null}
              </div>
              <div className="mt-0.5 text-xs text-gray-400">
                업로더: {detail.owner_name} ({detail.owner_email})
              </div>
            </div>

            {summaryDisplay ? (
              <div>
                <h4 className="mb-1 text-sm font-medium text-gray-700">
                  요약
                </h4>
                <pre className="max-h-60 overflow-auto whitespace-pre-wrap rounded-md bg-gray-50 p-3 text-xs text-gray-800">
                  {summaryDisplay}
                </pre>
              </div>
            ) : null}

            <div>
              <h4 className="mb-1 text-sm font-medium text-gray-700">
                트랜스크립트 ({segments.length}개)
              </h4>
              <div className="max-h-80 overflow-y-auto rounded-md border border-gray-200">
                <ul className="divide-y divide-gray-100">
                  {segments.map((seg, idx) => {
                    const s = seg as Record<string, unknown>
                    const text =
                      typeof s.text === 'string' ? s.text : ''
                    const time =
                      typeof s.timestamp === 'string' ? s.timestamp : ''
                    const translated =
                      typeof s.translated_text === 'string'
                        ? s.translated_text
                        : null
                    return (
                      <li key={idx} className="px-3 py-2 text-xs">
                        <div className="text-gray-400">{time}</div>
                        <div className="mt-0.5 text-gray-900">{text}</div>
                        {translated ? (
                          <div className="mt-0.5 text-gray-500 italic">
                            {translated}
                          </div>
                        ) : null}
                      </li>
                    )
                  })}
                </ul>
              </div>
            </div>
          </div>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            닫기
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function formatDate(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString('ko-KR', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function formatDuration(seconds: number | null): string {
  if (seconds == null || !Number.isFinite(seconds)) return '—'
  const total = Math.max(0, Math.round(seconds))
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60
  if (h > 0) return `${h}시간 ${m}분`
  if (m > 0) return `${m}분 ${s}초`
  return `${s}초`
}
