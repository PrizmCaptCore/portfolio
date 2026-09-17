import { useState, useEffect, useRef } from 'react';
import { TranscriptSegmentData } from '@/types';

const INTERVAL_MS = 15; // Character reveal interval
const DURATION_MS = 800; // Total streaming duration
const INITIAL_CHARS = 5; // Show first N characters immediately

interface StreamingSegment {
  id: string;
  fullText: string;
  visibleText: string;
}

/**
 * Hook to manage the typewriter/streaming effect for new transcripts
 * Gradually reveals characters in a transcript over 800ms
 */
export function useTranscriptStreaming(
  segments: TranscriptSegmentData[],
  isRecording: boolean,
  enableStreaming: boolean
) {
  const [streamingSegment, setStreamingSegment] = useState<StreamingSegment | null>(null);
  const lastSegmentIdRef = useRef<string | null>(null);
  const streamingIntervalRef = useRef<NodeJS.Timeout | null>(null);

  useEffect(() => {
    if (!isRecording || !enableStreaming || segments.length === 0) {
      // Clear streaming when not recording
      if (streamingIntervalRef.current) {
        clearInterval(streamingIntervalRef.current);
        streamingIntervalRef.current = null;
      }
      setStreamingSegment(null);
      lastSegmentIdRef.current = null;
      return;
    }

    const latestSegment = segments[segments.length - 1];

    // Check if this is a new segment
    if (latestSegment.id !== lastSegmentIdRef.current) {
      lastSegmentIdRef.current = latestSegment.id;

      // Clear any existing streaming interval
      if (streamingIntervalRef.current) {
        clearInterval(streamingIntervalRef.current);
        streamingIntervalRef.current = null;
      }

      const fullText = latestSegment.text;

      // Completed segment: show full text immediately (never typewriter on "final" rows)
      if (latestSegment.is_partial === false) {
        setStreamingSegment({
          id: latestSegment.id,
          fullText,
          visibleText: fullText,
        });
        return;
      }

      // Show first characters immediately
      const initialText = fullText.substring(0, Math.min(INITIAL_CHARS, fullText.length));

      setStreamingSegment({
        id: latestSegment.id,
        fullText,
        visibleText: initialText,
      });

      // If text is short enough, no need to stream
      if (fullText.length <= INITIAL_CHARS) {
        return;
      }

      // Calculate how many characters to reveal per tick
      const totalTicks = Math.floor(DURATION_MS / INTERVAL_MS);
      const remainingChars = fullText.length - INITIAL_CHARS;
      const charsPerTick = Math.max(2, Math.ceil(remainingChars / totalTicks));

      let charIndex = INITIAL_CHARS;

      streamingIntervalRef.current = setInterval(() => {
        charIndex += charsPerTick;

        if (charIndex >= fullText.length) {
          // Streaming complete - show full text
          setStreamingSegment({
            id: latestSegment.id,
            fullText,
            visibleText: fullText,
          });

          // Clear interval
          if (streamingIntervalRef.current) {
            clearInterval(streamingIntervalRef.current);
            streamingIntervalRef.current = null;
          }
        } else {
          // Update visible text
          setStreamingSegment(prev => prev ? {
            ...prev,
            visibleText: fullText.substring(0, charIndex),
          } : null);
        }
      }, INTERVAL_MS);
    } else {
      // Same segment id but transcript text may have grown (e.g. partial → final on one row).
      // Previously we ignored updates and left visibleText stuck on the first short string.
      setStreamingSegment(prev => {
        if (!prev || prev.id !== latestSegment.id) {
          return prev;
        }
        if (prev.fullText === latestSegment.text) {
          return prev;
        }
        return {
          id: latestSegment.id,
          fullText: latestSegment.text,
          visibleText: latestSegment.text,
        };
      });
      if (streamingIntervalRef.current) {
        clearInterval(streamingIntervalRef.current);
        streamingIntervalRef.current = null;
      }
    }

    // Cleanup on unmount or when dependencies change
    return () => {
      if (streamingIntervalRef.current) {
        clearInterval(streamingIntervalRef.current);
        streamingIntervalRef.current = null;
      }
    };
  }, [segments, isRecording, enableStreaming]);

  /**
   * Get the display text for a segment, with streaming effect if applicable
   */
  const getDisplayText = (segment: TranscriptSegmentData): string => {
    if (segment.is_partial === false) {
      return segment.text;
    }
    if (streamingSegment && segment.id === streamingSegment.id) {
      return streamingSegment.visibleText;
    }
    return segment.text;
  };

  return {
    streamingSegmentId: streamingSegment?.id ?? null,
    getDisplayText,
  };
}
