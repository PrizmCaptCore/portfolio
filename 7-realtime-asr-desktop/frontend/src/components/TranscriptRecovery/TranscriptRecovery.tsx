/**
 * TranscriptRecovery Component
 *
 * Modal dialog for recovering interrupted meetings from IndexedDB.
 * Displays recoverable meetings, allows preview, and enables recovery or deletion.
 */

import React, { useState, useEffect } from 'react';
import { formatDistanceToNow } from 'date-fns';
import { AlertCircle, CheckCircle2, Clock, FileText, Trash2, XCircle, AlertTriangle } from 'lucide-react';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { MeetingMetadata, StoredTranscript } from '@/services/indexedDBService';
import { cn } from '@/lib/utils';

interface TranscriptRecoveryProps {
  isOpen: boolean;
  onClose: () => void;
  recoverableMeetings: MeetingMetadata[];
  onRecover: (meetingId: string) => Promise<any>;
  onDelete: (meetingId: string) => Promise<void>;
  onLoadPreview: (meetingId: string) => Promise<StoredTranscript[]>;
}

export function TranscriptRecovery({
  isOpen,
  onClose,
  recoverableMeetings,
  onRecover,
  onDelete,
  onLoadPreview,
}: TranscriptRecoveryProps) {
  const [selectedMeetingId, setSelectedMeetingId] = useState<string | null>(null);
  const [previewTranscripts, setPreviewTranscripts] = useState<StoredTranscript[]>([]);
  const [isLoadingPreview, setIsLoadingPreview] = useState(false);
  const [isRecovering, setIsRecovering] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [recoverError, setRecoverError] = useState<string | null>(null);
  const [confirmingDelete, setConfirmingDelete] = useState(false);

  // Reset selection when dialog opens
  useEffect(() => {
    if (isOpen) {
      setSelectedMeetingId(null);
      setPreviewTranscripts([]);
      setRecoverError(null);
      setConfirmingDelete(false);
    }
  }, [isOpen]);

  // Auto-select first meeting if available
  useEffect(() => {
    if (isOpen && recoverableMeetings.length > 0 && !selectedMeetingId) {
      handleMeetingSelect(recoverableMeetings[0].meetingId);
    }
  }, [isOpen, recoverableMeetings]);

  const handleMeetingSelect = async (meetingId: string) => {
    setSelectedMeetingId(meetingId);
    setIsLoadingPreview(true);

    try {
      const transcripts = await onLoadPreview(meetingId);
      // Limit to first 10 for preview
      setPreviewTranscripts(transcripts.slice(0, 10));
    } catch (error) {
      console.error('Failed to load preview:', error);
      setPreviewTranscripts([]);
    } finally {
      setIsLoadingPreview(false);
    }
  };

  const handleRecover = async () => {
    if (!selectedMeetingId) return;

    setIsRecovering(true);
    setRecoverError(null);
    try {
      const result = await onRecover(selectedMeetingId);
      console.log('Recovery successful:', result);
      onClose();
    } catch (error) {
      console.error('Recovery failed:', error);
      const msg = error instanceof Error
        ? error.message
        : typeof error === 'string'
          ? error
          : JSON.stringify(error);
      setRecoverError(msg);
    } finally {
      setIsRecovering(false);
    }
  };

  const handleDeleteConfirm = async () => {
    if (!selectedMeetingId) return;

    setIsDeleting(true);
    setConfirmingDelete(false);
    try {
      await onDelete(selectedMeetingId);
      setSelectedMeetingId(null);
      setPreviewTranscripts([]);
      setRecoverError(null);
    } catch (error) {
      console.error('Delete failed:', error);
      const msg = error instanceof Error
        ? error.message
        : typeof error === 'string'
          ? error
          : '회의 삭제에 실패했습니다';
      setRecoverError(msg);
    } finally {
      setIsDeleting(false);
    }
  };

  const selectedMeeting = recoverableMeetings.find(m => m.meetingId === selectedMeetingId);

  return (
    <Dialog open={isOpen} onOpenChange={onClose}>
      <DialogContent className="max-w-4xl h-[80vh] flex flex-col p-0">
        <DialogHeader className="px-6 pt-6">
          <DialogTitle className="text-2xl">중단된 회의 복구</DialogTitle>
          <DialogDescription>
            중단된 회의 {recoverableMeetings.length}개를 발견했습니다. 회의를 선택하면 미리 보고 복구할 수 있습니다.
          </DialogDescription>
        </DialogHeader>

        <div className="flex-1 flex gap-4 px-6 pb-6 overflow-hidden">
          {/* Meeting List */}
          <div className="w-1/3 flex flex-col">
            <h3 className="text-sm font-medium mb-2">중단된 회의</h3>
            <ScrollArea className="flex-1 border rounded-lg">
              <div className="p-2 space-y-2">
                {recoverableMeetings.map((meeting) => (
                  <button
                    key={meeting.meetingId}
                    onClick={() => handleMeetingSelect(meeting.meetingId)}
                    className={cn(
                      'w-full text-left p-3 rounded-lg border transition-colors',
                      selectedMeetingId === meeting.meetingId
                        ? 'bg-primary/10 border-primary'
                        : 'hover:bg-muted border-transparent'
                    )}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex-1 min-w-0">
                        <p className="font-medium text-sm truncate">{meeting.title}</p>
                        <p className="text-xs text-muted-foreground flex items-center gap-1 mt-1">
                          <Clock className="w-3 h-3" />
                          {formatDistanceToNow(new Date(meeting.lastUpdated), { addSuffix: true })}
                        </p>
                        <p className="text-xs text-muted-foreground flex items-center gap-1 mt-1">
                          <FileText className="w-3 h-3" />
                          전사 {meeting.transcriptCount}개
                        </p>
                      </div>
                      {meeting.folderPath ? (
                        <span title="오디오 사용 가능">
                          <CheckCircle2 className="w-4 h-4 text-green-500 flex-shrink-0" />
                        </span>
                      ) : (
                        <span title="오디오 없음">
                          <AlertCircle className="w-4 h-4 text-yellow-500 flex-shrink-0" />
                        </span>
                      )}
                    </div>
                  </button>
                ))}
              </div>
            </ScrollArea>
          </div>

          {/* Preview Panel */}
          <div className="flex-1 flex flex-col">
            <h3 className="text-sm font-medium mb-2">미리 보기</h3>
            <div className="flex-1 border rounded-lg overflow-hidden flex flex-col">
              {selectedMeeting ? (
                <>
                  {/* Meeting Info */}
                  <div className="p-4 border-b bg-muted/50">
                    <h4 className="font-semibold">{selectedMeeting.title}</h4>
                    <p className="text-sm text-muted-foreground mt-1">
                      시작 {new Date(selectedMeeting.startTime).toLocaleString('ko-KR')}
                    </p>
                    <div className="flex items-center gap-4 mt-2 text-sm">
                      <span className="flex items-center gap-1">
                        <FileText className="w-4 h-4" />
                        전사 {selectedMeeting.transcriptCount}개
                      </span>
                      {selectedMeeting.folderPath ? (
                        <span className="flex items-center gap-1 text-green-600">
                          <CheckCircle2 className="w-4 h-4" />
                          오디오 사용 가능
                        </span>
                      ) : (
                        <span className="flex items-center gap-1 text-yellow-600">
                          <AlertCircle className="w-4 h-4" />
                          오디오 없음
                        </span>
                      )}
                    </div>
                  </div>

                  {/* Transcript Preview */}
                  <ScrollArea className="flex-1 p-4">
                    {isLoadingPreview ? (
                      <div className="flex items-center justify-center h-full text-muted-foreground">
                        미리 보기를 불러오는 중…
                      </div>
                    ) : previewTranscripts.length > 0 ? (
                      <div className="space-y-3">
                        <Alert>
                          <AlertDescription>
                            전사 세그먼트 처음 {previewTranscripts.length}개 표시 중 (총 {selectedMeeting.transcriptCount}개)
                          </AlertDescription>
                        </Alert>
                        {previewTranscripts.map((transcript, index) => {
                          // Handle different timestamp formats
                          const getTimestamp = () => {
                            if (!transcript.timestamp) return '--:--';
                            try {
                              const date = new Date(transcript.timestamp);
                              if (isNaN(date.getTime())) {
                                // If timestamp is invalid, try audio_start_time
                                if (transcript.audio_start_time !== undefined) {
                                  const totalSecs = Math.floor(transcript.audio_start_time);
                                  const mins = Math.floor(totalSecs / 60);
                                  const secs = totalSecs % 60;
                                  return `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
                                }
                                return '--:--';
                              }
                              return date.toLocaleTimeString();
                            } catch {
                              return '--:--';
                            }
                          };

                          return (
                            <div key={index} className="text-sm">
                              <span className="text-muted-foreground">[{getTimestamp()}]</span>{' '}
                              <span>{transcript.text}</span>
                            </div>
                          );
                        })}
                        {selectedMeeting.transcriptCount > 10 && (
                          <p className="text-sm text-muted-foreground italic">
                            … 그리고 전사 {selectedMeeting.transcriptCount - 10}개 더
                          </p>
                        )}
                      </div>
                    ) : (
                      <div className="flex items-center justify-center h-full text-muted-foreground">
                        미리 볼 전사가 없습니다
                      </div>
                    )}
                  </ScrollArea>
                </>
              ) : (
                <div className="flex items-center justify-center h-full text-muted-foreground">
                  미리 볼 회의를 선택하세요
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Error message above footer */}
        {recoverError && (
          <div className="px-6 pb-2">
            <Alert variant="destructive" className="py-2">
              <AlertTriangle className="w-4 h-4" />
              <AlertDescription className="text-xs break-all">{recoverError}</AlertDescription>
            </Alert>
          </div>
        )}

        <DialogFooter className="px-6 pb-6 gap-2">
          <Button
            variant="outline"
            onClick={onClose}
            disabled={isRecovering || isDeleting}
          >
            취소
          </Button>

          {/* Two-step delete: first click shows confirm, second click executes */}
          {confirmingDelete ? (
            <>
              <Button
                variant="outline"
                onClick={() => setConfirmingDelete(false)}
                disabled={isDeleting}
              >
                삭제 취소
              </Button>
              <Button
                variant="destructive"
                onClick={handleDeleteConfirm}
                disabled={isDeleting}
              >
                {isDeleting ? (
                  <><XCircle className="w-4 h-4 mr-2 animate-spin" />삭제 중…</>
                ) : (
                  <><Trash2 className="w-4 h-4 mr-2" />삭제 확인</>
                )}
              </Button>
            </>
          ) : (
            <Button
              variant="destructive"
              onClick={() => { setConfirmingDelete(true); setRecoverError(null); }}
              disabled={!selectedMeetingId || isRecovering || isDeleting}
            >
              <Trash2 className="w-4 h-4 mr-2" />
              삭제
            </Button>
          )}

          <Button
            onClick={handleRecover}
            disabled={!selectedMeetingId || isRecovering || isDeleting || confirmingDelete}
          >
            {isRecovering ? (
              <>
                <CheckCircle2 className="w-4 h-4 mr-2 animate-spin" />
                복구 중…
              </>
            ) : (
              <>
                <CheckCircle2 className="w-4 h-4 mr-2" />
                복구
              </>
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
