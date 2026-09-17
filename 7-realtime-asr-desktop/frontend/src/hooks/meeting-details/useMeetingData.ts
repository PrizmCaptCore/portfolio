import { useState, useCallback, useRef, useEffect } from 'react';
import { Transcript, Summary } from '@/types';
import { BlockNoteSummaryViewRef } from '@/components/AISummary/BlockNoteSummaryView';
import { CurrentMeeting, useSidebar } from '@/components/Sidebar/SidebarProvider';
import { invoke as invokeTauri } from '@tauri-apps/api/core';
import { toast } from 'sonner';

interface UseMeetingDataProps {
  meeting: any;
  summaryData: Summary | null;
  onMeetingUpdated?: () => Promise<void>;
}

export function useMeetingData({ meeting, summaryData, onMeetingUpdated }: UseMeetingDataProps) {
  // State
  // Use prop directly since summary generation fetches transcripts independently
  const transcripts = meeting.transcripts;
  const [meetingTitle, setMeetingTitle] = useState(meeting.title || '+ 새 회의');
  const [isEditingTitle, setIsEditingTitle] = useState(false);
  const [isTitleDirty, setIsTitleDirty] = useState(false);
  const [aiSummary, setAiSummary] = useState<Summary | null>(summaryData);
  const [isSaving, setIsSaving] = useState(false);
  // Keep the dirty flag as actual state — earlier this was a write-only
  // setter (`const [, setIsSummaryDirty]`), which meant dirty transitions
  // never triggered a re-render of the parent so the save button's green
  // tint and the BlockNote-vs-fallback save branch couldn't both rely on
  // it. We now lift it up so SummaryPanel reads it from props and the save
  // path can reset it after a successful write.
  const [isSummaryDirty, setIsSummaryDirty] = useState(false);
  const [, setError] = useState<string>('');

  // Ref for BlockNoteSummaryView
  const blockNoteSummaryRef = useRef<BlockNoteSummaryViewRef>(null);

  // Sidebar context
  const { setCurrentMeeting, setMeetings, meetings: sidebarMeetings } = useSidebar();

  // Sync aiSummary state when summaryData prop changes (fixes display of fetched summaries)
  useEffect(() => {
    console.log('[useMeetingData] Syncing summary data from prop:', summaryData ? 'present' : 'null');
    setAiSummary(summaryData);
  }, [summaryData]); // Only trigger when parent prop changes, not when aiSummary changes

  // Handlers
  const handleTitleChange = useCallback((newTitle: string) => {
    setMeetingTitle(newTitle);
    setIsTitleDirty(true);
  }, []);

  const handleSummaryChange = useCallback((newSummary: Summary) => {
    setAiSummary(newSummary);
    // Legacy AISummary's onSummaryChange used to leave the dirty flag
    // untouched, so the save button never lit up after an edit and users
    // would assume their changes weren't being captured. Mark dirty here
    // so both visual cue and the post-save reset stay coherent across
    // legacy and BlockNote formats.
    setIsSummaryDirty(true);
  }, []);

  const handleSaveMeetingTitle = useCallback(async () => {
    try {
      await invokeTauri('api_save_meeting_title', {
        meetingId: meeting.id,
        title: meetingTitle,
      });

      console.log('Save meeting title success');
      setIsTitleDirty(false);

      // Update meetings with new title
      const updatedMeetings = sidebarMeetings.map((m: CurrentMeeting) =>
        m.id === meeting.id ? { id: m.id, title: meetingTitle } : m
      );
      setMeetings(updatedMeetings);
      setCurrentMeeting({ id: meeting.id, title: meetingTitle });
      return true;
    } catch (error) {
      console.error('Failed to save meeting title:', error);
      if (error instanceof Error) {
        setError(error.message);
      } else {
        setError('회의 제목 저장에 실패했습니다: 알 수 없는 오류');
      }
      return false;
    }
  }, [meeting.id, meetingTitle, sidebarMeetings, setMeetings, setCurrentMeeting]);

  const handleSaveSummary = useCallback(async (summary: Summary | { markdown?: string; summary_json?: any[] }) => {
    console.log(' handleSaveSummary called with:', {
      hasMarkdown: 'markdown' in summary,
      hasSummaryJson: 'summary_json' in summary,
      summaryKeys: Object.keys(summary)
    });

    try {
      let formattedSummary: any;

      // Check if it's the new BlockNote format
      if ('markdown' in summary || 'summary_json' in summary) {
        console.log(' Saving new format (markdown/blocknote)');
        formattedSummary = summary;
      } else {
        console.log(' Saving legacy format');
        formattedSummary = {
          MeetingName: meetingTitle,
          MeetingNotes: {
            sections: Object.entries(summary).map(([, section]) => ({
              title: section.title,
              blocks: section.blocks
            }))
          }
        };
      }

      await invokeTauri('api_save_meeting_summary', {
        meetingId: meeting.id,
        summary: formattedSummary,
      });

      console.log(' Save meeting summary success');
    } catch (error) {
      console.error(' Failed to save meeting summary:', error);
      if (error instanceof Error) {
        setError(error.message);
      } else {
        setError('회의 요약 저장에 실패했습니다: 알 수 없는 오류');
      }
    }
  }, [meeting.id, meetingTitle]);

  const saveAllChanges = useCallback(async () => {
    setIsSaving(true);
    try {
      // Save meeting title only if changed
      if (isTitleDirty) {
        await handleSaveMeetingTitle();
      }

      // Save BlockNote editor changes if dirty (BlockNote tracks its own
      // dirty internally and resets it after handleSave completes); legacy
      // edits flow through aiSummary and rely on `isSummaryDirty` for the
      // post-save reset below.
      if (blockNoteSummaryRef.current?.isDirty) {
        console.log(' Saving BlockNote editor changes...');
        await blockNoteSummaryRef.current.saveSummary();
        setIsSummaryDirty(false);
      } else if (isSummaryDirty && aiSummary) {
        await handleSaveSummary(aiSummary);
        setIsSummaryDirty(false);
      }

      toast.success("변경 사항을 저장했습니다");
    } catch (error) {
      console.error('Failed to save changes:', error);
      toast.error("변경 사항 저장에 실패했습니다", { description: String(error) });
    } finally {
      setIsSaving(false);
    }
  }, [isTitleDirty, handleSaveMeetingTitle, aiSummary, handleSaveSummary, isSummaryDirty]);

  // Update meeting title from external source (e.g., AI summary)
  const updateMeetingTitle = useCallback((newTitle: string) => {
    console.log(' Updating meeting title to:', newTitle);
    setMeetingTitle(newTitle);
    const updatedMeetings = sidebarMeetings.map((m: CurrentMeeting) =>
      m.id === meeting.id ? { id: m.id, title: newTitle } : m
    );
    setMeetings(updatedMeetings);
    setCurrentMeeting({ id: meeting.id, title: newTitle });
  }, [meeting.id, sidebarMeetings, setMeetings, setCurrentMeeting]);

  return {
    // State
    transcripts,
    meetingTitle,
    isEditingTitle,
    isTitleDirty,
    aiSummary,
    isSaving,
    isSummaryDirty,
    blockNoteSummaryRef,

    // Setters
    setMeetingTitle,
    setIsEditingTitle,
    setAiSummary,
    setIsSummaryDirty,

    // Handlers
    handleTitleChange,
    handleSummaryChange,
    handleSaveSummary,
    handleSaveMeetingTitle,
    saveAllChanges,
    updateMeetingTitle,
  };
}
