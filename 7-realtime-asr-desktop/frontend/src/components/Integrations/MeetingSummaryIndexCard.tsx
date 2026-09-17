'use client'

import { useEffect, useState } from 'react'
import { invoke } from '@tauri-apps/api/core'
import { Brain, Loader2, RefreshCw } from 'lucide-react'
import { Button } from '@/components/ui/button'

interface RagStatus {
  chunk_count: number
  meeting_chunk_count: number
  embedding_dim: number | null
  last_synced_at: string | null
  last_full_sync: string | null
}

interface ReindexResult {
  total: number
  indexed: number
  unchanged: number
  skipped: number
  failed: number
}

/**
 * Backfill control for meeting-summary RAG indexing. Past summaries get
 * indexed automatically when they're newly generated; this card is the
 * recovery path for users who already have a backlog of summaries from
 * before the feature shipped, or after a local DB wipe.
 */
export function MeetingSummaryIndexCard() {
  const [status, setStatus] = useState<RagStatus | null>(null)
  const [running, setRunning] = useState(false)
  const [lastResult, setLastResult] = useState<ReindexResult | null>(null)
  const [error, setError] = useState<string | null>(null)

  const refreshStatus = async () => {
    try {
      const s = await invoke<RagStatus>('rag_get_status')
      setStatus(s)
    } catch (e) {
      console.warn('rag_get_status failed:', e)
    }
  }

  useEffect(() => {
    refreshStatus()
  }, [])

  const handleReindex = async () => {
    if (running) return
    setRunning(true)
    setError(null)
    try {
      const result = await invoke<ReindexResult>('rag_reindex_all_meeting_summaries')
      setLastResult(result)
      await refreshStatus()
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      setError(msg)
    } finally {
      setRunning(false)
    }
  }

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-purple-50">
            <Brain className="h-5 w-5 text-purple-600" />
          </div>
          <div>
            <h3 className="text-sm font-semibold text-gray-900">미팅 요약 색인</h3>
            <p className="mt-0.5 text-xs text-gray-600">
              과거 미팅 요약을 AI 채팅이 검색할 수 있도록 색인합니다. 새 요약은 생성 시 자동으로 추가돼요.
            </p>
            <p className="mt-1 text-xs text-gray-500">
              색인된 요약: <span className="font-medium text-gray-700">{status?.meeting_chunk_count ?? '-'}</span>
              {' · '}
              Notion 청크: <span className="font-medium text-gray-700">{status?.chunk_count ?? '-'}</span>
            </p>
            {lastResult && (
              <p className="mt-1 text-xs text-gray-500">
                마지막 색인 결과 — 처리 {lastResult.total} / 신규 {lastResult.indexed} / 변동 없음 {lastResult.unchanged}
                {lastResult.failed > 0 && ` / 실패 ${lastResult.failed}`}
              </p>
            )}
            {error && <p className="mt-1 text-xs text-red-600">오류: {error}</p>}
          </div>
        </div>
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={running}
          onClick={handleReindex}
          className="shrink-0"
        >
          {running ? (
            <>
              <Loader2 className="mr-1 h-4 w-4 animate-spin" />
              색인 중…
            </>
          ) : (
            <>
              <RefreshCw className="mr-1 h-4 w-4" />
              전체 색인
            </>
          )}
        </Button>
      </div>
    </div>
  )
}
