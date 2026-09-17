/**
 * Configuration Service
 *
 * Handles all configuration-related Tauri backend calls.
 * Pure 1-to-1 wrapper - no error handling changes, exact same behavior as direct invoke calls.
 */

import { invoke } from '@tauri-apps/api/core';
import { TranscriptModelProps } from '@/components/TranscriptSettings';

export interface ModelConfig {
  // Summary provider selection was removed from the UI — all summaries now
  // route through the Relay gateway. This is a fixed discriminant at the
  // type level so callers can't accidentally pass a legacy value like
  // 'openai' / 'claude' / etc. Any old value read from the DB is normalized
  // onto 'relay-ai' in `normalizeSummaryProvider`.
  provider: 'relay-ai';
  model: string;
  whisperModel: string;
  /**
   * @deprecated Use providerApiKeys from ConfigContext instead.
   * This field may contain stale data when provider changes without saving.
   */
  apiKey?: string | null;
  // Relay AI fields — historical storage shape. New code shouldn't rely
  // on these being populated; the Rust backend falls back to
  // `config::gateway_url()` when relayAIEndpoint is null/empty.
  relayAIEndpoint?: string | null;
  relayAIModel?: string | null;
  relayAIApiKey?: string | null;
  maxTokens?: number | null;
  temperature?: number | null;
  topP?: number | null;
}

export interface RelayAIConfig {
  endpoint: string;
  apiKey: string | null;
  model: string;
  maxTokens: number | null;
  temperature: number | null;
  topP: number | null;
}

export interface RecordingPreferences {
  preferred_mic_device: string | null;
  preferred_system_device: string | null;
}

/**
 * Configuration Service
 * Singleton service for managing app configuration
 */
export class ConfigService {
  /**
   * Get saved transcript model configuration
   * @returns Promise with { provider, model, apiKey }
   */
  async getTranscriptConfig(): Promise<TranscriptModelProps> {
    return invoke<TranscriptModelProps>('api_get_transcript_config');
  }

  /**
   * Get saved summary model configuration
   * @returns Promise with { provider, model, whisperModel }
   */
  async getModelConfig(): Promise<ModelConfig> {
    return invoke<ModelConfig>('api_get_model_config');
  }

  /**
   * Get saved audio device preferences
   * @returns Promise with { preferred_mic_device, preferred_system_device }
   */
  async getRecordingPreferences(): Promise<RecordingPreferences> {
    return invoke<RecordingPreferences>('get_recording_preferences');
  }

  /**
   * Get Relay AI configuration
   * @returns Promise with RelayAIConfig or null if not configured
   */
  async getRelayAIConfig(): Promise<RelayAIConfig | null> {
    return invoke<RelayAIConfig | null>('api_get_relay_ai_config');
  }

  /**
   * Save Relay AI configuration
   * @param config - RelayAIConfig to save
   * @returns Promise with result status
   */
  async saveRelayAIConfig(config: RelayAIConfig): Promise<{ status: string; message: string }> {
    return invoke<{ status: string; message: string }>('api_save_relay_ai_config', {
      endpoint: config.endpoint,
      apiKey: config.apiKey,
      model: config.model,
      maxTokens: config.maxTokens,
      temperature: config.temperature,
      topP: config.topP,
    });
  }

  /**
   * Test Relay AI connection
   * @param endpoint - API endpoint URL
   * @param apiKey - Optional API key
   * @param model - Model name
   * @returns Promise with test result
   */
  async testRelayAIConnection(
    endpoint: string,
    apiKey: string | null,
    model: string
  ): Promise<{ status: string; message: string; http_status?: number }> {
    return invoke<{ status: string; message: string; http_status?: number }>('api_test_relay_ai_connection', {
      endpoint,
      apiKey,
      model,
    });
  }
}

// Export singleton instance
export const configService = new ConfigService();
