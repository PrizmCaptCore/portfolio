"use client"

import {
  useCallback,
  useRef,
  useReducer,
  startTransition,
  useEffect,
  useState,
  useMemo,
  memo,
} from "react"
import { useVirtualizer } from "@tanstack/react-virtual"
import { Check } from "lucide-react"
import { useAutoScroll } from "@/hooks/useAutoScroll"
import { useTranscriptStreaming } from "@/hooks/useTranscriptStreaming"
import { ConfidenceIndicator } from "./ConfidenceIndicator"
import { Tooltip, TooltipContent, TooltipTrigger } from "./ui/tooltip"
import { RecordingStatusBar } from "./RecordingStatusBar"
import { motion, AnimatePresence } from "framer-motion"
import { TranscriptSegmentData } from "@/types"

/** What to show under each segment when live assistant features are enabled */
export interface LiveAssistUiOptions {
  showCoaching: boolean
}

export interface VirtualizedTranscriptViewProps {
  /** Transcript segments to display */
  segments: TranscriptSegmentData[]
  /** Whether recording is in progress */
  isRecording?: boolean
  /** Whether recording is paused */
  isPaused?: boolean
  /** Whether processing/finalizing transcription */
  isProcessing?: boolean
  /** Whether stopping */
  isStopping?: boolean
  /** Enable streaming effect for latest segment */
  enableStreaming?: boolean
  /** Show confidence indicators */
  showConfidence?: boolean
  /** Live assistant rows (intent / reply hints); off for meeting history unless set */
  liveAssistUi?: LiveAssistUiOptions
  /** Completely disable auto-scroll behavior (for meeting details page) */
  disableAutoScroll?: boolean
  /**
   * Optional ref to the *actual* scrollable ancestor. When the parent
   * already provides an `overflow-y-auto` container (e.g. the recording
   * page's TranscriptPanel), pass that ref here so useAutoScroll, the
   * virtualizer, and the load-more observers all agree on which element
   * scrolls. Without this, our inner div with `h-full overflow-y-auto`
   * collapses to content height inside the parent scroll, the wheel
   * events go to the parent only, and our hook listens to the wrong
   * element — manifesting as "I scrolled up but the next transcript
   * line yanked me back". Defaults to the internal scrollRef when omitted
   * (meeting-details path).
   */
  scrollContainerRef?: React.RefObject<HTMLDivElement | null>
  /** Whether translation rows should be shown. When false, translated results stay in data but are hidden. */
  showTranslationRow?: boolean
  /**
   * 'inline' (default) stacks the translation underneath each transcript line.
   * 'split' renders transcript and translation as two side-by-side columns
   * within each segment row, so users can compare them line-for-line.
   */
  layoutMode?: 'inline' | 'split'
  /** Current audio playback time in seconds for transcript highlighting. */
  playbackTimeSeconds?: number
  /** Seek playback when transcript timestamp is clicked. */
  onTimestampClick?: (seconds: number) => void

  // Pagination props (infinite scroll)
  hasMore?: boolean
  isLoadingMore?: boolean
  totalCount?: number
  loadedCount?: number
  onLoadMore?: () => void
}

// Threshold for enabling virtualization (below this, use simple rendering)
const VIRTUALIZATION_THRESHOLD = 10

// Helper function to format seconds as recording-relative time [MM:SS]
function formatRecordingTime(seconds: number | undefined): string {
  if (seconds === undefined) return "[--:--]"

  const totalSeconds = Math.floor(seconds)
  const minutes = Math.floor(totalSeconds / 60)
  const secs = totalSeconds % 60

  return `[${minutes.toString().padStart(2, "0")}:${secs.toString().padStart(2, "0")}]`
}

// Helper function to remove filler words and repetitions
function cleanStopWords(text: string): string {
  const stopWords = ["uh", "um", "er", "ah", "hmm", "hm", "eh", "oh"]

  let cleanedText = text
  stopWords.forEach((word) => {
    const pattern = new RegExp(`\\b${word}\\b[,\\s]*`, "gi")
    cleanedText = cleanedText.replace(pattern, " ")
  })

  return cleanedText.replace(/\s+/g, " ").trim()
}

