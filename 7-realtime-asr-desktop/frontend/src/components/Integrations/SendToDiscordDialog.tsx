'use client'

import { useEffect, useMemo, useState } from 'react'
import { ExternalLink, Loader2, Send } from 'lucide-react'
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
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { toast } from 'sonner'
import {
  listWebhooks,
  sendToDiscordWebhook,
  type DiscordWebhook,
} from '@/services/discordService'
import { useRouter } from 'next/navigation'

interface SendToDiscordDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** Called when the dialog is opened — must return the markdown to send. */
  getMarkdown: () => Promise<string>
  /** Optional meeting title used as inline header / attachment file name. */
  meetingTitle?: string
}

export function SendToDiscordDialog({
  open,
  onOpenChange,
  getMarkdown,
  meetingTitle,
}: SendToDiscordDialogProps) {
  const router = useRouter()
  const [markdown, setMarkdown] = useState<string>('')
  const [isLoadingMarkdown, setIsLoadingMarkdown] = useState(false)
  const [webhooks, setWebhooks] = useState<DiscordWebhook[]>([])
  const [isLoadingWebhooks, setIsLoadingWebhooks] = useState(false)
  const [selectedId, setSelectedId] = useState<string>('')
  const [isSending, setIsSending] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!open) {
      setError(null)
      setMarkdown('')
      setSelectedId('')
      return
    }

    setIsLoadingMarkdown(true)
    getMarkdown()
      .then((md) => {
        if (!md) {
          setError('보낼 내용이 비어 있어요. 먼저 요약을 생성하세요.')
          return
        }
        setMarkdown(md)
      })
      .catch((e) => setError(e?.message || 'markdown_load_failed'))
      .finally(() => setIsLoadingMarkdown(false))

    setIsLoadingWebhooks(true)
    listWebhooks()
      .then(setWebhooks)
      .catch(() => setWebhooks([]))
      .finally(() => setIsLoadingWebhooks(false))
  }, [open, getMarkdown])

  const previewLines = useMemo(
    () => markdown.split('\n').slice(0, 6).join('\n'),
    [markdown],
  )

  const selected = useMemo(
    () => webhooks.find((w) => w.id === selectedId) ?? null,
    [webhooks, selectedId],
  )

  const handleSend = async () => {
    if (!selected || !markdown) return
    setIsSending(true)
    setError(null)
    try {
      await sendToDiscordWebhook(selected.url, markdown, meetingTitle)
      toast.success(`Discord ${selected.label}에 전송했습니다`)
      onOpenChange(false)
    } catch (e: any) {
      setError(e?.message || 'send_failed')
    } finally {
      setIsSending(false)
    }
  }

  const canSend = !isSending && !isLoadingMarkdown && markdown && selected

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Discord로 전송</DialogTitle>
          <DialogDescription>
            저장된 Webhook 채널 중 하나를 골라 회의 요약을 보냅니다. 2000자가 넘으면
            <code className="mx-1 rounded bg-gray-100 px-1 text-xs">.md</code>
            첨부 파일로 전송돼요.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-2">
          <div className="space-y-1.5">
            <label className="text-sm font-medium text-gray-700">Webhook</label>

            {isLoadingWebhooks ? (
              <div className="flex h-10 items-center px-3 text-sm text-gray-400">
                <Loader2 className="mr-2 h-4 w-4 animate-spin" /> 불러오는 중…
              </div>
            ) : webhooks.length === 0 ? (
              <div className="rounded-md border border-dashed border-gray-200 bg-gray-50 px-4 py-4 text-center text-xs text-gray-600">
                <p>저장된 Webhook이 없어요.</p>
                <button
                  type="button"
                  onClick={() => {
                    onOpenChange(false)
                    router.push('/settings')
                  }}
                  className="mt-2 inline-flex items-center gap-1 text-xs text-blue-600 hover:underline"
                >
                  <ExternalLink className="h-3 w-3" />
                  설정에서 Webhook 추가하기
                </button>
              </div>
            ) : (
              <Select value={selectedId} onValueChange={setSelectedId}>
                <SelectTrigger>
                  <SelectValue placeholder="Webhook 선택" />
                </SelectTrigger>
                <SelectContent>
                  {webhooks.map((w) => (
                    <SelectItem key={w.id} value={w.id}>
                      {w.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
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
                  {markdown.length > 1990 && ' · 첨부 파일로 전송'}
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

