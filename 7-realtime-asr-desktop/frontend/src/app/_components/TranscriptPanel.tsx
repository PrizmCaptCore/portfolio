import { VirtualizedTranscriptView } from "@/components/VirtualizedTranscriptView"
import { PermissionWarning } from "@/components/PermissionWarning"
import { SelectionTranslatePopover } from "@/components/SelectionTranslatePopover"
import { Button } from "@/components/ui/button"
import { ButtonGroup } from "@/components/ui/button-group"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Switch } from "@/components/ui/switch"
import { Columns2, Copy, Languages, Rows2 } from "lucide-react"
import { useTranscripts } from "@/contexts/TranscriptContext"
import { useConfig } from "@/contexts/ConfigContext"
import { useRecordingState } from "@/contexts/RecordingStateContext"
import { usePermissionCheck } from "@/hooks/usePermissionCheck"
import { ModalType } from "@/hooks/useModalState"
import { useIsLinux } from "@/hooks/usePlatform"
import { useEffect, useMemo, useState } from "react"

/**
 * TranscriptPanel Component
 *
 * Displays transcript content with controls for copying and language settings.
 * Uses TranscriptContext, ConfigContext, and RecordingStateContext internally.
 */

interface TranscriptPanelProps {
  // indicates stop-processing state for transcripts; derived from backend statuses.
  isProcessingStop: boolean
  isStopping: boolean
  showModal: (name: ModalType, message?: string) => void
}

