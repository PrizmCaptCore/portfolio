/// Summary module - handles all meeting summary generation functionality
///
/// This module contains:
/// - LLM client for communicating with hosted AI providers (OpenAI, Claude, Groq, OpenRouter, RelayAI)
/// - Processor for chunking transcripts and generating summaries
/// - Service layer for orchestrating summary generation
/// - Templates for structured meeting summary generation
/// - Tauri commands for frontend integration
use serde::{Deserialize, Serialize};

/// Relay AI-compatible endpoint configuration
/// Stored as JSON in the database and used for connecting to any OpenAI-compatible API server
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RelayAIConfig {
    /// Base URL of the OpenAI-compatible API endpoint (e.g., "http://localhost:8000/v1")
    pub endpoint: String,
    /// API key for authentication (optional if server doesn't require it)
    #[serde(rename = "apiKey")]
    pub api_key: Option<String>,
    /// Model identifier to use (e.g., "gpt-4", "llama-3-70b", "mistral-7b")
    pub model: String,
    /// Maximum tokens for completion (optional)
    #[serde(rename = "maxTokens")]
    pub max_tokens: Option<i32>,
    /// Temperature parameter (0.0-2.0, optional)
    pub temperature: Option<f32>,
    /// Top-P sampling parameter (0.0-1.0, optional)
    #[serde(rename = "topP")]
    pub top_p: Option<f32>,
}

/// Live transcript assistant: intent summary + reply hints (`translation` is always empty; kept for IPC shape).
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct LiveAssistResult {
    pub translation: String,
    pub intent_summary: String,
    pub reply_ideas: Vec<String>,
}

pub mod commands;
pub mod llm_client;
pub mod processor;
pub mod service;
pub mod template_commands;
pub mod templates;

// Re-export Tauri commands. Wildcard pulls in both the public functions and
// every macro-generated sibling symbol — `__cmd__*` (Tauri 1.x) and
// `__tauri_command_name_*` (Tauri 2.x) — so `tauri::generate_handler!` can
// resolve `summary::api_<name>` references in lib.rs without us having to
// hand-maintain the symbol list. Matches the pattern in `api/mod.rs`.
pub use commands::*;
pub use template_commands::*;

// Re-export commonly used items
pub use llm_client::LLMProvider;
pub use processor::{
    chunk_text, clean_llm_markdown_output, extract_meeting_name_from_markdown,
    generate_meeting_summary, rough_token_count,
};
pub use service::SummaryService;
