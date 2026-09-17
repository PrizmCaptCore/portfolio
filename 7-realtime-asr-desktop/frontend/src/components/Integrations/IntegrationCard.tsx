'use client'

import { useEffect, useState } from 'react'
import { invoke } from '@tauri-apps/api/core'
import {
  CheckCircle2,
  Database,
  Link as LinkIcon,
  Loader2,
  RefreshCw,
  Unlink,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  disconnect as apiDisconnect,
  startConnect,
  type IntegrationProvider,
} from '@/services/integrationService'
import { useIntegrationStatus } from '@/hooks/useIntegrationStatus'

interface IntegrationCardProps {
  provider: IntegrationProvider
  title: string
  description: string
  icon: React.ReactNode
  /**
   * Render the card in "Coming Soon" mode: icon, title, description still show,
   * but the Connect/Disconnect button is replaced with a disabled badge. Use
   * this for providers whose backend OAuth approval is still in progress so
   * users see the planned capability without being able to attempt a flow that
   * would fail.
   */
  comingSoon?: boolean
}

interface RagStatus {
  chunk_count: number
  embedding_dim: number | null
  last_synced_at: string | null
  last_full_sync: string | null
}

interface SyncResult {
  chunks_inserted: number
  pages_seen: number
  embedding_dim: number | null
  last_synced_at: string | null
}

// How long to wait between triggering the backend Celery sync and pulling
// the freshly-chunked rows. Chosen empirically: a small Notion workspace
// (~50 pages) takes 8-15s end-to-end on RunPod's embedding endpoint.
// Longer waits get the user a more "complete" sync but add UI lag; users
// can always re-click to pull more.
const BACKEND_SYNC_WAIT_MS = 12_000

function formatRelative(iso: string | null): string {
  if (!iso) return '동기화 이력 없음'
  const t = Date.parse(iso)
  if (Number.isNaN(t)) return '동기화 이력 없음'
  const diff = Date.now() - t
  if (diff < 60_000) return '방금 전'
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}분 전`
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}시간 전`
  return `${Math.floor(diff / 86_400_000)}일 전`
}

export function IntegrationCard({
  provider,
  title,
  description,
  icon,
  comingSoon = false,
}: IntegrationCardProps) {
  const { status, isLoading, error, refresh, startPolling } =
    useIntegrationStatus(provider)
  const [isConnecting, setIsConnecting] = useState(false)
  const [isDisconnecting, setIsDisconnecting] = useState(false)
  const [localError, setLocalError] = useState<string | null>(null)

  const handleConnect = async () => {
    setIsConnecting(true)
    setLocalError(null)
    try {
      const { authorize_url } = await startConnect(provider)
      await invoke('open_external_url', { url: authorize_url })
      startPolling(3000, 120_000)
    } catch (e: any) {
      setLocalError(e?.message || 'connect_failed')
    } finally {
      setIsConnecting(false)
    }
  }

  const handleDisconnect = async () => {
    setIsDisconnecting(true)
    setLocalError(null)
    try {
      await apiDisconnect(provider)
      // Notion: privacy parity with the backend cascade. The disconnect
      // endpoint deletes NotionPage/NotionChunk for the user; we mirror
      // it on the local sqlite-vec index so the chatbot can no longer
      // surface the user's notes after they've severed the connection.
      // Best-effort: a failure here is logged but doesn't roll back the
      // backend disconnect — user already lost the integration on the
      // server side, and they can run the dedicated reset elsewhere.
      if (provider === 'notion') {
        try {
          await invoke('rag_clear_notion')
        } catch (e) {
          console.warn('rag_clear_notion failed (continuing):', e)
        }
      }
      await refresh()
    } catch (e: any) {
      setLocalError(e?.message || 'disconnect_failed')
    } finally {
      setIsDisconnecting(false)
    }
  }

  const connected = status?.connected === true
  const shownError = localError || error

  return (
    <div className="flex items-start justify-between rounded-lg border border-gray-200 bg-white p-5">
      <div className="flex items-start gap-4">
        <div className="flex h-10 w-10 items-center justify-center rounded-md bg-gray-50">
          {icon}
        </div>
        <div>
          <div className="flex items-center gap-2">
            <h3 className="font-semibold text-gray-900">{title}</h3>
            {connected && (
              <span className="inline-flex items-center gap-1 rounded-full bg-green-50 px-2 py-0.5 text-xs text-green-700">
                <CheckCircle2 className="h-3 w-3" />
                연결됨
              </span>
            )}
          </div>
          <p className="mt-0.5 text-sm text-gray-600">{description}</p>
          {connected && status?.workspace && (
            <p className="mt-1 text-xs text-gray-500">
              워크스페이스: <span className="font-medium">{status.workspace}</span>
            </p>
          )}
          {connected && provider === 'notion' && (
            <NotionSyncRow disconnected={!connected} />
          )}
          {shownError && (
            <p className="mt-1 text-xs text-red-600">오류: {shownError}</p>
          )}
        </div>
      </div>

      <div className="shrink-0 self-center">
        {comingSoon ? (
          <span className="inline-flex items-center rounded-full bg-gray-100 px-3 py-1 text-xs font-medium text-gray-600 ring-1 ring-gray-200">
            준비 중
          </span>
        ) : isLoading ? (
          <Loader2 className="h-5 w-5 animate-spin text-gray-400" />
        ) : connected ? (
          <Button
            variant="outline"
            size="sm"
            onClick={handleDisconnect}
            disabled={isDisconnecting}
          >
            {isDisconnecting ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <Unlink className="mr-2 h-4 w-4" />
            )}
            연결 해제
          </Button>
        ) : (
          <Button size="sm" onClick={handleConnect} disabled={isConnecting}>
            {isConnecting ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <LinkIcon className="mr-2 h-4 w-4" />
            )}
            연결
          </Button>
        )}
      </div>
    </div>
  )
}

