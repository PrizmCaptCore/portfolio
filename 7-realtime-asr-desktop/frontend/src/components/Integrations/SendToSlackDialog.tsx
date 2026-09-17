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
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { toast } from 'sonner'
import {
  listSlackChannels,
  sendToSlack,
  type SlackChannel,
} from '@/services/integrationService'

interface SendToSlackDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** Called when the dialog is opened — must return the markdown to send. */
  getMarkdown: () => Promise<string>
}

export function SendToSlackDialog({
  open,
  onOpenChange,
  getMarkdown,
}: SendToSlackDialogProps) {
  const [markdown, setMarkdown] = useState<string>('')
  const [isLoadingMarkdown, setIsLoadingMarkdown] = useState(false)
  const [channels, setChannels] = useState<SlackChannel[]>([])
  const [isLoadingChannels, setIsLoadingChannels] = useState(false)
  const [selectedChannel, setSelectedChannel] = useState<string>('')
  const [isSending, setIsSending] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!open) {
      setError(null)
      setMarkdown('')
      setSelectedChannel('')
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
    listSlackChannels()
      .then((res) => setChannels(res.channels))
      .catch((e) => setError(e?.message || 'channels_load_failed'))
      .finally(() => setIsLoadingChannels(false))
  }, [open, getMarkdown])

  const previewLines = useMemo(
    () => markdown.split('\n').slice(0, 6).join('\n'),
    [markdown],
  )

  const handleSend = async () => {
    if (!selectedChannel || !markdown) return
    setIsSending(true)
    setError(null)
    try {
      await sendToSlack(selectedChannel, markdown)
      const channelName =
        channels.find((c) => c.id === selectedChannel)?.name ?? selectedChannel
      toast.success(`Slack #${channelName}에 전송했습니다`)
      onOpenChange(false)
    } catch (e: any) {
      setError(e?.message || 'send_failed')
    } finally {
      setIsSending(false)
    }
  }

  const canSend =
    !isSending && !isLoadingMarkdown && markdown && selectedChannel

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Slack으로 전송</DialogTitle>
          <DialogDescription>
            회의 요약을 선택한 채널에 전송합니다. 전송 전 내용을 꼭 확인하세요.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-2">
          {/* Channel picker */}
          <div className="space-y-1.5">
            <label className="text-sm font-medium text-gray-700">채널</label>
            <Select
              value={selectedChannel}
              onValueChange={setSelectedChannel}
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
                {channels.map((c) => (
                  <SelectItem key={c.id} value={c.id}>
                    {c.is_private ? '🔒 ' : '# '}
                    {c.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
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
