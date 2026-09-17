'use client';

import React, { useEffect, useState } from 'react';
import { X, Info, Shield } from 'lucide-react';
import { getDisplayVersion } from '@/lib/version';

interface AnalyticsDataModalProps {
  isOpen: boolean;
  onClose: () => void;
  onConfirmDisable: () => void;
}

export default function AnalyticsDataModal({ isOpen, onClose, onConfirmDisable }: AnalyticsDataModalProps) {
  const [appVersion, setAppVersion] = useState<string>('');

  useEffect(() => {
    getDisplayVersion().then(setAppVersion).catch(console.error);
  }, []);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg shadow-xl max-w-2xl w-full mx-4 max-h-[90vh] overflow-y-auto">
        {/* Header */}
        <div className="flex items-center justify-between p-6 border-b border-gray-200">
          <div className="flex items-center gap-3">
            <Shield className="w-6 h-6 text-blue-600" />
            <h2 className="text-xl font-semibold text-gray-900">수집하는 데이터</h2>
          </div>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Content */}
        <div className="p-6 space-y-6">
          {/* Privacy Notice */}
          <div className="bg-green-50 border border-green-200 rounded-lg p-4">
            <div className="flex items-start gap-3">
              <Info className="w-5 h-5 text-green-600 mt-0.5 flex-shrink-0" />
              <div className="text-sm text-green-800">
                <p className="font-semibold mb-1">개인정보를 안전하게 보호합니다</p>
                <p><strong>익명 사용 데이터만</strong> 수집합니다. 회의 내용, 이름, 개인정보는 절대 수집하지 않습니다.</p>
              </div>
            </div>
          </div>

          {/* Data Categories */}
          <div className="space-y-4">
            <h3 className="text-lg font-semibold text-gray-900">수집 항목:</h3>

            {/* Model Preferences */}
            <div className="border border-gray-200 rounded-lg p-4">
              <h4 className="font-semibold text-gray-900 mb-2">1. 모델 선호도</h4>
              <ul className="text-sm text-gray-700 space-y-1 ml-4">
                <li>• 전사 모델 (예: "CNN STT")</li>
                <li>• 요약 모델 (예: "Llama 3.2", "Claude Sonnet")</li>
                <li>• 모델 제공자 (예: "OpenAI", "Claude", "OpenRouter")</li>
              </ul>
              <p className="text-xs text-gray-500 mt-2 italic">사용자가 선호하는 모델을 파악하는 데 사용합니다</p>
            </div>

            {/* Meeting Metrics */}
            <div className="border border-gray-200 rounded-lg p-4">
              <h4 className="font-semibold text-gray-900 mb-2">2. 익명 회의 지표</h4>
              <ul className="text-sm text-gray-700 space-y-1 ml-4">
                <li>• 녹음 시간 (예: "125초")</li>
                <li>• 일시정지 시간 (예: "5초")</li>
                <li>• 전사 세그먼트 수</li>
                <li>• 처리한 오디오 청크 수</li>
              </ul>
              <p className="text-xs text-gray-500 mt-2 italic">성능 최적화와 사용 패턴 파악에 사용합니다</p>
            </div>

            {/* Device Types */}
            <div className="border border-gray-200 rounded-lg p-4">
              <h4 className="font-semibold text-gray-900 mb-2">3. 기기 종류 (이름 아님)</h4>
              <ul className="text-sm text-gray-700 space-y-1 ml-4">
                <li>• 마이크 유형: "블루투스" / "유선" / "알 수 없음"</li>
                <li>• 시스템 오디오 유형: "블루투스" / "유선" / "알 수 없음"</li>
              </ul>
              <p className="text-xs text-gray-500 mt-2 italic">호환성 개선에 사용하며, 실제 기기 이름은 수집하지 않습니다</p>
            </div>

            {/* Usage Patterns */}
            <div className="border border-gray-200 rounded-lg p-4">
              <h4 className="font-semibold text-gray-900 mb-2">4. 앱 사용 패턴</h4>
              <ul className="text-sm text-gray-700 space-y-1 ml-4">
                <li>• 앱 시작·종료 이벤트</li>
                <li>• 세션 시간</li>
                <li>• 기능 사용 (예: "설정 변경")</li>
                <li>• 오류 발생 (버그 수정에 활용)</li>
              </ul>
              <p className="text-xs text-gray-500 mt-2 italic">사용자 경험 개선에 사용합니다</p>
            </div>

            {/* Platform Info */}
            <div className="border border-gray-200 rounded-lg p-4">
              <h4 className="font-semibold text-gray-900 mb-2">5. 플랫폼 정보</h4>
              <ul className="text-sm text-gray-700 space-y-1 ml-4">
                <li>• 운영체제 (예: "macOS", "Windows")</li>
                <li>• 앱 버전 (모든 이벤트에 자동 포함)</li>
                <li>• 아키텍처 (예: "x86_64", "aarch64")</li>
              </ul>
              <p className="text-xs text-gray-500 mt-2 italic">플랫폼별 지원 우선순위를 정하는 데 사용합니다</p>
            </div>
          </div>

          {/* What We DON'T Collect */}
          <div className="bg-red-50 border border-red-200 rounded-lg p-4">
            <h4 className="font-semibold text-red-900 mb-2">수집하지 않는 항목:</h4>
            <ul className="text-sm text-red-800 space-y-1 ml-4">
              <li>•  회의 제목 또는 이름</li>
              <li>•  회의 전사 또는 내용</li>
              <li>•  오디오 녹음 파일</li>
              <li>•  실제 기기 이름 (유형만 수집: 블루투스/유선)</li>
              <li>•  개인정보</li>
              <li>•  특정 사용자를 식별할 수 있는 모든 정보</li>
            </ul>
          </div>

          {/* Example Event */}
          <div className="bg-gray-50 border border-gray-200 rounded-lg p-4">
            <h4 className="font-semibold text-gray-900 mb-2">이벤트 예시:</h4>
            <pre className="text-xs text-gray-700 overflow-x-auto">
              {`{
  "event": "meeting_ended",
  "app_version": "${appVersion}",
  "total_duration_seconds": "125.5",
  "microphone_device_type": "Wired",
  "system_audio_device_type": "Bluetooth",
  "chunks_processed": "150",
  "had_fatal_error": "false"
}`}
            </pre>
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between gap-4 p-6 border-t border-gray-200 bg-gray-50">
          <button
            onClick={onClose}
            className="px-4 py-2 text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50 transition-colors"
          >
            활성화 유지
          </button>
          <button
            onClick={onConfirmDisable}
            className="px-4 py-2 text-white bg-red-600 rounded-md hover:bg-red-700 transition-colors"
          >
            통계 수집 비활성화
          </button>
        </div>
      </div>
    </div>
  );
}
