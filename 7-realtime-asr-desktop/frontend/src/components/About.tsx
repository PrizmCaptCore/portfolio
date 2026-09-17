import React, { useState, useEffect } from "react";
import { invoke } from '@tauri-apps/api/core';
import { getDisplayVersion } from '@/lib/version';
import Image from 'next/image';
import { UpdateDialog } from "./UpdateDialog";
import { updateService, UpdateInfo } from '@/services/updateService';
import { Button } from './ui/button';
import { Loader2, CheckCircle2 } from 'lucide-react';
import { toast } from 'sonner';


export function About() {
    const [currentVersion, setCurrentVersion] = useState<string>('');
    const [updateInfo, setUpdateInfo] = useState<UpdateInfo | null>(null);
    const [isChecking, setIsChecking] = useState(false);
    const [showUpdateDialog, setShowUpdateDialog] = useState(false);

    useEffect(() => {
        // Display-safe: dev builds show "DEMO" instead of leaking the dev
        // placeholder semver. Real releases show the injected tag version.
        getDisplayVersion().then(setCurrentVersion).catch(console.error);
    }, []);

    const handleCheckForUpdates = async () => {
        setIsChecking(true);
        try {
            const info = await updateService.checkForUpdates(true);
            setUpdateInfo(info);
            if (info.available) {
                setShowUpdateDialog(true);
            } else {
                toast.success('최신 버전을 사용 중입니다');
            }
        } catch (error: any) {
            console.error('Failed to check for updates:', error);
            toast.error('업데이트 확인에 실패했습니다: ' + (error.message || '알 수 없는 오류'));
        } finally {
            setIsChecking(false);
        }
    };

    const handleGoToRelayPlatform = () => {
        const url = 'https://example.com';
        invoke('open_external_url', { url }).catch((error) => {
            console.error('Failed to open external URL:', error);
            toast.error('브라우저를 열지 못했습니다. 잠시 후 다시 시도해주세요.');
        });
    };

    return (
        <div className="p-4 space-y-4 h-[80vh] overflow-y-auto">
            {/* Compact Header */}
            <div className="text-center">
                <div className="mb-3">
                    <Image
                        src="/icon_128x128.png"
                        alt="Relay Assistant 로고"
                        width={64}
                        height={64}
                        className="mx-auto"
                    />
                </div>
                {/* <h1 className="text-xl font-bold text-gray-900">Relay Assistant</h1> */}
                {currentVersion && (
                    <span className="text-sm text-gray-500">
                        {' '}
                        {currentVersion === 'DEMO' ? 'DEMO' : `v${currentVersion}`}
                    </span>
                )}
                <p className="text-medium text-gray-600 mt-1">
                    글로벌 미팅과 커뮤니케이션을 더 자신 있게
                </p>
                <div className="mt-3">
                    <Button
                        onClick={handleCheckForUpdates}
                        disabled={isChecking}
                        variant="outline"
                        size="sm"
                        className="text-xs"
                    >
                        {isChecking ? (
                            <>
                                <Loader2 className="h-3 w-3 mr-2 animate-spin" />
                                확인 중…
                            </>
                        ) : (
                            <>
                                <CheckCircle2 className="h-3 w-3 mr-2" />
                                업데이트 확인
                            </>
                        )}
                    </Button>
                    {updateInfo?.available && (
                        <div className="mt-2 text-xs text-blue-600">
                            업데이트 가능: v{updateInfo.version}
                        </div>
                    )}
                </div>
            </div>

            {/* Features Grid - Compact */}
            <div className="space-y-3">
                <h2 className="text-base font-semibold text-gray-800">Relay Assistant만의 차별점</h2>
                <div className="grid grid-cols-2 gap-2">
                    <div className="bg-gray-50 rounded p-3 hover:bg-gray-100 transition-colors">
                        <h3 className="font-bold text-sm text-gray-900 mb-1">실시간 전사 및 번역</h3>
                        <p className="text-xs text-gray-600 leading-relaxed">회의 음성을 실시간으로 인식하고 번역하여 글로벌 커뮤니케이션을 지원합니다.</p>
                    </div>
                    <div className="bg-gray-50 rounded p-3 hover:bg-gray-100 transition-colors">
                        <h3 className="font-bold text-sm text-gray-900 mb-1">실시간 의도 분석</h3>
                        <p className="text-xs text-gray-600 leading-relaxed">회의와 대화 속에서 상대방이 실제로 전달하려는 핵심 의도를 빠르게 파악할 수 있습니다.</p>
                    </div>
                    <div className="bg-gray-50 rounded p-3 hover:bg-gray-100 transition-colors">
                        <h3 className="font-bold text-sm text-gray-900 mb-1">맥락 기반 응답 가이드</h3>
                        <p className="text-xs text-gray-600 leading-relaxed">현재 대화 흐름과 상황을 바탕으로 자연스러운 답변 방향을 제안합니다.</p>
                    </div>
                    <div className="bg-gray-50 rounded p-3 hover:bg-gray-100 transition-colors">
                        <h3 className="font-bold text-sm text-gray-900 mb-1">다양한 미팅 환경 지원</h3>
                        <p className="text-xs text-gray-600 leading-relaxed">Zoom, Google Meet, Teams 등 다양한 환경에서 사용할 수 있습니다.</p>
                    </div>
                </div>
                <div className="pt-1">
                    <Button
                        onClick={handleGoToRelayPlatform}
                        variant="outline"
                        size="sm"
                        className="w-full text-xs"
                    >
                        Relay Platform에서 연습하기
                    </Button>
                </div>
            </div>

            {/* Update Dialog */}
            <UpdateDialog
                open={showUpdateDialog}
                onOpenChange={setShowUpdateDialog}
                updateInfo={updateInfo}
            />
        </div>

    )
}
