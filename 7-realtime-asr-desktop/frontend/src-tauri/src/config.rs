/// Application configuration constants
///
/// Centralized definitions for default models and settings.
/// Used across database initialization, import, and retranscription.

/// Production relay_web AI gateway. Used as the default when
/// `RELAY_TRANSLATION_URL` isn't set (e.g., in release builds that don't
/// ship a .env). `make dev-cloud` can still override via env.
pub const DEFAULT_GATEWAY_URL: &str = "https://api.example.com/api/v1/ai";

/// Resolve the gateway URL: env var if set, otherwise the baked-in default.
pub fn gateway_url() -> String {
    std::env::var("RELAY_TRANSLATION_URL")
        .unwrap_or_else(|_| DEFAULT_GATEWAY_URL.to_string())
}

/// Read the JWT access token straight off disk so every call sees what
/// `AuthContext` most recently persisted. Going through `app.store()` hits an
/// in-process Tauri store cache that doesn't reliably reflect frontend writes,
/// which causes Rust polling loops to keep sending a stale (expired) token.
///
/// The 30-minute JWT is refreshed proactively by the frontend (timer + pre-
/// request check in `apiClient.ts`), so long-running Rust loops must re-read
/// this on each iteration to pick up the new token — never capture once and
/// reuse for the life of the function.
pub fn read_access_token<R: tauri::Runtime>(app: &tauri::AppHandle<R>) -> Option<String> {
    use tauri::Manager;
    let data_dir = app.path().app_data_dir().ok()?;
    let path = data_dir.join("auth.json");
    let contents = std::fs::read_to_string(&path).ok()?;
    let v: serde_json::Value = serde_json::from_str(&contents).ok()?;
    v.get("access_token")?.as_str().map(|s| s.to_string())
}

/// `read_access_token` variant for call sites that don't carry an `AppHandle`
/// (lazy-initialized translators, background tasks). Resolves the same
/// directory that Tauri's `app_data_dir()` uses on each platform:
///   - macOS:   ~/Library/Application Support/<bundle_id>/auth.json
///   - Windows: %APPDATA%\<bundle_id>\auth.json
///   - Linux:   $XDG_DATA_HOME/<bundle_id>/auth.json (or ~/.local/share/…)
pub fn read_access_token_global() -> Option<String> {
    let path = dirs::data_dir()?
        .join("com.relay.assistant")
        .join("auth.json");
    let contents = std::fs::read_to_string(&path).ok()?;
    let v: serde_json::Value = serde_json::from_str(&contents).ok()?;
    v.get("access_token")?.as_str().map(|s| s.to_string())
}

/// Default Whisper model for transcription when no preference is configured.
/// This is the recommended balance of accuracy and speed.
pub const DEFAULT_WHISPER_MODEL: &str = "large-v3-turbo";

/// Default CNN STT model for transcription when no preference is configured.
/// This is the quantized version optimized for speed.
pub const DEFAULT_CNN_STT_MODEL: &str = "cnn-stt-0.6b-int8";

/// Whisper model catalog with metadata for all supported models.
/// Used by both WhisperEngine::discover_models() and discover_models_standalone().
///
/// Format: (name, filename, size_mb, accuracy, speed, description)
pub const WHISPER_MODEL_CATALOG: &[(&str, &str, u32, &str, &str, &str)] = &[
    // Standard f16 models (full precision)
    (
        "tiny",
        "ggml-tiny.bin",
        74,
        "Decent",
        "Very Fast",
        "Fastest processing, good for real-time use",
    ),
    (
        "base",
        "ggml-base.bin",
        142,
        "Good",
        "Fast",
        "Good balance of speed and accuracy",
    ),
    (
        "small",
        "ggml-small.bin",
        466,
        "Good",
        "Medium",
        "Better accuracy, moderate speed",
    ),
    (
        "medium",
        "ggml-medium.bin",
        1463,
        "High",
        "Slow",
        "High accuracy for professional use",
    ),
    (
        "large-v3-turbo",
        "ggml-large-v3-turbo.bin",
        1549,
        "High",
        "Medium",
        "Best accuracy with improved speed",
    ),
    (
        "large-v3",
        "ggml-large-v3.bin",
        2951,
        "High",
        "Slow",
        "Most Accurate, latest large model",
    ),
    // Q5_1 quantized models (balanced speed/accuracy, slightly better quality than Q5_0)
    (
        "tiny-q5_1",
        "ggml-tiny-q5_1.bin",
        31,
        "Decent",
        "Very Fast",
        "Quantized tiny model, ~50% faster processing",
    ),
    (
        "base-q5_1",
        "ggml-base-q5_1.bin",
        57,
        "Good",
        "Fast",
        "Quantized base model, good speed/accuracy balance",
    ),
    (
        "small-q5_1",
        "ggml-small-q5_1.bin",
        181,
        "Good",
        "Fast",
        "Quantized small model, faster than f16 version",
    ),
    // Q5_0 quantized models (balanced speed/accuracy)
    (
        "medium-q5_0",
        "ggml-medium-q5_0.bin",
        514,
        "High",
        "Medium",
        "Quantized medium model, professional quality",
    ),
    (
        "large-v3-turbo-q5_0",
        "ggml-large-v3-turbo-q5_0.bin",
        547,
        "High",
        "Medium",
        "Quantized large model, best balance",
    ),
    (
        "large-v3-q5_0",
        "ggml-large-v3-q5_0.bin",
        1031,
        "High",
        "Slow",
        "Quantized large model, high accuracy",
    ),
];
