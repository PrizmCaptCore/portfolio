'use client'

import { useEffect, useState } from 'react'
import { Loader2, Mail, MessageSquare, Sparkles } from 'lucide-react'
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
import { Textarea } from '@/components/ui/textarea'
import { toast } from 'sonner'
import {
  generateFollowUp,
  type FollowUpTone,
} from '@/services/followUpService'
import { getStatus } from '@/services/integrationService'
import { useAuth } from '@/contexts/AuthContext'
// TEMP: SendToGmailDialog import retained but marked unused while OAuth pending.
import { SendToGmailDialog } from '@/components/Integrations/SendToGmailDialog'
void SendToGmailDialog
import { SendToSlackDialog } from '@/components/Integrations/SendToSlackDialog'

interface ComposeFollowUpDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** Returns the meeting summary used as input. */
  getSummary: () => Promise<string>
  meetingTitle?: string
  /** Optional pre-fill for Gmail recipients. */
  defaultRecipients?: string[]
}

const TONE_LABELS: Record<FollowUpTone, string> = {
  professional: '정중·전문',
  concise: '간결·핵심만',
  action_items: '액션 아이템 중심',
  thanks: '감사 인사 중심',
}

// TEMP: 'email' channel kept in the union but UI-disabled while Gmail / Outlook
// Mail OAuth approval is pending. Re-enable email-related UI below to restore.
type ChannelChoice = 'email' | 'slack'

export function ComposeFollowUpDialog({
  open,
  onOpenChange,
  getSummary,
  meetingTitle,
  defaultRecipients,
}: ComposeFollowUpDialogProps) {
  const { isAuthenticated } = useAuth()
  // `defaultRecipients` is only consumed by the Gmail dialog (currently disabled);
  // keep the prop so callers don't need to change.
  void defaultRecipients
  const [tone, setTone] = useState<FollowUpTone>('professional')
  // Default to slack while email is disabled.
  const [channel, setChannel] = useState<ChannelChoice>('slack')
  const [draft, setDraft] = useState<string>('')
  const [isGenerating, setIsGenerating] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [summary, setSummary] = useState<string>('')

  // Track which downstream dialog is open. The compose dialog closes when
  // dispatching so the user only sees one modal at a time.
  const [sendTarget, setSendTarget] = useState<'email' | 'slack' | null>(null)

  // Connection status for the dispatch buttons — we hide options the user
  // hasn't connected rather than showing a dead button.
  // TEMP: Gmail status removed while OAuth approval pending.
  const [connectedSlack, setConnectedSlack] = useState(false)

  useEffect(() => {
    if (!open) {
      setError(null)
      setDraft('')
      setSummary('')
      setSendTarget(null)
      return
    }
    getSummary()
      .then((s) => {
        if (!s) setError('요약이 없어요. 먼저 요약을 생성하세요.')
        else setSummary(s)
      })
      .catch((e) => setError(e?.message || 'summary_load_failed'))
  }, [open, getSummary])

  useEffect(() => {
    if (!isAuthenticated || !open) return
    // TEMP: Gmail status check skipped while OAuth approval pending.
    getStatus('slack')
      .catch(() => ({ connected: false }))
      .then((s) => {
        setConnectedSlack(s.connected === true)
      })
  }, [isAuthenticated, open])

  const handleGenerate = async () => {
    if (!summary) {
      setError('요약이 비어 있어요.')
      return
    }
    setIsGenerating(true)
    setError(null)
    try {
      const text = await generateFollowUp({
        summary,
        tone,
        channel,
        meetingTitle,
      })
      setDraft(text)
    } catch (e: any) {
      const code = e?.message || 'generation_failed'
      setError(
        code === 'subscription_required'
          ? '유료 플랜이 필요한 기능이에요.'
          : `초안 생성 실패: ${code}`,
      )
    } finally {
      setIsGenerating(false)
    }
  }

  const dispatchTo = (target: 'email' | 'slack') => {
    if (!draft.trim()) {
      setError('먼저 초안을 생성하거나 직접 작성하세요.')
      return
    }
    setSendTarget(target)
    onOpenChange(false)
  }

  const draftCharCount = draft.length

  return (
    <>
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent className="max-w-xl">
          <DialogHeader>
            <DialogTitle>Follow-up 작성</DialogTitle>
            <DialogDescription>
              회의 요약을 바탕으로 후속 메시지 초안을 만들고, Slack 또는 메일로 바로 보냅니다.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-3 py-2">
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <label className="text-sm font-medium text-gray-700">톤</label>
                <Select value={tone} onValueChange={(v) => setTone(v as FollowUpTone)}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {Object.entries(TONE_LABELS).map(([v, label]) => (
                      <SelectItem key={v} value={v}>
                        {label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1.5">
                <label className="text-sm font-medium text-gray-700">대상 채널</label>
                <Select
                  value={channel}
                  onValueChange={(v) => setChannel(v as ChannelChoice)}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {/* Email channel disabled until Gmail / Outlook Mail OAuth is approved. */}
                    <SelectItem value="email" disabled>
                      이메일 (Coming Soon)
                    </SelectItem>
                    <SelectItem value="slack">Slack</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>

            <Button
              variant="outline"
              onClick={handleGenerate}
              disabled={isGenerating || !summary}
              className="w-full"
            >
              {isGenerating ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <Sparkles className="mr-2 h-4 w-4" />
              )}
              {draft ? '다시 생성' : '초안 생성'}
            </Button>

            <div className="space-y-1.5">
              <div className="flex items-center justify-between">
                <label className="text-sm font-medium text-gray-700">초안</label>
                {draft && (
                  <span className="text-xs text-gray-500">
                    {draftCharCount.toLocaleString()}자
                  </span>
                )}
              </div>
              <Textarea
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                placeholder="초안 생성을 누르거나 직접 작성하세요."
                className="min-h-[180px] max-h-[320px] font-mono text-sm"
              />
            </div>

            {error && (
              <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
                {error}
              </div>
            )}

            {!connectedSlack && (
              <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
                Slack을 설정에서 먼저 연결하면 바로 보낼 수 있어요.
              </div>
            )}
          </div>

          <DialogFooter className="gap-2 sm:gap-2">
            <Button variant="outline" onClick={() => onOpenChange(false)}>
              닫기
            </Button>
            <Button
              variant="outline"
              disabled={!connectedSlack || !draft.trim()}
              onClick={() => dispatchTo('slack')}
              title={connectedSlack ? 'Slack으로 보내기' : 'Slack을 먼저 연결하세요'}
            >
              <MessageSquare className="mr-2 h-4 w-4 text-[#4A154B]" />
              Slack으로 보내기
            </Button>
            {/* 메일로 보내기 — Gmail / Outlook Mail OAuth 승인 대기. Disabled
                with "Coming Soon" tooltip so the planned action stays visible. */}
            <Button
              disabled
              title="OAuth 승인 대기 중 — 곧 지원될 예정입니다"
            >
              <Mail className="mr-2 h-4 w-4" />
              메일로 보내기 (Coming Soon)
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* TEMP: SendToGmailDialog mount disabled while OAuth approval pending.
      <SendToGmailDialog
        open={sendTarget === 'email'}
        onOpenChange={(o) => !o && setSendTarget(null)}
        getMarkdown={async () => draft}
        defaultSubject={meetingTitle}
        defaultRecipients={defaultRecipients}
      />
      */}
      <SendToSlackDialog
        open={sendTarget === 'slack'}
        onOpenChange={(o) => !o && setSendTarget(null)}
        getMarkdown={async () => draft}
      />
    </>
  )
}
