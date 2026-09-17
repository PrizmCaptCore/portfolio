"use client"

import { Transcript, TranscriptSegmentData } from "@/types"
import { TranscriptView } from "@/components/TranscriptView"
import { VirtualizedTranscriptView } from "@/components/VirtualizedTranscriptView"
import { SelectionTranslatePopover } from "@/components/SelectionTranslatePopover"
import { TranscriptButtonGroup } from "./TranscriptButtonGroup"
import { useEffect, useMemo, useRef, useState } from "react"
import type { CSSProperties } from "react"
import { invoke } from "@tauri-apps/api/core"
import AudioPlayer from "react-h5-audio-player"
import { addCollection } from "@iconify/react"

// react-h5-audio-player renders icons via @iconify/react which by default
// fetches SVG data from api.iconify.design at runtime. That fails under the
// Tauri CSP (and offline). Load the pre-bundled MDI subset from public/icons/
// so icons render locally. Safe to call multiple times — addCollection
// merges by prefix and is idempotent for a given payload.
let audioIconsLoaded = false
async function ensureAudioIconsLoaded() {
  if (audioIconsLoaded) return
  audioIconsLoaded = true
  try {
    const res = await fetch("/icons/mdi-audio.json")
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
    addCollection(await res.json())
  } catch (e) {
    audioIconsLoaded = false
    console.warn("[TranscriptPanel] failed to load mdi-audio icons:", e)
  }
}

interface TranscriptPanelProps {
  transcripts: Transcript[]
  onCopyTranscript: () => void
  onOpenMeetingFolder: () => Promise<void>
  isRecording: boolean
  disableAutoScroll?: boolean

  // Optional pagination props (when using virtualization)
  usePagination?: boolean
  segments?: TranscriptSegmentData[]
  hasMore?: boolean
  isLoadingMore?: boolean
  totalCount?: number
  loadedCount?: number
  onLoadMore?: () => void

  // Retranscription props
  meetingId?: string
  meetingFolderPath?: string | null
  onRefetchTranscripts?: () => Promise<void>
  panelClassName?: string
  panelStyle?: CSSProperties
}

