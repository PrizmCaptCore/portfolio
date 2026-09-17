import { useCallback, RefObject } from 'react';
import { Transcript, Summary } from '@/types';
import { BlockNoteSummaryViewRef } from '@/components/AISummary/BlockNoteSummaryView';
import { toast } from 'sonner';
import Analytics from '@/lib/analytics';
import { invoke as invokeTauri } from '@tauri-apps/api/core';
import { copyToClipboard } from '@/lib/clipboard';

interface UseCopyOperationsProps {
  meeting: any;
  transcripts: Transcript[];
  meetingTitle: string;
  aiSummary: Summary | null;
  blockNoteSummaryRef: RefObject<BlockNoteSummaryViewRef>;
}

export function useCopyOperations({
  meeting,
  transcripts,
  meetingTitle,
  aiSummary,
  blockNoteSummaryRef,
}: UseCopyOperationsProps) {

  // Helper function to fetch ALL transcripts for copying (not just paginated data)
  const fetchAllTranscripts = useCallback(async (meetingId: string): Promise<Transcript[]> => {
    try {
      console.log(' Fetching all transcripts for copying:', meetingId);

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

      console.log(` Fetched ${allData.transcripts.length} transcripts from database for copying`);
      return allData.transcripts;
    } catch (error) {
      console.error(' Error fetching all transcripts:', error);
      toast.error('복사할 전사 데이터를 불러오지 못했습니다');
      return [];
    }
  }, []);

  // Copy transcript to clipboard
  const handleCopyTranscript = useCallback(async () => {
    // CHANGE: Fetch ALL transcripts from database, not from pagination state
    console.log(' Fetching all transcripts for copying...');
    const allTranscripts = await fetchAllTranscripts(meeting.id);

    if (!allTranscripts.length) {
      const error_msg = '복사할 전사 내용이 없습니다';
      console.log(error_msg);
      toast.error(error_msg);
      return;
    }

    console.log(` Copying ${allTranscripts.length} transcripts to clipboard`);

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

    const header = `# 회의 전사: ${meeting.id} - ${meetingTitle ?? meeting.title}\n\n`;
    const date = `## 날짜: ${new Date(meeting.created_at).toLocaleDateString('ko-KR')}\n\n`;
    const fullTranscript = allTranscripts
      .map(t => `${formatTime(t.audio_start_time, t.timestamp)} ${t.text}  `)
      .join('\n');

    await copyToClipboard(header + date + fullTranscript);
    toast.success("전사 내용을 클립보드에 복사했습니다");

    // Track copy analytics
    const wordCount = allTranscripts
      .map(t => t.text.split(/\s+/).length)
      .reduce((a, b) => a + b, 0);

    await Analytics.trackCopy('transcript', {
      meeting_id: meeting.id,
      transcript_length: allTranscripts.length.toString(),
      word_count: wordCount.toString()
    });
  }, [meeting, meetingTitle, fetchAllTranscripts]);

  // Build the summary markdown (with metadata header) from the current editor / summary state.
  // Returns an empty string if no summary content is available.
  const getSummaryMarkdown = useCallback(async (): Promise<string> => {
    let summaryMarkdown = '';

    if (blockNoteSummaryRef.current?.getMarkdown) {
      summaryMarkdown = await blockNoteSummaryRef.current.getMarkdown();
    }

    if (!summaryMarkdown && aiSummary && 'markdown' in aiSummary) {
      summaryMarkdown = (aiSummary as any).markdown || '';
    }

    if (!summaryMarkdown && aiSummary) {
      const sections = Object.entries(aiSummary)
        .filter(([key]) => {
          return key !== 'markdown' && key !== 'summary_json' && key !== '_section_order' && key !== 'MeetingName';
        })
        .map(([, section]) => {
          if (section && typeof section === 'object' && 'title' in section && 'blocks' in section) {
            const sectionTitle = `## ${section.title}\n\n`;
            const sectionContent = section.blocks
              .map((block: any) => `- ${block.content}`)
              .join('\n');
            return sectionTitle + sectionContent;
          }
          return '';
        })
        .filter(s => s.trim())
        .join('\n\n');
      summaryMarkdown = sections;
    }

    if (!summaryMarkdown.trim()) return '';

    const header = `# 회의 요약: ${meetingTitle}\n\n`;
    const metadata = `**회의 ID:** ${meeting.id}\n**날짜:** ${new Date(meeting.created_at).toLocaleDateString('ko-KR', {
      year: 'numeric',
      month: 'long',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    })}\n\n---\n\n`;

    return header + metadata + summaryMarkdown;
  }, [aiSummary, meetingTitle, meeting, blockNoteSummaryRef]);

  // Copy summary to clipboard
  const handleCopySummary = useCallback(async () => {
    try {
      const fullMarkdown = await getSummaryMarkdown();

      if (!fullMarkdown) {
        toast.error('복사할 요약 내용이 없습니다');
        return;
      }

      await copyToClipboard(fullMarkdown);
      toast.success("요약을 클립보드에 복사했습니다");

      await Analytics.trackCopy('summary', {
        meeting_id: meeting.id,
        has_markdown: (!!aiSummary && 'markdown' in aiSummary).toString()
      });
    } catch (error) {
      console.error('Failed to copy summary:', error);
      toast.error("요약 복사에 실패했습니다");
    }
  }, [aiSummary, meeting, getSummaryMarkdown]);

  return {
    handleCopyTranscript,
    handleCopySummary,
    getSummaryMarkdown,
  };
}
