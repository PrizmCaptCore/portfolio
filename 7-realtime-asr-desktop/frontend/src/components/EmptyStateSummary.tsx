'use client';

import { motion } from 'framer-motion';
import { FileQuestion, Sparkles } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';

interface EmptyStateSummaryProps {
  onGenerate: () => void;
  hasModel: boolean;
  isGenerating?: boolean;
}

export function EmptyStateSummary({ onGenerate, hasModel, isGenerating = false }: EmptyStateSummaryProps) {
  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.95 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ duration: 0.3, ease: 'easeOut' }}
      className="flex flex-col items-center justify-center h-full p-8 text-center"
    >
      <FileQuestion className="w-16 h-16 text-gray-300 mb-4" />
      <h3 className="text-lg font-semibold text-gray-900 mb-2">
        아직 생성된 요약이 없습니다
      </h3>
      <p className="text-sm text-gray-500 mb-6 max-w-md">
        AI 요약을 생성하면 회의 전사에서 핵심 포인트, 액션 아이템, 결정 사항을 한눈에 확인할 수 있습니다.
      </p>

      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger asChild>
            <div>
              <Button
                onClick={onGenerate}
                disabled={!hasModel || isGenerating}
                className="gap-2"
              >
                <Sparkles className="w-4 h-4" />
                {isGenerating ? '생성 중…' : '요약 생성'}
              </Button>
            </div>
          </TooltipTrigger>
          {!hasModel && (
            <TooltipContent>
              <p>설정에서 모델을 먼저 선택해 주세요</p>
            </TooltipContent>
          )}
        </Tooltip>
      </TooltipProvider>

      {!hasModel && (
        <p className="text-xs text-amber-600 mt-3">
          설정에서 모델을 먼저 선택해 주세요
        </p>
      )}
    </motion.div>
  );
}
