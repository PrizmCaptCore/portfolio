import React from 'react';
import { ShieldCheck, Sparkles, CloudCog } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { OnboardingContainer } from '../OnboardingContainer';
import { useOnboarding } from '@/contexts/OnboardingContext';

export function WelcomeStep() {
  const { goNext } = useOnboarding();

  const features = [
    {
      icon: ShieldCheck,
      title: '녹음과 회의 데이터는 이 기기 안에서만 보관됩니다',
    },
    {
      icon: Sparkles,
      title: '요약과 어시스턴스는 직접 설정한 AI 제공자를 사용합니다',
    },
    {
      icon: CloudCog,
      title: '초기 설정 단계에서 로컬 모델을 함께 다운로드하지 않습니다',
    },
  ];

  return (
    <OnboardingContainer
      title="Relay Assistant에 오신 걸 환영합니다"
      description="앱을 먼저 준비한 뒤, 설정에서 사용할 AI 제공자를 연결할 수 있어요."
      step={1}
      totalSteps={3}
      hideProgress={true}
    >
      <div className="flex flex-col items-center space-y-10">
        <div className="h-px w-16 bg-gray-300" />

        <div className="w-full max-w-md space-y-4 rounded-lg border border-gray-200 bg-white p-6 shadow-sm">
          {features.map((feature, index) => {
            const Icon = feature.icon;
            return (
              <div key={index} className="flex items-start gap-3">
                <div className="mt-0.5 flex-shrink-0">
                  <div className="flex h-5 w-5 items-center justify-center rounded-full bg-gray-100">
                    <Icon className="h-3 w-3 text-gray-700" />
                  </div>
                </div>
                <p className="text-sm leading-relaxed text-gray-700">{feature.title}</p>
              </div>
            );
          })}
        </div>

        <div className="w-full max-w-xs space-y-3">
          <Button onClick={goNext} className="h-11 w-full bg-gray-900 text-white hover:bg-gray-800">
            계속하기
          </Button>
          <p className="text-center text-xs text-gray-500">
            이제 초기 설정은 앱 환경 구성에 집중합니다. 모델 다운로드는 포함되지 않아요.
          </p>
        </div>
      </div>
    </OnboardingContainer>
  );
}
