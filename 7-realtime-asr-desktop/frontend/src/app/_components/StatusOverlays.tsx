interface StatusOverlaysProps {
  // Status flags
  isStarting: boolean;        // Initializing recording before it starts
  isProcessing: boolean;      // Processing transcription after recording stops
  isSaving: boolean;          // Saving transcript to database

  // Layout
  sidebarCollapsed: boolean;  // For responsive margin calculation
}

// Internal reusable component for individual status overlays
interface StatusOverlayProps {
  show: boolean;
  message: string;
  sidebarCollapsed: boolean;
}

function StatusOverlay({ show, message, sidebarCollapsed }: StatusOverlayProps) {
  if (!show) return null;

  return (
    <div className="fixed bottom-4 left-0 right-[var(--docked-ai-rail-width,0px)] z-10">
      <div
        className="flex justify-center pl-8 transition-[margin] duration-300"
        style={{
          marginLeft: sidebarCollapsed ? '4rem' : '16rem'
        }}
      >
        <div className="w-2/3 max-w-[750px] flex justify-center">
          <div className="bg-white rounded-lg shadow-lg px-4 py-2 flex items-center space-x-2">
            <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-gray-900"></div>
            <span className="text-sm text-gray-700">{message}</span>
          </div>
        </div>
      </div>
    </div>
  );
}

// Main exported component - renders multiple status overlays
export function StatusOverlays({
  isStarting,
  isProcessing,
  isSaving,
  sidebarCollapsed
}: StatusOverlaysProps) {
  return (
    <>
      {/* Start status overlay - shown while preparing recorder startup */}
      <StatusOverlay
        show={isStarting}
        message="녹음을 준비하는 중…"
        sidebarCollapsed={sidebarCollapsed}
      />

      {/* Processing status overlay - shown after recording stops while finalizing transcription */}
      <StatusOverlay
        show={isProcessing}
        message="전사를 마무리하는 중…"
        sidebarCollapsed={sidebarCollapsed}
      />

      {/* Saving status overlay - shown while saving transcript to database */}
      <StatusOverlay
        show={isSaving}
        message="전사를 저장하는 중…"
        sidebarCollapsed={sidebarCollapsed}
      />
    </>
  );
}
