// audio/transcription/deepgram_provider.rs
//
// Deepgram transcription provider with speaker diarization.

use super::provider::{TranscriptResult, TranscriptionError, TranscriptionProvider};
use async_trait::async_trait;
use log::{info, warn};

pub struct DeepgramProvider {
    api_key: String,
    model: String,
}

impl DeepgramProvider {
    pub fn new(api_key: String, model: String) -> Self {
        Self { api_key, model }
    }
}

#[async_trait]
impl TranscriptionProvider for DeepgramProvider {
    async fn transcribe(
        &self,
        audio: Vec<f32>,
        language: Option<String>,
    ) -> Result<TranscriptResult, TranscriptionError> {
        if audio.is_empty() {
            return Err(TranscriptionError::AudioTooShort {
                samples: 0,
                minimum: 1600,
            });
        }

        let wav_bytes = encode_as_wav(&audio, 16000);

        let lang = language.as_deref().unwrap_or("en");
        let url = format!(
            "https://api.deepgram.com/v1/listen?model={}&language={}&diarize=true&punctuate=true",
            self.model, lang
        );

        let client = reqwest::Client::new();
        let response = client
            .post(&url)
            .header("Authorization", format!("Token {}", self.api_key))
            .header("Content-Type", "audio/wav")
            .body(wav_bytes)
            .send()
            .await
            .map_err(|e| TranscriptionError::EngineFailed(format!("Network error: {}", e)))?;

        if !response.status().is_success() {
            let status = response.status();
            let body = response.text().await.unwrap_or_default();
            warn!("Deepgram API error {}: {}", status, body);
            return Err(TranscriptionError::EngineFailed(format!(
                "Deepgram API error {}: {}",
                status, body
            )));
        }

        let json: serde_json::Value = response.json().await.map_err(|e| {
            TranscriptionError::EngineFailed(format!("Failed to parse response: {}", e))
        })?;

        let words = json["results"]["channels"][0]["alternatives"][0]["words"]
            .as_array()
            .cloned()
            .unwrap_or_default();

        let text = if words.is_empty() {
            json["results"]["channels"][0]["alternatives"][0]["transcript"]
                .as_str()
                .unwrap_or("")
                .to_string()
        } else {
            format_diarized(&words)
        };

        let confidence = json["results"]["channels"][0]["alternatives"][0]["confidence"]
            .as_f64()
            .map(|c| c as f32);

        info!("Deepgram transcription result: '{}'", text.trim());

        Ok(TranscriptResult {
            text,
            confidence,
            is_partial: false,
            detected_language: None,
        })
    }

    async fn is_model_loaded(&self) -> bool {
        !self.api_key.is_empty()
    }

    async fn get_current_model(&self) -> Option<String> {
        Some(self.model.clone())
    }

    fn provider_name(&self) -> &'static str {
        "Deepgram"
    }
}

/// Group words by speaker and format as "[Speaker N] text ..." segments.
/// Falls back to plain text if no speaker info is available.
fn format_diarized(words: &[serde_json::Value]) -> String {
    let mut result = String::new();
    let mut current_speaker: Option<u64> = None;
    let mut current_segment = String::new();

    for word in words {
        let speaker = word["speaker"].as_u64();
        let text = word["punctuated_word"]
            .as_str()
            .or_else(|| word["word"].as_str())
            .unwrap_or("");

        if speaker != current_speaker {
            // Flush previous segment
            if !current_segment.is_empty() {
                if let Some(spk) = current_speaker {
                    if !result.is_empty() {
                        result.push(' ');
                    }
                    result.push_str(&format!("[Speaker {}] {}", spk, current_segment.trim()));
                } else {
                    result.push_str(current_segment.trim());
                }
                current_segment.clear();
            }
            current_speaker = speaker;
        }

        if !current_segment.is_empty() {
            current_segment.push(' ');
        }
        current_segment.push_str(text);
    }

    // Flush last segment
    if !current_segment.is_empty() {
        if let Some(spk) = current_speaker {
            if !result.is_empty() {
                result.push(' ');
            }
            result.push_str(&format!("[Speaker {}] {}", spk, current_segment.trim()));
        } else {
            if !result.is_empty() {
                result.push(' ');
            }
            result.push_str(current_segment.trim());
        }
    }

    result.trim().to_string()
}

fn encode_as_wav(samples: &[f32], sample_rate: u32) -> Vec<u8> {
    let num_channels: u16 = 1;
    let bits_per_sample: u16 = 16;
    let data_size = (samples.len() * 2) as u32;
    let file_size = 36 + data_size;

    let mut buf = Vec::with_capacity(44 + samples.len() * 2);

    buf.extend_from_slice(b"RIFF");
    buf.extend_from_slice(&file_size.to_le_bytes());
    buf.extend_from_slice(b"WAVE");
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
    buf.extend_from_slice(b"data");
    buf.extend_from_slice(&data_size.to_le_bytes());

    for &s in samples {
        let s = (s * 32767.0).clamp(-32768.0, 32767.0) as i16;
        buf.extend_from_slice(&s.to_le_bytes());
    }

    buf
}
