import { useCallback, useEffect, useRef, useState } from 'react'
import {
  getStatus,
  type IntegrationProvider,
  type IntegrationStatus,
} from '@/services/integrationService'
import { useAuth } from '@/contexts/AuthContext'

interface UseIntegrationStatusResult {
  status: IntegrationStatus | null
  isLoading: boolean
  error: string | null
  refresh: () => Promise<void>
  startPolling: (intervalMs?: number, timeoutMs?: number) => void
  stopPolling: () => void
}

export function useIntegrationStatus(
  provider: IntegrationProvider,
): UseIntegrationStatusResult {
  const { isAuthenticated } = useAuth()
  const [status, setStatus] = useState<IntegrationStatus | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const pollDeadlineRef = useRef<number>(0)

  const fetchStatus = useCallback(async () => {
    if (!isAuthenticated) {
      setStatus(null)
      setIsLoading(false)
      return
    }
    try {
      const s = await getStatus(provider)
      setStatus(s)
      setError(null)
    } catch (e: any) {
      setError(e?.message || 'status_fetch_failed')
    } finally {
      setIsLoading(false)
    }
  }, [provider, isAuthenticated])

  const stopPolling = useCallback(() => {
    if (pollTimerRef.current) {
      clearInterval(pollTimerRef.current)
      pollTimerRef.current = null
    }
  }, [])

  const startPolling = useCallback(
    (intervalMs = 3000, timeoutMs = 120_000) => {
      stopPolling()
      pollDeadlineRef.current = Date.now() + timeoutMs
      pollTimerRef.current = setInterval(async () => {
        if (Date.now() > pollDeadlineRef.current) {
          stopPolling()
          return
        }
        await fetchStatus()
      }, intervalMs)
    },
    [fetchStatus, stopPolling],
  )

  useEffect(() => {
    fetchStatus()
    return () => stopPolling()
  }, [fetchStatus, stopPolling])

  // Stop polling once connected.
  useEffect(() => {
    if (status?.connected && pollTimerRef.current) {
      stopPolling()
    }
  }, [status?.connected, stopPolling])

  return { status, isLoading, error, refresh: fetchStatus, startPolling, stopPolling }
}
