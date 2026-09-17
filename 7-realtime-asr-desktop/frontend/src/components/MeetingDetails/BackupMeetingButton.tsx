'use client'

import { useEffect, useState } from 'react'
import { Check, ChevronDown, Cloud, Loader2, Users } from 'lucide-react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { useAuth } from '@/contexts/AuthContext'
import { uploadMeeting } from '@/services/meetingsService'
import { listTeams, type Team } from '@/services/teamsService'
import type { Summary, Transcript } from '@/types'

interface BackupMeetingButtonProps {
  meeting: {
    id: string
    title: string
    created_at: string
  }
  transcripts: Transcript[]
  summary: Summary | null
}

type BackupTarget =
  | { kind: 'private' }
  | { kind: 'team'; uuid: string; name: string }

/**
 * Manual cloud-backup trigger for the active meeting.
 *
 * Split-button UX: the dropdown lets the user pick where the backup goes —
 * private to themselves or shared with one of their teams. Re-clicking with a
 * different target re-uploads to the same cloud row (upsert keyed on
 * client_meeting_id) and changes its team association in place.
 *
 * Audio is intentionally not uploaded; only transcript + summary text.
 */
export function BackupMeetingButton({
  meeting,
  transcripts,
  summary,
}: BackupMeetingButtonProps) {
  const { accessToken, isAuthenticated } = useAuth()
  const [isUploading, setIsUploading] = useState(false)
  const [lastTarget, setLastTarget] = useState<BackupTarget | null>(null)
  const [teams, setTeams] = useState<Team[]>([])

  // Lazy team list fetch — we want it ready by the time the user opens the
  // dropdown, but we don't need it on mount of every meeting view. Fetch is
  // cheap and the list is short-lived (refetched on each mount).
  useEffect(() => {
    if (!accessToken) return
    let cancelled = false
    listTeams(accessToken)
      .then((list) => {
        if (!cancelled) setTeams(list)
      })
      .catch(() => {
        // silent — sharing dropdown will just show "팀 없음"
      })
    return () => {
      cancelled = true
    }
  }, [accessToken])

  if (!isAuthenticated || !accessToken) return null

  const upload = async (target: BackupTarget) => {
    setIsUploading(true)
    const startedAt = performance.now()
    try {
      const lastEnd = transcripts.reduce<number | null>((acc, t) => {
        const end =
          typeof t.audio_end_time === 'number' ? t.audio_end_time : null
        if (end === null) return acc
        return acc === null || end > acc ? end : acc
      }, null)

      const payload = {
        client_meeting_id: meeting.id,
        title: meeting.title,
        started_at: meeting.created_at || null,
        duration_seconds: lastEnd !== null ? Math.round(lastEnd) : null,
        transcript_segments: transcripts,
        summary: summary ?? {},
        team_uuid: target.kind === 'team' ? target.uuid : null,
      }

      const serialized = JSON.stringify(payload)
      const sizeBytes = new TextEncoder().encode(serialized).length
      const sizeMb = (sizeBytes / 1024 / 1024).toFixed(2)
      console.info(
        '[BackupMeeting] uploading',
        meeting.id,
        `target=${target.kind === 'team' ? `team:${target.name}` : 'private'}`,
        `segments=${transcripts.length}`,
        `payload=${sizeMb}MB`,
      )

      await uploadMeeting(accessToken, payload)
      const elapsedMs = Math.round(performance.now() - startedAt)
      console.info(
        `[BackupMeeting] upload OK in ${elapsedMs}ms (${sizeMb}MB)`,
      )
      setLastTarget(target)
      toast.success(
        target.kind === 'team'
          ? `'${target.name}' 팀에 공유했습니다`
          : '회의를 클라우드에 백업했습니다',
      )
    } catch (err) {
      const elapsedMs = Math.round(performance.now() - startedAt)
      const message = err instanceof Error ? err.message : String(err)
      console.error(
        '[BackupMeeting] upload failed',
        meeting.id,
        `after ${elapsedMs}ms`,
        err,
      )
      toast.error('백업에 실패했습니다', {
        description: `${message} (${elapsedMs}ms)`,
      })
    } finally {
      setIsUploading(false)
    }
  }

  const successLabel =
    lastTarget?.kind === 'team' ? `'${lastTarget.name}' 공유됨` : '백업됨'
  const idleLabel = '백업'

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="outline"
          size="sm"
          disabled={isUploading}
          title={
            lastTarget
              ? `${successLabel} · 다른 곳으로도 백업하려면 메뉴에서 선택`
              : '클라우드에 백업하거나 팀에 공유'
          }
        >
          {isUploading ? (
            <Loader2 className="animate-spin" />
          ) : lastTarget ? (
            <Check className="text-green-600" />
          ) : (
            <Cloud />
          )}
          <span className="hidden lg:inline">
            {isUploading ? '백업 중…' : lastTarget ? successLabel : idleLabel}
          </span>
          <ChevronDown className="h-3 w-3 opacity-50" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-52">
        <DropdownMenuLabel>백업 대상</DropdownMenuLabel>
        <DropdownMenuItem
          onClick={() => upload({ kind: 'private' })}
          disabled={isUploading}
        >
          <Cloud className="mr-2 h-4 w-4" />
          내게만 (비공개)
        </DropdownMenuItem>
        {teams.length > 0 ? (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuLabel className="text-xs font-normal text-gray-400">
              팀 공유
            </DropdownMenuLabel>
            {teams.map((team) => (
              <DropdownMenuItem
                key={team.uuid}
                onClick={() =>
                  upload({ kind: 'team', uuid: team.uuid, name: team.name })
                }
                disabled={isUploading}
              >
                <Users className="mr-2 h-4 w-4" />
                <span className="truncate">{team.name}</span>
              </DropdownMenuItem>
            ))}
          </>
        ) : null}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
