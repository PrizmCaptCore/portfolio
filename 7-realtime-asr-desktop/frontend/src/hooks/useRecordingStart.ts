import { useState, useEffect, useCallback } from 'react';
import { invoke } from '@tauri-apps/api/core';
import { useTranscripts } from '@/contexts/TranscriptContext';
import { useSidebar } from '@/components/Sidebar/SidebarProvider';
import { useConfig } from '@/contexts/ConfigContext';
import { useRecordingState, RecordingStatus } from '@/contexts/RecordingStateContext';
import { recordingService } from '@/services/recordingService';
import Analytics from '@/lib/analytics';
import { showRecordingNotification } from '@/lib/recordingNotification';
import { toast } from 'sonner';

interface UseRecordingStartReturn {
  handleRecordingStart: () => Promise<void>;
  isAutoStarting: boolean;
}

/**
 * Custom hook for managing recording start lifecycle.
 * Handles both manual start (button click) and auto-start (from sidebar navigation).
 *
 * Features:
 * - Meeting title generation (format: Meeting DD_MM_YY_HH_MM_SS)
 * - Transcript clearing on start
 * - Analytics tracking
 * - Recording notification display
 * - Auto-start from sidebar via sessionStorage flag
 */
export function useRecordingStart(
  isRecording: boolean,
  setIsRecording: (value: boolean) => void,
  showModal?: (name: 'modelSelector', message?: string) => void
): UseRecordingStartReturn {
  const [isAutoStarting, setIsAutoStarting] = useState(false);

  const { clearTranscripts, setMeetingTitle } = useTranscripts();
  const { setIsMeetingActive } = useSidebar();
  const { selectedDevices, languagesConfigured } = useConfig();
  const recordingState = useRecordingState();
  const { setStatus } = recordingState;

  // Generate meeting title with timestamp
  const generateMeetingTitle = useCallback(() => {
    const now = new Date();
    const day = String(now.getDate()).padStart(2, '0');
    const month = String(now.getMonth() + 1).padStart(2, '0');
    const year = String(now.getFullYear()).slice(-2);
    const hours = String(now.getHours()).padStart(2, '0');
    const minutes = String(now.getMinutes()).padStart(2, '0');
    const seconds = String(now.getSeconds()).padStart(2, '0');
    return `Meeting ${day}_${month}_${year}_${hours}_${minutes}_${seconds}`;
  }, []);

  // Check if transcription provider is ready
  const checkTranscriptionReady = useCallback(async (): Promise<boolean> => {
    try {
      const config = await invoke<{ provider: string; model: string; api_key: string | null }>('api_get_transcript_config');
      if (!config) return false;
      // Local providers don't need an API key
      if (config.provider === 'cnn-stt' || config.provider === 'whisper') {
        return true;
      }
      const key = await invoke<string>('api_get_transcript_api_key', { provider: config.provider });
      return typeof key === 'string' && key.trim().length > 0;
    } catch (error) {
      console.error('Failed to check transcription readiness:', error);
      return false;
    }
  }, []);

  // Handle manual recording start (from button click)
  const handleRecordingStart = useCallback(async () => {
    try {
      console.log('handleRecordingStart called - checking transcription API key');

      // Defense in depth: the home-screen record button is disabled when
      // languages aren't picked, but auto-start from sidebar nav and the
      // sessionStorage flag both come through this path too. Bail with a
      // visible toast instead of starting a recording the user hasn't
      // finished configuring.
      if (!languagesConfigured) {
        toast.error('언어 설정이 필요합니다', {
          description: '듣는 언어와 자막 언어를 먼저 선택해 주세요.',
          duration: 5000,
        });
        setStatus(RecordingStatus.IDLE);
        return;
      }

      const transcriptionReady = await checkTranscriptionReady();
      if (!transcriptionReady) {
        toast.error('전사 설정이 필요합니다', {
          description: '설정 > 전사에서 제공자를 선택하고 API 키를 입력해 주세요.',
          duration: 5000,
        });
        setStatus(RecordingStatus.IDLE);
        return;
      }

      console.log('Transcription ready - setting up meeting title and state');

      const randomTitle = generateMeetingTitle();
      setMeetingTitle(randomTitle);

      // Set STARTING status before initiating backend recording
      setStatus(RecordingStatus.STARTING, '녹음을 시작하는 중…');

      // Start the actual backend recording
      console.log('Starting backend recording with meeting:', randomTitle);
      await recordingService.startRecordingWithDevices(
        selectedDevices?.micDevice || null,
        selectedDevices?.systemDevice || null,
        randomTitle
      );
      console.log('Backend recording started successfully');

      // Update state after successful backend start
      // Note: RECORDING status will be set by RecordingStateContext event listener
      console.log('Setting isRecordingState to true');
      setIsRecording(true); // This will also update the sidebar via the useEffect
      clearTranscripts(); // Clear previous transcripts when starting new recording
      setIsMeetingActive(true);
      Analytics.trackButtonClick('start_recording', 'home_page');

      // Show recording notification if enabled
      await showRecordingNotification();
    } catch (error) {
      console.error('Failed to start recording:', error);
      setStatus(RecordingStatus.ERROR, error instanceof Error ? error.message : '녹음을 시작하지 못했습니다');
      setIsRecording(false); // Reset state on error
      Analytics.trackButtonClick('start_recording_error', 'home_page');
      // Re-throw so RecordingControls can handle device-specific errors
      throw error;
    }
  }, [generateMeetingTitle, setMeetingTitle, setIsRecording, clearTranscripts, setIsMeetingActive, checkTranscriptionReady, selectedDevices, showModal, setStatus, languagesConfigured]);

  // Keep sidebar/tray auto-start in "preparing" until the backend reports active
  // recording — avoids flashing RecordingControls before the control bar is ready.
  useEffect(() => {
    if (!isAutoStarting) return;
    if (
      recordingState.isRecording &&
      recordingState.status === RecordingStatus.RECORDING
    ) {
      setIsAutoStarting(false);
    }
  }, [
    isAutoStarting,
    recordingState.isRecording,
    recordingState.status,
  ]);

  // Check for autoStartRecording flag and start recording automatically
  useEffect(() => {
    const checkAutoStartRecording = async () => {
      if (typeof window !== 'undefined') {
        const shouldAutoStart = sessionStorage.getItem('autoStartRecording');
        if (shouldAutoStart === 'true' && !isRecording && !isAutoStarting) {
          console.log('Auto-starting recording from navigation...');
          setIsAutoStarting(true);
          sessionStorage.removeItem('autoStartRecording'); // Clear the flag

          const transcriptionReady = await checkTranscriptionReady();
          if (!transcriptionReady) {
            toast.error('OpenAI API 키가 설정되지 않았습니다', {
              description: '설정 > 전사에서 OpenAI API 키를 입력해 주세요.',
              duration: 5000,
            });
            setStatus(RecordingStatus.IDLE);
            setIsAutoStarting(false);
            return;
          }

          // Start the actual backend recording
          try {
            // Generate meeting title
            const generatedMeetingTitle = generateMeetingTitle();

            // Set STARTING status before initiating backend recording
            setStatus(RecordingStatus.STARTING, '녹음을 시작하는 중…');

            console.log('Auto-starting backend recording with meeting:', generatedMeetingTitle);
            const result = await recordingService.startRecordingWithDevices(
              selectedDevices?.micDevice || null,
              selectedDevices?.systemDevice || null,
              generatedMeetingTitle
            );
            console.log('Auto-start backend recording result:', result);

            // Update UI state after successful backend start
            // Note: RECORDING status will be set by RecordingStateContext event listener
            setMeetingTitle(generatedMeetingTitle);
            setIsRecording(true);
            clearTranscripts();
            setIsMeetingActive(true);
            Analytics.trackButtonClick('start_recording', 'sidebar_auto');

            // Show recording notification if enabled
            await showRecordingNotification();
          } catch (error) {
            console.error('Failed to auto-start recording:', error);
            setStatus(RecordingStatus.ERROR, error instanceof Error ? error.message : '자동 녹음 시작에 실패했습니다');
            alert('녹음 시작에 실패했습니다. ');
            Analytics.trackButtonClick('start_recording_error', 'sidebar_auto');
            setIsAutoStarting(false);
          }
        }
      }
    };

    checkAutoStartRecording();
  }, [
    isRecording,
    isAutoStarting,
    selectedDevices,
    generateMeetingTitle,
    setMeetingTitle,
    setIsRecording,
    clearTranscripts,
    setIsMeetingActive,
    checkTranscriptionReady,
    showModal,
    setStatus,
  ]);

  // Listen for direct recording trigger from sidebar when already on home page
  useEffect(() => {
    const handleDirectStart = async () => {
      if (isRecording || isAutoStarting) {
        console.log('Recording already in progress, ignoring direct start event');
        return;
      }

      console.log('Direct start from sidebar - checking transcription API key');
      setIsAutoStarting(true);

      const transcriptionReady = await checkTranscriptionReady();
      if (!transcriptionReady) {
        toast.error('전사 설정이 필요합니다', {
          description: '설정 > 전사에서 제공자를 선택하고 API 키를 입력해 주세요.',
          duration: 5000,
        });
        setStatus(RecordingStatus.IDLE);
        setIsAutoStarting(false);
        return;
      }

      try {
        // Generate meeting title
        const generatedMeetingTitle = generateMeetingTitle();

        // Set STARTING status before initiating backend recording
        setStatus(RecordingStatus.STARTING, '녹음을 시작하는 중…');

        console.log('Starting backend recording with meeting:', generatedMeetingTitle);
        const result = await recordingService.startRecordingWithDevices(
          selectedDevices?.micDevice || null,
          selectedDevices?.systemDevice || null,
          generatedMeetingTitle
        );
        console.log('Backend recording result:', result);

        // Update UI state after successful backend start
        // Note: RECORDING status will be set by RecordingStateContext event listener
        setMeetingTitle(generatedMeetingTitle);
        setIsRecording(true);
        clearTranscripts();
        setIsMeetingActive(true);
        Analytics.trackButtonClick('start_recording', 'sidebar_direct');

        // Show recording notification if enabled
        await showRecordingNotification();
      } catch (error) {
        console.error('Failed to start recording from sidebar:', error);
        setStatus(RecordingStatus.ERROR, error instanceof Error ? error.message : '사이드바에서 녹음을 시작하지 못했습니다');
        alert('녹음 시작에 실패했습니다. ');
        Analytics.trackButtonClick('start_recording_error', 'sidebar_direct');
        setIsAutoStarting(false);
      }
    };

    window.addEventListener('start-recording-from-sidebar', handleDirectStart);

    return () => {
      window.removeEventListener('start-recording-from-sidebar', handleDirectStart);
    };
  }, [
    isRecording,
    isAutoStarting,
    selectedDevices,
    generateMeetingTitle,
    setMeetingTitle,
    setIsRecording,
    clearTranscripts,
    setIsMeetingActive,
    checkTranscriptionReady,
    showModal,
    setStatus,
  ]);

  return {
    handleRecordingStart,
    isAutoStarting,
  };
}
