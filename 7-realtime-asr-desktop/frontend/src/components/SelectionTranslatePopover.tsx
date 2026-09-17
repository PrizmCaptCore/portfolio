'use client';

import { useEffect, useLayoutEffect, useRef, useState, useCallback } from 'react';
import { invoke } from '@tauri-apps/api/core';
import { Languages, Copy, Check, X, Loader2, Sparkles } from 'lucide-react';
import { LiveAssistResult } from '@/types';
import { useConfig } from '@/contexts/ConfigContext';
import { useTranscripts } from '@/contexts/TranscriptContext';
import { useRecordingState } from '@/contexts/RecordingStateContext';
import { copyToClipboard } from '@/lib/clipboard';

interface SelectionState {
  text: string;
  rect: DOMRect;
  firstRowId: string | null;
}

interface Props {
  scopeSelector?: string;
}

const PRIOR_CONTEXT_ROWS = 5;

interface RagSearchHit {
  chunk_id: number;
  page_id: string;
  page_title: string;
  page_url: string;
  chunk_index: number;
  text: string;
  distance: number;
}

/**
 * Best-effort RAG retrieval for the drag-suggest path. Returns a
 * formatted snippet block ready to be concatenated with the prior
 * transcript context, or empty string when there's nothing to add
 * (no Notion sync, embed call failed, no relevant hits).
 *
 * Kept silent on failure: drag-suggest is interactive, and the user
 * is waiting on a popover — a backend embed timeout shouldn't be
 * surfaced here.
 */
async function buildRagSnippet(query: string): Promise<string> {
  const trimmed = query.trim();
  if (!trimmed) return '';
  let hits: RagSearchHit[] = [];
  try {
    hits = (await invoke('rag_search', { query: trimmed, k: 3 })) as RagSearchHit[];
  } catch (e) {
    console.warn('rag_search failed during drag-suggest (continuing without):', e);
    return '';
  }
  if (!hits.length) return '';
  const lines = hits.map((h) => {
    // Trim chunks to ~600 chars so 3 hits + prior transcript still
    // comfortably fit inside the gateway's prompt budget.
    const text = h.text.length > 600 ? h.text.slice(0, 600) + '…' : h.text;
    const label = h.page_title || h.page_id || '문서';
    return `- [${label}] ${text.replace(/\s+/g, ' ').trim()}`;
  });
  return ['[참고 문서 (Notion)]', ...lines].join('\n');
}

/**
 * Index the in-progress meeting's running transcript into the local RAG
 * store so that the upcoming `rag_search` can retrieve mid-meeting content.
 * Hash-deduped on the Rust side, so calling this every time the user
 * triggers 의도 분석 costs at most one SELECT when nothing has changed.
 *
 * Best-effort: if the index call fails, the search just falls back to
 * whatever was already indexed (Notion + prior summaries).
 */
async function indexCurrentMeetingIfActive(
  meetingId: string | null,
  meetingTitle: string,
  transcriptText: string,
): Promise<void> {
  if (!meetingId) return;
  const trimmed = transcriptText.trim();
  if (!trimmed) return;
  try {
    await invoke('rag_index_current_meeting_transcript', {
      meetingId,
      title: meetingTitle,
      text: trimmed,
    });
  } catch (e) {
    console.warn('rag_index_current_meeting_transcript failed (continuing):', e);
  }
}