// Memoized transcript segment component
const defaultLiveAssistUi: LiveAssistUiOptions = {
  showCoaching: false,
}

const TranscriptSegment = memo(function TranscriptSegment({
  id,
  timestamp,
  text,
  tentativeText,
  source,
  confidence,
  isStreaming,
  showConfidence,
  translated_text,
  translation_pending,
  translation_error,
  coaching_intent,
  coaching_replies,
  liveAssistUi = defaultLiveAssistUi,
  showTranslationRow = true,
  layoutMode = 'inline',
  isActiveByPlayback = false,
  onTimestampClick,
}: {
  id: string
  timestamp: number
  text: string
  /** Volatile tail of `text` (stable-prefix commit logic). Rendered dimmed/italic. */
  tentativeText?: string
  /** "Me" (microphone-dominant) or "Speaker" (system-audio-dominant), based on backend speaker detection. */
  source?: string
  confidence?: number
  isStreaming: boolean
  showConfidence: boolean
  translated_text?: string
  translation_pending?: boolean
  translation_error?: string
  coaching_intent?: string
  coaching_replies?: string[]
  liveAssistUi?: LiveAssistUiOptions
  /** Whether to render the translation row. Toggling translation off hides existing translated text without deleting it. */
  showTranslationRow?: boolean
  /** See VirtualizedTranscriptViewProps.layoutMode */
  layoutMode?: 'inline' | 'split'
  isActiveByPlayback?: boolean
  onTimestampClick?: (seconds: number) => void
}) {
  const displayText =
    cleanStopWords(text) || (text.trim() === "" ? "[무음]" : text)
  // Stable-prefix commit split: if a tentative tail is present and matches the
  // suffix of the displayed text, render the prefix solid and the tail dimmed.
  // (cleanStopWords may strip filler words, so the suffix match can fail —
  // in that case fall back to rendering the whole text as committed.)
  let committedPart = displayText
  let tentativePart = ""
  if (
    tentativeText &&
    tentativeText.length > 0 &&
    displayText.endsWith(tentativeText)
  ) {
    committedPart = displayText
      .slice(0, displayText.length - tentativeText.length)
      .trimEnd()
    tentativePart = tentativeText
  }
  const hasTranslationContent =
    translation_pending || !!translated_text || !!translation_error
  const showTranslation = showTranslationRow && hasTranslationContent
  const renderTranscriptLine = () => (
    <p
      className={`text-sm leading-relaxed ${isActiveByPlayback ? "text-blue-600" : "text-gray-500"}`}
    >
      {committedPart}
      {tentativePart && (
        <>
          {committedPart && " "}
          <span className="text-gray-400 italic opacity-70">
            {tentativePart}
          </span>
        </>
      )}
    </p>
  )

  // Translation cell is shared between inline (stacked) and split (side-by-side)
  // layouts. In split mode it is always rendered (even when empty) so that the
  // two columns stay aligned across segments.
  const renderTranslationCell = () => {
    if (translation_error) {
      return (
        <span className="text-amber-700 text-xs">{translation_error}</span>
      )
    }
    if (!translated_text && !translation_pending) {
      return <span className="text-xs text-gray-300">—</span>
    }
    return (
      <p className="text-base text-gray-900 leading-relaxed font-medium">
        {translated_text}
        {translation_pending && (
          <span className="inline-block w-0.5 h-4 bg-gray-600 ml-0.5 animate-pulse align-middle" />
        )}
      </p>
    )
  }

  const renderTranscriptCell = () =>
    isStreaming ? (
      <div className="bg-gray-100 border border-gray-200 rounded-lg px-3 py-2">
        {renderTranscriptLine()}
      </div>
    ) : (
      <div
        className={
          isActiveByPlayback
            ? "rounded px-2 py-1 -mx-1 bg-blue-50 border border-blue-100"
            : undefined
        }
      >
        {renderTranscriptLine()}
      </div>
    )

  return (
    <div id={`segment-${id}`} className="mb-3">
      <div className="flex items-start gap-2">
        {/* Timestamp and speaker label; both stay out of drag-selection translation targets. */}
        <div
          className="flex flex-col items-end mt-1 flex-shrink-0 min-w-[60px] select-none"
          style={{ WebkitUserSelect: "none", userSelect: "none" }}
        >
          <Tooltip>
            <TooltipTrigger>
              <button
                type="button"
                onClick={() => onTimestampClick?.(timestamp)}
                className={`text-xs transition-colors ${
                  onTimestampClick
                    ? "text-blue-500 hover:text-blue-700 cursor-pointer"
                    : "text-gray-400 cursor-default"
                }`}
                title={onTimestampClick ? "해당 시점으로 이동" : "타임스탬프"}
              >
                {formatRecordingTime(timestamp)}
              </button>
            </TooltipTrigger>
            <TooltipContent>
              {confidence !== undefined && showConfidence && (
                <ConfidenceIndicator
                  confidence={confidence}
                  showIndicator={showConfidence}
                />
              )}
            </TooltipContent>
          </Tooltip>
          {/* Speaker label shown below the timestamp. */}
          {source && (
            <span
              className={`text-[10px] mt-0.5 px-1 rounded ${
                source === "Me"
                  ? "bg-blue-50 text-blue-600"
                  : "bg-gray-100 text-gray-500"
              }`}
              title={
                source === "Me"
                  ? "마이크 주요 음원 (나)"
                  : "시스템 오디오 주요 음원 (상대방)"
              }
            >
              {source === "Me" ? "나" : "상대"}
            </span>
          )}
        </div>
        {layoutMode === 'split' && showTranslationRow ? (
          <div className="flex-1 grid grid-cols-2 gap-3 min-w-0">
            <div className="min-w-0">{renderTranscriptCell()}</div>
            {/* Keep the translation column out of drag-selection so it does
                not get re-sent into translation along with its own source. */}
            <div
              className="min-w-0 select-none"
              style={{ WebkitUserSelect: "none", userSelect: "none" }}
            >
              {renderTranslationCell()}
            </div>
          </div>
        ) : (
          <div className="flex-1 min-w-0">
            {renderTranscriptCell()}
            {showTranslation && (
              <div
                className="mt-1 select-none"
                style={{ WebkitUserSelect: "none", userSelect: "none" }}
              >
                {renderTranslationCell()}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
})

export const VirtualizedTranscriptView: React.FC<
  VirtualizedTranscriptViewProps
> = ({
  segments,
  isRecording = false,
  isPaused = false,
  isProcessing = false,
  isStopping = false,
  enableStreaming = false,
  showConfidence = true,
  liveAssistUi = defaultLiveAssistUi,
  disableAutoScroll = false,
  scrollContainerRef,
  hasMore = false,
  isLoadingMore = false,
  totalCount = 0,
  loadedCount = 0,
  onLoadMore,
  showTranslationRow = true,
  layoutMode = 'inline',
  playbackTimeSeconds,
  onTimestampClick,
}) => {
  const playbackSecond =
    typeof playbackTimeSeconds === "number" &&
    Number.isFinite(playbackTimeSeconds)
      ? playbackTimeSeconds
      : undefined
  const activeSegmentIdByPlayback = useMemo(() => {
    if (typeof playbackSecond !== "number" || segments.length === 0)
      return undefined

    const getEffectiveEnd = (index: number) => {
      const segment = segments[index]
      const nextStart = segments[index + 1]?.timestamp
      const fallbackEnd =
        typeof nextStart === "number" ? nextStart : segment.timestamp + 1
      const rawEnd = segment.endTime ?? fallbackEnd
      return Math.max(segment.timestamp, rawEnd)
    }

    for (let i = 0; i < segments.length; i += 1) {
      if (playbackSecond < getEffectiveEnd(i)) {
        return segments[i].id
      }
    }

    return undefined
  }, [playbackSecond, segments])
  // Create scroll ref first - shared between virtualizer and auto-scroll hook.
  // When the caller supplies an external ref (parent owns the actual
  // scroll container), prefer that — otherwise our hook would listen to
  // a non-scrolling inner div and miss the user's wheel events entirely.
  const internalScrollRef = useRef<HTMLDivElement>(null)
  const scrollRef = scrollContainerRef ?? internalScrollRef
  const usingExternalScroll = scrollContainerRef != null
  // Ref for infinite scroll trigger element
  const loadMoreTriggerRef = useRef<HTMLDivElement>(null)

  // Force re-render without flushSync (avoids React warning)
  const [, rerender] = useReducer((x: number) => x + 1, 0)

  // Setup virtualizer for efficient rendering of large lists
  const virtualizer = useVirtualizer({
    count: segments.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => 60, // Estimated height per segment
    overscan: 10, // Render extra items above/below viewport
    onChange: () => {
      startTransition(() => {
        rerender()
      })
    },
  })

  // Custom hook for auto-scrolling (supports both virtualized and non-virtualized).
  // We surface the state + manual-scroll callback so the toggle pill below
  // can show the user what mode they're in and let them flip it on demand
  // — implicit intent detection alone proved unreliable across momentum
  // scrolling, partial transcript updates, and Framer animation timing.
  const { autoScroll, setAutoScroll, scrollToBottom } = useAutoScroll({
    scrollRef,
    segments,
    isRecording,
    isPaused,
    virtualizer,
    virtualizationThreshold: VIRTUALIZATION_THRESHOLD,
    disableAutoScroll,
  })

  // Streaming text effect hook (typewriter animation for new transcripts)
  const { streamingSegmentId, getDisplayText } = useTranscriptStreaming(
    segments,
    isRecording,
    enableStreaming,
  )

  // Infinite scroll: IntersectionObserver to trigger loading more
  useEffect(() => {
    if (
      !onLoadMore ||
      !hasMore ||
      isLoadingMore ||
      isRecording ||
      segments.length === 0
    ) {
      return
    }

    const triggerElement = loadMoreTriggerRef.current
    if (!triggerElement) return

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting && hasMore && !isLoadingMore) {
          onLoadMore()
        }
      },
      {
        root: null,
        rootMargin: "100px",
        threshold: 0,
      },
    )

    observer.observe(triggerElement)

    return () => observer.disconnect()
  }, [hasMore, isLoadingMore, onLoadMore, isRecording, segments.length])

  // Scroll-based fallback for fast scrolling
  useEffect(() => {
    if (!onLoadMore || !hasMore || isLoadingMore || isRecording) return

    const scrollElement = scrollRef.current
    if (!scrollElement) return

    let ticking = false

    const handleScroll = () => {
      if (ticking || isLoadingMore || !hasMore) return

      ticking = true
      requestAnimationFrame(() => {
        const { scrollTop, scrollHeight, clientHeight } = scrollElement
        const scrollBottom = scrollHeight - scrollTop - clientHeight

        // Trigger load when within 200px of bottom
        if (scrollBottom < 200 && hasMore && !isLoadingMore) {
          onLoadMore()
        }
        ticking = false
      })
    }

    scrollElement.addEventListener("scroll", handleScroll, { passive: true })
    return () => scrollElement.removeEventListener("scroll", handleScroll)
  }, [onLoadMore, hasMore, isLoadingMore, isRecording])

  // Use simple rendering for small lists, virtualization for large lists
  const useVirtualization = segments.length >= VIRTUALIZATION_THRESHOLD

  return (
    <div
      // When the parent owns the scroll container we drop `h-full
      // overflow-y-auto` from this inner div — having two nested scroll
      // surfaces makes wheel events ambiguous and gives the parent's
      // scroll handler nothing to listen to until the inner container
      // exhausts its own scroll. Single-source-of-truth wins.
      ref={internalScrollRef}
      className={
        usingExternalScroll
          ? "flex flex-col px-4 py-2"
          : "flex flex-col h-full overflow-y-auto px-4 py-2"
      }
    >
      {/* Recording Status Bar - Sticky at top, always visible when recording */}
      <AnimatePresence>
        {isRecording && (
          <div className="sticky top-0 z-10 bg-white pb-2">
            <RecordingStatusBar isPaused={isPaused} />
          </div>
        )}
      </AnimatePresence>

      {/* Content - add padding when recording to prevent overlap */}
      <div className={isRecording ? "pt-2" : ""}>
        {segments.length === 0 ? (
          // Empty state
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="text-center text-gray-500 mt-8"
          >
            {isRecording ? (
              <>
                <div className="flex items-center justify-center mb-3">
                  <div
                    className={`w-3 h-3 rounded-full ${isPaused ? "bg-orange-500" : "bg-blue-500 animate-pulse"}`}
                  ></div>
                </div>
                <p className="text-sm text-gray-600">
                  {isPaused ? "녹음이 일시정지되었습니다" : "음성을 기다리는 중…"}
                </p>
                <p className="text-xs mt-1 text-gray-400">
                  {isPaused
                    ? "재개를 눌러 녹음을 계속하세요"
                    : "말을 시작하면 실시간으로 전사됩니다"}
                </p>
              </>
            ) : (
              <>
                <p className="text-lg font-semibold">
                  Relay Assistant에 오신 걸 환영합니다!
                </p>
                <p className="text-xs mt-1">
                  녹음을 시작하면 실시간 전사가 표시됩니다
                </p>
              </>
            )}
          </motion.div>
        ) : useVirtualization ? (
          // Virtualized rendering for large lists
          <>
            <div
              style={{
                height: virtualizer.getTotalSize(),
                width: "100%",
                position: "relative",
              }}
            >
              {virtualizer.getVirtualItems().map((virtualRow) => {
                const segment = segments[virtualRow.index]
                const isStreaming = streamingSegmentId === segment.id

                return (
                  <div
                    key={segment.id}
                    data-index={virtualRow.index}
                    ref={virtualizer.measureElement}
                    style={{
                      position: "absolute",
                      top: 0,
                      left: 0,
                      width: "100%",
                      transform: `translateY(${virtualRow.start}px)`,
                    }}
                  >
                    <TranscriptSegment
                      id={segment.id}
                      timestamp={segment.timestamp}
                      text={getDisplayText(segment)}
                      tentativeText={segment.tentative_text}
                      source={segment.source}
                      confidence={segment.confidence}
                      isStreaming={isStreaming}
                      showConfidence={showConfidence}
                      translated_text={segment.translated_text}
                      translation_pending={segment.translation_pending}
                      translation_error={segment.translation_error}
                      coaching_intent={segment.coaching_intent}
                      coaching_replies={segment.coaching_replies}
                      liveAssistUi={liveAssistUi}
                      showTranslationRow={showTranslationRow}
                      layoutMode={layoutMode}
                      isActiveByPlayback={
                        segment.id === activeSegmentIdByPlayback
                      }
                      onTimestampClick={onTimestampClick}
                    />
                  </div>
                )
              })}
            </div>

            {/* Infinite scroll trigger and loading indicator */}
            {(hasMore || isLoadingMore) &&
              !isRecording &&
              segments.length > 0 && (
                <div
                  ref={loadMoreTriggerRef}
                  className="flex justify-center items-center py-4 mt-2"
                >
                  {isLoadingMore ? (
                    <div className="flex items-center gap-2 text-gray-500">
                      <div className="w-4 h-4 border-2 border-gray-300 border-t-gray-600 rounded-full animate-spin" />
                      <span className="text-sm">더 불러오는 중…</span>
                    </div>
                  ) : hasMore && totalCount > 0 ? (
                    <span className="text-sm text-gray-400">
                      세그먼트 {loadedCount}/{totalCount}개 표시 중
                    </span>
                  ) : null}
                </div>
              )}

            {/* Listening indicator when recording */}
            {!isStopping &&
              isRecording &&
              !isPaused &&
              !isProcessing &&
              segments.length > 0 && (
                <motion.div
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  className="flex items-center gap-2 mt-4 text-gray-500"
                >
                  <div className="w-2 h-2 bg-blue-500 rounded-full animate-pulse"></div>
                  <span className="text-sm">듣고 있는 중…</span>
                </motion.div>
              )}
          </>
        ) : (
          // Simple rendering for small lists (better animations)
          <>
            <div className="space-y-1">
              {segments.map((segment) => {
                const isStreaming = streamingSegmentId === segment.id

                return (
                  <motion.div
                    key={segment.id}
                    initial={{ opacity: 0, y: 5 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.15 }}
                  >
                    <TranscriptSegment
                      id={segment.id}
                      timestamp={segment.timestamp}
                      text={getDisplayText(segment)}
                      tentativeText={segment.tentative_text}
                      source={segment.source}
                      confidence={segment.confidence}
                      isStreaming={isStreaming}
                      showConfidence={showConfidence}
                      translated_text={segment.translated_text}
                      translation_pending={segment.translation_pending}
                      translation_error={segment.translation_error}
                      coaching_intent={segment.coaching_intent}
                      coaching_replies={segment.coaching_replies}
                      liveAssistUi={liveAssistUi}
                      showTranslationRow={showTranslationRow}
                      layoutMode={layoutMode}
                      isActiveByPlayback={
                        segment.id === activeSegmentIdByPlayback
                      }
                      onTimestampClick={onTimestampClick}
                    />
                  </motion.div>
                )
              })}
            </div>

            {/* Infinite scroll trigger (for small lists that grow) */}
            {(hasMore || isLoadingMore) &&
              !isRecording &&
              segments.length > 0 && (
                <div
                  ref={loadMoreTriggerRef}
                  className="flex justify-center items-center py-4 mt-2"
                >
                  {isLoadingMore ? (
                    <div className="flex items-center gap-2 text-gray-500">
                      <div className="w-4 h-4 border-2 border-gray-300 border-t-gray-600 rounded-full animate-spin" />
                      <span className="text-sm">더 불러오는 중…</span>
                    </div>
                  ) : hasMore && totalCount > 0 ? (
                    <span className="text-sm text-gray-400">
                      세그먼트 {loadedCount}/{totalCount}개 표시 중
                    </span>
                  ) : null}
                </div>
              )}

            {/* Listening indicator when recording */}
            {!isStopping &&
              isRecording &&
              !isPaused &&
              !isProcessing &&
              segments.length > 0 && (
                <motion.div
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  className="flex items-center gap-2 mt-4 text-gray-500"
                >
                  <div className="w-2 h-2 bg-blue-500 rounded-full animate-pulse"></div>
                  <span className="text-sm">듣고 있는 중…</span>
                </motion.div>
              )}
          </>
        )}
      </div>

      {/* Auto-scroll toggle pill — visible only during live recording.
          Sticky so it stays pinned to the viewport bottom while the
          transcript scrolls behind it. The wrapper is `pointer-events-none`
          so the empty space around the pill doesn't intercept selection /
          drag actions on the transcript; the button itself opts back in
          with `pointer-events-auto`.

          Two visual states, designed so the user can tell at a glance
          whether auto-scroll is currently on:
            - OFF: outlined "활성화" CTA — explicit invitation to enable.
            - ON:  filled blue pill with a check + "켜짐" label.
          On click, OFF→ON also jumps to the latest content. */}
      {isRecording && !disableAutoScroll && (
        <div className="pointer-events-none sticky bottom-3 z-20 mt-2 flex justify-end pr-3">
          <button
            type="button"
            onClick={() => {
              if (autoScroll) {
                setAutoScroll(false)
              } else {
                scrollToBottom()
              }
            }}
            className={`pointer-events-auto inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium shadow-md transition-colors ${
              autoScroll
                ? "bg-blue-600 text-white hover:bg-blue-700"
                : "border border-gray-200 bg-white text-gray-700 hover:bg-gray-50"
            }`}
            aria-pressed={autoScroll}
            title={
              autoScroll
                ? "자동 스크롤이 켜져 있습니다 — 누르면 비활성화"
                : "자동 스크롤이 꺼져 있습니다 — 누르면 활성화"
            }
          >
            {autoScroll ? (
              <Check className="h-3 w-3" />
            ) : (
              <span className="inline-block h-3 w-3 rounded-sm border border-gray-300" />
            )}
            {autoScroll ? "켜짐" : "활성화"}
          </button>
        </div>
      )}
    </div>
  )
}
