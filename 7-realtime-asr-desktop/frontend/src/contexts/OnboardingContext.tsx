'use client';

import React, { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import { invoke } from '@tauri-apps/api/core';
import type { PermissionStatus, OnboardingPermissions } from '@/types/onboarding';

interface OnboardingStatus {
  version: string;
  completed: boolean;
  current_step: number;
  model_status: {
    cnn_stt: string;
    summary: string;
  };
  last_updated: string;
}

interface OnboardingContextType {
  currentStep: number;
  databaseExists: boolean;
  permissions: OnboardingPermissions;
  permissionsSkipped: boolean;
  goToStep: (step: number) => void;
  goNext: () => void;
  goPrevious: () => void;
  setPermissionStatus: (permission: keyof OnboardingPermissions, status: PermissionStatus) => void;
  setPermissionsSkipped: (skipped: boolean) => void;
  completeOnboarding: () => Promise<void>;
}

const OnboardingContext = createContext<OnboardingContextType | undefined>(undefined);

export function OnboardingProvider({ children }: { children: React.ReactNode }) {
  const [currentStep, setCurrentStep] = useState(1);
  const [completed, setCompleted] = useState(false);
  const [databaseExists, setDatabaseExists] = useState(false);
  const [permissionsSkipped, setPermissionsSkipped] = useState(false);
  const [permissions, setPermissions] = useState<OnboardingPermissions>({
    microphone: 'not_determined',
    systemAudio: 'not_determined',
    screenRecording: 'not_determined',
  });

  const saveTimeoutRef = useRef<NodeJS.Timeout>();
  const isCompletingRef = useRef(false);

  useEffect(() => {
    const initialize = async () => {
      await Promise.all([loadOnboardingStatus(), initializeDatabaseInBackground(), checkDatabaseStatus()]);
    };

    void initialize();
  }, []);

  useEffect(() => {
    if (saveTimeoutRef.current) clearTimeout(saveTimeoutRef.current);
    if (completed || isCompletingRef.current) return;

    saveTimeoutRef.current = setTimeout(() => {
      void saveOnboardingStatus();
    }, 500);

    return () => {
      if (saveTimeoutRef.current) clearTimeout(saveTimeoutRef.current);
    };
  }, [currentStep, completed]);

  const initializeDatabaseInBackground = async () => {
    try {
      const isFirstLaunch = await invoke<boolean>('check_first_launch');
      if (!isFirstLaunch) {
        setDatabaseExists(true);
        return;
      }

      const legacyPath = await invoke<string | null>('check_default_legacy_database');
      if (legacyPath) {
        await invoke('import_and_initialize_database', { legacyDbPath: legacyPath });
      } else {
        await invoke('initialize_fresh_database');
      }

      setDatabaseExists(true);
    } catch (error) {
      console.error('[OnboardingContext] Failed to initialize database:', error);
    }
  };

  const checkDatabaseStatus = async () => {
    try {
      const isFirstLaunch = await invoke<boolean>('check_first_launch');
      setDatabaseExists(!isFirstLaunch);
    } catch (error) {
      console.error('[OnboardingContext] Failed to check database status:', error);
    }
  };

  const loadOnboardingStatus = async () => {
    try {
      const status = await invoke<OnboardingStatus | null>('get_onboarding_status');
      if (!status) {
        return;
      }

      setCurrentStep(Math.max(1, Math.min(status.current_step, 3)));
      setCompleted(status.completed);
    } catch (error) {
      console.error('[OnboardingContext] Failed to load onboarding status:', error);
    }
  };

  const saveOnboardingStatus = async () => {
    if (isCompletingRef.current) {
      return;
    }

    try {
      await invoke('save_onboarding_status_cmd', {
        status: {
          version: '1.0',
          completed,
          current_step: currentStep,
          model_status: {
            cnn_stt: 'not_applicable',
            summary: 'not_applicable',
          },
          last_updated: new Date().toISOString(),
        },
      });
    } catch (error) {
      console.error('[OnboardingContext] Failed to save onboarding status:', error);
    }
  };

  const completeOnboarding = async () => {
    try {
      isCompletingRef.current = true;
      if (saveTimeoutRef.current) {
        clearTimeout(saveTimeoutRef.current);
      }

      await invoke('complete_onboarding', { model: '' });
      setCompleted(true);
    } finally {
      isCompletingRef.current = false;
    }
  };

  const setPermissionStatus = useCallback((permission: keyof OnboardingPermissions, status: PermissionStatus) => {
    setPermissions((prev) => ({
      ...prev,
      [permission]: status,
    }));
  }, []);

  const goToStep = useCallback((step: number) => {
    setCurrentStep(Math.max(1, Math.min(step, 3)));
  }, []);

  const goNext = useCallback(() => {
    setCurrentStep((prev) => Math.min(prev + 1, 3));
  }, []);

  const goPrevious = useCallback(() => {
    setCurrentStep((prev) => Math.max(prev - 1, 1));
  }, []);

  return (
    <OnboardingContext.Provider
      value={{
        currentStep,
        databaseExists,
        permissions,
        permissionsSkipped,
        goToStep,
        goNext,
        goPrevious,
        setPermissionStatus,
        setPermissionsSkipped,
        completeOnboarding,
      }}
    >
      {children}
    </OnboardingContext.Provider>
  );
}

export function useOnboarding() {
  const context = useContext(OnboardingContext);
  if (!context) {
    throw new Error('useOnboarding must be used within an OnboardingProvider');
  }
  return context;
}
