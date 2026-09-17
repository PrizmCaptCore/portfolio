import React, { useEffect, useState } from 'react';
import { Database, KeyRound, Mic } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { OnboardingContainer } from '../OnboardingContainer';
import { useOnboarding } from '@/contexts/OnboardingContext';

export function SetupOverviewStep() {
  const { goNext, completeOnboarding } = useOnboarding();
  const [isMac, setIsMac] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    const checkPlatform = async () => {
      try {
        const { platform } = await import('@tauri-apps/plugin-os');
        setIsMac(platform() === 'macos');
      } catch (error) {
        setIsMac(navigator.userAgent.includes('Mac'));
      }
    };

    void checkPlatform();
  }, []);

  const handleContinue = async () => {
    if (isMac) {
      goNext();
      return;
    }

    setIsSubmitting(true);
    try {
      await completeOnboarding();
      window.location.reload();
    } finally {
      setIsSubmitting(false);
    }
  };

  const steps = [
    {
      icon: Database,
      title: '로컬 작업 공간 초기화',
      description: '데스크톱 앱이 사용할 회의 데이터베이스와 저장 폴더를 생성합니다.',
    },
    {
      icon: KeyRound,
      title: 'AI 제공자는 나중에 연결',
      description: '요약에 사용할 모델은 더 이상 번들 다운로드 없이 설정에서 직접 연결합니다.',
    },
    {
      icon: Mic,
      title: '녹음 권한 부여',
      description: isMac ? '다음 단계에서 macOS 권한을 요청합니다.' : '필요 시 시스템 설정에서 권한을 직접 부여할 수 있습니다.',
    },
  ];

  return (
    <OnboardingContainer
      title="설정 개요"
      description="앱이 초기화 준비를 마쳤습니다. 외부 AI 제공자는 초기 설정이 끝난 뒤 설정 화면에서 연결합니다."
      step={2}
      totalSteps={isMac ? 3 : 2}
    >
      <div className="flex flex-col items-center space-y-8">
        <div className="w-full max-w-xl space-y-3">
          {steps.map((step) => {
            const Icon = step.icon;
            return (
              <div key={step.title} className="rounded-xl border border-gray-200 bg-white p-4">
                <div className="flex items-start gap-3">
                  <div className="flex h-10 w-10 items-center justify-center rounded-full bg-gray-100">
                    <Icon className="h-5 w-5 text-gray-700" />
                  </div>
                  <div>
                    <h3 className="font-medium text-gray-900">{step.title}</h3>
                    <p className="mt-1 text-sm text-gray-600">{step.description}</p>
                  </div>
                </div>
              </div>
            );
          })}
        </div>

        <div className="w-full max-w-xs">
          <Button
            onClick={handleContinue}
            disabled={isSubmitting}
            className="w-full h-11 bg-gray-900 hover:bg-gray-800 text-white"
          >
            {isSubmitting ? '설정 마무리 중…' : isMac ? '계속하기' : '설정 완료'}
          </Button>
        </div>
      </div>
    </OnboardingContainer>
  );
}
