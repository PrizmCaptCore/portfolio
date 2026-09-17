'use client'

import { useEffect, useState } from 'react'
import { ExternalLink, Loader2, Plus, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { toast } from 'sonner'
import {
  DiscordError,
  deleteWebhook,
  listWebhooks,
  saveWebhook,
  validateWebhookUrl,
  type DiscordWebhook,
} from '@/services/discordService'
import { invoke } from '@tauri-apps/api/core'

/**
 * Discord webhook list + add/delete UI. Lives inside IntegrationsSettings
 * below the OAuth-based provider cards.
 *
 * Webhooks are inherently many-per-account (one per channel) so we don't
 * try to pretend they fit the single-account "Connect / Disconnect" pattern
 * other providers use — instead this is a list with a + button.
 */
export function DiscordWebhooksSettings() {
  const [webhooks, setWebhooks] = useState<DiscordWebhook[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [isAddOpen, setIsAddOpen] = useState(false)
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null)

  const refresh = async () => {
    setIsLoading(true)
    try {
      setWebhooks(await listWebhooks())
    } catch {
      // listWebhooks shouldn't fail in practice (local store), but if it does
      // we just show an empty list rather than blocking the settings page.
      setWebhooks([])
    } finally {
      setIsLoading(false)
    }
  }

  useEffect(() => {
    void refresh()
  }, [])

  const handleDelete = async (id: string) => {
    try {
      await deleteWebhook(id)
      await refresh()
      toast.success('Webhook을 삭제했어요')
    } catch (e: any) {
      toast.error(`삭제 실패: ${e?.message ?? e}`)
    } finally {
      setConfirmDeleteId(null)
    }
  }

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-5">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <h3 className="font-semibold text-gray-900">Discord Webhooks</h3>
            <span className="rounded bg-gray-100 px-1.5 py-0.5 text-[10px] text-gray-600">
              직접 전송
            </span>
          </div>
          <p className="mt-0.5 text-sm text-gray-600">
            전송할 채널의 Webhook URL을 추가하면 회의 요약을 그 채널로 직접 보낼 수 있어요. 채널
            우클릭 → 채널 편집 → 연동(Integrations) → 웹후크에서 만들 수 있어요.
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={() => setIsAddOpen(true)}
          className="shrink-0"
        >
          <Plus className="mr-1 h-4 w-4" /> 추가
        </Button>
      </div>

      <div className="mt-4">
        {isLoading ? (
          <div className="flex items-center justify-center py-6 text-gray-400">
            <Loader2 className="h-4 w-4 animate-spin" />
          </div>
        ) : webhooks.length === 0 ? (
          <div className="rounded-md border border-dashed border-gray-200 bg-gray-50 px-4 py-6 text-center text-xs text-gray-500">
            아직 추가된 Webhook이 없어요. 위 "추가" 버튼으로 시작해주세요.
          </div>
        ) : (
          <ul className="divide-y divide-gray-100">
            {webhooks.map((w) => (
              <li
                key={w.id}
                className="flex items-center justify-between gap-3 py-3"
              >
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium text-gray-900">
                    {w.label}
                  </div>
                  <div className="truncate text-xs text-gray-500">{w.url}</div>
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setConfirmDeleteId(w.id)}
                  title="삭제"
                  className="shrink-0 text-gray-500 hover:text-red-600"
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              </li>
            ))}
          </ul>
        )}
      </div>

      <AddWebhookDialog
        open={isAddOpen}
        onOpenChange={setIsAddOpen}
        onAdded={refresh}
      />

      <Dialog
        open={confirmDeleteId !== null}
        onOpenChange={(o) => !o && setConfirmDeleteId(null)}
      >
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>Webhook을 삭제할까요?</DialogTitle>
            <DialogDescription>
              이 작업은 되돌릴 수 없어요. Discord 채널의 Webhook 자체는 삭제되지 않으니 필요하면
              나중에 같은 URL로 다시 추가할 수 있습니다.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirmDeleteId(null)}>
              취소
            </Button>
            <Button
              variant="destructive"
              onClick={() => confirmDeleteId && handleDelete(confirmDeleteId)}
            >
              삭제
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

interface AddWebhookDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  onAdded: () => Promise<void> | void
}

function AddWebhookDialog({ open, onOpenChange, onAdded }: AddWebhookDialogProps) {
  const [label, setLabel] = useState('')
  const [url, setUrl] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [isSaving, setIsSaving] = useState(false)

  useEffect(() => {
    if (!open) {
      setLabel('')
      setUrl('')
      setError(null)
    }
  }, [open])

  const handleSubmit = async () => {
    setError(null)
    if (!url.trim()) {
      setError('Webhook URL을 입력해주세요.')
      return
    }
    if (!validateWebhookUrl(url)) {
      setError(
        'URL 형식이 올바르지 않아요. https://discord.com/api/webhooks/<id>/<token> 형태여야 해요.',
      )
      return
    }
    setIsSaving(true)
    try {
      await saveWebhook(label, url)
      await onAdded()
      onOpenChange(false)
      toast.success('Webhook을 추가했어요')
    } catch (e: any) {
      if (e instanceof DiscordError && e.code === 'duplicate_webhook') {
        setError('이 URL은 이미 추가되어 있어요.')
      } else {
        setError(e?.message ?? '추가 실패')
      }
    } finally {
      setIsSaving(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Discord Webhook 추가</DialogTitle>
          <DialogDescription>
            Discord에서 발급한 Webhook URL을 입력해주세요.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3 py-2">
          <div className="space-y-1.5">
            <Label htmlFor="discord-webhook-label">이름 (라벨)</Label>
            <Input
              id="discord-webhook-label"
              placeholder="예: 마케팅 #general"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              maxLength={60}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="discord-webhook-url">Webhook URL</Label>
            <Input
              id="discord-webhook-url"
              type="url"
              placeholder="https://discord.com/api/webhooks/…"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              autoComplete="off"
              spellCheck={false}
            />
            <button
              type="button"
              onClick={() =>
                invoke('open_external_url', {
                  url: 'https://support.discord.com/hc/en-us/articles/228383668',
                }).catch(() => {})
              }
              className="inline-flex items-center gap-1 text-xs text-blue-600 hover:underline"
            >
              <ExternalLink className="h-3 w-3" />
              Webhook URL 만드는 법
            </button>
          </div>

          {error && (
            <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
              {error}
            </div>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            취소
          </Button>
          <Button onClick={handleSubmit} disabled={isSaving}>
            {isSaving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            추가
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
