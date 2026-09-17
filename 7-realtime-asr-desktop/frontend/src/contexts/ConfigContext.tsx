'use client';

import React, { createContext, useContext, useState, useEffect, useCallback, useMemo, ReactNode, useRef } from 'react';
import { TranscriptModelProps } from '@/components/TranscriptSettings';
import { SelectedDevices } from '@/components/DeviceSelection';
import { configService, ModelConfig } from '@/services/configService';
import { invoke } from '@tauri-apps/api/core';
import Analytics from '@/lib/analytics';
import { BetaFeatures, BetaFeatureKey, loadBetaFeatures, saveBetaFeatures } from '@/types/betaFeatures';
import {
  DEFAULT_LIVE_COACHING_INTENT_LANGUAGE,
} from '@/constants/liveTranslation';
import { DEFAULT_CNN_STT_MODEL } from '@/constants/modelDefaults';
import { normalizeSummaryProvider } from '@/lib/summaryProviders';

export interface StorageLocations {
  database: string;
  models: string;
  recordings: string;
}

export interface NotificationSettings {
  recording_notifications: boolean;
  time_based_reminders: boolean;
  meeting_reminders: boolean;
  respect_do_not_disturb: boolean;
  notification_sound: boolean;
  system_permission_granted: boolean;
  consent_given: boolean;
  manual_dnd_mode: boolean;
  notification_preferences: {
    show_recording_started: boolean;
    show_recording_stopped: boolean;
    show_recording_paused: boolean;
    show_recording_resumed: boolean;
    show_transcription_complete: boolean;
    show_meeting_reminders: boolean;
    show_system_errors: boolean;
    meeting_reminder_minutes: number[];
  };
}

interface ConfigContextType {
  // Model configuration
  modelConfig: ModelConfig;
  setModelConfig: (config: ModelConfig | ((prev: ModelConfig) => ModelConfig)) => void;

  // Transcript model configuration
  transcriptModelConfig: TranscriptModelProps;
  setTranscriptModelConfig: (config: TranscriptModelProps | ((prev: TranscriptModelProps) => TranscriptModelProps)) => void;

  // Device configuration
  selectedDevices: SelectedDevices;
  setSelectedDevices: (devices: SelectedDevices) => void;

  // Language preference
  selectedLanguage: string;
  setSelectedLanguage: (lang: string) => void;

  /** Language for live “likely intent” hints (summary LLM). “You could say” stays English. */
  liveCoachingIntentLanguage: string;
  setLiveCoachingIntentLanguage: (label: string) => void;
  /** Intent summary + suggested replies in English (same LLM) */
  liveCoachingEnabled: boolean;
  setLiveCoachingEnabled: (enabled: boolean) => void;

  /** Toggle live transcript translation via Google Translate. When off, no translation requests are sent. */
  translationEnabled: boolean;
  setTranslationEnabled: (enabled: boolean) => void;
  /** True while the translate Modal container is being warmed up after an OFF→ON toggle. */
  translatorWarming: boolean;

  /** User language (`ko` or `en`). Used as the translation target, and matching detected languages are skipped. */
  userLanguage: string;
  setUserLanguage: (lang: string) => void;

  /**
   * Source-side STT language. Currently locked to `'en'` — wired here so
   * the TranscriptPanel selectors can flip between "selected" and "needs
   * to be set by the user". `*Configured` flags track whether the user has
   * explicitly picked the value (vs. just inheriting a default), which is
   * what we gate the recording flow on.
   */
  sourceLanguage: string;
  setSourceLanguage: (lang: string) => void;
  sourceLanguageConfigured: boolean;
  userLanguageConfigured: boolean;
  /** True when both source and target languages have been explicitly set by the user. */
  languagesConfigured: boolean;

  // UI preferences
  showConfidenceIndicator: boolean;
  toggleConfidenceIndicator: (checked: boolean) => void;

  // Beta features
  betaFeatures: BetaFeatures;
  toggleBetaFeature: (featureKey: BetaFeatureKey, enabled: boolean) => void;

