'use client';

import React, { useEffect } from 'react';
import { listen } from '@tauri-apps/api/event';
import { toast } from 'sonner';
import { useRecordingStop } from '@/hooks/useRecordingStop';

/**
 * RecordingPostProcessingProvider
 *
 * This provider handles post-processing when recording stops from any source:
 * - Tray menu stop
 * - Global keyboard shortcut
 * - Overlay stop button
 * - Main UI stop button
 *
 * It listens for the 'recording-stop-complete' event from Rust backend
 * and triggers the full post-processing flow (save to database, navigate, analytics)
 * regardless of which page the user is currently on.
 */
export function RecordingPostProcessingProvider({ children }: { children: React.ReactNode }) {
  // No-op functions since the global RecordingStateContext already handles state updates
  // These are only needed for the hook's local component state management
  const setIsRecording = () => { };
  const setIsRecordingDisabled = () => { };

  const {
    handleRecordingStop,
  } = useRecordingStop(setIsRecording, setIsRecordingDisabled);

  useEffect(() => {
    let unlistenFn: (() => void) | undefined;

    const setupListener = async () => {
      try {
        // Listen for recording-stop-complete event from Rust
        unlistenFn = await listen<boolean>('recording-stop-complete', (event) => {
          console.log('[RecordingPostProcessing] Received recording-stop-complete event:', event.payload);

          // Call the post-processing handler
          // event.payload is the callApi boolean (true for normal stops)
          handleRecordingStop(event.payload);
        });

        console.log('[RecordingPostProcessing] Event listener set up successfully');
      } catch (error) {
        console.error('[RecordingPostProcessing] Failed to set up event listener:', error);
      }
    };

    setupListener();

    return () => {
      if (unlistenFn) {
        console.log('[RecordingPostProcessing] Cleaning up event listener');
        unlistenFn();
      }
    };
  }, [handleRecordingStop]);

  // Silence-driven auto-stop: warn the user at 2 minutes of silence with a
  // dismissable toast, then surface the auto-stop notification at 3 minutes.
  // The actual stop_recording call is performed by the Rust monitor task.
  useEffect(() => {
    let unlistenWarn: (() => void) | undefined;
    let unlistenStop: (() => void) | undefined;

    const setup = async () => {
      unlistenWarn = await listen<{ seconds_until_stop: number }>(
        'recording-silence-warning',
        (event) => {
          const seconds = event.payload?.seconds_until_stop ?? 60;
          // No dismiss action by design: silence has no value to record. Speak
          // and the worker will reset the clock automatically.
          toast.warning(
            `${seconds}초 후 무음으로 인해 녹음이 자동 종료됩니다`,
            {
              id: 'silence-warning',
              duration: seconds * 1000,
            },
          );
        },
      );

      unlistenStop = await listen<{ elapsed_secs: number }>(
        'recording-auto-stopped-silence',
        () => {
          toast.dismiss('silence-warning');
          toast.info('무음으로 인해 녹음이 자동 종료되었습니다');
        },
      );
    };

    setup();

    return () => {
      unlistenWarn?.();
      unlistenStop?.();
    };
  }, []);

  return <>{children}</>;
}