export function TranscriptPanel({
  transcripts,
  onCopyTranscript,
  onOpenMeetingFolder,
  isRecording,
  disableAutoScroll = false,
  usePagination = false,
  segments,
  hasMore,
  isLoadingMore,
  totalCount,
  loadedCount,
  onLoadMore,
  meetingId,
  meetingFolderPath,
  onRefetchTranscripts,
  panelClassName,
  panelStyle,
}: TranscriptPanelProps) {
  const [audioPath, setAudioPath] = useState<string | null>(null)
  const [audioLoading, setAudioLoading] = useState(false)
  const [audioLookupError, setAudioLookupError] = useState<string | null>(null)
  const [currentTime, setCurrentTime] = useState(0)
  const [duration, setDuration] = useState(0)
  const [audioPlayError, setAudioPlayError] = useState<string | null>(null)
  const [audioSrc, setAudioSrc] = useState<string | null>(null)
  const audioPlayerRef = useRef<AudioPlayer | null>(null)

  // Side-by-side vs stacked layout for transcript + translation. Persisted so
  // the choice survives navigation; default to the more compact stacked view.
  const [layoutMode, setLayoutMode] = useState<'inline' | 'split'>(() => {
    if (typeof window === 'undefined') return 'inline'
    return window.localStorage.getItem('transcriptLayoutMode') === 'split'
      ? 'split'
      : 'inline'
  })
  useEffect(() => {
    if (typeof window === 'undefined') return
    window.localStorage.setItem('transcriptLayoutMode', layoutMode)
  }, [layoutMode])

  useEffect(() => {
    ensureAudioIconsLoaded()
  }, [])

  const formatTime = (seconds: number) => {
    if (!Number.isFinite(seconds) || seconds < 0) return "00:00"
    const mins = Math.floor(seconds / 60)
    const secs = Math.floor(seconds % 60)
    return `${mins.toString().padStart(2, "0")}:${secs.toString().padStart(2, "0")}`
  }

  const handleTimestampClick = (seconds: number) => {
    const audioElement = audioPlayerRef.current?.audio.current
    if (!audioElement) return

    const safeDuration =
      Number.isFinite(audioElement.duration) && audioElement.duration > 0
        ? audioElement.duration
        : Number.POSITIVE_INFINITY
    const clampedTime = Math.max(0, Math.min(seconds, safeDuration))
    audioElement.currentTime = clampedTime
    setCurrentTime(clampedTime)
  }

  useEffect(() => {
    let cancelled = false

    const loadMeetingAudioPath = async () => {
      if (!meetingFolderPath) {
        setAudioPath(null)
        return
      }

      setAudioLoading(true)
      setAudioLookupError(null)

      try {
        const foundPath = await invoke<string | null>(
          "find_meeting_audio_file",
          {
            meetingFolderPath,
          },
        )

        if (!cancelled) {
          setAudioPath(foundPath)
        }
      } catch (err) {
        if (!cancelled) {
          setAudioPath(null)
          setAudioLookupError(err instanceof Error ? err.message : String(err))
        }
      } finally {
        if (!cancelled) {
          setAudioLoading(false)
        }
      }
    }

    loadMeetingAudioPath()

    return () => {
      cancelled = true
    }
  }, [meetingFolderPath])

  useEffect(() => {
    setCurrentTime(0)
    setDuration(0)
    setAudioPlayError(null)
  }, [audioPath])

  // Convert transcripts to segments if pagination is not used but we want virtualization
  const convertedSegments = useMemo(() => {
    if (usePagination && segments) {
      return segments
    }
    // Convert transcripts to segments for virtualization
    return transcripts.map((t) => ({
      id: t.id,
      timestamp: t.audio_start_time ?? 0,
      endTime: t.audio_end_time,
      text: t.text,
      source: t.source,
      is_partial: t.is_partial ?? false,
      confidence: t.confidence,
      tentative_text: t.tentative_text,
      translated_text: t.translated_text,
    }))
  }, [transcripts, usePagination, segments])

  useEffect(() => {
    let revokedUrl: string | null = null
    let cancelled = false

    const resolveAudioSrc = async () => {
      if (!audioPath) {
        setAudioSrc(null)
        return
      }

      if (/^https?:\/\//.test(audioPath) || audioPath.startsWith("asset:")) {
        setAudioSrc(audioPath)
        return
      }

      try {
        const audioBytes = await invoke<number[]>("read_audio_file", {
          filePath: audioPath,
        })
        if (cancelled) return

        const extension = audioPath.split(".").pop()?.toLowerCase()
        const mimeType =
          extension === "mp4" || extension === "m4a"
            ? "audio/mp4"
            : extension === "wav"
              ? "audio/wav"
              : extension === "mp3"
                ? "audio/mpeg"
                : "audio/*"

        const blob = new Blob([new Uint8Array(audioBytes)], { type: mimeType })
        const objectUrl = URL.createObjectURL(blob)
        revokedUrl = objectUrl
        setAudioSrc(objectUrl)
      } catch {
        if (!cancelled) {
          // Fallback: let player try the original path directly.
          setAudioSrc(audioPath)
        }
      }
    }

    resolveAudioSrc()

    return () => {
      cancelled = true
      if (revokedUrl) {
        URL.revokeObjectURL(revokedUrl)
      }
    }
  }, [audioPath])

  return (
    <div
      className={`hidden md:flex md:w-1/4 lg:w-1/3 min-w-0 border-r border-gray-200 bg-white flex-col relative shrink-0 ${panelClassName ?? ""}`}
      style={panelStyle}
    >
      {/* Title area */}
      <div className="p-4 border-b border-gray-200">
        <TranscriptButtonGroup
          transcriptCount={
            usePagination
              ? (totalCount ?? convertedSegments.length)
              : transcripts?.length || 0
          }
          onCopyTranscript={onCopyTranscript}
          onOpenMeetingFolder={onOpenMeetingFolder}
          meetingId={meetingId}
          meetingFolderPath={meetingFolderPath}
          onRefetchTranscripts={onRefetchTranscripts}
          layoutMode={layoutMode}
          onToggleLayoutMode={() =>
            setLayoutMode((m) => (m === 'inline' ? 'split' : 'inline'))
          }
        />
      </div>

      {/* Transcript content. Limit selection-based actions to `meeting-transcript-scope`. */}
      <div
        className="flex-1 overflow-hidden pb-4"
        id="meeting-transcript-scope"
      >
        <VirtualizedTranscriptView
          segments={convertedSegments}
          isRecording={isRecording}
          isPaused={false}
          isProcessing={false}
          isStopping={false}
          enableStreaming={false}
          showConfidence={true}
          disableAutoScroll={disableAutoScroll}
          hasMore={hasMore}
          isLoadingMore={isLoadingMore}
          totalCount={totalCount}
          loadedCount={loadedCount}
          onLoadMore={onLoadMore}
          layoutMode={layoutMode}
          playbackTimeSeconds={audioPath ? currentTime : undefined}
          onTimestampClick={audioPath ? handleTimestampClick : undefined}
        />
      </div>

      {/* Audio player at bottom of transcript section */}
      {!isRecording && convertedSegments.length > 0 && (
        <div className="p-3 border-t border-gray-200 bg-white">
          {audioLoading && (
            <div className="text-xs text-gray-400">오디오 파일 확인 중...</div>
          )}
          {!audioLoading && !audioPath && (
            <div className="text-xs text-gray-400">
              재생 가능한 오디오 파일을 찾지 못했습니다.
            </div>
          )}
          {!audioLoading && audioSrc && (
            <div className="">
              <AudioPlayer
                ref={audioPlayerRef}
                src={audioSrc}
                showSkipControls={false}
                showJumpControls={true}
                customAdditionalControls={[]}
                autoPlayAfterSrcChange={false}
                layout="stacked"
                timeFormat="mm:ss"
                listenInterval={100}
                onListen={() => {
                  const audioElement = audioPlayerRef.current?.audio.current
                  if (audioElement) {
                    setCurrentTime(audioElement.currentTime)
                  }
                }}
                onLoadedMetaData={() => {
                  const audioElement = audioPlayerRef.current?.audio.current
                  setDuration(
                    audioElement && Number.isFinite(audioElement.duration)
                      ? audioElement.duration
                      : 0,
                  )
                  setAudioPlayError(null)
                }}
                onSeeked={() => {
                  const audioElement = audioPlayerRef.current?.audio.current
                  if (audioElement) {
                    setCurrentTime(audioElement.currentTime)
                  }
                }}
                onError={(e: Event) => {
                  const el = e.currentTarget as HTMLAudioElement | null
                  const me = el?.error
                  const codeName = me
                    ? ({
                        1: "MEDIA_ERR_ABORTED",
                        2: "MEDIA_ERR_NETWORK",
                        3: "MEDIA_ERR_DECODE",
                        4: "MEDIA_ERR_SRC_NOT_SUPPORTED",
                      } as const)[me.code] ?? `UNKNOWN(${me.code})`
                    : "no-error-object"
                  const srcKind = audioSrc?.startsWith("blob:")
                    ? "blob"
                    : audioSrc?.startsWith("asset:") ||
                        audioSrc?.startsWith("http://asset.")
                      ? "asset"
                      : audioSrc?.startsWith("http")
                        ? "http"
                        : "path"
                  const detail = `${codeName}${me?.message ? ` — ${me.message}` : ""} [src=${srcKind}]`
                  console.error("[AudioPlayer] media error:", detail, e)
                  setAudioPlayError(`오디오 재생 중 오류: ${detail}`)
                }}
              />
            </div>
          )}
          {(audioLookupError || audioPlayError) && (
            <div className="text-xs text-red-500 mt-2">
              {audioPlayError ?? audioLookupError}
            </div>
          )}
        </div>
      )}

      {/* Drag selection -> translation popover for ad-hoc review translations. */}
      <SelectionTranslatePopover scopeSelector="#meeting-transcript-scope" />
    </div>
  )
}
