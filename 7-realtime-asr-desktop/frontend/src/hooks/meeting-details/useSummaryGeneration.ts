import { useState, useCallback } from 'react';
import { Transcript, Summary } from '@/types';
import { ModelConfig } from '@/components/ModelSettingsModal';
import { CurrentMeeting, useSidebar } from '@/components/Sidebar/SidebarProvider';
import { invoke as invokeTauri } from '@tauri-apps/api/core';
import { toast } from 'sonner';
import Analytics from '@/lib/analytics';
import { useConfig } from '@/contexts/ConfigContext';

type SummaryStatus = 'idle' | 'processing' | 'summarizing' | 'regenerating' | 'completed' | 'error';

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
 * Pull the top-k Notion chunks relevant to this meeting from the local
 * sqlite-vec index and format them as a prompt-ready context block.
 *
 * Failures are intentionally swallowed: RAG augmentation is a "if I can,
 * I will" feature, and the user's summary should never be held hostage
 * by a backend embed call that times out, an empty index (no Notion sync
 * yet), or a missing endpoint. The caller decides what to do with an
 * empty string return.
 *
 * Query construction: the meeting title alone is often too short to
 * embed meaningfully (many auto-titled meetings are just dates), so we
 * concatenate it with a transcript snippet. We cap the snippet to keep
 * the embedding payload small — the gateway times out at 60s and a 50KB
 * embedding request just wastes that budget.
 */
async function buildRagContextBlock(
  meetingTitle: string,
  transcriptText: string,
): Promise<string> {
  const titleStr = (meetingTitle || '').trim();
  // First ~800 chars of transcript is typically enough topical signal
  // for an embedding without dragging in pleasantries/sign-offs.
  const snippet = transcriptText.trim().slice(0, 800);
  const query = [titleStr, snippet].filter((s) => s.length > 0).join(' — ');
  if (!query) return '';

  let hits: RagSearchHit[] = [];
  try {
    hits = (await invokeTauri('rag_search', { query, k: 5 })) as RagSearchHit[];
  } catch (e) {
    console.warn('rag_search failed during summary generation (continuing without RAG):', e);
    return '';
  }
  if (!hits.length) return '';

  const lines = hits.map((h) => {
    // Clip per-chunk text so a single huge chunk can't crowd out the
    // others (or the actual transcript) in the LLM's attention window.
    const text = h.text.length > 1200 ? h.text.slice(0, 1200) + '…' : h.text;
    const sourceLabel = h.page_title || h.page_id || '문서';
    return `- [${sourceLabel}]\n  ${text.replace(/\n/g, '\n  ')}`;
  });

  return [
    '[참고 문서 (Notion에서 검색된 관련 자료)]',
    ...lines,
    '',
    '위 자료는 참고용입니다. 회의 전사 내용이 우선되어야 하며, 자료가 회의 내용과 충돌할 경우 회의 내용을 따라 주세요.',
  ].join('\n');
}

/**
 * Fire-and-forget: index this meeting's freshly-completed summary into the
 * local RAG store so future chat queries can retrieve it. Failure is
 * logged but never surfaced — the user has already seen "요약 완료" and
 * an indexing hiccup shouldn't block that flow. The next chat pass that
 * happens to need this meeting will simply miss it; the bulk reindex
 * button in settings is the recovery path.
 */
function indexMeetingSummaryInBackground(meetingId: string): void {
  invokeTauri('rag_index_meeting_summary', { meetingId }).catch((e) => {
    console.warn('rag_index_meeting_summary failed (continuing):', e);
  });
}

interface UseSummaryGenerationProps {
  meeting: any;
  transcripts: Transcript[];
  modelConfig: ModelConfig;
  isModelConfigLoading: boolean;
  selectedTemplate: string;
  onMeetingUpdated?: () => Promise<void>;
  updateMeetingTitle: (title: string) => void;
  setAiSummary: (summary: Summary | null) => void;
  onOpenModelSettings?: () => void;
}

