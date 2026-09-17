'use client';

import { createContext, useContext, useCallback, ReactNode } from 'react';
import { useConfig } from './ConfigContext';
import { toast } from 'sonner';

interface ImportDialogContextType {
  openImportDialog: (filePath?: string | null) => void;
}

const ImportDialogContext = createContext<ImportDialogContextType | null>(null);

export const useImportDialog = () => {
  const ctx = useContext(ImportDialogContext);
  if (!ctx) throw new Error('useImportDialog must be used within ImportDialogProvider');
  return ctx;
};

interface ImportDialogProviderProps {
  children: ReactNode;
  onOpen: (filePath?: string | null) => void;
}

export function ImportDialogProvider({ children, onOpen }: ImportDialogProviderProps) {
  const { betaFeatures } = useConfig();

  const openImportDialog = useCallback((filePath?: string | null) => {
    // Gate: Check beta feature flag before opening dialog
    if (!betaFeatures.importAndRetranscribe) {
      toast.error('베타 기능이 꺼져 있습니다', {
        description: '설정 > 베타에서 "오디오 가져오기 및 재전사"를 활성화하면 사용할 수 있습니다.'
      });
      return;
    }

    onOpen(filePath);
  }, [onOpen, betaFeatures]);

  return (
    <ImportDialogContext.Provider value={{ openImportDialog }}>
      {children}
    </ImportDialogContext.Provider>
  );
}
