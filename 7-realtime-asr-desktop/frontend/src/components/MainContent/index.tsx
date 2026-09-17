"use client"

import React, { useEffect, useMemo, useState } from "react"
import { usePathname, useRouter } from "next/navigation"
import {
  MessageSquare,
  Mic,
  PanelLeftOpen,
  SearchIcon,
  X,
} from "lucide-react"
import { useSidebar } from "@/components/Sidebar/SidebarProvider"
import { useRecordingState } from "@/contexts/RecordingStateContext"
import { useTranscripts } from "@/contexts/TranscriptContext"
import { useConfig } from "@/contexts/ConfigContext"
import { sendChatMessage } from "@/services/chatService"
import {
  InputGroup,
  InputGroupAddon,
  InputGroupButton,
  InputGroupInput,
} from "@/components/ui/input-group"
import { useResizableDockedAiRail } from "@/hooks/useResizableDockedAiRail"
import { cn } from "@/lib/utils"
import { AgentChatPanel } from "./AgentChatPanel"

const DOCKED_AI_MINIMIZED_KEY = "relay-docked-ai-minimized"

interface MainContentProps {
  children: React.ReactNode
}

const MainContent: React.FC<MainContentProps> = ({ children }) => {
  const pathname = usePathname()
  const {
    isCollapsed,
    toggleCollapse,
    searchQuery,
    updateSearchQuery,
    searchResults,
    isSearching,
    currentMeeting,
    setCurrentMeeting,
    handleRecordingToggle,
  } = useSidebar()
  const router = useRouter()
  const { isRecording } = useRecordingState()
  const { languagesConfigured } = useConfig()
  const {
    transcripts,
    meetingTitle: contextMeetingTitle,
    currentMeetingId,
  } = useTranscripts()
  const [isAgentDrawerOpen, setIsAgentDrawerOpen] = useState(false)
  const [agentInput, setAgentInput] = useState("")
  const [isAgentSending, setIsAgentSending] = useState(false)
  const [agentMessages, setAgentMessages] = useState<
    Array<{ role: "user" | "agent"; text: string }>
  >([
    {
      role: "agent",
      text: "질문을 남기면 현재 페이지의 미팅 내용과 Notion 노트를 바탕으로 답해드릴게요.",
    },
  ])

  const hideTopToolbar = pathname === "/settings"
  const showAgentChrome = !hideTopToolbar
  const [isDockedAiMinimized, setIsDockedAiMinimized] = useState(false)
  const uniqueSearchResults = useMemo(() => {
    const seenMeetingIds = new Set<string>()
    return searchResults.filter((result) => {
      if (seenMeetingIds.has(result.id)) return false
      seenMeetingIds.add(result.id)
      return true
    })
  }, [searchResults])
  const highlightMatch = (text: string, query: string) => {
    const trimmedQuery = query.trim()
    if (!trimmedQuery) return text

    const escapedQuery = trimmedQuery.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
    const regex = new RegExp(`(${escapedQuery})`, "gi")
    const parts = text.split(regex)

    return parts.map((part, idx) =>
      part.toLowerCase() === trimmedQuery.toLowerCase() ? (
        <mark
          key={`${part}-${idx}`}
          className="rounded bg-yellow-200 px-0.5 text-gray-900"
        >
          {part}
        </mark>
      ) : (
        <React.Fragment key={`${part}-${idx}`}>{part}</React.Fragment>
      ),
    )
  }

  useEffect(() => {
    try {
      if (window.localStorage.getItem(DOCKED_AI_MINIMIZED_KEY) === "1") {
        setIsDockedAiMinimized(true)
      }
    } catch {
      /* ignore */
    }
  }, [])

  const setDockedAiMinimized = (minimized: boolean) => {
    setIsDockedAiMinimized(minimized)
    try {
      window.localStorage.setItem(DOCKED_AI_MINIMIZED_KEY, minimized ? "1" : "0")
    } catch {
      /* ignore */
    }
  }

  const { dockedAiRailVar, onResizePointerDown, isXl } = useResizableDockedAiRail(
    showAgentChrome,
    !isDockedAiMinimized,
  )

  const handleSendAgentMessage = async () => {
    const text = agentInput.trim()
    if (!text || isAgentSending) return

    const newHistory = [
      ...agentMessages,
      { role: "user" as const, text },
    ]
    setAgentMessages(newHistory)
    setAgentInput("")
    setIsAgentSending(true)

    // Concatenate finalized transcript lines as conversation context for the
    // model. Partial rows would inject the same words twice as they finalize.
    const transcriptText = transcripts
      .filter((t) => t.text && t.is_partial !== true)
      .map((t) => (t.source ? `${t.source}: ${t.text}` : t.text))
      .join("\n")

    const meetingTitle =
      currentMeeting?.title && currentMeeting.title !== "+ 새 회의"
        ? currentMeeting.title
        : contextMeetingTitle && contextMeetingTitle !== "+ New Call"
          ? contextMeetingTitle
          : undefined

    // Forward the meeting id whenever the user is "on" a meeting — recording,
    // viewing the details page, or otherwise scoped to it via the sidebar.
    // chatService uses this to inject that meeting's summary + transcript
    // directly into the LLM prompt so the chat works without depending on
    // RAG (Notion-less users would otherwise see empty results). The
    // 'intro-call' placeholder seeded by SidebarProvider is filtered out.
    // During recording we still prefer the TranscriptContext id since that
    // tracks the live recording's frontend id.
    const sidebarMeetingId =
      currentMeeting?.id && currentMeeting.id !== 'intro-call'
        ? currentMeeting.id
        : undefined
    const meetingIdForChat = isRecording
      ? currentMeetingId ?? sidebarMeetingId
      : sidebarMeetingId

    try {
      const reply = await sendChatMessage({
        history: newHistory,
        meetingTitle,
        transcriptText: transcriptText.length > 0 ? transcriptText : undefined,
        currentMeetingId: meetingIdForChat,
      })
      setAgentMessages((prev) => [...prev, { role: "agent", text: reply }])
    } catch (e) {
      const msg = e instanceof Error ? e.message : "unknown_error"
      setAgentMessages((prev) => [
        ...prev,
        { role: "agent", text: `오류가 발생했어요: ${msg}` },
      ])
    } finally {
      setIsAgentSending(false)
    }
  }

  return (
    <main
      className={cn(
        "flex min-h-0 flex-1 flex-col overflow-hidden transition-all duration-300",
        isCollapsed ? "ml-16" : "ml-64",
      )}
      style={{ ["--docked-ai-rail-width" as string]: dockedAiRailVar }}
    >
      <div className="flex min-h-0 flex-1 flex-col overflow-hidden xl:flex-row">
        <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
          {!hideTopToolbar && (
            <header
              className="flex shrink-0 flex-col border-b border-gray-200 bg-white transition-[box-shadow] duration-200"
              aria-label="기본 툴바"
            >
              <div className="flex h-14 shrink-0 items-center gap-2 px-2">
                {isCollapsed && (
                  <button
                    type="button"
                    onClick={toggleCollapse}
                    aria-label="사이드바 펼치기"
                    className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md border border-gray-200 text-gray-600 transition-colors hover:bg-gray-50"
                  >
                    <PanelLeftOpen className="h-5 w-5 shrink-0" />
                  </button>
                )}
                <div className="relative mx-auto w-full max-w-2xl min-w-0 flex-1 px-2">
                  <InputGroup>
                    <InputGroupInput
                      placeholder="회의 내용 검색…"
                      value={searchQuery}
                      onChange={(e) => updateSearchQuery(e.target.value)}
                    />
                    <InputGroupAddon>
                      <SearchIcon />
                    </InputGroupAddon>
                    {searchQuery && (
                      <InputGroupAddon align={"inline-end"}>
                        <InputGroupButton onClick={() => updateSearchQuery("")}>
                          <X />
                        </InputGroupButton>
                      </InputGroupAddon>
                    )}
                    {isSearching && (
                      <InputGroupAddon align={"inline-end"}>
                        <span className="text-xs text-blue-500">검색 중…</span>
                      </InputGroupAddon>
                    )}
                  </InputGroup>
                  {searchQuery.trim() && (
                    <div className="absolute left-2 right-2 top-full z-20 mt-2 rounded-lg border border-gray-200 bg-white shadow-lg">
                      <div className="max-h-72 overflow-y-auto py-1">
                        {uniqueSearchResults.map((result) => (
                          <button
                            key={result.id}
                            type="button"
                            className="w-full px-3 py-2 text-left transition-colors hover:bg-gray-50"
                            onClick={() => {
                              setCurrentMeeting({ id: result.id, title: result.title })
                              router.push(`/meeting-details?id=${result.id}`)
                            }}
                          >
                            <div className="truncate text-sm font-medium text-gray-800">
                              {highlightMatch(result.title, searchQuery)}
                            </div>
                            <div className="line-clamp-2 text-xs text-gray-500">
                              {highlightMatch(result.matchContext, searchQuery)}
                            </div>
                          </button>
                        ))}
                        {!isSearching && uniqueSearchResults.length === 0 && (
                          <div className="px-3 py-4 text-center text-sm text-gray-500">
                            검색 결과가 없습니다.
                          </div>
                        )}
                      </div>
                    </div>
                  )}
                </div>
                <button
                  type="button"
                  onClick={handleRecordingToggle}
                  // Stop is always allowed; start requires both languages
                  // to be picked first. The transcript panel highlights
                  // the unset selectors so the user knows where to look
                  // when this button is greyed out.
                  disabled={!isRecording && !languagesConfigured}
                  title={
                    !isRecording && !languagesConfigured
                      ? "녹음 시작 전 듣는 언어와 자막 언어를 선택해 주세요"
                      : undefined
                  }
                  className={`mr-2 inline-flex h-9 shrink-0 items-center gap-2 rounded-md px-3 text-sm font-medium text-white transition-colors disabled:cursor-not-allowed disabled:opacity-60 ${
                    isRecording
                      ? "bg-red-500 hover:bg-red-600"
                      : "bg-blue-600 hover:bg-blue-700"
                  }`}
                >
                  <Mic className="h-4 w-4" />
                  <span>{isRecording ? "녹음 중지" : "녹음"}</span>
                </button>
                {showAgentChrome && (
                  <button
                    type="button"
                    onClick={() => setIsAgentDrawerOpen(true)}
                    className="mr-2 inline-flex h-9 shrink-0 items-center gap-2 rounded-md border border-gray-200 bg-white px-3 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-50 xl:hidden"
                  >
                    <MessageSquare className="h-4 w-4" />
                    <span>AI 채팅</span>
                  </button>
                )}
              </div>
            </header>
          )}
          <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-auto">
            {children}
          </div>
        </div>
        {showAgentChrome && !isDockedAiMinimized && (
          <AgentChatPanel
            variant="docked"
            messages={agentMessages}
            input={agentInput}
            onInputChange={setAgentInput}
            onSend={handleSendAgentMessage}
            isSending={isAgentSending}
            onDockResizePointerDown={onResizePointerDown}
            onDockMinimize={() => setDockedAiMinimized(true)}
            className="hidden min-w-0 shrink-0 xl:flex xl:w-[var(--docked-ai-rail-width,0px)]"
          />
        )}
      </div>

      {showAgentChrome && isXl && isDockedAiMinimized && (
        <button
          type="button"
          onClick={() => setDockedAiMinimized(false)}
          className="fixed bottom-6 right-6 z-[45] inline-flex items-center gap-2 rounded-full border border-gray-200 bg-white px-4 py-3 text-sm font-medium text-gray-800 shadow-lg transition-colors hover:bg-gray-50"
          aria-label="AI Chat 펼치기"
        >
          <MessageSquare className="h-5 w-5 shrink-0 text-blue-600" />
          <span>AI 채팅</span>
        </button>
      )}

      {showAgentChrome && isAgentDrawerOpen && (
        <AgentChatPanel
          variant="drawer"
          messages={agentMessages}
          input={agentInput}
          onInputChange={setAgentInput}
          onSend={handleSendAgentMessage}
          isSending={isAgentSending}
          onClose={() => setIsAgentDrawerOpen(false)}
          className="xl:hidden"
        />
      )}
    </main>
  )
}

export default MainContent
