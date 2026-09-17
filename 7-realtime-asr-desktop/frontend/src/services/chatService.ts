/**
 * AI chat backed by /ai/summarize/ (OpenAI-compatible) with optional
 * RAG augmentation from the local sqlite-vec index.
 *
 * Non-streaming: callers await the full assistant turn before rendering.
 * Streaming would need a separate SSE endpoint, which we don't have yet.
 */

import { invoke } from '@tauri-apps/api/core'
import { authedFetch } from './apiClient'

export type ChatRole = 'user' | 'agent'
export interface ChatMessage {
  role: ChatRole
  text: string
}

interface RagSearchHit {
  chunk_id: number
  source: 'notion' | 'meeting' | string
  distance: number
  page_id: string
  page_title: string
  page_url: string
  chunk_index: number
  text: string
}

export interface SendChatParams {
  /** Conversation history. Last entry MUST be the user message we're answering. */
  history: ChatMessage[]
  /** Title of the meeting the user is currently viewing, if any. */
  meetingTitle?: string
  /** Concatenated transcript text for the current meeting, if any. */
  transcriptText?: string
  /**
   * Frontend-side meeting id the user is currently working with. May be:
   *   - the in-progress recording's id (when recording is active)
   *   - the id of the past meeting the user is viewing (meeting-details
   *     page) — global TranscriptContext is empty in this case so the
   *     chat panel has no transcript context unless we fetch it here.
   * When given, we always inject that meeting's summary into the system
   * prompt directly (bypasses RAG) so the chat works even when Notion
   * isn't connected and KNN would otherwise return zero hits. We also
   * pull the meeting's transcripts inline if `transcriptText` wasn't
   * already passed by the caller. During recording we additionally index
   * the running transcript so the *next* RAG pass can surface it.
   */
  currentMeetingId?: string
  /** Default true. Set false to skip the local RAG lookup. */
  useRag?: boolean
}

const MAX_HISTORY_TURNS = 10
const MAX_TRANSCRIPT_CHARS = 8000
const MAX_SUMMARY_CHARS = 6000
const MAX_RAG_CHUNK_CHARS = 1500
const RAG_K = 5

/** Shape of api_get_summary's Tauri response (best-effort — fields vary). */
interface ApiSummaryResponse {
  status?: string
  data?: any
  error?: string
}

interface ApiTranscriptsResponse {
  transcripts?: Array<{
    text?: string
    source?: string
    is_partial?: boolean
  }>
}

/** Flatten the various summary shapes (`markdown`, sectioned legacy,
 * BlockNote `summary_json`) down to plain text usable as LLM context.
 * Returns null when the summary is empty / unparseable so the caller
 * can fall back to "no summary" prompts cleanly.
 */
function extractSummaryText(raw: unknown): string | null {
  if (raw == null) return null
  let data: any = raw
  if (typeof data === 'string') {
    try {
      data = JSON.parse(data)
    } catch {
      // Plain string — treat as the markdown body itself.
      const trimmed = data.trim()
      return trimmed.length > 0 ? trimmed : null
    }
  }
  if (typeof data !== 'object') return null
  if (typeof data.markdown === 'string') {
    const trimmed = data.markdown.trim()
    if (trimmed.length > 0) return trimmed
  }
  // Legacy sectioned format: each top-level key is a section with
  // {title, blocks: [{content}, ...]}. Mirror what
  // rag/commands.rs::extract_summary_text does so the chat sees the same
  // text shape that the RAG indexer would.
  const sections: string[] = []
  for (const [key, val] of Object.entries(data)) {
    if (!val || typeof val !== 'object') continue
    const section = val as any
    if (!('blocks' in section)) continue
    const title = typeof section.title === 'string' && section.title ? section.title : key
    const lines = [`## ${title}`]
    if (Array.isArray(section.blocks)) {
      for (const block of section.blocks) {
        const content = block?.content
        if (typeof content === 'string' && content.trim()) {
          lines.push(content.trim())
        }
      }
    }
    if (lines.length > 1) sections.push(lines.join('\n'))
  }
  return sections.length > 0 ? sections.join('\n\n') : null
}

