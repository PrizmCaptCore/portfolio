import { useRef, useState, useEffect, useCallback, RefObject } from "react";
import { Virtualizer } from "@tanstack/react-virtual";

interface UseAutoScrollProps {
    scrollRef: RefObject<HTMLDivElement | null>;
    segments: any[];
    isRecording: boolean;
    isPaused: boolean;
    activeSegmentId?: string;
    virtualizer?: Virtualizer<HTMLDivElement, Element>;
    virtualizationThreshold?: number;
    disableAutoScroll?: boolean; // Completely disable auto-scroll behavior (for meeting details page)
}

interface UseAutoScrollReturn {
    autoScroll: boolean;
    setAutoScroll: (value: boolean) => void;
    scrollToBottom: () => void;
}

// Threshold in pixels to consider "at the bottom"
const SCROLL_THRESHOLD = 100;

/**
 * Custom hook to manage auto-scrolling behavior for transcript
 *
 * Features:
 * - Auto-scrolls to bottom when new content arrives during recording
 * - Pauses auto-scroll when user manually scrolls up
 * - Resumes auto-scroll when user scrolls back to the bottom
 *
 * @param segments - Array of transcript segments
 * @param isRecording - Whether recording is in progress
 * @param isPaused - Whether recording is paused
 * @param activeSegmentId - ID of the currently active segment
 * @returns Scroll ref, auto-scroll state, and scroll control functions
 */
