"use client";

import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { ButtonGroup } from '@/components/ui/button-group';
import { Copy, Save, Loader2, Search, FolderOpen, Sparkles } from 'lucide-react';
import Analytics from '@/lib/analytics';
import { ShareMenu } from '@/components/Integrations/ShareMenu';
import { ComposeFollowUpDialog } from './ComposeFollowUpDialog';
import { BackupMeetingButton } from './BackupMeetingButton';
import type { Summary, Transcript } from '@/types';

interface SummaryUpdaterButtonGroupProps {
  isSaving: boolean;
  isDirty: boolean;
  onSave: () => Promise<void>;
  onCopy: () => Promise<void>;
  onFind?: () => void;
  onOpenFolder: () => Promise<void>;
  hasSummary: boolean;
  getSummaryMarkdown?: () => Promise<string>;
  meetingTitle?: string;
  meeting: {
    id: string;
    title: string;
    created_at: string;
  };
  transcripts: Transcript[];
  summary: Summary | null;
}

export function SummaryUpdaterButtonGroup({
  isSaving,
  isDirty,
  onSave,
  onCopy,
  onFind,
  onOpenFolder,
  hasSummary,
  getSummaryMarkdown,
  meetingTitle,
  meeting,
  transcripts,
  summary,
}: SummaryUpdaterButtonGroupProps) {
  const [followUpOpen, setFollowUpOpen] = useState(false);

  return (
    <ButtonGroup>
      {/* Save button */}
      <Button
        variant="outline"
        size="sm"
        className={`${isDirty ? 'bg-green-200' : ""}`}
        title={isSaving ? "저장 중" : "변경 사항 저장"}
        onClick={() => {
          Analytics.trackButtonClick('save_changes', 'meeting_details');
          onSave();
        }}
        disabled={isSaving}
      >
        {isSaving ? (
          <>
            <Loader2 className="animate-spin" />
            <span className="hidden lg:inline">저장 중…</span>
          </>
        ) : (
          <>
            <Save />
            <span className="hidden lg:inline">저장</span>
          </>
        )}
      </Button>

      {/* Copy button */}
      <Button
        variant="outline"
        size="sm"
        title="요약 복사"
        onClick={() => {
          Analytics.trackButtonClick('copy_summary', 'meeting_details');
          onCopy();
        }}
        disabled={!hasSummary}
        className="cursor-pointer"
      >
        <Copy />
        <span className="hidden lg:inline">복사</span>
      </Button>

      {/* Compose follow-up: opens an LLM-drafted message routed to Slack or email. */}
      {getSummaryMarkdown && (
        <>
          <Button
            variant="outline"
            size="sm"
            title="Follow-up 작성"
            onClick={() => {
              Analytics.trackButtonClick('compose_followup', 'meeting_details');
              setFollowUpOpen(true);
            }}
            disabled={!hasSummary}
          >
            <Sparkles />
            <span className="hidden lg:inline">follow-up 작성</span>
          </Button>
          <ComposeFollowUpDialog
            open={followUpOpen}
            onOpenChange={setFollowUpOpen}
            getSummary={getSummaryMarkdown}
            meetingTitle={meetingTitle}
          />
        </>
      )}

      {/* Share to external app (Slack / Notion / Gmail) */}
      {getSummaryMarkdown && (
        <ShareMenu
          getMarkdown={getSummaryMarkdown}
          defaultTitle={meetingTitle}
          disabled={!hasSummary}
        />
      )}
      <BackupMeetingButton
        meeting={meeting}
        transcripts={transcripts}
        summary={summary}
      />

      {/* Find button */}
      {/* {onFind && (
        <Button
          variant="outline"
          size="sm"
          title="Find in Summary"
          onClick={() => {
            Analytics.trackButtonClick('find_in_summary', 'meeting_details');
            onFind();
          }}
          disabled={!hasSummary}
          className="cursor-pointer"
        >
          <Search />
          <span className="hidden lg:inline">Find</span>
        </Button>
      )} */}
    </ButtonGroup>
  );
}
