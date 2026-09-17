'use client'

import './globals.css'
import { Source_Sans_3 } from 'next/font/google'
import Sidebar from '@/components/Sidebar'
import { SidebarProvider } from '@/components/Sidebar/SidebarProvider'
import MainContent from '@/components/MainContent'
import AnalyticsProvider from '@/components/AnalyticsProvider'
import { Toaster, toast } from 'sonner'
import "sonner/dist/styles.css"
import { useState, useEffect, useCallback } from 'react'
import { usePathname } from 'next/navigation'
import { listen, UnlistenFn } from '@tauri-apps/api/event'
import { invoke } from '@tauri-apps/api/core'
import {
  isPermissionGranted,
  requestPermission,
  sendNotification,
} from '@tauri-apps/plugin-notification'
import { WebviewWindow } from '@tauri-apps/api/webviewWindow'
import { getCurrentWindow, primaryMonitor } from '@tauri-apps/api/window'
import { TooltipProvider } from '@/components/ui/tooltip'
import { RecordingStateProvider } from '@/contexts/RecordingStateContext'
import { TranscriptProvider } from '@/contexts/TranscriptContext'
import { ConfigProvider, useConfig } from '@/contexts/ConfigContext'
import { OnboardingProvider } from '@/contexts/OnboardingContext'
import { OnboardingFlow } from '@/components/onboarding'
import { AuthProvider, useAuth } from '@/contexts/AuthContext'
import { LoginPage } from '@/components/auth/LoginPage'
import { PaywallPage } from '@/components/auth/PaywallPage'
import { loadBetaFeatures } from '@/types/betaFeatures'
import { DownloadProgressToastProvider } from '@/components/shared/DownloadProgressToast'
import { UpdateCheckProvider } from '@/components/UpdateCheckProvider'
import { RecordingPostProcessingProvider } from '@/contexts/RecordingPostProcessingProvider'
import { ImportAudioDialog, ImportDropOverlay } from '@/components/ImportAudio'
import { ImportDialogProvider } from '@/contexts/ImportDialogContext'
import { isAudioExtension, getAudioFormatsDisplayList } from '@/constants/audioFormats'
import { LiveTranscriptTranslation } from '@/components/LiveTranscriptTranslation'


const sourceSans3 = Source_Sans_3({
  subsets: ['latin'],
  weight: ['400', '500', '600', '700'],
  variable: '--font-source-sans-3',
})

// Module-level component — stable reference across RootLayout re-renders.
// Defined here (not inside RootLayout) so React never sees a new function type
// on re-render, which would cause unmount/remount and break initialization logic.
function ConditionalImportDialog({
  showImportDialog,
  handleImportDialogClose,
  importFilePath,
}: {
  showImportDialog: boolean;
  handleImportDialogClose: (open: boolean) => void;
  importFilePath: string | null;
}) {
  const { betaFeatures } = useConfig();

  // Only mount ImportAudioDialog (and its hooks/listeners) when feature is enabled
  if (!betaFeatures.importAndRetranscribe) {
    return null;
  }

  return (
    <ImportAudioDialog
      open={showImportDialog}
      onOpenChange={handleImportDialogClose}
      preselectedFile={importFilePath}
    />
  );
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  // The floating "meeting detected" alert window mounts this same root
  // layout (Next.js App Router has a single root layout). For that route we
  // skip every provider, sidebar, and global listener so the popup window
  // stays cheap and side-effect free.
  const pathname = usePathname()
  const isAlertWindow = pathname === '/meeting-alert'

  return (
    <html
      lang="en"
      style={isAlertWindow ? { background: 'transparent' } : undefined}
    >
      <body
        className={`${sourceSans3.variable} font-sans antialiased`}
        style={isAlertWindow ? { background: 'transparent' } : undefined}
      >
        {isAlertWindow ? children : <MainAppShell>{children}</MainAppShell>}
      </body>
    </html>
  )
}

function MainAppShell({ children }: { children: React.ReactNode }) {
  return (
    <AuthProvider>
      <AuthenticatedShell>{children}</AuthenticatedShell>
    </AuthProvider>
  )
}

