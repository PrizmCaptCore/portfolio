"use client"

import { useCallback, useEffect, useState } from "react"

const XL_MEDIA = "(min-width: 1280px)"
const STORAGE_KEY = "relay-docked-ai-rail-px"
const RAIL_MIN = 280
const RAIL_MAX_HARD = 720

function defaultRailPx(vw: number) {
  return Math.max(RAIL_MIN, Math.min(420, Math.round(vw * 0.38)))
}

function clampRail(px: number, vw: number) {
  const max = Math.min(RAIL_MAX_HARD, Math.round(vw * 0.55))
  return Math.max(RAIL_MIN, Math.min(max, Math.round(px)))
}

export function useResizableDockedAiRail(
  showAgentChrome: boolean,
  /** When false (e.g. user minimized docked chat), rail width CSS var is 0. */
  dockedRailExpanded: boolean,
) {
  const [railPx, setRailPx] = useState(400)
  const [isXl, setIsXl] = useState(false)

  useEffect(() => {
    if (typeof window === "undefined") return
    const mq = window.matchMedia(XL_MEDIA)
    const applyStored = () => {
      const raw = window.localStorage.getItem(STORAGE_KEY)
      const parsed = raw ? parseInt(raw, 10) : NaN
      const vw = window.innerWidth
      const base = Number.isFinite(parsed) ? parsed : defaultRailPx(vw)
      setRailPx(clampRail(base, vw))
    }
    applyStored()
    setIsXl(mq.matches)
    const onChange = () => setIsXl(mq.matches)
    mq.addEventListener("change", onChange)
    const onResize = () => {
      setRailPx((w) => clampRail(w, window.innerWidth))
    }
    window.addEventListener("resize", onResize)
    return () => {
      mq.removeEventListener("change", onChange)
      window.removeEventListener("resize", onResize)
    }
  }, [])

  const dockedAiRailVar =
    showAgentChrome && isXl && dockedRailExpanded ? `${railPx}px` : "0px"

  const onResizePointerDown = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      e.preventDefault()
      const handle = e.currentTarget
      handle.setPointerCapture(e.pointerId)
      const startX = e.clientX
      const startW = railPx
      const lastW = { current: startW }

      const onMove = (ev: PointerEvent) => {
        const next = clampRail(startX - ev.clientX + startW, window.innerWidth)
        lastW.current = next
        setRailPx(next)
      }
      const onUp = (ev: PointerEvent) => {
        try {
          handle.releasePointerCapture(ev.pointerId)
        } catch {
          /* ignore */
        }
        window.removeEventListener("pointermove", onMove)
        window.removeEventListener("pointerup", onUp)
        window.removeEventListener("pointercancel", onUp)
        try {
          window.localStorage.setItem(STORAGE_KEY, String(lastW.current))
        } catch {
          /* private mode */
        }
      }
      window.addEventListener("pointermove", onMove)
      window.addEventListener("pointerup", onUp)
      window.addEventListener("pointercancel", onUp)
    },
    [railPx],
  )

  return { railPx, isXl, dockedAiRailVar, onResizePointerDown }
}