  // Summary configuration
  isAutoSummary: boolean;
  toggleIsAutoSummary: (checked: boolean) => void;

  // Provider-specific API keys
  providerApiKeys: {
    claude: string | null;
    groq: string | null;
    openai: string | null;
    openrouter: string | null;
  };
  updateProviderApiKey: (provider: string, apiKey: string | null) => void;

  // Preference settings (lazy loaded)
  notificationSettings: NotificationSettings | null;
  storageLocations: StorageLocations | null;
  isLoadingPreferences: boolean;
  loadPreferences: () => Promise<void>;
  updateNotificationSettings: (settings: NotificationSettings) => Promise<void>;
}

const ConfigContext = createContext<ConfigContextType | undefined>(undefined);


export function ConfigProvider({ children }: { children: ReactNode }) {
  // Model configuration state
  const [modelConfig, setModelConfig] = useState<ModelConfig>({
    provider: 'relay-ai',
    // Placeholder identifier shown in-app. The real backing model tag is
    // resolved server-side by the Rust gateway path — keep UI-level code
    // model-agnostic.
    model: 'relay-ai',
    whisperModel: 'large-v3',
    relayAIEndpoint: '',
    relayAIModel: 'relay-ai',
    relayAIApiKey: null,
  });

  // Transcript model configuration state
  const [transcriptModelConfig, setTranscriptModelConfig] = useState<TranscriptModelProps>({
    provider: 'cnn-stt',
    model: DEFAULT_CNN_STT_MODEL,
    apiKey: null
  });

  // Provider-specific API keys (loaded once at startup)
  // Note: Gemini omitted for now - add when UI support is added
  const [providerApiKeys, setProviderApiKeys] = useState<{
    claude: string | null;
    groq: string | null;
    openai: string | null;
    openrouter: string | null;
  }>({
    claude: null,
    groq: null,
    openai: null,
    openrouter: null,
  });

  // Device configuration state
  const [selectedDevices, setSelectedDevices] = useState<SelectedDevices>({
    micDevice: null,
    systemDevice: null
  });

  // Language preference state
  const [selectedLanguage, setSelectedLanguage] = useState<string>(() => {
    if (typeof window !== 'undefined') {
      const saved = localStorage.getItem('primaryLanguage');
      return saved || 'auto';
    }
    return 'auto';
  });

  const [liveCoachingIntentLanguage, setLiveCoachingIntentLanguageState] = useState<string>(() => {
    if (typeof window !== 'undefined') {
      const saved =
        localStorage.getItem('liveCoachingIntentLanguage') ??
        localStorage.getItem('liveTranslateTargetLabel');
      return saved || DEFAULT_LIVE_COACHING_INTENT_LANGUAGE;
    }
    return DEFAULT_LIVE_COACHING_INTENT_LANGUAGE;
  });

  const [liveCoachingEnabled, setLiveCoachingEnabledState] = useState<boolean>(() => {
    if (typeof window !== 'undefined') {
      return localStorage.getItem('liveCoachingEnabled') === 'true';
    }
    return false;
  });

  // Keep translation enabled by default to preserve the existing behavior.
  const [translationEnabled, setTranslationEnabledState] = useState<boolean>(() => {
    if (typeof window !== 'undefined') {
      const saved = localStorage.getItem('translationEnabled');
      return saved !== null ? saved === 'true' : true;
    }
    return true;
  });
  const [translatorWarming, setTranslatorWarming] = useState<boolean>(false);

  // Use a deterministic initial value during SSR to avoid hydration mismatch,
  // then update from localStorage or navigator.language after mount.
  const [userLanguage, setUserLanguageState] = useState<string>('ko');

  // Source language is currently locked to English (the only thing the
  // STT pipeline supports), but we still track an explicit "user picked
  // it" flag so the onboarding flow can require an explicit click on the
  // selector before recording is allowed.
  const [sourceLanguage, setSourceLanguageState] = useState<string>('en');
  const [sourceLanguageConfigured, setSourceLanguageConfiguredState] = useState<boolean>(() => {
    if (typeof window !== 'undefined') {
      return localStorage.getItem('sourceLanguageConfigured') === 'true';
    }
    return false;
  });

  // `userLanguageConfigured` lags behind `userLanguage`: existing installs
  // already have a `userLanguage` value persisted (from the old toggle
  // button) and we don't want to retroactively force them through a
  // re-onboarding step. Treat any prior `userLanguage` localStorage
  // entry as "configured" so upgrades are silent; new installs land on
  // false and have to pick before recording works.
  const [userLanguageConfigured, setUserLanguageConfiguredState] = useState<boolean>(false);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    const saved = localStorage.getItem('userLanguage');
    if (saved === 'ko' || saved === 'en') {
      // Hydrate the value so downstream consumers (LiveTranscript-
      // Translation, summary requests) keep working, but DO NOT mark it
      // as user-configured. Upgraders should re-confirm their subtitle
      // language explicitly via the new picker — the dropdown is
      // intentionally the single source of truth for "this user knows
      // what target language they want".
      setUserLanguageState(saved);
      return;
    }
    const navLang = (navigator.language || 'en').toLowerCase();
    setUserLanguageState(navLang.startsWith('ko') ? 'ko' : 'en');
  }, []);

  // UI preferences state
  const [showConfidenceIndicator, setShowConfidenceIndicator] = useState<boolean>(() => {
    if (typeof window !== 'undefined') {
      const saved = localStorage.getItem('showConfidenceIndicator');
      return saved !== null ? saved === 'true' : true;
    }
    return true;
  });

  // Summary configs
  const [isAutoSummary, setisAutoSummary] = useState<boolean>(() => {
    if (typeof window !== 'undefined') {
      const saved = localStorage.getItem('isAutoSummary');
      return saved !== null ? saved === 'true' : false
    }
    return false;
  });

  // Beta features state (localStorage)
  const [betaFeatures, setBetaFeatures] = useState<BetaFeatures>(() => {
    return loadBetaFeatures();
  });

  // Preference settings state (lazy loaded)
  const [notificationSettings, setNotificationSettings] = useState<NotificationSettings | null>(null);
  const [storageLocations, setStorageLocations] = useState<StorageLocations | null>(null);
  const [isLoadingPreferences, setIsLoadingPreferences] = useState(false);
  const preferencesLoadedRef = useRef(false);
  const isLoadingRef = useRef(false);

  // Load transcript configuration on mount
  useEffect(() => {
    const loadTranscriptConfig = async () => {
      try {
        const config = await configService.getTranscriptConfig();
        if (config) {
          console.log('[ConfigContext] Loaded saved transcript config:', config);
          setTranscriptModelConfig({
            provider: config.provider || 'cnn-stt',
            model: config.model || DEFAULT_CNN_STT_MODEL,
            apiKey: config.apiKey || null
          });
        }
      } catch (error) {
        console.error('[ConfigContext] Failed to load transcript config:', error);
      }
    };
    loadTranscriptConfig();
  }, []);

  // Sync language preference to Rust on mount (fixes startup desync bug)
  useEffect(() => {
    if (selectedLanguage) {
      invoke('set_language_preference', { language: selectedLanguage })
        .then(() => {
          console.log('[ConfigContext] Synced language preference to Rust on startup:', selectedLanguage);
        })
        .catch(err => {
          console.error('[ConfigContext] Failed to sync language preference to Rust on startup:', err);
        });
    }
  }, []); 

  // Load model configuration on mount
  useEffect(() => {
    const fetchModelConfig = async () => {
      try {
        const data = await configService.getModelConfig();
        if (data && data.provider) {
          const normalizedProvider = normalizeSummaryProvider(data.provider);

          // If provider is relay-ai, fetch the additional config
          if (normalizedProvider === 'relay-ai') {
            try {
              const customConfig = await configService.getRelayAIConfig();
              if (customConfig) {
                // Merge custom config fields into modelConfig
                console.log('[ConfigContext] Loading Relay AI config:', {
                  endpoint: customConfig.endpoint,
                  model: customConfig.model,
                });
                const resolvedModel = customConfig.model || data.model || '';
                setModelConfig(prev => ({
                  ...prev,
                  provider: normalizedProvider,
                  model: resolvedModel || prev.model,
                  whisperModel: data.whisperModel || prev.whisperModel,
                  relayAIEndpoint: customConfig.endpoint,
                  relayAIModel: customConfig.model,
                  relayAIApiKey: customConfig.apiKey,
                  maxTokens: customConfig.maxTokens,
                  temperature: customConfig.temperature,
                  topP: customConfig.topP,
                }));

                // Seed per-provider model cache from DB
                if (resolvedModel) {
                  const map = JSON.parse(localStorage.getItem('providerModelMap') || '{}');
                  map[normalizedProvider] = resolvedModel;
                  localStorage.setItem('providerModelMap', JSON.stringify(map));
                }

                return; // Early return
              }
            } catch (err) {
              console.error('[ConfigContext] Failed to fetch Relay AI config:', err);
            }
          }

          // For non-relay-ai providers, just set base config
          setModelConfig(prev => ({
            ...prev,
            provider: normalizedProvider,
            model: data.model || prev.model,
            whisperModel: data.whisperModel || prev.whisperModel,
          }));

          // Seed per-provider model cache from DB
          if (data.model) {
            const map = JSON.parse(localStorage.getItem('providerModelMap') || '{}');
            map[normalizedProvider] = data.model;
            localStorage.setItem('providerModelMap', JSON.stringify(map));
          }
        }
      } catch (error) {
        console.error('Failed to fetch saved model config in ConfigContext:', error);
      }
    };
    fetchModelConfig();
  }, []);

  // Load all provider API keys on mount
  useEffect(() => {
    const loadAllApiKeys = async () => {
      try {
        const providers = ['claude', 'groq', 'openai', 'openrouter'];
        const keys = await Promise.all(
          providers.map(p =>
            invoke<string>('api_get_api_key', { provider: p })
              .catch(() => null) // Gracefully handle missing keys
          )
        );

        setProviderApiKeys({
          claude: keys[0],
          groq: keys[1],
          openai: keys[2],
          openrouter: keys[3],
        });
        console.log('[ConfigContext] Loaded provider API keys');
      } catch (error) {
        console.error('[ConfigContext] Failed to load provider API keys:', error);
      }
    };

    loadAllApiKeys();
  }, []);

  // Listen for model config updates from other components
  useEffect(() => {
    const setupListener = async () => {
      const { listen } = await import('@tauri-apps/api/event');
      const unlisten = await listen<ModelConfig>('model-config-updated', (event) => {
        console.log('[ConfigContext] Received model-config-updated event:', event.payload);
        setModelConfig(event.payload);

        // Update provider-specific key when config changes
        if (event.payload.apiKey && event.payload.provider !== 'relay-ai') {
          updateProviderApiKey(event.payload.provider, event.payload.apiKey);
        }
      });
      return unlisten;
    };

    let cleanup: (() => void) | undefined;
    setupListener().then(fn => cleanup = fn);

    return () => {
      cleanup?.();
    };
  }, []);

  // Load device preferences on mount
  useEffect(() => {
    const loadDevicePreferences = async () => {
      try {
        const prefs = await configService.getRecordingPreferences();
        if (prefs && (prefs.preferred_mic_device || prefs.preferred_system_device)) {
          setSelectedDevices({
            micDevice: prefs.preferred_mic_device,
            systemDevice: prefs.preferred_system_device
          });
          console.log('Loaded device preferences:', prefs);
        }
      } catch (error) {
        console.log('No device preferences found or failed to load:', error);
      }
    };
    loadDevicePreferences();
  }, []);

  // Toggle confidence indicator with localStorage persistence
  const toggleConfidenceIndicator = useCallback((checked: boolean) => {
    setShowConfidenceIndicator(checked);
    if (typeof window !== 'undefined') {
      localStorage.setItem('showConfidenceIndicator', checked.toString());
    }
    // Trigger a custom event to notify other components
    window.dispatchEvent(new CustomEvent('confidenceIndicatorChanged', { detail: checked }));
  }, []);

  const toggleIsAutoSummary = useCallback((checked: boolean) => {
    setisAutoSummary(checked);
    if (typeof window !== 'undefined') {
      localStorage.setItem('isAutoSummary', checked.toString());
    }
  }, [])

  // Toggle beta feature with localStorage persistence and analytics
  const toggleBetaFeature = useCallback((featureKey: BetaFeatureKey, enabled: boolean) => {
    setBetaFeatures(prev => {
      const updated = { ...prev, [featureKey]: enabled };
      saveBetaFeatures(updated);

      // Track analytics with specific feature
      Analytics.track('beta_feature_toggled', {
        feature: featureKey,
        enabled: enabled.toString(),
      }).catch(err => console.error('Failed to track beta feature toggle:', err));

      return updated;
    });
  }, []);

  // Update individual provider API key
  const updateProviderApiKey = useCallback((provider: string, apiKey: string | null) => {
    setProviderApiKeys(prev => ({ ...prev, [provider]: apiKey }));
  }, []);

  // Lazy load preference settings (only loads if not already cached)
  const loadPreferences = useCallback(async () => {
    // If already loaded, don't reload
    if (preferencesLoadedRef.current) {
      return;
    }

    // If currently loading, don't start another load
    if (isLoadingRef.current) {
      return;
    }

    isLoadingRef.current = true;
    setIsLoadingPreferences(true);
    try {
      // Load notification settings from backend
      let settings: NotificationSettings | null = null;
      try {
        settings = await invoke<NotificationSettings>('get_notification_settings');
        setNotificationSettings(settings);
      } catch (notifError) {
        console.error('[ConfigContext] Failed to load notification settings:', notifError);
        // Use default values if notification settings fail to load
        setNotificationSettings(null);
      }

      // Load storage locations
      const [dbDir, modelsDir, recordingsDir] = await Promise.all([
        invoke<string>('get_database_directory'),
        invoke<string>('whisper_get_models_directory'),
        invoke<string>('get_default_recordings_folder_path')
      ]);

      setStorageLocations({
        database: dbDir,
        models: modelsDir,
        recordings: recordingsDir
      });

      // Mark as loaded
      preferencesLoadedRef.current = true;
    } catch (error) {
      console.error('[ConfigContext] Failed to load preferences:', error);
    } finally {
      isLoadingRef.current = false;
      setIsLoadingPreferences(false);
    }
  }, []);

  // Update notification settings
  const updateNotificationSettings = useCallback(async (settings: NotificationSettings) => {
    try {
      await invoke('set_notification_settings', { settings });
      setNotificationSettings(settings);
    } catch (error) {
      console.error('[ConfigContext] Failed to update notification settings:', error);
      throw error; // Re-throw so component can handle error
    }
  }, []);

  // Wrapper for setSelectedLanguage that persists to localStorage and syncs to Rust
  const handleSetSelectedLanguage = useCallback((lang: string) => {
    setSelectedLanguage(lang);
    if (typeof window !== 'undefined') {
      localStorage.setItem('primaryLanguage', lang);
    }
    // Sync with Rust in-memory state for live recording
    invoke('set_language_preference', { language: lang }).catch(err =>
      console.error('Failed to sync language preference to Rust:', err)
    );
  }, []);

  const setLiveCoachingIntentLanguage = useCallback((label: string) => {
    setLiveCoachingIntentLanguageState(label);
    if (typeof window !== 'undefined') {
      localStorage.setItem('liveCoachingIntentLanguage', label);
    }
  }, []);

  const setLiveCoachingEnabled = useCallback((enabled: boolean) => {
    setLiveCoachingEnabledState(enabled);
    if (typeof window !== 'undefined') {
      localStorage.setItem('liveCoachingEnabled', enabled ? 'true' : 'false');
    }
  }, []);

  const setTranslationEnabled = useCallback((enabled: boolean) => {
    setTranslationEnabledState(enabled);
    if (typeof window !== 'undefined') {
      localStorage.setItem('translationEnabled', enabled ? 'true' : 'false');
    }
    if (enabled) {
      // Wake the Modal translate container before the user starts speaking
      // again — without this, the first translate call after toggling on
      // pays the 70s+ cold-start while STT subtitles already stream past.
      setTranslatorWarming(true);
      invoke('warmup_translate')
        .catch((err) => {
          console.warn('warmup_translate failed:', err);
        })
        .finally(() => {
          setTranslatorWarming(false);
        });
    }
  }, []);

  const setUserLanguage = useCallback((lang: string) => {
    // Ignore unsupported values for now; only Korean and English are supported.
    if (lang !== 'ko' && lang !== 'en') return;
    setUserLanguageState(lang);
    setUserLanguageConfiguredState(true);
    if (typeof window !== 'undefined') {
      localStorage.setItem('userLanguage', lang);
    }
  }, []);

  const setSourceLanguage = useCallback((lang: string) => {
    // Source is locked to English at the STT layer; we still go through
    // a setter so the "configured" flag flips when the user explicitly
    // picks the option from the dropdown.
    if (lang !== 'en') return;
    setSourceLanguageState(lang);
    setSourceLanguageConfiguredState(true);
    if (typeof window !== 'undefined') {
      localStorage.setItem('sourceLanguageConfigured', 'true');
    }
  }, []);

  const languagesConfigured = sourceLanguageConfigured && userLanguageConfigured;

  const value: ConfigContextType = useMemo(() => ({
    modelConfig,
    setModelConfig,
    isAutoSummary,
    toggleIsAutoSummary,
    providerApiKeys,
    updateProviderApiKey,
    transcriptModelConfig,
    setTranscriptModelConfig,
    selectedDevices,
    setSelectedDevices,
    selectedLanguage,
    setSelectedLanguage: handleSetSelectedLanguage,
    liveCoachingIntentLanguage,
    setLiveCoachingIntentLanguage,
    liveCoachingEnabled,
    setLiveCoachingEnabled,
    translationEnabled,
    setTranslationEnabled,
    translatorWarming,
    userLanguage,
    setUserLanguage,
    sourceLanguage,
    setSourceLanguage,
    sourceLanguageConfigured,
    userLanguageConfigured,
    languagesConfigured,
    showConfidenceIndicator,
    toggleConfidenceIndicator,
    betaFeatures,
    toggleBetaFeature,
    notificationSettings,
    storageLocations,
    isLoadingPreferences,
    loadPreferences,
    updateNotificationSettings,
  }), [
    modelConfig,
    isAutoSummary,
    toggleIsAutoSummary,
    providerApiKeys,
    updateProviderApiKey,
    transcriptModelConfig,
    selectedDevices,
    selectedLanguage,
    handleSetSelectedLanguage,
    liveCoachingIntentLanguage,
    setLiveCoachingIntentLanguage,
    liveCoachingEnabled,
    setLiveCoachingEnabled,
    translationEnabled,
    setTranslationEnabled,
    translatorWarming,
    userLanguage,
    setUserLanguage,
    sourceLanguage,
    setSourceLanguage,
    sourceLanguageConfigured,
    userLanguageConfigured,
    languagesConfigured,
    showConfidenceIndicator,
    toggleConfidenceIndicator,
    betaFeatures,
    toggleBetaFeature,
    notificationSettings,
    storageLocations,
    isLoadingPreferences,
    loadPreferences,
    updateNotificationSettings,
  ]);

  return (
    <ConfigContext.Provider value={value}>
      {children}
    </ConfigContext.Provider>
  );
}

export function useConfig() {
  const context = useContext(ConfigContext);
  if (context === undefined) {
    throw new Error('useConfig must be used within a ConfigProvider');
  }
  return context;
}
