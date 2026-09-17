'use client';

import { useEffect, useRef, useCallback } from 'react';
import { invoke } from '@tauri-apps/api/core';
import { useTranscripts } from '@/contexts/TranscriptContext';
import { useConfig } from '@/contexts/ConfigContext';

const MAX_CONCURRENT = 3;

/**
 * Automatic translation with Google Translate.
 *
 * Only final transcripts detected as a different language than `userLanguage`
 * are translated. Matching-language utterances are skipped to avoid
 * unnecessary cost and duplicate UI.
 *
 * Concurrent translation calls are capped by `MAX_CONCURRENT`; extra work is
 * queued until a slot becomes available.
 */
export function LiveTranscriptTranslation() {
  const { transcripts, patchTranscriptBySequenceId } = useTranscripts();
  const { translationEnabled, userLanguage } = useConfig();
  const inFlightRef = useRef<Set<number>>(new Set());
  const consumedSeqRef = useRef<Set<number>>(new Set());
  const pendingQueueRef = useRef<{ text: string; seqId: number; target: string }[]>([]);
  const drainQueueRef = useRef<() => void>(() => {});

  const startTranslation = useCallback(
    async (text: string, seqId: number, target: string) => {
      inFlightRef.current.add(seqId);
      patchTranscriptBySequenceId(seqId, { translation_pending: true, translated_text: '' });

      try {
        const translated = await invoke<string>('api_translate', { text, target });
        patchTranscriptBySequenceId(seqId, {
          translated_text: translated,
          translation_pending: false,
        });
      } catch (err) {
        patchTranscriptBySequenceId(seqId, {
          translation_pending: false,
          translation_error: err instanceof Error ? err.message : String(err),
        });
      } finally {
        inFlightRef.current.delete(seqId);
        drainQueueRef.current();
      }
    },
    [patchTranscriptBySequenceId]
  );

  const drainQueue = useCallback(() => {
    while (pendingQueueRef.current.length > 0 && inFlightRef.current.size < MAX_CONCURRENT) {
      const next = pendingQueueRef.current.shift()!;
      if (!inFlightRef.current.has(next.seqId)) {
        startTranslation(next.text, next.seqId, next.target);
      }
    }
  }, [startTranslation]);

  drainQueueRef.current = drainQueue;

  const translateSentence = useCallback(
    (text: string, seqId: number, target: string) => {
      if (!text.trim() || inFlightRef.current.has(seqId)) return;

      if (inFlightRef.current.size >= MAX_CONCURRENT) {
        pendingQueueRef.current.push({ text, seqId, target });
        return;
      }

      startTranslation(text, seqId, target);
    },
    [startTranslation]
  );

  // Reset on new recording
  useEffect(() => {
    if (transcripts.length === 0) {
      consumedSeqRef.current.clear();
      inFlightRef.current.clear();
      pendingQueueRef.current = [];
    }
  }, [transcripts.length]);

  // Translate each new final STT result.
  // - Translation toggle OFF -> no calls and no consumed marks, so enabling it
  //   later can backfill pending rows.
  // - Detected as the same language -> skip and mark as consumed.
  // - Different language or unknown detected_language -> translate.
  useEffect(() => {
    if (!translationEnabled) return;
    for (const t of transcripts) {
      if (t.sequence_id === undefined) continue;
      if (t.is_partial || !t.text.trim()) continue;
      if (consumedSeqRef.current.has(t.sequence_id)) continue;

      // When detected_language is present, compare it against the user language.
      // If it is missing, translate conservatively in case auto-detect failed or
      // the provider does not expose language detection.
      if (t.detected_language && t.detected_language === userLanguage) {
        consumedSeqRef.current.add(t.sequence_id);
        continue;
      }

      consumedSeqRef.current.add(t.sequence_id);
      translateSentence(t.text, t.sequence_id, userLanguage);
    }
  }, [transcripts, translateSentence, translationEnabled, userLanguage]);

  return null;
}
