"use client";

import { Button } from '@/components/ui/button';
import { ButtonGroup } from '@/components/ui/button-group';
import { Columns2, Copy, FolderOpen, Rows2 } from 'lucide-react';
import Analytics from '@/lib/analytics';


interface TranscriptButtonGroupProps {
  transcriptCount: number;
  onCopyTranscript: () => void;
  onOpenMeetingFolder: () => Promise<void>;
  meetingId?: string;
  meetingFolderPath?: string | null;
  onRefetchTranscripts?: () => Promise<void>;
  layoutMode?: 'inline' | 'split';
  onToggleLayoutMode?: () => void;
}


export function TranscriptButtonGroup({
  transcriptCount,
  onCopyTranscript,
  onOpenMeetingFolder,
  layoutMode,
  onToggleLayoutMode,
}: TranscriptButtonGroupProps) {
  return (
    <div className="flex items-center justify-center w-full gap-2">
      <ButtonGroup>
        <Button
          variant="outline"
          size="sm"
          onClick={() => {
            Analytics.trackButtonClick('copy_transcript', 'meeting_details');
            onCopyTranscript();
          }}
          disabled={transcriptCount === 0}
          title={transcriptCount === 0 ? '전사 내용 없음' : '전사 복사'}
        >
          <Copy />
          <span className="hidden lg:inline">복사</span>
        </Button>

        <Button
          size="sm"
          variant="outline"
          className="xl:px-4"
          onClick={() => {
            Analytics.trackButtonClick('open_recording_folder', 'meeting_details');
            onOpenMeetingFolder();
          }}
          title="녹음 폴더 열기"
        >
          <FolderOpen className="xl:mr-2" size={18} />
          <span className="hidden lg:inline">녹음 파일</span>
        </Button>

        {onToggleLayoutMode && (
          <Button
            size="sm"
            variant="outline"
            onClick={() => {
              Analytics.trackButtonClick(
                layoutMode === 'split' ? 'transcript_layout_inline' : 'transcript_layout_split',
                'meeting_details',
              );
              onToggleLayoutMode();
            }}
            title={
              layoutMode === 'split'
                ? '번역을 transcript 아래에 표시'
                : '번역을 transcript와 나란히 표시'
            }
          >
            {layoutMode === 'split' ? <Rows2 size={18} /> : <Columns2 size={18} />}
            <span className="hidden lg:inline">
              {layoutMode === 'split' ? '쌓기' : '나누기'}
            </span>
          </Button>
        )}
      </ButtonGroup>
    </div>
  );
}