/**
 * Notion-specific sync controls: shows local index size + last sync time,
 * and a button that fires the two-step sync (queue Celery → wait → pull).
 *
 * Rendered inside the Notion card body rather than as a sibling card so
 * it stays visually subordinate to the connection state — disconnecting
 * Notion makes the whole row disappear, which matches user expectation.
 */
function NotionSyncRow({ disconnected }: { disconnected: boolean }) {
  const [ragStatus, setRagStatus] = useState<RagStatus | null>(null)
  const [syncing, setSyncing] = useState(false)
  const [syncStage, setSyncStage] = useState<string>('')
  const [syncError, setSyncError] = useState<string | null>(null)

  const refreshStatus = async () => {
    try {
      const s = await invoke<RagStatus>('rag_get_status')
      setRagStatus(s)
    } catch {
      // Status fetch failure is non-fatal — we just show "이력 없음".
    }
  }

  useEffect(() => {
    if (disconnected) {
      setRagStatus(null)
      return
    }
    refreshStatus()
  }, [disconnected])

  const handleSync = async () => {
    setSyncing(true)
    setSyncError(null)
    try {
      setSyncStage('백엔드 동기화 요청 중…')
      await invoke('rag_trigger_backend_sync')

      setSyncStage(`백엔드에서 임베딩 중… (${BACKEND_SYNC_WAIT_MS / 1000}초)`)
      await new Promise((r) => setTimeout(r, BACKEND_SYNC_WAIT_MS))

      setSyncStage('로컬 인덱스 갱신 중…')
      const result = await invoke<SyncResult>('rag_sync')

      setSyncStage(
        `+${result.chunks_inserted}개 chunk (${result.pages_seen}개 페이지)`,
      )
      await refreshStatus()
    } catch (e: any) {
      setSyncError(e?.message || String(e) || 'sync_failed')
    } finally {
      setSyncing(false)
      // Clear the transient stage label after a beat so the steady-state
      // status row reasserts itself without needing a re-render trigger.
      setTimeout(() => setSyncStage(''), 4000)
    }
  }

  return (
    <div className="mt-2 flex items-center gap-3 text-xs">
      <span className="inline-flex items-center gap-1 text-gray-500">
        <Database className="h-3 w-3" />
        {ragStatus?.chunk_count ?? 0}개 chunk
      </span>
      <span className="text-gray-400">·</span>
      <span className="text-gray-500">
        {syncStage || formatRelative(ragStatus?.last_synced_at ?? null)}
      </span>
      <Button
        size="sm"
        variant="ghost"
        className="h-6 px-2 text-xs"
        onClick={handleSync}
        disabled={syncing}
      >
        {syncing ? (
          <Loader2 className="mr-1 h-3 w-3 animate-spin" />
        ) : (
          <RefreshCw className="mr-1 h-3 w-3" />
        )}
        동기화
      </Button>
      {syncError && (
        <span className="text-red-600">오류: {syncError}</span>
      )}
    </div>
  )
}
