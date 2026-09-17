import { useState, useEffect, useCallback } from 'react';
import { ModelConfig } from '@/components/ModelSettingsModal';
import { invoke as invokeTauri } from '@tauri-apps/api/core';
import { toast } from 'sonner';
import Analytics from '@/lib/analytics';
import { normalizeSummaryProvider } from '@/lib/summaryProviders';

interface UseModelConfigurationProps {
  serverAddress: string | null;
}

export function useModelConfiguration({ serverAddress }: UseModelConfigurationProps) {
  const [modelConfig, setModelConfig] = useState<ModelConfig>({
    provider: 'relay-ai',
    model: '',
    whisperModel: 'large-v3',
  });
  const [isLoading, setIsLoading] = useState(true);
  const [, setError] = useState<string>('');

  useEffect(() => {
    const fetchModelConfig = async () => {
      setIsLoading(true);
      try {
        const data = (await invokeTauri('api_get_model_config', {})) as any;
        if (data?.provider) {
          const provider = normalizeSummaryProvider(data.provider);

          if (provider === 'relay-ai') {
            const customConfig = (await invokeTauri('api_get_relay_ai_config')) as any;
            setModelConfig({
              provider,
              model: customConfig?.model || data.model || '',
              whisperModel: data.whisperModel || 'large-v3',
              relayAIEndpoint: customConfig?.endpoint || '',
              relayAIModel: customConfig?.model || '',
              relayAIApiKey: customConfig?.apiKey || '',
              maxTokens: customConfig?.maxTokens ?? null,
              temperature: customConfig?.temperature ?? null,
              topP: customConfig?.topP ?? null,
            });
          } else {
            let apiKey = data.apiKey ?? null;
            if (!apiKey) {
              try {
                apiKey = (await invokeTauri('api_get_api_key', { provider })) as string;
              } catch (error) {
                console.error('Failed to fetch API key:', error);
              }
            }

            setModelConfig({
              provider,
              model: data.model || '',
              whisperModel: data.whisperModel || 'large-v3',
              apiKey,
            });
          }
        }
      } catch (error) {
        console.error('Failed to fetch model config:', error);
      } finally {
        setIsLoading(false);
      }
    };

    void fetchModelConfig();
  }, [serverAddress]);

  useEffect(() => {
    const setupListener = async () => {
      const { listen } = await import('@tauri-apps/api/event');
      const unlisten = await listen<ModelConfig>('model-config-updated', (event) => {
        setModelConfig(event.payload);
      });

      return unlisten;
    };

    let cleanup: (() => void) | undefined;
    void setupListener().then((fn) => {
      cleanup = fn;
    });

    return () => {
      cleanup?.();
    };
  }, []);

  const handleSaveModelConfig = useCallback(async (updatedConfig?: ModelConfig) => {
    try {
      const configToSave = updatedConfig || modelConfig;
      const payload = {
        provider: normalizeSummaryProvider(configToSave.provider),
        model: configToSave.model,
        whisperModel: configToSave.whisperModel,
        apiKey: configToSave.apiKey ?? null,
      };

      if (
        updatedConfig &&
        (updatedConfig.provider !== modelConfig.provider || updatedConfig.model !== modelConfig.model)
      ) {
        await Analytics.trackModelChanged(
          modelConfig.provider,
          modelConfig.model,
          payload.provider,
          payload.model
        );
      }

      await invokeTauri('api_save_model_config', payload);
      setModelConfig({ ...configToSave, provider: payload.provider });

      const { emit } = await import('@tauri-apps/api/event');
      await emit('model-config-updated', { ...configToSave, provider: payload.provider });

      toast.success('요약 설정을 저장했습니다');
      await Analytics.trackSettingsChanged('model_config', `${payload.provider}_${payload.model}`);
    } catch (error) {
      console.error('Failed to save model config:', error);
      toast.error('요약 설정을 저장하지 못했습니다', { description: String(error) });
      setError(error instanceof Error ? error.message : '모델 설정 저장에 실패했습니다');
    }
  }, [modelConfig]);

  return {
    modelConfig,
    setModelConfig,
    handleSaveModelConfig,
    isLoading,
  };
}
