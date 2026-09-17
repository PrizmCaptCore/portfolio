// audio/transcription/mod.rs
//
// Transcription module: OpenAI provider, engine management, and worker pool.

pub mod deepgram_provider;
pub mod engine;
pub mod nemo_provider;
pub mod openai_provider;
pub mod provider;
pub mod silence;
pub mod worker;

pub use deepgram_provider::DeepgramProvider;
pub use engine::{
    close_nemo_provider, get_or_init_transcription_engine, validate_transcription_model_ready,
    TranscriptionEngine,
};
pub use nemo_provider::NemoProvider;
pub use openai_provider::OpenAIProvider;
pub use provider::{TranscriptResult, TranscriptionError, TranscriptionProvider};
pub use worker::{reset_speech_detected_flag, start_transcription_task, TranscriptUpdate};