export function useAutoScroll({
    scrollRef,
    segments,
    isRecording,
    isPaused,
    activeSegmentId,
    virtualizer,
    virtualizationThreshold = 10,
    disableAutoScroll = false,
}: UseAutoScrollProps): UseAutoScrollReturn {
    const useVirtualization = virtualizer && segments.length >= virtualizationThreshold;
    const [autoScroll, setAutoScroll] = useState(true);
    // Ref to always have current autoScroll value in effects
    const autoScrollRef = useRef(autoScroll);
    autoScrollRef.current = autoScroll;

    // Synchronous mirror of `autoScroll` for the segment effect. State
    // updates lag by a render so the segment effect can't trust them when
    // a transcript arrives in the same tick as the user's scroll.
    const userScrolledRef = useRef(false);
    // Track if we're doing a programmatic scroll
    const isProgrammaticScrollRef = useRef(false);
    // Track previous segment count to detect new segments
    const prevSegmentCountRef = useRef(segments.length);

    /**
     * Check if the user is scrolled near the bottom
     */
    const isNearBottom = useCallback(() => {
        if (!scrollRef.current) return true;
        const { scrollTop, scrollHeight, clientHeight } = scrollRef.current;
        return scrollHeight - scrollTop - clientHeight <= SCROLL_THRESHOLD;
    }, [scrollRef]);

    /**
     * Scroll to bottom programmatically. When the list is virtualized we
     * have to drive the virtualizer (and then a backup direct scrollTop set
     * after it renders) — a plain scrollTop assignment lands on whatever
     * the virtualizer currently has rendered, which is rarely the actual
     * end. The programmatic flag is held for a longer window so any
     * delayed scroll events from the virtualizer settling don't get
     * mistaken for the user wheel-scrolling away from the bottom (which
     * would immediately turn auto-scroll back off).
     */
    const scrollToBottom = useCallback(() => {
        if (!scrollRef.current) return;

        isProgrammaticScrollRef.current = true;

        if (useVirtualization && virtualizer) {
            const totalSize = virtualizer.getTotalSize();
            virtualizer.scrollToOffset(totalSize + 1000, { align: "end" });
            // Belt-and-suspenders: re-pin scrollTop to the bottom after the
            // virtualizer's render lands, so the visible viewport actually
            // sits at the end (the virtualizer's offset math can leave us
            // a row or two short on tall content).
            setTimeout(() => {
                if (scrollRef.current) {
                    scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
                }
            }, 50);
        } else {
            scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
        }

        userScrolledRef.current = false;
        setAutoScroll(true);

        // Hold the programmatic flag long enough for the virtualizer (and
        // any layout reflow) to finish — anything shorter and a tail
        // scroll event sneaks through to the user-intent handler and
        // immediately flips auto-scroll back off.
        setTimeout(() => {
            isProgrammaticScrollRef.current = false;
        }, useVirtualization ? 250 : 50);
    }, [scrollRef, useVirtualization, virtualizer]);

    // One-way scroll handler: a manual scroll only ever turns auto-scroll
    // OFF. Re-enabling is reserved for the explicit "활성화" button.
    //
    // Earlier we synced auto-scroll to "near bottom", but that bounced the
    // state when the user scrolled back near the bottom (or when partial
    // transcript updates briefly nudged the layout), and broke the user's
    // mental model — they'd see "활성화" while content was still following
    // because the toggle had silently flipped under them. The toggle is now
    // strictly user-driven: scroll wheel ⇒ OFF, button click ⇒ ON.
    useEffect(() => {
        const container = scrollRef.current;
        if (!container) return;

        const handleScroll = () => {
            // Programmatic scroll-to-bottom — ignore. Otherwise the moment
            // we reach the bottom would (incorrectly) be treated as a user
            // action.
            if (isProgrammaticScrollRef.current) return;
            const nearBottom = isNearBottom();
            // Only act on "user moved away from the bottom". Returning to
            // the bottom on its own is NOT a re-enable signal — the user
            // has to press the button to turn auto-scroll back on.
            if (!nearBottom) {
                userScrolledRef.current = true;
                if (autoScrollRef.current) {
                    setAutoScroll(false);
                }
            }
        };

        container.addEventListener("scroll", handleScroll, { passive: true });
        return () => container.removeEventListener("scroll", handleScroll);
    }, [isNearBottom, scrollRef]);

    // Auto-scroll to bottom whenever the segments array changes during
    // recording — this covers both new segments AND in-place updates to
    // existing segments (translation results landing in `translated_text`,
    // tentative-text growing, etc.). Earlier this gated on
    // `segments.length > prev`, which silently dropped translation/partial
    // updates because they don't change the count.
    //
    // Guards:
    //   - autoScrollRef.current: explicit toggle is ON
    //   - !userScrolledRef.current: user hasn't manually scrolled away (the
    //     scroll handler flips this synchronously on the first wheel notch)
    //   - isRecording && !isPaused: only follow live content
    // We deliberately don't gate on isNearBottom here — when the toggle is
    // ON and the user hasn't moved, we want to chase content growth even
    // if a burst of translations momentarily pushes us past the
    // 100 px "near-bottom" threshold.
    useEffect(() => {
        if (disableAutoScroll) {
            return;
        }

        prevSegmentCountRef.current = segments.length;

        if (
            !autoScrollRef.current ||
            userScrolledRef.current ||
            !isRecording ||
            isPaused ||
            segments.length === 0
        ) {
            return;
        }

        isProgrammaticScrollRef.current = true;

        if (useVirtualization && virtualizer) {
            const totalSize = virtualizer.getTotalSize();
            virtualizer.scrollToOffset(totalSize + 1000, { align: "end" });
            setTimeout(() => {
                if (scrollRef.current) {
                    scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
                }
            }, 50);
        } else if (scrollRef.current) {
            scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
        }

        setTimeout(() => {
            isProgrammaticScrollRef.current = false;
        }, 150);
    }, [segments, isRecording, isPaused, useVirtualization, virtualizer, scrollRef, disableAutoScroll]);

    // Auto-scroll to active segment (when clicking on search results, etc.)
    useEffect(() => {
        if (activeSegmentId) {
            isProgrammaticScrollRef.current = true;

            if (useVirtualization && virtualizer) {
                const index = segments.findIndex((s: any) => s.id === activeSegmentId);
                if (index >= 0) {
                    virtualizer.scrollToIndex(index, { align: "center", behavior: "smooth" });
                }
            } else {
                const element = document.getElementById(`segment-${activeSegmentId}`);
                if (element) {
                    element.scrollIntoView({ behavior: "smooth", block: "center" });
                }
            }

            // Reset the flag after scroll animation completes
            setTimeout(() => {
                isProgrammaticScrollRef.current = false;
            }, 500);
        }
    }, [activeSegmentId, useVirtualization, virtualizer, segments]);

    return {
        autoScroll,
        setAutoScroll,
        scrollToBottom,
    };
}
