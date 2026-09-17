import React, { useEffect, useState, useCallback } from 'react';
import { invoke } from '@tauri-apps/api/core';
import { Mic, Volume2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { OnboardingContainer } from '../OnboardingContainer';
import { PermissionRow } from '../shared';
import { useOnboarding } from '@/contexts/OnboardingContext';

export function PermissionsStep() {
  const { setPermissionStatus, setPermissionsSkipped, permissions, completeOnboarding } = useOnboarding();
  const [isPending, setIsPending] = useState(false);

  const checkPermissions = useCallback(async () => {
    console.log('[PermissionsStep] Current permission states:', permissions);
  }, [permissions]);

  useEffect(() => {
    void checkPermissions();
  }, [checkPermissions]);

  const handleMicrophoneAction = async () => {
    if (permissions.microphone === 'denied') {
      try {
        await invoke('open_system_settings');
      } catch {
        alert('시스템 환경설정 > 보안 및 개인정보 보호 > 마이크에서 마이크 접근을 허용해 주세요');
      }
      return;
    }

    setIsPending(true);
    try {
      const granted = await invoke<boolean>('trigger_microphone_permission');
      setPermissionStatus('microphone', granted ? 'authorized' : 'denied');
    } catch (error) {
      console.error('[PermissionsStep] Failed to request microphone permission:', error);
      setPermissionStatus('microphone', 'denied');
    } finally {
      setIsPending(false);
    }
  };

  const handleSystemAudioAction = async () => {
    if (permissions.systemAudio === 'denied') {
      try {
        await invoke('open_system_settings');
      } catch {
        alert('시스템 설정 > 개인정보 보호 및 보안 > 오디오 캡처에서 오디오 캡처를 허용해 주세요');
      }
      return;
    }

    setIsPending(true);
    try {
      const granted = await invoke<boolean>('trigger_system_audio_permission_command');
      setPermissionStatus('systemAudio', granted ? 'authorized' : 'denied');
    } catch (error) {
      console.error('[PermissionsStep] Failed to request system audio permission:', error);
      setPermissionStatus('systemAudio', 'denied');
    } finally {
      setIsPending(false);
    }
  };

  const handleFinish = async () => {
    try {
      await completeOnboarding();
      window.location.reload();
    } catch (error) {
      console.error('Failed to complete onboarding:', error);
    }
  };

  const handleSkip = async () => {
    setPermissionsSkipped(true);
    await handleFinish();
  };

  const allPermissionsGranted =
    permissions.microphone === 'authorized' &&
    permissions.systemAudio === 'authorized';

  return (
    <OnboardingContainer
      title="권한 부여"
      description="회의를 녹음하려면 Relay Assistant에 마이크와 시스템 오디오 접근 권한이 필요합니다"
      step={3}
      totalSteps={3}
      hideProgress={true}
      showNavigation={allPermissionsGranted}
      canGoNext={allPermissionsGranted}
    >
      <div className="max-w-lg mx-auto space-y-6">
        <div className="space-y-4">
          <PermissionRow
            icon={<Mic className="w-5 h-5" />}
            title="마이크"
            description="회의 중 음성을 캡처하기 위해 필요합니다"
            status={permissions.microphone}
            isPending={isPending}
            onAction={handleMicrophoneAction}
          />

          <PermissionRow
            icon={<Volume2 className="w-5 h-5" />}
            title="시스템 오디오"
            description="활성화를 눌러 오디오 캡처 권한을 부여해 주세요"
            status={permissions.systemAudio}
            isPending={isPending}
            onAction={handleSystemAudioAction}
          />
        </div>

        <div className="flex flex-col gap-3 pt-4">
          <Button onClick={handleFinish} disabled={!allPermissionsGranted} className="w-full h-11">
            설정 완료
          </Button>

          <button
            onClick={handleSkip}
            className="text-sm text-neutral-500 hover:text-neutral-700 transition-colors"
          >
            나중에 설정할게요
          </button>

          {!allPermissionsGranted && (
            <p className="text-xs text-center text-muted-foreground">
              권한이 없으면 녹음이 동작하지 않습니다. 설정에서 나중에 권한을 부여할 수 있습니다.
            </p>
          )}
        </div>
      </div>
    </OnboardingContainer>
  );
}