export function SelectionTranslatePopover({ scopeSelector }: Props) {
  const { userLanguage } = useConfig();
  const { transcripts, currentMeetingId, meetingTitle } = useTranscripts();
  const { isRecording } = useRecordingState();
  const [selection, setSelection] = useState<SelectionState | null>(null);
  const [translated, setTranslated] = useState<string | null>(null);
  const [translating, setTranslating] = useState(false);
  const [translateError, setTranslateError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const [assist, setAssist] = useState<LiveAssistResult | null>(null);
  const [assisting, setAssisting] = useState(false);
  const [assistError, setAssistError] = useState<string | null>(null);
  const [copiedReplyIdx, setCopiedReplyIdx] = useState<number | null>(null);

  const [manualMode, setManualMode] = useState(false);

  const popoverRef = useRef<HTMLDivElement>(null);

  const close = useCallback(() => {
    setSelection(null);
    setTranslated(null);
    setTranslateError(null);
    setTranslating(false);
    setCopied(false);
    setAssist(null);
    setAssistError(null);
    setAssisting(false);
    setCopiedReplyIdx(null);
    setManualMode(false);
  }, []);

  // Selection-finalised listener.
  //
  // Earlier this hook listened to `selectionchange`, which fires on every
  // pointer move while the user drags — the popover then re-rendered and
  // jumped around mid-selection, making it hard to tell which words were
  // actually being grabbed. We now only react to `mouseup` and `keyup`
  // (keyboard selections via Shift+Arrow / Cmd+Shift+End / etc.), which
  // mark the moment the user "lets go" of the selection. The popover
  // therefore appears once, in its final position, with the final text.
  useEffect(() => {
    const captureFinalisedSelection = () => {
      const sel = window.getSelection();
      if (!sel || sel.isCollapsed || sel.rangeCount === 0) {
        return;
      }

      const text = sel.toString().trim();
      if (!text) return;

      if (scopeSelector) {
        const root = document.querySelector(scopeSelector);
        if (!root) return;
        const range = sel.getRangeAt(0);
        if (!root.contains(range.commonAncestorContainer)) {
          return;
        }
      }

      const range = sel.getRangeAt(0);
      let firstRowId: string | null = null;
      let node: Node | null = range.startContainer;
      while (node) {
        if (node instanceof HTMLElement && node.id?.startsWith('segment-')) {
          firstRowId = node.id;
          break;
        }
        node = node.parentNode;
      }

      const rect = range.getBoundingClientRect();
      setSelection({ text, rect, firstRowId });
      setTranslated(null);
      setTranslateError(null);
      setCopied(false);
      setAssist(null);
      setAssistError(null);
      setCopiedReplyIdx(null);
      setManualMode(false);
    };

    // Track whether the mousedown that began this potential drag landed
    // inside the scope. Without this, an unrelated drag (resizing the AI
    // chat rail, dragging a scrollbar, etc.) would still fire mouseup on
    // document — and if a stale selection happened to live inside the
    // transcript scope from earlier, we'd pop the translate UI even
    // though the user is clearly doing something else.
    let mousedownInScope = false;

    const isInScope = (target: EventTarget | null): boolean => {
      if (!scopeSelector) return true;
      if (!target || !(target instanceof Node)) return false;
      const root = document.querySelector(scopeSelector);
      return !!root && root.contains(target);
    };

    const handleMouseDown = (e: MouseEvent) => {
      mousedownInScope = isInScope(e.target);
    };

    // Defer one tick — at the precise moment of mouseup the browser hasn't
    // necessarily committed the new selection range yet on some engines
    // (notably WebKit), so reading getSelection() inline would give us the
    // pre-mouseup state. A queueMicrotask is enough; setTimeout(0) also
    // works but adds a visible frame of latency.
    const handleMouseUp = () => {
      if (!mousedownInScope) return;
      mousedownInScope = false;
      queueMicrotask(captureFinalisedSelection);
    };
    const handleKeyUp = (e: KeyboardEvent) => {
      // Only treat keys that can extend a selection. Anything else (typing
      // inside an input, pressing Escape) shouldn't open the popover.
      const selectionKeys = new Set([
        'ArrowLeft',
        'ArrowRight',
        'ArrowUp',
        'ArrowDown',
        'Home',
        'End',
        'PageUp',
        'PageDown',
      ]);
      if (e.shiftKey && selectionKeys.has(e.key)) {
        queueMicrotask(captureFinalisedSelection);
      }
    };

    // Use capture-phase mousedown so we observe it even if a child handler
    // calls stopPropagation (e.g., a custom drag handle on the AI rail).
    document.addEventListener('mousedown', handleMouseDown, true);
    document.addEventListener('mouseup', handleMouseUp);
    document.addEventListener('keyup', handleKeyUp);
    return () => {
      document.removeEventListener('mousedown', handleMouseDown, true);
      document.removeEventListener('mouseup', handleMouseUp);
      document.removeEventListener('keyup', handleKeyUp);
    };
  }, [scopeSelector]);

  useEffect(() => {
    if (!selection) return;

    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') close();
    };

    const handleClick = (e: MouseEvent) => {
      if (popoverRef.current?.contains(e.target as Node)) return;
      close();
    };

    document.addEventListener('keydown', handleKey);
    document.addEventListener('mousedown', handleClick);
    return () => {
      document.removeEventListener('keydown', handleKey);
      document.removeEventListener('mousedown', handleClick);
    };
  }, [selection, close]);

  const cleanedSelection = useCallback(() => {
    if (!selection) return '';
    return selection.text
      .replace(/\s+/g, ' ')
      .replace(/(\s)\.\s*\.\s*\.+/g, '$1')
      .trim();
  }, [selection]);

  const handleTranslate = useCallback(async () => {
    if (!selection || translated || translating) return;
    setTranslating(true);
    setTranslateError(null);

    const cleaned = cleanedSelection();
    if (!cleaned) {
      setTranslateError('번역할 텍스트가 없습니다');
      setTranslating(false);
      return;
    }

    try {
      // Drag-translate goes through a dedicated command that follows the
      // same readiness pre-flight recording-start does (/health/ + /ready/
      // polling) before POSTing the real translation. Real-time recording
      // translation keeps using `api_translate` since recording-start has
      // already pre-flighted.
      const result = await invoke<string>('api_translate_drag', {
        text: cleaned,
      });
      setTranslated(result);
    } catch (e) {
      setTranslateError(typeof e === 'string' ? e : (e as Error)?.message ?? '번역에 실패했습니다');
    } finally {
      setTranslating(false);
    }
  }, [selection, translated, translating, cleanedSelection]);

  const buildPriorContext = useCallback((): string | null => {
    if (!selection?.firstRowId) return null;
    const firstRow = document.getElementById(selection.firstRowId);
    if (!firstRow) return null;

    const allSegments = Array.from(
      document.querySelectorAll<HTMLElement>('[id^="segment-"]')
    );
    const idx = allSegments.indexOf(firstRow);
    if (idx <= 0) return null;
    const priorRows = allSegments
      .slice(Math.max(0, idx - PRIOR_CONTEXT_ROWS), idx)
      .map((el) => {
        const para = el.querySelector('p');
        return para?.textContent?.trim() || '';
      })
      .filter((s) => s.length > 0);

    if (priorRows.length === 0) return null;
    return priorRows.join('\n');
  }, [selection]);

  const handleAssist = useCallback(async () => {
    if (!selection || assist || assisting) return;
    setAssisting(true);
    setAssistError(null);

    const cleaned = cleanedSelection();
    if (!cleaned) {
      setAssistError('분석할 텍스트가 없습니다');
      setAssisting(false);
      return;
    }

    try {
      const prior = buildPriorContext();
      // While a recording is in progress, index the running transcript first
      // so the immediately-following rag_search can retrieve content from
      // the current meeting itself, not just past meetings + Notion.
      if (isRecording && currentMeetingId) {
        const fullTranscript = transcripts
          .map((t) => t.text)
          .filter((s) => s.trim().length > 0)
          .join('\n');
        await indexCurrentMeetingIfActive(currentMeetingId, meetingTitle, fullTranscript);
      }
      // Run RAG retrieval after the index call so any newly-indexed chunks
      // are visible to KNN. The hash dedupe keeps the index call cheap when
      // the transcript hasn't grown since last invocation.
      const ragSnippet = await buildRagSnippet(cleaned);

      // Combine prior transcript + RAG into a single field. Backend
      // treats `priorTranscriptContext` as opaque additional context,
      // so concatenation is safe — separator makes it readable to the
      // LLM and to humans debugging prompts.
      const combinedContext = [prior, ragSnippet].filter((s) => s && s.length > 0).join('\n\n---\n\n');
      const finalContext = combinedContext.length > 0 ? combinedContext : null;

      const targetLanguageName = userLanguage === 'en' ? 'English' : 'Korean';
      // Drag-suggest goes through a dedicated command that runs the same
      // readiness pre-flight as api_translate_drag but against the
      // summary-specific endpoints (/summary/warmup/ + /summary/ready/).
      const result = await invoke<LiveAssistResult>('api_suggest_drag', {
        text: cleaned,
        targetLanguageName,
        priorTranscriptContext: finalContext,
      });
      setAssist(result);
    } catch (e) {
      setAssistError(typeof e === 'string' ? e : (e as Error)?.message ?? '분석에 실패했습니다');
    } finally {
      setAssisting(false);
    }
  }, [
    selection,
    assist,
    assisting,
    cleanedSelection,
    buildPriorContext,
    userLanguage,
    isRecording,
    currentMeetingId,
    meetingTitle,
    transcripts,
  ]);

  const handleCopy = useCallback(async () => {
    const textToCopy = translated ?? selection?.text;
    if (!textToCopy) return;
    try {
      await copyToClipboard(textToCopy);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch (e) {
      console.error('Copy failed:', e);
    }
  }, [translated, selection]);

  const handleCopyReply = useCallback(async (idx: number, text: string) => {
    try {
      await copyToClipboard(text);
      setCopiedReplyIdx(idx);
      setTimeout(() => setCopiedReplyIdx((current) => (current === idx ? null : current)), 1500);
    } catch (e) {
      console.error('Copy reply failed:', e);
    }
  }, []);

  useEffect(() => {
    if (!selection) return;
    const el = popoverRef.current;
    if (!el) return;
    if (typeof ResizeObserver === 'undefined') return;

    // Only treat a resize as user-driven when the pointer is down near a resize
    // edge. Content-driven size changes (translation loading, etc.) are ignored
    // so they cannot create a feedback loop with setPopoverStyle.
    let userResizing = false;

    const onMouseDown = (e: MouseEvent) => {
      const rect = el.getBoundingClientRect();
      const EDGE = 20;
      if (e.clientX >= rect.right - EDGE || e.clientY >= rect.bottom - EDGE) {
        userResizing = true;
      }
    };
    const onMouseUp = () => { userResizing = false; };

    const ro = new ResizeObserver((entries) => {
      if (!userResizing) return;
      const entry = entries[0];
      const cw = entry.contentRect.width;
      const ch = entry.contentRect.height;
      setManualMode(true);
      setPopoverStyle((prev) => ({
        ...prev,
        position: 'fixed',
        boxSizing: 'border-box',
        width: `${cw + /* padding (p-3 = 12*2) + border 2 */ 26}px`,
        height: `${ch + 26}px`,
        maxHeight: 'none',
      }));
    });

    el.addEventListener('mousedown', onMouseDown);
    document.addEventListener('mouseup', onMouseUp);
    ro.observe(el);

    return () => {
      el.removeEventListener('mousedown', onMouseDown);
      document.removeEventListener('mouseup', onMouseUp);
      ro.disconnect();
    };
  }, [selection]);

  const handleHeaderMouseDown = useCallback(
    (e: React.MouseEvent<HTMLDivElement>) => {
      if ((e.target as HTMLElement).closest('button')) return;
      e.preventDefault();

      const el = popoverRef.current;
      if (!el) return;

      const startRect = el.getBoundingClientRect();
      const startX = e.clientX;
      const startY = e.clientY;
      const popW = startRect.width;
      const popH = startRect.height;
      const MARGIN = 8;

      setManualMode(true);

      const onMove = (ev: MouseEvent) => {
        const dx = ev.clientX - startX;
        const dy = ev.clientY - startY;
        let nextLeft = startRect.left + dx;
        let nextTop = startRect.top + dy;
        nextLeft = Math.max(MARGIN, Math.min(nextLeft, window.innerWidth - popW - MARGIN));
        nextTop = Math.max(MARGIN, Math.min(nextTop, window.innerHeight - popH - MARGIN));
        setPopoverStyle((prev) => ({
          ...prev,
          position: 'fixed',
          top: `${nextTop}px`,
          left: `${nextLeft}px`,
          width: `${popW}px`,
          visibility: 'visible',
        }));
      };

      const onUp = () => {
        document.removeEventListener('mousemove', onMove);
        document.removeEventListener('mouseup', onUp);
      };

      document.addEventListener('mousemove', onMove);
      document.addEventListener('mouseup', onUp);
    },
    []
  );

  const [popoverStyle, setPopoverStyle] = useState<React.CSSProperties>({
    position: 'fixed',
    visibility: 'hidden',
    top: 0,
    left: 0,
  });

  useLayoutEffect(() => {
    if (!selection) return;
    if (manualMode) return;
    const el = popoverRef.current;
    if (!el) return;

    const POPOVER_WIDTH = 360;
    const MARGIN = 8;
    const OFFSET = 8;
    const MIN_HEIGHT = 120;

    const vw = window.innerWidth;
    const vh = window.innerHeight;
    const rect = selection.rect;

    const spaceAbove = rect.top - MARGIN - OFFSET;
    const spaceBelow = vh - rect.bottom - MARGIN - OFFSET;

    const placeAbove = spaceAbove >= MIN_HEIGHT && spaceAbove >= spaceBelow;
    const availableHeight = Math.max(
      MIN_HEIGHT,
      placeAbove ? spaceAbove : spaceBelow
    );

    const naturalHeight = el.scrollHeight;
    const finalHeight = Math.min(naturalHeight, availableHeight);

    const top = placeAbove
      ? rect.top - OFFSET - finalHeight
      : rect.bottom + OFFSET;

    let left = rect.left + rect.width / 2 - POPOVER_WIDTH / 2;
    left = Math.max(MARGIN, Math.min(left, vw - POPOVER_WIDTH - MARGIN));

    setPopoverStyle({
      position: 'fixed',
      top: `${top}px`,
      left: `${left}px`,
      width: `${POPOVER_WIDTH}px`,
      maxHeight: `${availableHeight}px`,
      visibility: 'visible',
    });
  }, [selection, translated, assist, translateError, assistError, manualMode]);

  if (!selection) return null;

  return (
    <div
      ref={popoverRef}
      className="z-50 bg-white rounded-lg shadow-xl border border-gray-200 p-3 text-sm flex flex-col"
      style={{ ...popoverStyle, resize: 'both', overflow: 'auto', minWidth: 280, minHeight: 120 }}
      onMouseDown={(e) => e.stopPropagation()}
    >
      <div
        className="flex items-center justify-between mb-2 pb-2 border-b border-gray-100 flex-shrink-0 cursor-grab active:cursor-grabbing select-none"
        onMouseDown={handleHeaderMouseDown}
      >
        <div className="flex items-center gap-1.5 text-xs text-gray-500 font-medium">
          <span>선택한 텍스트</span>
        </div>
        <button
          onClick={close}
          className="text-gray-400 hover:text-gray-600 p-0.5"
          aria-label="닫기"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto">

      <div className="text-xs text-gray-700 mb-2 leading-relaxed">
        {selection.text}
      </div>

      <div className="flex items-center gap-2 mb-2 flex-wrap">
        <button
          onClick={handleTranslate}
          disabled={translating || !!translated}
          className="flex items-center gap-1.5 px-3 py-1.5 bg-blue-600 text-white rounded-md text-xs font-medium hover:bg-blue-700 disabled:bg-blue-400 disabled:cursor-not-allowed"
        >
          {translating ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <Languages className="h-3.5 w-3.5" />
          )}
          {translating ? '번역 중…' : '번역'}
        </button>
        <button
          onClick={handleAssist}
          disabled={assisting || !!assist}
          className="flex items-center gap-1.5 px-3 py-1.5 bg-purple-600 text-white rounded-md text-xs font-medium hover:bg-purple-700 disabled:bg-purple-400 disabled:cursor-not-allowed"
          title="LLM에게 화자의 의도와 답변 아이디어를 요청합니다"
        >
          {assisting ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <Sparkles className="h-3.5 w-3.5" />
          )}
          {assisting ? '분석 중…' : '의도 분석'}
        </button>
        <button
          onClick={handleCopy}
          className="flex items-center gap-1.5 px-3 py-1.5 bg-gray-100 text-gray-700 rounded-md text-xs font-medium hover:bg-gray-200"
        >
          {copied ? (
            <Check className="h-3.5 w-3.5 text-green-600" />
          ) : (
            <Copy className="h-3.5 w-3.5" />
          )}
          {copied ? '복사됨' : '복사'}
        </button>
      </div>

      {translateError && (
        <div className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded px-2 py-1.5 mb-2">
          {translateError}
        </div>
      )}
      {translated && !translateError && (
        <div className="text-sm text-gray-900 bg-blue-50 border border-blue-100 rounded px-2 py-1.5 leading-relaxed mb-2">
          {translated}
        </div>
      )}

      {assistError && (
        <div className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded px-2 py-1.5">
          {assistError}
        </div>
      )}
      {assist && !assistError && (
        <div className="bg-purple-50 border border-purple-100 rounded px-2 py-2 text-xs leading-relaxed">
          {assist.intentSummary && (
            <div className="mb-2">
              <div className="text-purple-700 font-semibold text-[11px] uppercase tracking-wide mb-0.5">
                의도
              </div>
              <div className="text-gray-800">{assist.intentSummary}</div>
            </div>
          )}
          {assist.replyIdeas && assist.replyIdeas.length > 0 && (
            <div>
              <div className="text-purple-700 font-semibold text-[11px] uppercase tracking-wide mb-1">
                답변 아이디어 (클릭하여 복사)
              </div>
              <ul className="space-y-1">
                {assist.replyIdeas.map((idea, i) => (
                  <li key={i}>
                    <button
                      onClick={() => handleCopyReply(i, idea)}
                      className="w-full text-left bg-white border border-purple-200 rounded px-2 py-1.5 text-gray-900 hover:bg-purple-100 hover:border-purple-300 transition-colors flex items-start gap-1.5"
                    >
                      <span className="flex-1">{idea}</span>
                      {copiedReplyIdx === i ? (
                        <Check className="h-3 w-3 text-green-600 flex-shrink-0 mt-0.5" />
                      ) : (
                        <Copy className="h-3 w-3 text-gray-400 flex-shrink-0 mt-0.5" />
                      )}
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      </div>
    </div>
  );
}
