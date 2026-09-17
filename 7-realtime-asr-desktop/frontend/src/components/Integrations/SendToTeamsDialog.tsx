'use client'

import { useEffect, useMemo, useState } from 'react'
import { Loader2, Send } from 'lucide-react'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { toast } from 'sonner'
import {
  listTeamsChannels,
  sendToTeams,
  type TeamsChannel,
} from '@/services/integrationService'

interface SendToTeamsDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** Called when the dialog is opened — must return the markdown to send. */
  getMarkdown: () => Promise<string>
}

export function SendToTeamsDialog({
  open,
  onOpenChange,
  getMarkdown,
}: SendToTeamsDialogProps) {
  const [markdown, setMarkdown] = useState<string>('')
  const [isLoadingMarkdown, setIsLoadingMarkdown] = useState(false)
  const [channels, setChannels] = useState<TeamsChannel[]>([])
  const [isLoadingChannels, setIsLoadingChannels] = useState(false)
  // Combined "<team_id>::<channel_id>" key, since channel ids in Graph aren't
  // globally unique without their team scope. Split before sending.
  const [selectedKey, setSelectedKey] = useState<string>('')
  const [isSending, setIsSending] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!open) {
      setError(null)
      setMarkdown('')
      setSelectedKey('')
      return
    }

    setIsLoadingMarkdown(true)
    getMarkdown()
      .then((md) => {
        if (!md) {
          setError('요약이 아직 없어요. 먼저 요약을 생성하세요.')
          return
        }
        setMarkdown(md)
      })
      .catch((e) => setError(e?.message || 'markdown_load_failed'))
      .finally(() => setIsLoadingMarkdown(false))

    setIsLoadingChannels(true)
    listTeamsChannels()
      .then((res) => setChannels(res.channels))
      .catch((e) => {
        const code = e?.message || 'channels_load_failed'
        // `graph_error` (502 from gateway) is the typical signal that the
        // user connected with a personal Microsoft account — Graph's Teams
        // endpoints are gated to work/school tenants. Surface a friendly
        // explanation rather than the raw code.
        if (code === 'graph_error') {
          setError(
            '회사/학교 Microsoft 계정 (Microsoft 365 / Azure AD) 으로 다시 연결해 주세요. 개인 Microsoft 계정 (@live.com, @hotmail.com, @outlook.com) 은 Teams 채널 데이터를 받아올 수 없어요.',
          )
        } else {
          setError(code)
        }
      })
      .finally(() => setIsLoadingChannels(false))
  }, [open, getMarkdown])

  // Group channels by team for the picker. Sorted alphabetically per team
  // so users with many teams can scan quickly.
  const groupedByTeam = useMemo(() => {
    const m = new Map<string, { team_name: string; channels: TeamsChannel[] }>()
    for (const ch of channels) {
      const entry = m.get(ch.team_id) ?? { team_name: ch.team_name, channels: [] }
      entry.channels.push(ch)
      m.set(ch.team_id, entry)
    }
    for (const [, entry] of m) {
      entry.channels.sort((a, b) => a.name.localeCompare(b.name))
    }
    return [...m.entries()].sort(([, a], [, b]) =>
      a.team_name.localeCompare(b.team_name),
    )
  }, [channels])

  const previewLines = useMemo(
    () => markdown.split('\n').slice(0, 6).join('\n'),
    [markdown],
  )

  const selected = useMemo(() => {
    if (!selectedKey) return null
    const [team_id, channel_id] = selectedKey.split('::')
    return channels.find(
      (c) => c.team_id === team_id && c.id === channel_id,
    )
  }, [selectedKey, channels])

  const handleSend = async () => {
    if (!selected || !markdown) return
    setIsSending(true)
    setError(null)
    try {
      await sendToTeams(selected.team_id, selected.id, markdown)
      toast.success(
        `Teams ${selected.team_name} / ${selected.name}에 전송했습니다`,
      )
      onOpenChange(false)
    } catch (e: any) {
      setError(e?.message || 'send_failed')
    } finally {
      setIsSending(false)
    }
  }

  const canSend =
    !isSending && !isLoadingMarkdown && markdown && selected

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Microsoft Teams로 전송</DialogTitle>
          <DialogDescription>
            회의 요약을 선택한 팀의 채널에 전송합니다. 전송 전 내용을 꼭 확인하세요.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-2">
          {/* Team / channel picker — grouped by team. */}
          <div className="space-y-1.5">
            <label className="text-sm font-medium text-gray-700">팀 / 채널</label>
            <Select
              value={selectedKey}
              onValueChange={setSelectedKey}
              disabled={isLoadingChannels || channels.length === 0}
            >
              <SelectTrigger>
                <SelectValue
                  placeholder={
                    isLoadingChannels ? '채널 불러오는 중…' : '채널 선택'
                  }
                />
              </SelectTrigger>
              <SelectContent>
                {groupedByTeam.map(([team_id, { team_name, channels: chs }]) => (
                  <SelectGroup key={team_id}>
                    <SelectLabel>{team_name}</SelectLabel>
                    {chs.map((c) => (
                      <SelectItem key={c.id} value={`${team_id}::${c.id}`}>
                        # {c.name}
                      </SelectItem>
                    ))}
                  </SelectGroup>
                ))}
              </SelectContent>
            </Select>
            {!isLoadingChannels && !error && channels.length === 0 && (
              <p className="text-xs text-gray-500">
                가입한 Teams가 없어요. 회사/학교 Microsoft 계정으로 연결되어 있는지, 어떤 팀에 가입되어
                있는지 확인해주세요.
              </p>
            )}
          </div>

          {/* Preview */}
          <div className="space-y-1.5">
            <div className="flex items-center justify-between">
              <label className="text-sm font-medium text-gray-700">
                전송 내용 미리보기
              </label>
              {markdown && (
                <span className="text-xs text-gray-500">
                  {markdown.length.toLocaleString()}자
                </span>
              )}
            </div>
            <div className="max-h-40 overflow-y-auto rounded-md border border-gray-200 bg-gray-50 p-3 text-xs">
              {isLoadingMarkdown ? (
                <Loader2 className="h-4 w-4 animate-spin text-gray-400" />
              ) : (
                <pre className="whitespace-pre-wrap font-mono text-gray-700">
                  {previewLines}
                  {markdown.split('\n').length > 6 && '\n…'}
                </pre>
              )}
            </div>
          </div>

          {error && (
            <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
              {error}
            </div>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            취소
          </Button>
          <Button onClick={handleSend} disabled={!canSend}>
            {isSending ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <Send className="mr-2 h-4 w-4" />
            )}
            전송
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
