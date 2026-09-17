"use client"

import React, { useEffect, useRef } from "react"
import { MessageSquare, Minimize2, Send, X } from "lucide-react"
import { cn } from "@/lib/utils"

export type AgentChatPanelVariant = "docked" | "drawer"

export interface AgentChatPanelProps {
  variant: AgentChatPanelVariant
  messages: Array<{ role: "user" | "agent"; text: string }>
  input: string
  onInputChange: (value: string) => void
  onSend: () => void
  /** Renders the typing indicator and disables input while a reply is in-flight. */
  isSending?: boolean
  onClose?: () => void
  /** Drag the left edge to resize (docked layout only). */
  onDockResizePointerDown?: (e: React.PointerEvent<HTMLDivElement>) => void
  /** Collapse docked panel to a corner FAB (xl layout). */
  onDockMinimize?: () => void
  className?: string
}

export function AgentChatPanel({
  variant,
  messages,
  input,
  onInputChange,
  onSend,
  isSending = false,
  onClose,
  onDockResizePointerDown,
  onDockMinimize,
  className,
}: AgentChatPanelProps) {
  const isDocked = variant === "docked"

  const scrollRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [messages.length, isSending])

  return (
    <aside
      className={cn(
        "flex min-h-0 flex-col bg-white",
        isDocked
          ? "relative h-full border-l border-gray-200"
          : "fixed bottom-4 right-4 z-40 h-[68vh] w-[400px] max-w-[92vw] rounded-2xl border border-gray-200 shadow-2xl",
        className,
      )}
      aria-label={isDocked ? "AI 채팅" : undefined}
    >
      {isDocked && onDockResizePointerDown && (
        <div
          role="separator"
          aria-orientation="vertical"
          aria-label="AI 채팅 너비 조절"
          onPointerDown={onDockResizePointerDown}
          className="absolute left-0 top-0 z-30 h-full w-3 -translate-x-1/2 cursor-col-resize touch-none hover:bg-blue-500/15 active:bg-blue-500/25"
        />
      )}
      <div className="flex shrink-0 items-start justify-between gap-2 border-b border-gray-100 px-4 py-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <MessageSquare className="h-4 w-4 shrink-0 text-gray-600" />
            <h2 className="text-sm font-semibold text-gray-800">AI 채팅</h2>
          </div>
          <p className="mt-1 text-xs text-gray-500">
            대화 기록·미팅 내용을 바탕으로 질문할 수 있어요.
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          {isDocked && onDockMinimize && (
            <button
              type="button"
              onClick={onDockMinimize}
              className="rounded-md border border-gray-200 p-1.5 text-gray-600 hover:bg-gray-50"
              aria-label="AI Chat 최소화"
              title="최소화"
            >
              <Minimize2 className="h-4 w-4" />
            </button>
          )}
          {!isDocked && onClose && (
            <button
              type="button"
              onClick={onClose}
              className="rounded-md border border-gray-200 p-1.5 text-gray-600 hover:bg-gray-50"
              aria-label="AI 채팅 닫기"
            >
              <X className="h-4 w-4" />
            </button>
          )}
        </div>
      </div>

      <div ref={scrollRef} className="min-h-0 flex-1 space-y-3 overflow-y-auto px-4 py-4">
        {messages.map((message, index) => (
          <div
            key={`${message.role}-${index}`}
            className={cn(
              "max-w-[92%] whitespace-pre-wrap rounded-2xl px-3 py-2 text-sm",
              message.role === "user"
                ? "ml-auto bg-blue-600 text-white"
                : "bg-gray-100 text-gray-800",
            )}
          >
            {message.text}
          </div>
        ))}
        {isSending && (
          <div
            className="max-w-[92%] rounded-2xl bg-gray-100 px-3 py-2 text-sm text-gray-800"
            aria-label="응답 작성 중"
          >
            <span className="inline-flex items-center gap-1">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-gray-500" />
              <span
                className="h-1.5 w-1.5 animate-pulse rounded-full bg-gray-500"
                style={{ animationDelay: "150ms" }}
              />
              <span
                className="h-1.5 w-1.5 animate-pulse rounded-full bg-gray-500"
                style={{ animationDelay: "300ms" }}
              />
            </span>
          </div>
        )}
      </div>

      <div className="shrink-0 border-t border-gray-100 p-3">
        <div className="flex items-end gap-2">
          <textarea
            value={input}
            onChange={(e) => onInputChange(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault()
                if (!isSending) onSend()
              }
            }}
            disabled={isSending}
            placeholder={isSending ? "응답을 생성하는 중…" : "대화·회의 내용에 대해 질문해 보세요…"}
            className="min-h-[42px] flex-1 resize-none rounded-lg border border-gray-200 px-3 py-2 text-sm outline-none transition focus:border-blue-500 disabled:cursor-not-allowed disabled:bg-gray-50 disabled:text-gray-500"
          />
          <button
            type="button"
            onClick={onSend}
            disabled={isSending || !input.trim()}
            className="inline-flex shrink-0 items-center gap-1 rounded-lg bg-blue-600 px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-gray-300"
          >
            <Send className="h-4 w-4" />
            <span>전송</span>
          </button>
        </div>
      </div>
    </aside>
  )
}
