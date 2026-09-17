'use client'

import { useEffect, useMemo, useState } from 'react'
import { Database, FileText, Loader2, Search, Send } from 'lucide-react'
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { toast } from 'sonner'
import {
  searchNotion,
  sendToNotion,
  type NotionSearchItem,
} from '@/services/integrationService'

interface SendToNotionDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  getMarkdown: () => Promise<string>
  /** Suggested title when creating a new page. */
  defaultTitle?: string
}

type Mode = 'append' | 'create'

export function SendToNotionDialog({
  open,
  onOpenChange,
  getMarkdown,
  defaultTitle = '',
}: SendToNotionDialogProps) {
  const [markdown, setMarkdown] = useState<string>('')
  const [isLoadingMarkdown, setIsLoadingMarkdown] = useState(false)
  const [query, setQuery] = useState<string>('')
  const [results, setResults] = useState<NotionSearchItem[]>([])
  const [isSearching, setIsSearching] = useState(false)
  const [selectedId, setSelectedId] = useState<string>('')
  const [mode, setMode] = useState<Mode>('append')
  const [title, setTitle] = useState<string>(defaultTitle)
  const [isSending, setIsSending] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!open) {
      setError(null)
      setMarkdown('')
      setSelectedId('')
      setQuery('')
      setResults([])
      setMode('append')
      setTitle(defaultTitle)
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

    setIsSearching(true)
    searchNotion({})
      .then((res) => setResults(res.results))
      .catch((e) => setError(e?.message || 'search_failed'))
      .finally(() => setIsSearching(false))
  }, [open, getMarkdown, defaultTitle])

  const runSearch = async (q: string) => {
    setIsSearching(true)
    setError(null)
    try {
      const res = await searchNotion({ q })
      setResults(res.results)
    } catch (e: any) {
      setError(e?.message || 'search_failed')
    } finally {
      setIsSearching(false)
    }
  }

  useEffect(() => {
    if (!open) return
    const t = setTimeout(() => runSearch(query), 300)
    return () => clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query, open])

  const previewLines = useMemo(
    () => markdown.split('\n').slice(0, 6).join('\n'),
    [markdown],
  )

  const selected = results.find((r) => r.id === selectedId)
  const isDatabaseSelected = selected?.object === 'database'
  // Databases only support create-mode (adding a new row); append doesn't apply.
  const effectiveMode: Mode = isDatabaseSelected ? 'create' : mode

  const handleSend = async () => {
    if (!selected || !markdown) return
    if (effectiveMode === 'create' && !title.trim()) {
      setError('제목을 입력하세요')
      return
    }
    setIsSending(true)
    setError(null)
    try {
      await sendToNotion({
        page_id: selected.id,
        markdown,
        mode: effectiveMode,
        object: isDatabaseSelected ? 'database' : 'page',
        ...(effectiveMode === 'create' ? { title: title.trim() } : {}),
      })
      toast.success(
        isDatabaseSelected
          ? `"${selected.title || 'DB'}"에 새 항목을 추가했어요`
          : effectiveMode === 'create'
            ? `"${title}" 페이지를 Notion에 만들었어요`
            : `"${selected.title || '페이지'}"에 내용을 추가했어요`,
      )
      onOpenChange(false)
    } catch (e: any) {
      setError(e?.message || 'send_failed')
    } finally {
      setIsSending(false)
    }
  }

  const canSend =
    !isSending &&
    !isLoadingMarkdown &&
    markdown &&
    selected &&
    (effectiveMode === 'append' || title.trim())

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>Notion으로 전송</DialogTitle>
          <DialogDescription>
            페이지에 내용을 추가하거나 하위 페이지로 새로 만들 수 있습니다.
          </DialogDescription>
        </DialogHeader>

        {/* `min-w-0` is the structural fix for "내부 텍스트가 가로로 늘어나
            다이얼로그 밖으로 삐져나옴" — shadcn `DialogContent` is a CSS
            grid container, so this body section is a grid item with
            default `min-width: auto`. That default forces the cell to be
            at least as wide as its content's intrinsic min-content size,
            and a long Korean page title or unbroken markdown line happily
            blows past the dialog's `max-w-xl` cap. Setting `min-width: 0`
            here lets the grid track shrink to the dialog's max-width and
            forces children (Select, Input, results list, preview) to wrap
            / truncate inside the box instead of escaping it. */}
        <div className="min-w-0 space-y-4 py-2">
          {/* Mode selector — hidden when a database is selected (create only) */}
          {!isDatabaseSelected && (
            <div className="space-y-1.5">
              <label className="text-sm font-medium text-gray-700">동작</label>
              <Select value={mode} onValueChange={(v) => setMode(v as Mode)}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="append">기존 페이지에 추가</SelectItem>
                  <SelectItem value="create">
                    선택한 페이지 아래에 새 페이지 만들기
                  </SelectItem>
                </SelectContent>
              </Select>
            </div>
          )}
          {isDatabaseSelected && (
            <div className="rounded-md border border-blue-200 bg-blue-50 px-3 py-2 text-xs text-blue-900">
              데이터베이스를 선택했습니다. 새 항목(row)을 추가합니다.
            </div>
          )}

          {/* Page search */}
          <div className="space-y-1.5">
            <label className="text-sm font-medium text-gray-700">
              {mode === 'create' ? '상위 페이지 검색' : '대상 페이지 검색'}
            </label>
            <div className="relative">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
              <Input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="페이지 이름으로 검색"
                className="pl-9"
              />
            </div>
            <div className="max-h-40 overflow-y-auto rounded-md border border-gray-200">
              {isSearching ? (
                <div className="p-3">
                  <Loader2 className="h-4 w-4 animate-spin text-gray-400" />
                </div>
              ) : results.length === 0 ? (
                <div className="p-3 text-xs text-gray-500">결과 없음</div>
              ) : (
                results.map((item) => {
                  const Icon = item.object === 'database' ? Database : FileText
                  return (
                    <button
                      key={item.id}
                      type="button"
                      onClick={() => setSelectedId(item.id)}
                      // `min-w-0` on the button forces the flex container to
                      // permit its children to shrink below their content
                      // size; without it the truncate span would refuse to
                      // collapse and the long Notion page titles push the
                      // whole dialog wider than its max-w-xl on macOS.
                      className={`flex w-full min-w-0 items-center gap-2 px-3 py-2 text-left text-sm hover:bg-gray-50 ${
                        selectedId === item.id ? 'bg-blue-50' : ''
                      }`}
                    >
                      <Icon className="h-4 w-4 shrink-0 text-gray-400" />
                      <span className="min-w-0 flex-1 truncate">
                        {item.title || '(제목 없음)'}
                      </span>
                      <span className="shrink-0 text-xs text-gray-400">
                        {item.object === 'database' ? 'DB' : 'page'}
                      </span>
                    </button>
                  )
                })
              )}
            </div>
          </div>

          {/* Title input for create mode (pages) or new row title (databases) */}
          {effectiveMode === 'create' && (
            <div className="space-y-1.5">
              <label className="text-sm font-medium text-gray-700">
                {isDatabaseSelected ? '새 항목 제목' : '새 페이지 제목'}
              </label>
              <Input
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="예: 2026-04-17 제품 킥오프 미팅"
              />
            </div>
          )}

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
            <div className="max-h-40 overflow-auto rounded-md border border-gray-200 bg-gray-50 p-3 text-xs">
              {isLoadingMarkdown ? (
                <Loader2 className="h-4 w-4 animate-spin text-gray-400" />
              ) : (
                // `break-words` so unbroken strings (URLs, code, long Korean
                // tokens without spaces) wrap inside the box instead of
                // pushing the preview — and through it the whole dialog —
                // out to the right on macOS.
                <pre className="whitespace-pre-wrap break-words font-mono text-gray-700">
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