export function TranscriptPanel({
  isProcessingStop,
  isStopping,
  showModal,
}: TranscriptPanelProps) {
  // Contexts
  const { transcripts, transcriptContainerRef, copyTranscript } =
    useTranscripts()
  const {
    liveCoachingEnabled,
    translationEnabled,
    setTranslationEnabled,
    translatorWarming,
    userLanguage,
    setUserLanguage,
    sourceLanguage,
    setSourceLanguage,
    sourceLanguageConfigured,
    userLanguageConfigured,
  } = useConfig()
  const { isRecording, isPaused } = useRecordingState()
  const { checkPermissions, isChecking, hasSystemAudio, hasMicrophone } =
    usePermissionCheck()
  const isLinux = useIsLinux()

  // Convert transcripts to segments for virtualized view
  const segments = useMemo(
    () =>
      transcripts.map((t) => ({
        id: t.id,
        timestamp: t.audio_start_time ?? 0,
        endTime: t.audio_end_time,
        text: t.text,
        source: t.source,
        is_partial: t.is_partial,
        confidence: t.confidence,
        tentative_text: t.tentative_text,
        translated_text: t.translated_text,
        translation_pending: t.translation_pending,
        translation_error: t.translation_error,
        coaching_intent: t.coaching_intent,
        coaching_replies: t.coaching_replies,
      })),
    [transcripts],
  )

  const liveAssistUi = useMemo(
    () => ({
      showCoaching: liveCoachingEnabled,
    }),
    [liveCoachingEnabled],
  )

  // Side-by-side vs stacked layout for transcript + translation. Persisted so
  // the choice survives reloads.
  const [layoutMode, setLayoutMode] = useState<"inline" | "split">(() => {
    if (typeof window === "undefined") return "inline"
    return window.localStorage.getItem("transcriptLayoutMode") === "split"
      ? "split"
      : "inline"
  })
  useEffect(() => {
    if (typeof window === "undefined") return
    window.localStorage.setItem("transcriptLayoutMode", layoutMode)
  }, [layoutMode])

  return (
    <div
      ref={transcriptContainerRef}
      className="w-full border-gray-200 bg-white flex flex-col overflow-y-auto"
    >
      {/* Title area - Sticky header */}
      <div className="sticky top-0 z-10 bg-white p-4 border-gray-200">
        <div className="flex flex-col space-y-3">
          <div className="flex  flex-col space-y-2">
            <div className="flex justify-center items-center gap-3 flex-wrap">
              {/* Listening (source) language. The STT pipeline only
                  speaks English right now — the dropdown still gates the
                  recording flow on an explicit user pick so we have a
                  consistent "languages have been confirmed" signal once
                  more sources land.

                  Empty initial state: when the user has never clicked
                  this dropdown, we pass an unmatched `value` so Radix
                  falls back to the placeholder. Once they pick "영어"
                  the configured flag flips and the badge renders normally.
                  amber border is the visual nudge to fix it before
                  recording. */}
              <div className="flex items-center gap-1.5 text-xs text-gray-600">
                <span className="text-gray-400">듣는 언어</span>
                <Select
                  value={sourceLanguageConfigured ? sourceLanguage : ""}
                  onValueChange={setSourceLanguage}
                >
                  <SelectTrigger
                    className={`h-7 w-[88px] text-xs px-2 ${
                      !sourceLanguageConfigured
                        ? "border-amber-400 ring-1 ring-amber-300 animate-pulse"
                        : ""
                    }`}
                  >
                    <SelectValue placeholder="선택">
                      {sourceLanguageConfigured ? "영어" : null}
                    </SelectValue>
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="en">영어</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              {/* Translation subtitle (target) language. Locked to
                  Korean: the live-translate path is EN→KO only — both
                  the Tauri-side `api_translate` (errors on non-ko
                  targets) and the RunPod translate Pod
                  (`forward_translate` takes no target language) are
                  hardcoded for that single direction. Adding more
                  targets here requires upgrading the upstream Pod to a
                  multi-direction model first.

                  Same empty-initial / amber-highlight pattern as the
                  source picker; user still has to confirm by clicking. */}
              <div className="flex items-center gap-1.5 text-xs text-gray-600">
                <span className="text-gray-400">번역 자막 언어</span>
                <Select
                  value={userLanguageConfigured ? userLanguage : ""}
                  onValueChange={setUserLanguage}
                >
                  <SelectTrigger
                    className={`h-7 w-[88px] text-xs px-2 ${
                      !userLanguageConfigured
                        ? "border-amber-400 ring-1 ring-amber-300 animate-pulse"
                        : ""
                    }`}
                  >
                    <SelectValue placeholder="선택">
                      {userLanguageConfigured ? "한국어" : null}
                    </SelectValue>
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="ko">한국어</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              {/* Google Translate auto-translation toggle. Translation only runs when
                  detected speech differs from the selected user language. */}
              <label
                className="flex items-center gap-2 text-xs text-gray-600 cursor-pointer select-none"
                title="감지된 다른 언어에 대해 자동 번역을 켜거나 끕니다"
              >
                <Languages className="h-3.5 w-3.5" />
                <span className="hidden md:inline">번역</span>
                <Switch
                  checked={translationEnabled}
                  onCheckedChange={setTranslationEnabled}
                  aria-label="번역 토글"
                />
                {translatorWarming ? (
                  <span className="text-[11px] text-amber-600 animate-pulse">
                    번역기 준비 중...
                  </span>
                ) : null}
              </label>
              <ButtonGroup>
                {transcripts?.length > 0 && (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={copyTranscript}
                    title="전사 복사"
                  >
                    <Copy />
                    <span className="hidden md:inline">복사</span>
                  </Button>
                )}
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() =>
                    setLayoutMode((m) => (m === "inline" ? "split" : "inline"))
                  }
                  title={
                    layoutMode === "split"
                      ? "번역을 transcript 아래에 표시"
                      : "번역을 transcript와 나란히 표시"
                  }
                >
                  {layoutMode === "split" ? (
                    <Rows2 className="h-3.5 w-3.5" />
                  ) : (
                    <Columns2 className="h-3.5 w-3.5" />
                  )}
                  <span className="hidden md:inline">
                    {layoutMode === "split" ? "쌓기" : "나누기"}
                  </span>
                </Button>
              </ButtonGroup>
            </div>
          </div>
        </div>
      </div>

      {/* Permission Warning - Not needed on Linux */}
      {!isRecording && !isChecking && !isLinux && (
        <div className="flex justify-center px-4 pt-4">
          <PermissionWarning
            hasMicrophone={hasMicrophone}
            hasSystemAudio={hasSystemAudio}
            onRecheck={checkPermissions}
            isRechecking={isChecking}
          />
        </div>
      )}

      {/* Limit selection-triggered actions to the live transcript area. */}
      <div className="pb-20" id="live-transcript-scope">
        <div className="flex justify-center">
          <div className="w-2/3 max-w-[750px]">
            <VirtualizedTranscriptView
              segments={segments}
              isRecording={isRecording}
              isPaused={isPaused}
              isProcessing={isProcessingStop}
              isStopping={isStopping}
              enableStreaming={isRecording}
              showConfidence={true}
              liveAssistUi={liveAssistUi}
              showTranslationRow={translationEnabled}
              layoutMode={layoutMode}
              // This panel is the actual scroll container (`overflow-y-auto`
              // on the outer div) — handing the ref down lets the
              // virtualizer's auto-scroll hook listen to *this* element's
              // wheel events. Without this the hook bound to an inner
              // non-scrolling div, so manual scroll-up was never observed
              // and the next transcript line yanked the view back down.
              scrollContainerRef={transcriptContainerRef}
            />
          </div>
        </div>
      </div>

      {/* Drag selection -> translation popover. This remains available even when
          auto-translation is enabled so users can translate multiple rows at once. */}
      <SelectionTranslatePopover scopeSelector="#live-transcript-scope" />
    </div>
  )
}
