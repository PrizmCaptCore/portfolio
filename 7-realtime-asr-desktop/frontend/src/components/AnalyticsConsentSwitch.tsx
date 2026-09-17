import React, { useContext, useState, useEffect } from 'react';
import { Switch } from '@/components/ui/switch';
import { Button } from '@/components/ui/button';
import { Info, Loader2, Copy, Check } from 'lucide-react';
import { AnalyticsContext } from './AnalyticsProvider';
import { load } from '@tauri-apps/plugin-store';
import { invoke } from '@tauri-apps/api/core';
import { getVersion } from '@tauri-apps/api/app';
import { Analytics } from '@/lib/analytics';
import { copyToClipboard } from '@/lib/clipboard';
import AnalyticsDataModal from './AnalyticsDataModal';


export default function AnalyticsConsentSwitch() {
  const { setIsAnalyticsOptedIn, isAnalyticsOptedIn } = useContext(AnalyticsContext);
  const [isProcessing, setIsProcessing] = useState(false);
  const [showModal, setShowModal] = useState(false);
  const [userId, setUserId] = useState<string>('');
  const [isCopied, setIsCopied] = useState(false);

  // Note: Store loading is handled by AnalyticsProvider to avoid race conditions

  useEffect(() => {
    const loadUserId = async () => {
      if (isAnalyticsOptedIn) {
        try {
          const id = await Analytics.getPersistentUserId();
          setUserId(id);
        } catch (error) {
          console.error('Failed to load user ID:', error);
        }
      } else {
        setUserId('');
      }
    };
    loadUserId();
  }, [isAnalyticsOptedIn]);

  const handleCopyUserId = async () => {
    if (!userId) return;

    try {
      await copyToClipboard(userId);
      setIsCopied(true);
      setTimeout(() => setIsCopied(false), 2000);

      // Track that user copied their ID
      await Analytics.track('user_id_copied', {
        user_id: userId
      });
    } catch (error) {
      console.error('Failed to copy user ID:', error);
    }
  };

  const handleToggle = async (enabled: boolean) => {
    // If user is trying to DISABLE, show the modal first
    if (!enabled) {
      setShowModal(true);
      // Track that user viewed the transparency modal
      try {
        await invoke('track_analytics_transparency_viewed');
      } catch (error) {
        console.error('Failed to track transparency view:', error);
      }
      return; // Don't disable yet, wait for modal confirmation
    }

    // If ENABLING, proceed immediately
    await performToggle(enabled);
  };

  const performToggle = async (enabled: boolean) => {
    // Optimistic update - immediately update UI state
    setIsAnalyticsOptedIn(enabled);
    setIsProcessing(true);

    try {
      const store = await load('analytics.json', {
        autoSave: false,
        defaults: {
          analyticsOptedIn: true
        }
      });
      await store.set('analyticsOptedIn', enabled);
      await store.save();

      if (enabled) {
        // Full analytics initialization (same as AnalyticsProvider)
        const userId = await Analytics.getPersistentUserId();

        // Initialize analytics
        await Analytics.init();

        // Identify user with enhanced properties immediately after init
        const appVersion = await getVersion();
        await Analytics.identify(userId, {
          app_version: appVersion,
          platform: 'tauri',
          first_seen: new Date().toISOString(),
          os: navigator.platform,
          user_agent: navigator.userAgent,
        });

        // Start analytics session with the same user ID
        await Analytics.startSession(userId);

        // Track app started (re-enabled)
        await Analytics.trackAppStarted();

        // Track that user enabled analytics
        try {
          await invoke('track_analytics_enabled');
        } catch (error) {
          console.error('Failed to track analytics enabled:', error);
        }

        console.log('Analytics re-enabled successfully');
      } else {
        // Track that user disabled analytics BEFORE disabling
        try {
          await invoke('track_analytics_disabled');
        } catch (error) {
          console.error('Failed to track analytics disabled:', error);
        }

        await Analytics.disable();
        console.log('Analytics disabled successfully');
      }
    } catch (error) {
      console.error('Failed to toggle analytics:', error);
      // Revert the optimistic update on error
      setIsAnalyticsOptedIn(!enabled);
      // You could also show a toast notification here to inform the user
    } finally {
      setIsProcessing(false);
    }
  };

  const handleConfirmDisable = async () => {
    setShowModal(false);
    await performToggle(false);
  };

  const handleCancelDisable = () => {
    setShowModal(false);
    // Keep analytics enabled, no state change needed
  };

  const handlePrivacyPolicyClick = async () => {
    try {
      await invoke('open_external_url', { url: 'https://github.com/Zackriya-Solutions/meeting-minutes/blob/main/PRIVACY_POLICY.md' });
    } catch (error) {
      console.error('Failed to open privacy policy link:', error);
    }
  };

  return (
    <>
      <div className="space-y-4">
        <div>
          <h3 className="text-base font-semibold text-gray-800 mb-2">사용 통계</h3>
          <p className="text-sm text-gray-600 mb-4">
            익명화된 사용 데이터를 공유해 Relay Assistant 개선에 도움을 주실 수 있습니다. 개인 콘텐츠는 수집하지 않으며 모든 정보는 기기 안에서만 처리됩니다.
          </p>
        </div>

        <div className="flex items-center justify-between p-3 bg-gray-50 rounded-lg border border-gray-200">
          <div>
            <h4 className="font-semibold text-gray-800">통계 수집 활성화</h4>
            <p className="text-sm text-gray-600">
              {isProcessing ? '적용 중…' : '익명 사용 패턴만 수집'}
            </p>
          </div>
          <div className="flex items-center gap-2 ml-4">
            {isProcessing && (
              <Loader2 className="w-4 h-4 animate-spin text-gray-500" />
            )}
            <Switch
              checked={isAnalyticsOptedIn}
              onCheckedChange={handleToggle}
              disabled={isProcessing}
            />
          </div>
        </div>

        {/* User ID Display */}
        {isAnalyticsOptedIn && userId && (
          <div className="p-4 border rounded-lg bg-gray-50">
            <div className="flex items-start justify-between gap-4">
              <div className="flex-1 min-w-0">
                <div className="font-medium text-gray-800 mb-1">사용자 ID</div>
                <p className="text-xs text-gray-600 mb-2">
                  문제를 문의하실 때 이 ID를 함께 알려주시면 해당 사용자의 로그를 더 빠르게 확인할 수 있습니다
                </p>
                <div className="flex items-center gap-2">
                  <code className="text-xs text-gray-700 bg-white px-2 py-1 rounded border border-gray-300 font-mono flex-1 truncate">
                    {userId}
                  </code>
                  <Button
                    onClick={handleCopyUserId}
                    variant="outline"
                    size="sm"
                    className="flex-shrink-0"
                    title="사용자 ID 복사"
                  >
                    {isCopied ? (
                      <>
                        <Check className="w-3.5 h-3.5 text-green-600" />
                        <span className="text-green-600">복사됨!</span>
                      </>
                    ) : (
                      <>
                        <Copy className="w-3.5 h-3.5" />
                        <span>복사</span>
                      </>
                    )}
                  </Button>
                </div>
              </div>
            </div>
          </div>
        )}

        <div className="flex items-start gap-2 p-2 bg-blue-50 rounded border border-blue-200">
          <Info className="w-4 h-4 text-blue-600 mt-0.5 flex-shrink-0" />
          <div className="text-xs text-blue-700">
            <p className="mb-1">
              회의, 전사, 녹음 데이터는 모두 사용자 기기 안에만 보관되며 외부로 전송되지 않습니다.
            </p>
            <button
              onClick={handlePrivacyPolicyClick}
              className="text-blue-600 hover:text-blue-800 underline hover:no-underline"
            >
              개인정보 처리방침 보기
            </button>
          </div>
        </div>
      </div>

      {/* 2-Step Opt-Out Modal */}
      <AnalyticsDataModal
        isOpen={showModal}
        onClose={handleCancelDisable}
        onConfirmDisable={handleConfirmDisable}
      />
    </>
  );
}