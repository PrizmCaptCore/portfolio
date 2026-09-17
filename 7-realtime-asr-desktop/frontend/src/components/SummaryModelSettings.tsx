'use client';

import { useState, useEffect, useCallback } from 'react';
import { invoke } from '@tauri-apps/api/core';
import { toast } from 'sonner';
import { ModelConfig, ModelSettingsModal } from '@/components/ModelSettingsModal';
import { Switch } from './ui/switch';
import { useConfig } from '@/contexts/ConfigContext';
import { normalizeSummaryProvider } from '@/lib/summaryProviders';

interface SummaryModelSettingsProps {
  refetchTrigger?: number; // Change this to trigger refetch
}

export function SummaryModelSettings({ refetchTrigger }: SummaryModelSettingsProps) {
  // Defaults intentionally omit the gateway URL and the underlying model tag.
  // The Rust backend resolves the effective endpoint from `config::gateway_url()`
  // at request time, so the frontend never needs to know (and should not
  // display) the upstream URL or the Ollama model name.
  const [modelConfig, setModelConfig] = useState<ModelConfig>({
    provider: 'relay-ai',
    model: '',
    whisperModel: '',
    apiKey: null,
    relayAIEndpoint: null,
    relayAIModel: null,
    relayAIApiKey: null,
  });

  const { isAutoSummary, toggleIsAutoSummary } = useConfig();

  // Reusable fetch function
  const fetchModelConfig = useCallback(async () => {
    try {
      const data = await invoke('api_get_model_config') as any;
      if (data && data.provider !== null) {
        const normalizedProvider = normalizeSummaryProvider(data.provider);

        if (normalizedProvider !== 'relay-ai' && !data.apiKey) {
          try {
            const apiKeyData = await invoke('api_get_api_key', {
              provider: normalizedProvider
            }) as string;
            data.apiKey = apiKeyData;
          } catch (err) {
            console.error('Failed to fetch API key:', err);
          }
        }

        if (normalizedProvider === 'relay-ai') {
          try {
            const customConfig = (await invoke('api_get_relay_ai_config')) as any;
            if (customConfig) {
              data.relayAIDisplayName = customConfig.displayName || null;
              data.relayAIEndpoint = customConfig.endpoint || null;
              data.relayAIModel = customConfig.model || null;
              data.relayAIApiKey = customConfig.apiKey || null;
              data.maxTokens = customConfig.maxTokens || null;
              data.temperature = customConfig.temperature || null;
              data.topP = customConfig.topP || null;
              data.model = customConfig.model || data.model;
            }
          } catch (err) {
            console.error('Failed to fetch Relay AI config:', err);
          }
        }

        setModelConfig({
          ...data,
          provider: normalizedProvider,
        });
      }
    } catch (error) {
      console.error('Failed to fetch model config:', error);
      toast.error('모델 설정을 불러오지 못했습니다');
    }
  }, []);

  // Fetch on mount
  useEffect(() => {
    fetchModelConfig();
  }, [fetchModelConfig]);

  // Refetch when trigger changes (optional external control)
  useEffect(() => {
    if (refetchTrigger !== undefined && refetchTrigger > 0) {
      fetchModelConfig();
    }
  }, [refetchTrigger, fetchModelConfig]);

  // Listen for model config updates from other components
  useEffect(() => {
    const setupListener = async () => {
      const { listen } = await import('@tauri-apps/api/event');
      const unlisten = await listen<ModelConfig>('model-config-updated', (event) => {
        console.log('SummaryModelSettings received model-config-updated event:', event.payload);
        setModelConfig(event.payload);
      });

      return unlisten;
    };

    let cleanup: (() => void) | undefined;
    setupListener().then(fn => cleanup = fn);

    return () => {
      cleanup?.();
    };
  }, []);

  // Save handler
  const handleSaveModelConfig = async (config: ModelConfig) => {
    try {
      await invoke('api_save_model_config', {
        provider: config.provider,
        model: config.model,
        whisperModel: config.whisperModel,
        apiKey: config.apiKey,
      });

      setModelConfig(config);

      // Emit event to sync other components
      const { emit } = await import('@tauri-apps/api/event');
      await emit('model-config-updated', config);

      toast.success('모델 설정을 저장했습니다');
    } catch (error) {
      console.error('Error saving model config:', error);
      toast.error('모델 설정 저장에 실패했습니다');
    }
  };

  return (
    <div className='flex flex-col gap-4'>
      <div className="bg-white rounded-lg border border-gray-200 p-6 shadow-sm">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-lg font-semibold text-gray-900 mb-2">자동 요약</h3>
            <p className="text-sm text-gray-600">회의 종료(중지) 후 요약을 자동으로 생성합니다</p>
          </div>
          <Switch checked={isAutoSummary} onCheckedChange={toggleIsAutoSummary} />
        </div>
      </div>

      <div className="bg-white rounded-lg border border-gray-200 p-6 shadow-sm">
        <h3 className="text-lg font-semibold mb-4">요약</h3>

        <ModelSettingsModal
          modelConfig={modelConfig}
          setModelConfig={setModelConfig}
          onSave={handleSaveModelConfig}
          skipInitialFetch={true}
        />
      </div>
    </div>
  );
}
