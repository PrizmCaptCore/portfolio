'use client'

// Standalone page rendered inside the floating "meeting detected" alert
// window. Kept intentionally tiny — no providers, no global app state — so
// the popup is fast to spawn and side-effect free. Auto-dismisses after a
// short timeout. Clicking the card focuses the main Relay window.
//
// The root layout detects this route and skips its global providers/sidebar,
// so this page renders inside an empty <body>.

import { useEffect, useRef } from 'react'
import { getCurrentWebviewWindow } from '@tauri-apps/api/webviewWindow'
import { Window } from '@tauri-apps/api/window'

const AUTO_DISMISS_MS = 6000

export default function MeetingAlertPage() {
  const dismissTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    const close = async () => {
      try {
        await getCurrentWebviewWindow().close()
      } catch (e) {
        console.warn('[meeting-alert] close failed', e)
      }
    }

    dismissTimer.current = setTimeout(close, AUTO_DISMISS_MS)

    return () => {
      if (dismissTimer.current) clearTimeout(dismissTimer.current)
    }
  }, [])

  const focusMain = async () => {
    try {
      const main = await Window.getByLabel('main')
      if (main) {
        await main.show()
        await main.unminimize()
        await main.setFocus()
      }
    } catch (e) {
      console.warn('[meeting-alert] focus main failed', e)
    } finally {
      try {
        await getCurrentWebviewWindow().close()
      } catch {}
    }
  }

  const dismiss = async (e: React.MouseEvent) => {
    e.stopPropagation()
    try {
      await getCurrentWebviewWindow().close()
    } catch {}
  }

  return (
    <div
      onClick={focusMain}
      style={{
        cursor: 'pointer',
        margin: 8,
        padding: '14px 16px',
        borderRadius: 12,
        background: 'rgba(28, 28, 30, 0.92)',
        color: 'white',
        boxShadow:
          '0 10px 30px rgba(0, 0, 0, 0.35), 0 2px 6px rgba(0, 0, 0, 0.25)',
        backdropFilter: 'blur(20px)',
        WebkitBackdropFilter: 'blur(20px)',
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        userSelect: 'none',
        fontFamily:
          '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
      }}
    >
      <div
        aria-hidden
        style={{
          width: 36,
          height: 36,
          borderRadius: 18,
          background: 'linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          flexShrink: 0,
          fontSize: 18,
        }}
      >
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div
          style={{
            fontSize: 13,
            fontWeight: 600,
            marginBottom: 2,
            opacity: 0.7,
          }}
        >
          Relay Assistant
        </div>
        <div style={{ fontSize: 14, fontWeight: 500 }}>
          회의가 감지되었습니다
        </div>
      </div>
      <button
        onClick={dismiss}
        aria-label="닫기"
        style={{
          background: 'rgba(255,255,255,0.12)',
          border: 'none',
          color: 'white',
          width: 24,
          height: 24,
          borderRadius: 12,
          cursor: 'pointer',
          fontSize: 14,
          lineHeight: 1,
          padding: 0,
          flexShrink: 0,
        }}
      >
        ×
      </button>
    </div>
  )
}
