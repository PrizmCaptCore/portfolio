import React, { useState, useEffect } from 'react';
import { Download, X, CheckCircle2, AlertCircle, Loader2 } from 'lucide-react';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from './ui/dialog';
import { Button } from './ui/button';
import { updateService, UpdateInfo, UpdateProgress } from '@/services/updateService';
import { toast } from 'sonner';

interface UpdateDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  updateInfo: UpdateInfo | null;
}

export function UpdateDialog({ open, onOpenChange, updateInfo }: UpdateDialogProps) {
  const [isDownloading, setIsDownloading] = useState(false);
  const [progress, setProgress] = useState<UpdateProgress | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open && updateInfo?.available) {
      // Reset state when dialog opens
      setIsDownloading(false);
      setProgress(null);
      setError(null);
    } else {
      // Reset state when dialog closes
      setIsDownloading(false);
      setProgress(null);
      setError(null);
    }
  }, [open, updateInfo]);

  const handleDownloadAndInstall = async () => {
    setIsDownloading(true);
    setError(null);
    setProgress({ downloaded: 0, total: 0, percentage: 0 });
    try {
      await updateService.downloadAndInstall((p) => setProgress(p));
      // updateService calls relaunch() on success, so control usually
      // doesn't return here. If it does, treat it as a successful queue.
    } catch (e) {
      setIsDownloading(false);
      const message =
        e instanceof Error ? e.message : '업데이트 설치에 실패했습니다';
      setError(message);
      toast.error('업데이트 설치 실패');
    }
  };

  const formatDate = (dateString?: string) => {
    if (!dateString) return '';
    try {
      return new Date(dateString).toLocaleDateString();
    } catch {
      return dateString;
    }
  };

  // Prevent closing the dialog when downloading
  const handleOpenChange = (newOpen: boolean) => {
    // If trying to close while downloading, prevent it
    if (!newOpen && isDownloading) {
      return;
    }
    // Otherwise, allow normal close behavior
    onOpenChange(newOpen);
  };

  // Prevent ESC key from closing dialog during download
  const handleEscapeKeyDown = (event: KeyboardEvent) => {
    if (isDownloading) {
      event.preventDefault();
    }
  };

  // Prevent outside clicks from closing dialog during download
  const handleInteractOutside = (event: Event) => {
    if (isDownloading) {
      event.preventDefault();
    }
  };

  if (!updateInfo?.available) {
    return null;
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent
        className="sm:max-w-[500px]"
        onEscapeKeyDown={handleEscapeKeyDown}
        onInteractOutside={handleInteractOutside}
      >
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            {isDownloading ? (
              <>
                <Loader2 className="h-5 w-5 animate-spin text-blue-600" />
                업데이트 다운로드 중
              </>
            ) : error ? (
              <>
                <AlertCircle className="h-5 w-5 text-red-600" />
                업데이트 오류
              </>
            ) : (
              <>
                <Download className="h-5 w-5 text-blue-600" />
                업데이트 사용 가능
              </>
            )}
          </DialogTitle>
          <DialogDescription>
            {isDownloading
              ? '최신 버전을 다운로드하는 중입니다…'
              : error
              ? '업데이트 중 오류가 발생했습니다'
              : `새 버전(${updateInfo.version})이 출시되었습니다`}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-4">
          {!isDownloading && !error && (
            <>
              <div className="space-y-2">
                <div className="flex justify-between text-sm">
                  <span className="text-muted-foreground">현재 버전:</span>
                  <span className="font-medium">{updateInfo.currentVersion}</span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-muted-foreground">새 버전:</span>
                  <span className="font-medium text-blue-600">{updateInfo.version}</span>
                </div>
                {updateInfo.date && (
                  <div className="flex justify-between text-sm">
                    <span className="text-muted-foreground">출시일:</span>
                    <span className="font-medium">{formatDate(updateInfo.date)}</span>
                  </div>
                )}
              </div>

              {updateInfo.body && (
                <div className="bg-gray-50 rounded-lg p-3 max-h-40 overflow-y-auto">
                  <p className="text-sm text-gray-700 whitespace-pre-wrap">
                    {updateInfo.body}
                  </p>
                </div>
              )}
            </>
          )}

          {isDownloading && progress && (
            <div className="space-y-2">
              <div className="relative">
                <div className="w-full bg-gray-200 rounded-full h-3">
                  <div
                    className="bg-blue-600 h-3 rounded-full transition-all duration-300 ease-out"
                    style={{ width: `${Math.min(progress.percentage, 100)}%` }}
                  />
                </div>
                <div className="flex justify-between text-xs text-gray-600 mt-1">
                  <span>{Math.round(progress.percentage)}% 완료</span>
                  {progress.total > 0 && (
                    <span>
                      {formatBytes(progress.downloaded)} / {formatBytes(progress.total)}
                    </span>
                  )}
                </div>
              </div>
              <p className="text-sm text-muted-foreground text-center">
                설치가 완료되면 앱이 자동으로 재시작됩니다
              </p>
            </div>
          )}

          {error && (
            <div className="bg-red-50 border border-red-200 rounded-lg p-3">
              <p className="text-sm text-red-800">{error}</p>
            </div>
          )}
        </div>

        <DialogFooter>
          {!isDownloading && !error && (
            <>
              <Button variant="outline" onClick={() => handleOpenChange(false)}>
                나중에
              </Button>
              <Button onClick={handleDownloadAndInstall} className="bg-blue-600 hover:bg-blue-700">
                <Download className="h-4 w-4 mr-2" />
                다운로드 및 설치
              </Button>
            </>
          )}
          {error && (
            <Button variant="outline" onClick={() => handleOpenChange(false)}>
              닫기
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 Bytes';
  const k = 1024;
  const sizes = ['Bytes', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i];
}
