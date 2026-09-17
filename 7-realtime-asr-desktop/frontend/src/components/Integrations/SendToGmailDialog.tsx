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
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { toast } from 'sonner'
import { sendGmail } from '@/services/integrationService'

interface SendToGmailDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** Initial body — markdown is fine, sent as plain text. */
  getMarkdown: () => Promise<string>
  /** Default subject line (e.g., meeting title). */
  defaultSubject?: string
  /** Pre-fill recipients from calendar attendees, if available. */
  defaultRecipients?: string[]
}

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

function parseAddresses(raw: string): { valid: string[]; invalid: string[] } {
  const tokens = raw
    .split(/[,;\n]/)
    .map((t) => t.trim())
    .filter(Boolean)
  const valid: string[] = []
  const invalid: string[] = []
  for (const t of tokens) {
    ;(EMAIL_RE.test(t) ? valid : invalid).push(t)
  }
  return { valid, invalid }
}

export function SendToGmailDialog({
  open,
  onOpenChange,
  getMarkdown,
  defaultSubject = '',
  defaultRecipients = [],
}: SendToGmailDialogProps) {
  const [toRaw, setToRaw] = useState<string>('')
  const [ccRaw, setCcRaw] = useState<string>('')
  const [showCc, setShowCc] = useState<boolean>(false)
  const [subject, setSubject] = useState<string>('')
  const [body, setBody] = useState<string>('')
  const [isLoadingBody, setIsLoadingBody] = useState(false)
  const [isSending, setIsSending] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!open) {
      setError(null)
      setBody('')
      setSubject('')
      setToRaw('')
      setCcRaw('')
      setShowCc(false)
      return
    }

    setSubject(defaultSubject)
    setToRaw(defaultRecipients.join(', '))

    setIsLoadingBody(true)
    getMarkdown()
      .then((md) => {
        if (!md) {
          setError('보낼 내용이 없어요. 먼저 요약이나 본문을 준비해주세요.')
          return
        }
        setBody(md)
      })
      .catch((e) => setError(e?.message || 'body_load_failed'))
      .finally(() => setIsLoadingBody(false))
  }, [open, getMarkdown, defaultSubject, defaultRecipients])

  const { valid: toValid, invalid: toInvalid } = useMemo(
    () => parseAddresses(toRaw),
    [toRaw],
  )
  const { valid: ccValid, invalid: ccInvalid } = useMemo(
    () => parseAddresses(ccRaw),
    [ccRaw],
  )

  const handleSend = async () => {
    if (toValid.length === 0) {
      setError('받는 사람 이메일을 한 명 이상 입력하세요.')
      return
    }
    if (toInvalid.length > 0 || ccInvalid.length > 0) {
      setError(`잘못된 이메일 형식: ${[...toInvalid, ...ccInvalid].join(', ')}`)
      return
    }
    if (!subject.trim()) {
      setError('제목을 입력하세요.')
      return
    }
    if (!body) {
      setError('본문이 비어 있어요.')
      return
    }

    setIsSending(true)
    setError(null)
    try {
      await sendGmail({
        to: toValid,
        cc: ccValid.length > 0 ? ccValid : undefined,
        subject: subject.trim(),
        body,
      })
      toast.success(
        `${toValid[0]}${toValid.length > 1 ? ` 외 ${toValid.length - 1}명` : ''}에게 보냈어요`,
      )
      onOpenChange(false)
    } catch (e: any) {
      const code = e?.message || 'send_failed'
      setError(
        code === 'reconnect_required'
          ? 'Google 권한이 만료되었어요. 설정에서 Gmail을 다시 연결해주세요.'
          : code,
      )
    } finally {
      setIsSending(false)
    }
  }

  const canSend =
    !isSending && !isLoadingBody && toValid.length > 0 && subject.trim() && body

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>메일로 전송</DialogTitle>
          <DialogDescription>
            Gmail로 보내기 전에 받는 사람과 내용을 확인하세요.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3 py-2">
          <div className="space-y-1.5">
            <label className="text-sm font-medium text-gray-700">받는 사람</label>
            <Input
              value={toRaw}
              onChange={(e) => setToRaw(e.target.value)}
              placeholder="example@company.com, another@company.com"
            />
            {toInvalid.length > 0 && (
              <p className="text-xs text-red-600">
                형식 확인: {toInvalid.join(', ')}
              </p>
            )}
            {!showCc && (
              <button
                type="button"
                onClick={() => setShowCc(true)}
                className="text-xs text-gray-500 hover:text-gray-700"
              >
                + 참조(CC) 추가
              </button>
            )}
          </div>

          {showCc && (
            <div className="space-y-1.5">
              <label className="text-sm font-medium text-gray-700">참조 (CC)</label>
              <Input
                value={ccRaw}
                onChange={(e) => setCcRaw(e.target.value)}
                placeholder="cc@company.com"
              />
              {ccInvalid.length > 0 && (
                <p className="text-xs text-red-600">
                  형식 확인: {ccInvalid.join(', ')}
                </p>
              )}
            </div>
          )}

          <div className="space-y-1.5">
            <label className="text-sm font-medium text-gray-700">제목</label>
            <Input
              value={subject}
              onChange={(e) => setSubject(e.target.value)}
              placeholder="회의 후속 안내"
            />
          </div>

          <div className="space-y-1.5">
            <div className="flex items-center justify-between">
              <label className="text-sm font-medium text-gray-700">본문</label>
              {body && (
                <span className="text-xs text-gray-500">
                  {body.length.toLocaleString()}자
                </span>
              )}
            </div>
            {isLoadingBody ? (
              <div className="rounded-md border border-gray-200 bg-gray-50 p-3">
                <Loader2 className="h-4 w-4 animate-spin text-gray-400" />
              </div>
            ) : (
              <Textarea
                value={body}
                onChange={(e) => setBody(e.target.value)}
                placeholder="본문을 작성하거나 붙여넣으세요"
                className="min-h-[160px] max-h-[320px] font-mono text-sm"
              />
            )}
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