function AuthenticatedShell({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, isLoading: isAuthLoading, isBillingLoading, isPaid } = useAuth()
  const [showOnboarding, setShowOnboarding] = useState(false)
  const [onboardingCompleted, setOnboardingCompleted] = useState(false)

  // Import audio state
  const [showDropOverlay, setShowDropOverlay] = useState(false)
  const [showImportDialog, setShowImportDialog] = useState(false)
  const [importFilePath, setImportFilePath] = useState<string | null>(null)

  useEffect(() => {
    if (!isAuthenticated) return
    // Check onboarding status first
    invoke<{ completed: boolean } | null>('get_onboarding_status')
      .then((status) => {
        const isComplete = status?.completed ?? false
        setOnboardingCompleted(isComplete)

        if (!isComplete) {
          console.log('[Layout] Onboarding not completed, showing onboarding flow')
          setShowOnboarding(true)
        } else {
          console.log('[Layout] Onboarding completed, showing main app')
        }
      })
      .catch((error) => {
        console.error('[Layout] Failed to check onboarding status:', error)
        // Default to showing onboarding if we can't check
        setShowOnboarding(true)
        setOnboardingCompleted(false)
      })
  }, [])

  // Disable context menu in production
  useEffect(() => {
    if (process.env.NODE_ENV === 'production') {
      const handleContextMenu = (e: MouseEvent) => e.preventDefault();
      document.addEventListener('contextmenu', handleContextMenu);
      return () => document.removeEventListener('contextmenu', handleContextMenu);
    }
  }, []);
  // Listen for external-meeting detection (a known meeting app started
  // capturing the mic). Fire the alert whenever a new bundle id appears in
  // the active set — not on the simple inactive→active transition, which
  // would miss a meeting that starts while some other meeting app is already
  // active. Also fires an OS notification + floating popover window so the
  // alert surfaces even when other apps cover the screen or focus mode is on.
  //
  // Only the main window subscribes — Tauri events are global and we don't
  // want the floating popover window to react to its own trigger.
  useEffect(() => {
    if (getCurrentWindow().label !== 'main') return;

    let prevBundleIds = new Set<string>();

    const notify = async () => {
      try {
        let granted = await isPermissionGranted();
        if (!granted) {
          granted = (await requestPermission()) === 'granted';
        }
        if (granted) {
          sendNotification({
            title: 'Relay Assistant',
            body: '회의가 감지되었습니다',
          });
        }
      } catch (e) {
        console.warn('[meeting-detector] OS notification failed:', e);
      }
    };

    const showFloatingAlert = async () => {
      try {
        // Reuse a stable label so a second concurrent trigger replaces the
        // previous popup instead of stacking infinite windows.
        const label = 'meeting-alert';
        const existing = await WebviewWindow.getByLabel(label);
        if (existing) {
          try { await existing.close(); } catch {}
        }

        const ALERT_W = 360;
        const ALERT_H = 92;
        const MARGIN = 16;

        // Position in the top-right of the primary monitor. Tauri window
        // options use logical pixels; primaryMonitor returns physical size +
        // scale factor, so divide to get logical coordinates.
        let x = MARGIN;
        let y = MARGIN;
        const monitor = await primaryMonitor();
        if (monitor) {
          const scale = monitor.scaleFactor || 1;
          const logicalW = monitor.size.width / scale;
          x = Math.max(0, logicalW - ALERT_W - MARGIN);
          y = MARGIN;
        }

        new WebviewWindow(label, {
          url: 'meeting-alert',
          title: 'Relay Assistant',
          width: ALERT_W,
          height: ALERT_H,
          x,
          y,
          resizable: false,
          decorations: false,
          transparent: true,
          alwaysOnTop: true,
          skipTaskbar: true,
          focus: false,
          shadow: false,
          visibleOnAllWorkspaces: true,
        });
      } catch (e) {
        console.warn('[meeting-detector] floating alert failed:', e);
      }
    };

    const unlisten = listen<{ active: boolean; bundle_ids: string[] }>(
      'meeting-status-changed',
      (event) => {
        const { bundle_ids } = event.payload;
        const newlyAdded = bundle_ids.filter((id) => !prevBundleIds.has(id));
        if (newlyAdded.length > 0) {
          toast.info('회의가 감지되었습니다', { duration: 6000 });
          notify();
          showFloatingAlert();
        }
        prevBundleIds = new Set(bundle_ids);
      }
    );
    return () => {
      unlisten.then((fn) => fn());
    };
  }, []);

  useEffect(() => {
    // Listen for tray recording toggle request
    const unlisten = listen('request-recording-toggle', () => {
      console.log('[Layout] Received request-recording-toggle from tray');

      if (showOnboarding) {
        toast.error("먼저 초기 설정을 완료해 주세요", {
          description: "온보딩을 마쳐야 녹음을 시작할 수 있습니다."
        });
      } else {
        // If in main app, forward to useRecordingStart via window event
        console.log('[Layout] Forwarding to start-recording-from-sidebar');
        window.dispatchEvent(new CustomEvent('start-recording-from-sidebar'));
      }
    });

    return () => {
      unlisten.then(fn => fn());
    };
  }, [showOnboarding]);

  // Handle file drop for audio import
  const handleFileDrop = useCallback((paths: string[]) => {
    // Check if beta features are enabled (read from localStorage directly since we're outside ConfigProvider)
    const betaFeatures = loadBetaFeatures();

    if (!betaFeatures.importAndRetranscribe) {
      toast.error('베타 기능이 꺼져 있습니다', {
        description: '설정 > 베타에서 "오디오 가져오기 및 재전사"를 활성화하면 사용할 수 있습니다.'
      });
      return;
    }

    // Find the first audio file
    const audioFile = paths.find(p => {
      const ext = p.split('.').pop()?.toLowerCase();
      return !!ext && isAudioExtension(ext);
    });

    if (audioFile) {
      console.log('[Layout] Audio file dropped:', audioFile);
      setImportFilePath(audioFile);
      setShowImportDialog(true);
    } else if (paths.length > 0) {
      toast.error('오디오 파일을 놓아주세요', {
        description: `지원 형식: ${getAudioFormatsDisplayList()}`
      });
    }
  }, []);

  // Listen for drag-drop events
  useEffect(() => {
    if (showOnboarding) return; // Don't handle drops during onboarding

    const unlisteners: UnlistenFn[] = [];
    const cleanedUpRef = { current: false };

    const setupListeners = async () => {
      // Drag enter/over - show overlay only if beta feature is enabled
      const unlistenDragEnter = await listen('tauri://drag-enter', () => {
        if (loadBetaFeatures().importAndRetranscribe) {
          setShowDropOverlay(true);
        }
      });
      if (cleanedUpRef.current) {
        unlistenDragEnter();
        return;
      }
      unlisteners.push(unlistenDragEnter);

      // Drag leave - hide overlay
      const unlistenDragLeave = await listen('tauri://drag-leave', () => {
        setShowDropOverlay(false);
      });
      if (cleanedUpRef.current) {
        unlistenDragLeave();
        unlisteners.forEach(u => u());
        return;
      }
      unlisteners.push(unlistenDragLeave);

      // Drop - process files
      const unlistenDrop = await listen<{ paths: string[] }>('tauri://drag-drop', (event) => {
        setShowDropOverlay(false);
        handleFileDrop(event.payload.paths);
      });
      if (cleanedUpRef.current) {
        unlistenDrop();
        unlisteners.forEach(u => u());
        return;
      }
      unlisteners.push(unlistenDrop);
    };

    setupListeners();

    return () => {
      cleanedUpRef.current = true;
      unlisteners.forEach((unlisten) => unlisten());
    };
  }, [showOnboarding, handleFileDrop]);

  // Handle import dialog close
  const handleImportDialogClose = useCallback((open: boolean) => {
    setShowImportDialog(open);
    if (!open) {
      setImportFilePath(null);
    }
  }, []);

  // Handler for ImportDialogProvider - opens import dialog from any child component
  const handleOpenImportDialog = useCallback((filePath?: string | null) => {
    setImportFilePath(filePath ?? null);
    setShowImportDialog(true);
  }, []);

  const handleOnboardingComplete = () => {
    console.log('[Layout] Onboarding completed, reloading app')
    setShowOnboarding(false)
    setOnboardingCompleted(true)
    // Optionally reload the window to ensure all state is fresh
    window.location.reload()
  }

  return (
    <>
      <AnalyticsProvider>
        <RecordingStateProvider>
          <TranscriptProvider>
            <ConfigProvider>
              <LiveTranscriptTranslation />
              <OnboardingProvider>
                <UpdateCheckProvider>
                  <SidebarProvider>
                    <TooltipProvider>
                      <RecordingPostProcessingProvider>
                        <ImportDialogProvider onOpen={handleOpenImportDialog}>
                          {/* Download progress toast provider - listens for background downloads */}
                          <DownloadProgressToastProvider />

                          {/* Auth → Billing → Onboarding → Main app */}
                          {isAuthLoading || isBillingLoading ? null : !isAuthenticated ? (
                            <LoginPage />
                          ) : !isPaid ? (
                            <PaywallPage />
                          ) : showOnboarding ? (
                            <OnboardingFlow onComplete={handleOnboardingComplete} />
                          ) : (
                            <div className="flex h-dvh min-h-0 w-full overflow-hidden">
                              <Sidebar />
                              <MainContent>{children}</MainContent>
                            </div>
                          )}
                          {/* Import audio overlay and dialog */}
                          <ImportDropOverlay visible={showDropOverlay} />
                          <ConditionalImportDialog
                            showImportDialog={showImportDialog}
                            handleImportDialogClose={handleImportDialogClose}
                            importFilePath={importFilePath}
                          />
                        </ImportDialogProvider>
                      </RecordingPostProcessingProvider>
                    </TooltipProvider>
                  </SidebarProvider>
                </UpdateCheckProvider>
              </OnboardingProvider>
            </ConfigProvider>
          </TranscriptProvider>
        </RecordingStateProvider>
      </AnalyticsProvider>

      <Toaster position="bottom-center" richColors closeButton />
    </>
  )
}