function joinTranscripts(rows: ApiTranscriptsResponse['transcripts']): string {
  if (!rows || rows.length === 0) return ''
  return rows
    .filter((t) => t.text && t.is_partial !== true)
    .map((t) => (t.source ? `${t.source}: ${t.text}` : (t.text ?? '')))
    .filter((line) => line.length > 0)
    .join('\n')
}

interface SystemPromptInputs {
  params: SendChatParams
  /** Effective transcript text — caller-provided OR fetched from currentMeetingId. */
  transcriptText?: string
  /** Summary text fetched from currentMeetingId (if any). */
  summaryText?: string
  ragHits: RagSearchHit[]
}

function buildSystemPrompt({ params, transcriptText, summaryText, ragHits }: SystemPromptInputs): string {
  const lines: string[] = [
    '당신은 사용자의 회의·노트 기반 AI 어시스턴트입니다.',
    '한국어로 답변하며, 컨텍스트에 없는 내용은 추측 없이 모른다고 말합니다.',
    '회의 요약/트랜스크립트와 Notion 노트 컨텍스트가 주어지면 이를 우선 근거로 사용합니다.',
  ]
  if (params.meetingTitle) {
    lines.push(`\n현재 보고 있는 회의: ${params.meetingTitle}`)
  }
  if (summaryText) {
    // The summary is high-signal (post-meeting condensed view), so it goes
    // before the raw transcript — the model sees the structured take first.
    const trimmed = summaryText.length > MAX_SUMMARY_CHARS
      ? summaryText.slice(0, MAX_SUMMARY_CHARS) + '\n... (요약 일부 생략)'
      : summaryText
    lines.push(`\n[현재 회의 요약]\n${trimmed}`)
  }
  if (transcriptText) {
    // Tail-truncation keeps the most recent exchange when transcripts are long
    // — relevance for chat is biased toward "what was just said".
    const trimmed = transcriptText.length > MAX_TRANSCRIPT_CHARS
      ? '... (앞부분 생략) ...\n' + transcriptText.slice(-MAX_TRANSCRIPT_CHARS)
      : transcriptText
    lines.push(`\n[현재 회의 트랜스크립트]\n${trimmed}`)
  }
  if (ragHits.length > 0) {
    // Split by source so the model can reason about Notion docs vs past
    // meeting summaries differently — meetings tend to be temporal
    // ("지난 회의에서…") while Notion docs are reference material.
    const notionHits = ragHits.filter((h) => h.source !== 'meeting')
    const meetingHits = ragHits.filter((h) => h.source === 'meeting')
    const renderHit = (hit: RagSearchHit): string => {
      const text = hit.text.length > MAX_RAG_CHUNK_CHARS
        ? hit.text.slice(0, MAX_RAG_CHUNK_CHARS) + '...'
        : hit.text
      return `${hit.page_title || hit.page_id}\n${text}`
    }
    if (notionHits.length > 0) {
      lines.push('\n[관련 Notion 노트 — 인용 시 페이지명을 함께 표기]')
      notionHits.forEach((hit, i) => {
        lines.push(`\n${i + 1}. ${renderHit(hit)}`)
      })
    }
    if (meetingHits.length > 0) {
      lines.push('\n[관련 과거 회의 요약 — 인용 시 회의명을 함께 표기]')
      meetingHits.forEach((hit, i) => {
        lines.push(`\n${i + 1}. ${renderHit(hit)}`)
      })
    }
  }
  return lines.join('\n')
}

