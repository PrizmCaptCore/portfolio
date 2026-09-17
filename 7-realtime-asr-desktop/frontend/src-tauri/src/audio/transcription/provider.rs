// audio/transcription/provider.rs
//
// Defines the unified TranscriptionProvider trait and common types for all
// transcription engines (Whisper, CNN STT, future providers).

use async_trait::async_trait;

// ============================================================================
// TRANSCRIPTION PROVIDER TRAIT & ERROR TYPES
// ============================================================================

/// Granular error types for transcription operations
#[derive(Debug, Clone)]
pub enum TranscriptionError {
    ModelNotLoaded,
    AudioTooShort { samples: usize, minimum: usize },
    EngineFailed(String),
    UnsupportedLanguage(String),
}

impl std::fmt::Display for TranscriptionError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::ModelNotLoaded => write!(f, "No transcription model is loaded"),
            Self::AudioTooShort { samples, minimum } => write!(
                f,
                "Audio too short: {} samples (minimum {})",
                samples, minimum
            ),
            Self::EngineFailed(msg) => write!(f, "Transcription engine failed: {}", msg),
            Self::UnsupportedLanguage(lang) => {
                write!(f, "Language '{}' is not supported by this provider", lang)
            }
        }
    }
}

impl std::error::Error for TranscriptionError {}

/// Unified transcription result across all providers
#[derive(Debug, Clone)]
pub struct TranscriptResult {
    pub text: String,
    pub confidence: Option<f32>, // None if provider doesn't support confidence scores
    pub is_partial: bool,
    pub detected_language: Option<String>,
}

/// Trait for transcription providers (Whisper, CNN STT, future providers)
#[async_trait]
pub trait TranscriptionProvider: Send + Sync {
    /// Transcribe audio samples to text
    ///
    /// # Arguments
    /// * `audio` - Audio samples (16kHz mono, f32 format)
    /// * `language` - Optional language hint (e.g., "en", "es", "fr")
    ///
    /// # Returns
    /// * `TranscriptResult` with text, optional confidence, and partial flag
    async fn transcribe(
        &self,
        audio: Vec<f32>,
        language: Option<String>,
    ) -> std::result::Result<TranscriptResult, TranscriptionError>;

    /// Check if a model is currently loaded
    async fn is_model_loaded(&self) -> bool;

    /// Get the name of the currently loaded model
    async fn get_current_model(&self) -> Option<String>;

    /// Get the provider name (for logging/debugging)
    fn provider_name(&self) -> &'static str;

    /// Whether this provider can be used for real-time partial previews.
    /// Only local models (e.g. CNN STT) should return true — cloud providers
    /// are too slow and expensive to call every 1.5 seconds.
    fn supports_partial(&self) -> bool {
        false
    }

    /// Whether the worker should skip the partial-chunk merge optimization.
    /// Streaming providers (e.g. NemoProvider) do their own buffering server-side;
    /// merging large chunks on the client breaks the server's VAD timing.
    fn prefers_raw_chunks(&self) -> bool {
        false
    }

    /// Reset session state before a new recording session starts.
    /// NemoProvider sends {"cmd":"reset"} to flush server-side VAD buffers.
    async fn reset_session(&self) {}

    /// Tear down any long-lived resources (e.g., WebSocket connections).
    /// Streaming providers should send a close frame and stop reconnecting
    /// so the remote server can start its idle-scaledown timer.
    async fn close(&self) {}
}
