'use client'

import { useEffect } from 'react'
import { authedFetch } from '@/services/apiClient'
import { useRecordingState } from '@/contexts/RecordingStateContext'

// Modal translate's scaledown_window is 60s (scripts/modal_translate.py), so
// without traffic the container goes cold within a minute. The initial
// warmup-on-toggle-ON path already covers OFF→ON, but a user who toggles
// translation off mid-meeting (or who simply pauses speech long enough that
// no `/translate/` calls fire) re-warms on toggle-ON and eats a 70s+ cold
// start.
//
// This hook sends a lightweight keep-alive POST for the full recording
// session regardless of the translation toggle state so Modal stays hot and
// toggling translation back on is instant.
//
// The gateway's /translate/warmup/ endpoint returns 200 immediately and
// pings Modal /health in a background thread, which resets Modal's idle
// timer without triggering inference. Fire-and-forget: any network error
// just means we'll try again on the next tick.
const KEEP_ALIVE_INTERVAL_MS = 45_000

export function useTranslationKeepAlive(): void {
  const { isRecording } = useRecordingState()

  useEffect(() => {
    if (!isRecording) return

    const ping = () => {
      authedFetch('/ai/translate/warmup/', { method: 'POST' }).catch((err) => {
        console.warn('[translate-keepalive] ping failed:', err)
      })
    }

    ping()
    const interval = window.setInterval(ping, KEEP_ALIVE_INTERVAL_MS)
    return () => {
      window.clearInterval(interval)
    }
  }, [isRecording])
}