export async function sendChatMessage(params: SendChatParams): Promise<string> {
  const { history, useRag = true } = params
  if (history.length === 0) {
    throw new Error('empty_history')
  }
  const lastUser = history[history.length - 1]
  if (lastUser.role !== 'user') {
    throw new Error('last_message_must_be_user')
  }

  // Always inject the currently-viewed meeting's summary (and transcript
  // if not already supplied) directly into the system prompt — this is
  // deterministic and works even when:
  //   - Notion isn't connected (RAG would have nothing to retrieve)
  //   - rag_sync_state.embedding_dim hasn't been bootstrapped (pre-PR
  //     #34 indexing path) so rag_search short-circuits to empty
  //   - the relevant chunk doesn't make KNN top-K against a noisy index
  // RAG is still consulted afterwards for cross-meeting / Notion context,
  // but it's no longer the only signal about the meeting in front of us.
  let inlineSummary: string | undefined
  let inlineTranscript: string | undefined
  if (params.currentMeetingId) {
    try {
      const resp = await invoke<ApiSummaryResponse>('api_get_summary', {
        meetingId: params.currentMeetingId,
      })
      // Statuses other than 'idle' may still carry usable data (e.g.,
      // 'cancelled'/'failed' with a backup restore). Trust extractor to
      // return null when there's nothing meaningful.
      if (resp?.status !== 'idle') {
        const text = extractSummaryText(resp?.data)
        if (text) inlineSummary = text
      }
    } catch (e) {
      console.warn('chatService: api_get_summary failed (continuing):', e)
    }

    // Only fall back to fetching the meeting's transcripts when the caller
    // didn't already provide them (during recording the global Transcript
    // context has the live rows; viewing a past meeting it's empty and we
    // fetch here).
    if (!params.transcriptText) {
      try {
        const resp = await invoke<ApiTranscriptsResponse>(
          'api_get_meeting_transcripts',
          {
            meetingId: params.currentMeetingId,
            limit: 500,
            offset: 0,
          },
        )
        const joined = joinTranscripts(resp?.transcripts)
        if (joined.length > 0) inlineTranscript = joined
      } catch (e) {
        console.warn(
          'chatService: api_get_meeting_transcripts failed (continuing):',
          e,
        )
      }
    }
  }

  const effectiveTranscript = params.transcriptText ?? inlineTranscript

  let ragHits: RagSearchHit[] = []
  if (useRag && lastUser.text.trim().length > 0) {
    // Index the running transcript first so the upcoming rag_search can
    // retrieve content from the in-progress meeting. Hash-deduped on the
    // Rust side, so calling per chat turn is cheap when nothing changed.
    if (params.currentMeetingId && params.transcriptText && params.transcriptText.trim()) {
      try {
        await invoke('rag_index_current_meeting_transcript', {
          meetingId: params.currentMeetingId,
          title: params.meetingTitle ?? '',
          text: params.transcriptText,
        })
      } catch (e) {
        console.warn(
          'rag_index_current_meeting_transcript failed in chat (continuing):',
          e,
        )
      }
    }
    try {
      ragHits = await invoke<RagSearchHit[]>('rag_search', {
        query: lastUser.text,
        k: RAG_K,
      })
    } catch (e) {
      // RAG is best-effort — empty index, sqlite-vec failure, or no Notion
      // connection should all degrade to a chat without retrieved notes.
      console.warn('rag_search failed in chat (continuing without RAG):', e)
    }
  }

  const recent = history.slice(-MAX_HISTORY_TURNS)
  const messages = [
    {
      role: 'system' as const,
      content: buildSystemPrompt({
        params,
        transcriptText: effectiveTranscript,
        summaryText: inlineSummary,
        ragHits,
      }),
    },
    ...recent.map((m) => ({
      role: (m.role === 'agent' ? 'assistant' : 'user') as 'user' | 'assistant',
      content: m.text,
    })),
  ]

  const res = await authedFetch('/ai/summarize/', {
    method: 'POST',
    body: JSON.stringify({
      messages,
      temperature: 0.5,
      max_tokens: 1000,
    }),
  })

  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    throw new Error(data?.detail || `http_${res.status}`)
  }
  const data = await res.json()
  const choice = (data?.choices ?? [])[0]
  const content = choice?.message?.content ?? choice?.text ?? ''
  if (!content) {
    throw new Error('empty_response')
  }
  return String(content).trim()
}