export function useSummaryGeneration({
  meeting,
  transcripts,
  modelConfig,
  isModelConfigLoading,
  selectedTemplate,
  onMeetingUpdated,
  updateMeetingTitle,
  setAiSummary,
  onOpenModelSettings,
}: UseSummaryGenerationProps) {
  const [summaryStatus, setSummaryStatus] = useState<SummaryStatus>('idle');
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const [originalTranscript, setOriginalTranscript] = useState<string>('');

  const { startSummaryPolling, stopSummaryPolling } = useSidebar();
  const { userLanguage } = useConfig();

  // Helper to get status message
  const getSummaryStatusMessage = useCallback((status: SummaryStatus) => {
    switch (status) {
      case 'processing':
        return '전사 처리 중…';
      case 'summarizing':
        return '요약 생성 중…';
      case 'regenerating':
        return '요약 재생성 중…';
      case 'completed':
        return '요약 완료';
      case 'error':
        return '요약 생성 중 오류';
      default:
        return '';
    }
  }, []);

  // Unified summary processing logic
  const processSummary = useCallback(async ({
    transcriptText,
    customPrompt = '',
    isRegeneration = false,
  }: {
    transcriptText: string;
    customPrompt?: string;
    isRegeneration?: boolean;
  }) => {
    setSummaryStatus(isRegeneration ? 'regenerating' : 'processing');
    setSummaryError(null);

    try {
      if (!transcriptText.trim()) {
        throw new Error('전사 내용이 없습니다. 먼저 텍스트를 추가해 주세요.');
      }

      if (!isRegeneration) {
        setOriginalTranscript(transcriptText);
      }

      console.log('Processing transcript with template:', selectedTemplate);

      // Calculate time since recording
      const timeSinceRecording = (Date.now() - new Date(meeting.created_at).getTime()) / 60000; // minutes

      // Track summary generation started
      await Analytics.trackSummaryGenerationStarted(
        modelConfig.provider,
        modelConfig.model,
        transcriptText.length,
        timeSinceRecording
      );

      // Track custom prompt usage if present
      if (customPrompt.trim().length > 0) {
        await Analytics.trackCustomPromptUsed(customPrompt.trim().length);
      }

      // Show toast notification for generation start
      toast.info(isRegeneration ? '요약 재생성 중…' : '요약 생성 중…', {
        description: 'Relay AI 사용',
        duration: 3000,
      });

      // Process transcript and get process_id
      const result = await invokeTauri('api_process_transcript', {
        text: transcriptText,
        model: modelConfig.provider,
        modelName: modelConfig.model,
        meetingId: meeting.id,
        chunkSize: 40000,
        overlap: 1000,
        customPrompt: customPrompt,
        templateId: selectedTemplate,
        language: userLanguage,
      }) as any;

      const process_id = result.process_id;
      console.log('Process ID:', process_id);

      // Start global polling via context
      startSummaryPolling(meeting.id, process_id, async (pollingResult) => {
        console.log('Summary status:', pollingResult);

        // Handle cancellation
        if (pollingResult.status === 'cancelled') {
          console.log('Summary generation was cancelled');

          // Reload summary from database (backend has already restored from backup)
          try {
            const existingSummary = await invokeTauri('api_get_summary', {
              meetingId: meeting.id
            }) as any;

            if (existingSummary?.data) {
              console.log('Restored previous summary after cancellation');
              setAiSummary(existingSummary.data);
              setSummaryStatus('completed');
            } else {
              setSummaryStatus('idle');
            }
          } catch (error) {
            console.error('Failed to reload summary after cancellation:', error);
            setSummaryStatus('idle');
          }

          setSummaryError(null);
          return;
        }

        // Handle errors
        if (pollingResult.status === 'error' || pollingResult.status === 'failed') {
          console.error('Backend returned error:', pollingResult.error);
          const errorMessage = pollingResult.error || (isRegeneration ? '요약 재생성에 실패했습니다' : '요약 생성에 실패했습니다');

          // If this was a regeneration, try to restore previous summary from database
          if (isRegeneration) {
            try {
              const existingSummary = await invokeTauri('api_get_summary', {
                meetingId: meeting.id
              }) as any;

              if (existingSummary?.data) {
                console.log('Restored previous summary after regeneration failure');
                setAiSummary(existingSummary.data);
                setSummaryStatus('completed');
                setSummaryError(null);

                // Show error toast with restoration message
                toast.error('요약 재생성에 실패했습니다', {
                  description: `${errorMessage}. 이전 요약을 복원했습니다.`,
                });

                await Analytics.trackSummaryGenerationCompleted(
                  modelConfig.provider,
                  modelConfig.model,
                  false,
                  undefined,
                  errorMessage
                );
                return;
              }
            } catch (error) {
              console.error('Failed to reload summary after error:', error);
            }
          }

          // Continue with normal error handling if not regeneration or reload failed
          setSummaryError(errorMessage);
          setSummaryStatus('error');

          // Check if this is a "model is required" error
          const isModelRequiredError = errorMessage.includes('model is required') ||
            errorMessage.includes('"model":"required"') ||
            errorMessage.toLowerCase().includes('model') && errorMessage.toLowerCase().includes('required');

          // Show error toast
          toast.error(isRegeneration ? '요약 재생성에 실패했습니다' : '요약 생성에 실패했습니다', {
            description: errorMessage.includes('Connection refused')
              ? '설정된 LLM 서비스에 연결할 수 없습니다. 엔드포인트와 자격증명을 확인해 주세요.'
              : errorMessage,
          });

          // Auto-open model settings modal if model is missing
          if (isModelRequiredError && onOpenModelSettings) {
            console.log(' Model required error detected, opening model settings...');
            onOpenModelSettings();
          }

          await Analytics.trackSummaryGenerationCompleted(
            modelConfig.provider,
            modelConfig.model,
            false,
            undefined,
            errorMessage
          );
          return;
        }

        // Handle successful completion
        if (pollingResult.status === 'completed' && pollingResult.data) {
          console.log('Summary generation completed:', pollingResult.data);

          // Update meeting title if available
          const meetingName = pollingResult.data.MeetingName || pollingResult.meetingName;
          if (meetingName) {
            updateMeetingTitle(meetingName);
          }

          // Check if backend returned markdown format (new flow)
          if (pollingResult.data.markdown) {
            console.log('Received markdown format from backend');
            setAiSummary({ markdown: pollingResult.data.markdown } as any);
            setSummaryStatus('completed');

            // Show success toast
            toast.success('요약이 생성되었습니다!', {
              description: '회의 요약이 준비되었습니다',
              duration: 4000,
            });

            if (meetingName && onMeetingUpdated) {
              await onMeetingUpdated();
            }

            indexMeetingSummaryInBackground(meeting.id);

            await Analytics.trackSummaryGenerationCompleted(
              modelConfig.provider,
              modelConfig.model,
              true
            );
            return;
          }

          // Legacy format handling
          const summarySections = Object.entries(pollingResult.data).filter(([key]) => key !== 'MeetingName');
          const allEmpty = summarySections.every(([, section]) => !(section as any).blocks || (section as any).blocks.length === 0);

          if (allEmpty) {
            console.error('Summary completed but all sections empty');
            setSummaryError('요약 생성이 끝났지만 내용이 비어 있습니다.');
            setSummaryStatus('error');

            await Analytics.trackSummaryGenerationCompleted(
              modelConfig.provider,
              modelConfig.model,
              false,
              undefined,
              'Empty summary generated'
            );
            return;
          }

          // Remove MeetingName from data before formatting
          const { MeetingName, ...summaryData } = pollingResult.data;

          // Format legacy summary data
          const formattedSummary: Summary = {};
          const sectionKeys = pollingResult.data._section_order || Object.keys(summaryData);

          for (const key of sectionKeys) {
            try {
              const section = summaryData[key];
              if (section && typeof section === 'object' && 'title' in section && 'blocks' in section) {
                const typedSection = section as { title?: string; blocks?: any[] };

                if (Array.isArray(typedSection.blocks)) {
                  formattedSummary[key] = {
                    title: typedSection.title || key,
                    blocks: typedSection.blocks.map((block: any) => ({
                      ...block,
                      color: 'default',
                      content: block?.content?.trim() || ''
                    }))
                  };
                } else {
                  formattedSummary[key] = {
                    title: typedSection.title || key,
                    blocks: []
                  };
                }
              }
            } catch (error) {
              console.warn(`Error processing section ${key}:`, error);
            }
          }

          setAiSummary(formattedSummary);
          setSummaryStatus('completed');

          // Show success toast
          toast.success('요약이 생성되었습니다!', {
            description: '회의 요약이 준비되었습니다',
            duration: 4000,
          });

          indexMeetingSummaryInBackground(meeting.id);

          await Analytics.trackSummaryGenerationCompleted(
            modelConfig.provider,
            modelConfig.model,
            true
          );

          if (meetingName && onMeetingUpdated) {
            await onMeetingUpdated();
          }
        }
      });
    } catch (error) {
      console.error(`Failed to ${isRegeneration ? 'regenerate' : 'generate'} summary:`, error);
      // Tauri invoke() may reject with a plain string, so force string
      // conversion instead of hiding the real message behind "Unknown error".
      const errorMessage =
        error instanceof Error
          ? error.message
          : typeof error === 'string'
            ? error
            : String(error ?? 'Unknown error');
      setSummaryError(errorMessage);
      setSummaryStatus('error');
      // Note: We don't clear the summary here because the backend has already restored from backup

      toast.error(isRegeneration ? '요약 재생성에 실패했습니다' : '요약 생성에 실패했습니다', {
        description: errorMessage,
      });

      await Analytics.trackSummaryGenerationCompleted(
        modelConfig.provider,
        modelConfig.model,
        false,
        undefined,
        errorMessage
      );
    }
  }, [
    meeting.id,
    meeting.created_at,
    modelConfig,
    selectedTemplate,
    startSummaryPolling,
    setAiSummary,
    updateMeetingTitle,
    onMeetingUpdated,
  ]);

  // Helper function to fetch ALL transcripts for summary generation
  const fetchAllTranscripts = useCallback(async (meetingId: string): Promise<Transcript[]> => {
    try {
      console.log(' Fetching all transcripts for meeting:', meetingId);

      // First, get total count by fetching first page
      const firstPage = await invokeTauri('api_get_meeting_transcripts', {
        meetingId,
        limit: 1,
        offset: 0,
      }) as { transcripts: Transcript[]; total_count: number; has_more: boolean };

      const totalCount = firstPage.total_count;
      console.log(` Total transcripts in database: ${totalCount}`);

      if (totalCount === 0) {
        return [];
      }

      // Fetch all transcripts in one call
      const allData = await invokeTauri('api_get_meeting_transcripts', {
        meetingId,
        limit: totalCount,
        offset: 0,
      }) as { transcripts: Transcript[]; total_count: number; has_more: boolean };

      console.log(` Fetched ${allData.transcripts.length} transcripts from database`);
      return allData.transcripts;
    } catch (error) {
      console.error(' Error fetching all transcripts:', error);
      toast.error('요약 생성을 위한 전사 데이터를 불러오지 못했습니다');
      return [];
    }
  }, []);

  // Public API: Generate summary from transcripts
  const handleGenerateSummary = useCallback(async (customPrompt: string = '') => {
    // Check if model config is still loading
    if (isModelConfigLoading) {
      console.log('Model configuration is still loading, please wait...');
      toast.info('모델 설정을 불러오는 중입니다. 잠시만 기다려 주세요…');
      return;
    }

    // CHANGE: Fetch ALL transcripts from database, not from pagination state
    console.log(' Fetching all transcripts for summary generation...');
    const allTranscripts = await fetchAllTranscripts(meeting.id);

    if (!allTranscripts.length) {
      const error_msg = '요약할 전사 내용이 없습니다';
      console.log(error_msg);
      toast.error(error_msg);
      return;
    }

    console.log(` Proceeding with ${allTranscripts.length} transcripts`);

    console.log(' Starting summary generation with config:', {
      provider: modelConfig.provider,
      model: modelConfig.model,
      template: selectedTemplate
    });

    // `relay-ai` routes through the Relay gateway (resolved server-side
    // in llm_client.rs), so endpoint/model don't need to be populated
    // client-side. Only gate non-gateway providers on having a model set.
    if (modelConfig.provider !== 'relay-ai' && !modelConfig.model?.trim()) {
      toast.error('요약 모델이 설정되지 않았습니다', {
        description: '요약을 생성하기 전에 설정에서 사용할 모델을 선택해 주세요.',
        duration: 5000,
      });
      onOpenModelSettings?.();
      return;
    }

    // Format timestamps as recording-relative [MM:SS] instead of wall-clock time
    const formatTime = (seconds: number | undefined, fallbackTimestamp: string): string => {
      if (seconds === undefined) {
        // For old transcripts without audio_start_time, use wall-clock time
        return fallbackTimestamp;
      }
      const totalSecs = Math.floor(seconds);
      const mins = Math.floor(totalSecs / 60);
      const secs = totalSecs % 60;
      return `[${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}]`;
    };

    const fullTranscript = allTranscripts
      .map(t => `${formatTime(t.audio_start_time, t.timestamp)} ${t.text}`)
      .join('\n');

    // RAG augmentation: pull relevant Notion chunks and prepend them to
    // whatever the user typed in customPrompt. Empty string (no hits or
    // index not synced) cleanly degrades to the original behavior.
    const ragBlock = await buildRagContextBlock(meeting.title || '', fullTranscript);
    const augmentedPrompt = ragBlock
      ? (customPrompt.trim()
          ? `${ragBlock}\n\n[사용자 추가 지시]\n${customPrompt.trim()}`
          : ragBlock)
      : customPrompt;

    await processSummary({ transcriptText: fullTranscript, customPrompt: augmentedPrompt });
  }, [meeting.id, meeting.title, fetchAllTranscripts, processSummary, modelConfig, isModelConfigLoading, selectedTemplate]);

  // Public API: Regenerate summary from original transcript
  const handleRegenerateSummary = useCallback(async () => {
    if (!originalTranscript.trim()) {
      console.error('No original transcript available for regeneration');
      return;
    }

    await processSummary({
      transcriptText: originalTranscript,
      isRegeneration: true
    });
  }, [originalTranscript, processSummary]);

  // Public API: Stop ongoing summary generation
  const handleStopGeneration = useCallback(async () => {
    console.log('Stopping summary generation for meeting:', meeting.id);

    try {
      // Call backend to cancel the summary generation
      await invokeTauri('api_cancel_summary', {
        meetingId: meeting.id
      });
      console.log(' Backend cancellation request sent for meeting:', meeting.id);
    } catch (error) {
      console.error('Failed to cancel summary generation:', error);
      // Continue with frontend cleanup even if backend call fails
    }

    // Stop polling
    stopSummaryPolling(meeting.id);

    // Reset status to idle
    setSummaryStatus('idle');
    setSummaryError(null);

    // Show toast notification
    toast.info('요약 생성을 중지했습니다', {
      description: '언제든 새로 요약을 생성할 수 있습니다',
      duration: 3000,
    });
  }, [meeting.id, stopSummaryPolling]);

  return {
    summaryStatus,
    summaryError,
    handleGenerateSummary,
    handleRegenerateSummary,
    handleStopGeneration,
    getSummaryStatusMessage,
  };
}
