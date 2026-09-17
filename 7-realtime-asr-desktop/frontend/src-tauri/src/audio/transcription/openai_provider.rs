// audio/transcription/openai_provider.rs
//
// OpenAI transcription provider (gpt-4o-transcription, whisper-1, etc.)

use super::provider::{TranscriptResult, TranscriptionError, TranscriptionProvider};
use async_trait::async_trait;
use log::{info, warn};

pub struct OpenAIProvider {
    api_key: String,
    model: String,
}

impl OpenAIProvider {
    pub fn new(api_key: String, model: String) -> Self {
        Self { api_key, model }
    }
}

#[async_trait]
impl TranscriptionProvider for OpenAIProvider {
    async fn transcribe(
        &self,
        audio: Vec<f32>,
        _language: Option<String>,
    ) -> Result<TranscriptResult, TranscriptionError> {
        if audio.is_empty() {
            return Err(TranscriptionError::AudioTooShort {
                samples: 0,
                minimum: 1600,
            });
        }

        let wav_bytes = encode_as_wav(&audio, 16000);

        let part = reqwest::multipart::Part::bytes(wav_bytes)
            .file_name("audio.wav")
            .mime_str("audio/wav")
            .map_err(|e| TranscriptionError::EngineFailed(e.to_string()))?;

        // Do not pass a language hint to OpenAI Whisper. Meetings are frequently
        // mixed-language, and the user's preferred UI language is often the
        // translation target rather than the spoken language. A strong hint can
        // therefore bias the transcript toward the wrong language. Using
        // `response_format=verbose_json` also lets us capture `language` for the
        // frontend's auto-translation decision.
        let form = reqwest::multipart::Form::new()
            .text("model", self.model.clone())
            .text("response_format", "verbose_json")
            .part("file", part);

        let client = reqwest::Client::new();
        let response = client
            .post("https://api.openai.com/v1/audio/transcriptions")
            .header("Authorization", format!("Bearer {}", self.api_key))
            .multipart(form)
            .send()
            .await
            .map_err(|e| TranscriptionError::EngineFailed(format!("Network error: {}", e)))?;

        if !response.status().is_success() {
            let status = response.status();
            let body = response.text().await.unwrap_or_default();
            warn!("OpenAI API error {}: {}", status, body);
            return Err(TranscriptionError::EngineFailed(format!(
                "OpenAI API error {}: {}",
                status, body
            )));
        }

        let json: serde_json::Value = response.json().await.map_err(|e| {
            TranscriptionError::EngineFailed(format!("Failed to parse response: {}", e))
        })?;

        let text = json["text"].as_str().unwrap_or("").to_string();

        // `verbose_json` may return either ISO 639-1 codes or English language
        // names, so normalize both shapes.
        let detected_language = json["language"]
            .as_str()
            .map(|s| normalize_language_code(s));

        info!(
            "OpenAI transcription result (lang={:?}): '{}'",
            detected_language,
            text.trim()
        );

        Ok(TranscriptResult {
            text,
            confidence: None,
            is_partial: false,
            detected_language,
        })
    }

    async fn is_model_loaded(&self) -> bool {
        !self.api_key.is_empty()
    }

    async fn get_current_model(&self) -> Option<String> {
        Some(self.model.clone())
    }

    fn provider_name(&self) -> &'static str {
        "OpenAI"
    }
}

/// Whisper `verbose_json` may return `language` either as:
///   - a full English name (`english`, `korean`, `japanese`, ...)
///   - an ISO 639-1 code (`en`, `ko`, `ja`, ...)
/// Normalize everything to ISO 639-1 when possible and otherwise keep a
/// lowercased fallback value for loose frontend matching.
fn normalize_language_code(raw: &str) -> String {
    let lower = raw.trim().to_lowercase();
    match lower.as_str() {
        "en" | "english" => "en".to_string(),
        "ko" | "korean" => "ko".to_string(),
        "ja" | "japanese" => "ja".to_string(),
        "zh" | "chinese" | "mandarin" => "zh".to_string(),
        "es" | "spanish" => "es".to_string(),
        "fr" | "french" => "fr".to_string(),
        "de" | "german" => "de".to_string(),
        "it" | "italian" => "it".to_string(),
        "pt" | "portuguese" => "pt".to_string(),
        "ru" | "russian" => "ru".to_string(),
        // Pass through two-letter codes as-is.
        s if s.len() == 2 => s.to_string(),
        // Keep other names lowercased for compatibility.
        other => other.to_string(),
    }
}

/// Encode f32 audio samples as a WAV file in memory
fn encode_as_wav(samples: &[f32], sample_rate: u32) -> Vec<u8> {
    let num_channels: u16 = 1;
    let bits_per_sample: u16 = 16;
    let data_size = (samples.len() * 2) as u32;
    let file_size = 36 + data_size;

    let mut buf = Vec::with_capacity(44 + samples.len() * 2);

    // RIFF header
    buf.extend_from_slice(b"RIFF");
    buf.extend_from_slice(&file_size.to_le_bytes());
    buf.extend_from_slice(b"WAVE");

    // fmt chunk
    buf.extend_from_slice(b"fmt ");
    buf.extend_from_slice(&16u32.to_le_bytes());
    buf.extend_from_slice(&1u16.to_le_bytes()); // PCM
    buf.extend_from_slice(&num_channels.to_le_bytes());
    buf.extend_from_slice(&sample_rate.to_le_bytes());
    let byte_rate = sample_rate * num_channels as u32 * bits_per_sample as u32 / 8;
    buf.extend_from_slice(&byte_rate.to_le_bytes());
    let block_align = num_channels * bits_per_sample / 8;
    buf.extend_from_slice(&block_align.to_le_bytes());
    buf.extend_from_slice(&bits_per_sample.to_le_bytes());

    // data chunk
    buf.extend_from_slice(b"data");
    buf.extend_from_slice(&data_size.to_le_bytes());

    // PCM samples: f32 -> i16
    for &s in samples {
        let s = (s * 32767.0).clamp(-32768.0, 32767.0) as i16;
        buf.extend_from_slice(&s.to_le_bytes());
    }

    buf
}
