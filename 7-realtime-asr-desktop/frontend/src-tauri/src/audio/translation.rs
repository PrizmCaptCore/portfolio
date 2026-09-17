// audio/translation.rs
//
// English → Korean translation.
// Two backends are supported:
//   1. HttpTranslator  — calls translation_server.py (Ollama/Modal).
//                        Activated when RELAY_TRANSLATION_URL is set.
//   2. MarianTranslator — offline Marian NMT fallback (no env var needed).

use std::sync::{Mutex, OnceLock};

#[cfg(feature = "local-ml")]
use std::collections::HashMap;
#[cfg(feature = "local-ml")]
use std::path::{Path, PathBuf};
#[cfg(feature = "local-ml")]
use candle_core::{DType, Device, Tensor};
#[cfg(feature = "local-ml")]
use candle_nn::VarBuilder;
#[cfg(feature = "local-ml")]
use candle_transformers::models::marian;
use log::info;
#[cfg(feature = "local-ml")]
use tokenizers::Tokenizer;

// ---------------------------------------------------------------------------
// Translator trait
// ---------------------------------------------------------------------------

pub trait Translator: Send + Sync {
    fn translate(&self, text: &str) -> Result<String, String>;
}

// ---------------------------------------------------------------------------
// HttpTranslator — delegates to translation_server.py
// ---------------------------------------------------------------------------

pub struct HttpTranslator {
    url: String,
    // Client is initialized lazily on the first translate() call.
    // reqwest::blocking::Client::build() creates an internal Tokio runtime and
    // panics if called from inside an existing async context (e.g. tokio::spawn).
    // translate() is always called from std::thread::spawn, so lazy init is safe.
    client: OnceLock<reqwest::blocking::Client>,
    // Serialize requests so only one HTTP call is in flight at a time.
    // Prevents overwhelming the backend (Ollama processes one inference at a time)
    // and avoids timeouts caused by queued requests on the server.
    gate: Mutex<()>,
}

impl HttpTranslator {
    pub fn new(base_url: &str) -> Self {
        // Gateway endpoint expects trailing slash: /api/v1/ai/translate/
        let base = base_url.trim_end_matches('/');
        let url = if base.ends_with("/ai") || base.ends_with("/v1/ai") {
            format!("{}/translate/", base)
        } else {
            format!("{}/translate", base)
        };
        info!("HttpTranslator: endpoint = {}", url);
        Self {
            url,
            client: OnceLock::new(),
            gate: Mutex::new(()),
        }
    }

    /// Read JWT access token from the auth.json store written by AuthContext.
    fn read_access_token(&self) -> Option<String> {
        crate::config::read_access_token_global()
    }

    fn client(&self) -> &reqwest::blocking::Client {
        self.client.get_or_init(|| {
            reqwest::blocking::Client::builder()
                .timeout(std::time::Duration::from_secs(60))
                .build()
                .expect("reqwest blocking client")
        })
    }
}

impl Translator for HttpTranslator {
    fn translate(&self, text: &str) -> Result<String, String> {
        if text.trim().is_empty() {
            return Ok(String::new());
        }
        let _guard = self.gate.lock().map_err(|e| format!("mutex poisoned: {}", e))?;
        let body = serde_json::json!({ "text": text });
        let mut req = self.client().post(&self.url).json(&body);
        if let Some(token) = self.read_access_token() {
            req = req.bearer_auth(token);
        }
        let resp = req
            .send()
            .map_err(|e| format!("HTTP send error: {}", e))?;

        if !resp.status().is_success() {
            return Err(format!("Translation server returned {}", resp.status()));
        }

        let json: serde_json::Value = resp.json()
            .map_err(|e| format!("JSON parse error: {}", e))?;

        json["translation"]
            .as_str()
            .map(|s| s.trim().to_string())
            .ok_or_else(|| "Missing 'translation' field in response".to_string())
    }
}

// ---------------------------------------------------------------------------
// Marian NMT offline fallback (gated behind `local-ml`). Everything below this
// banner down to the next `// === END local-ml ===` marker only compiles when
// the feature is enabled — release builds skip it entirely.
// ---------------------------------------------------------------------------

#[cfg(feature = "local-ml")]
fn en_ko_config() -> marian::Config {
    marian::Config {
        vocab_size: 32001,
        decoder_vocab_size: Some(32001),
        d_model: 1024,
        encoder_layers: 6,
        decoder_layers: 6,
        encoder_attention_heads: 16,
        decoder_attention_heads: 16,
        encoder_ffn_dim: 4096,
        decoder_ffn_dim: 4096,
        activation_function: candle_nn::Activation::Relu,
        max_position_embeddings: 1024,
        eos_token_id: 2,
        forced_eos_token_id: 2,
        decoder_start_token_id: 32000,
        is_encoder_decoder: true,
        pad_token_id: 32000,
        scale_embedding: true,
        share_encoder_decoder_embeddings: true,
        use_cache: true,
    }
}

// ---------------------------------------------------------------------------
// Translator
// ---------------------------------------------------------------------------

#[cfg(feature = "local-ml")]
pub struct MarianTranslator {
    model: Mutex<marian::MTModel>,
    tokenizer: Tokenizer,
    /// id → token mapping for decoding output
    id_to_token: Vec<String>,
    config: marian::Config,
    device: Device,
}

#[cfg(feature = "local-ml")]
unsafe impl Send for MarianTranslator {}
#[cfg(feature = "local-ml")]
unsafe impl Sync for MarianTranslator {}

#[cfg(feature = "local-ml")]
impl MarianTranslator {
    pub fn new(model_dir: &Path) -> Result<Self, String> {
        let (device, dtype) = select_device_and_dtype();
        let config = en_ko_config();

        // Load model weights
        let model_path = model_dir.join("model.safetensors");
        if !model_path.exists() {
            return Err(format!("model.safetensors not found in {}", model_dir.display()));
        }

        info!(
            "Loading Marian EN→KO on {:?} with dtype {:?}",
            device, dtype
        );

        let vb = unsafe {
            VarBuilder::from_mmaped_safetensors(&[&model_path], dtype, &device)
                .map_err(|e| format!("Failed to load model weights: {}", e))?
        };

        let model = marian::MTModel::new(&config, vb)
            .map_err(|e| format!("Failed to create Marian model: {}", e))?;

        // Load tokenizer (JSON format, converted from SentencePiece)
        let tokenizer_path = model_dir.join("tokenizer.json");
        if !tokenizer_path.exists() {
            return Err(format!(
                "tokenizer.json not found in {}. Run: python scripts/setup_translation_model.py",
                model_dir.display()
            ));
        }
        let tokenizer = Tokenizer::from_file(&tokenizer_path)
            .map_err(|e| format!("Failed to load tokenizer: {}", e))?;

        // Load vocab.json for id → token decoding
        let vocab_path = model_dir.join("vocab.json");
        let id_to_token = load_vocab(&vocab_path)?;

        info!(
            "Marian EN→KO translator ready: vocab_size={}",
            id_to_token.len()
        );

        Ok(Self {
            model: Mutex::new(model),
            tokenizer,
            id_to_token,
            config,
            device,
        })
    }

    /// Translate English text to Korean.
    pub fn translate(&self, text: &str) -> Result<String, String> {
        if text.trim().is_empty() {
            return Ok(String::new());
        }

        let mut model = self.model.lock().map_err(|e| format!("Model lock: {}", e))?;

        // Each call is an independent generation — clear stale KV from prior sentences.
        // Without this, attention cost scales with total history and quality degrades.
        model.reset_kv_cache();

        // Encode input
        let encoding = self.tokenizer
            .encode(text, true)
            .map_err(|e| format!("Tokenizer encode: {}", e))?;
        let mut token_ids: Vec<u32> = encoding.get_ids().to_vec();
        token_ids.push(self.config.eos_token_id as u32);

        let input_ids = Tensor::new(token_ids.as_slice(), &self.device)
            .map_err(|e| format!("Input tensor: {}", e))?
            .unsqueeze(0)
            .map_err(|e| format!("Unsqueeze: {}", e))?;

        // Encoder forward pass
        let encoder_out = model.encoder().forward(&input_ids, 0)
            .map_err(|e| format!("Encoder forward: {}", e))?;

        // Decoder: greedy generation
        let mut logits_processor =
            candle_transformers::generation::LogitsProcessor::new(42, None, None);

        let mut output_ids = vec![self.config.decoder_start_token_id as u32];
        let max_length = 512;

        for index in 0..max_length {
            let context_size = if index >= 1 { 1 } else { output_ids.len() };
            let start_pos = output_ids.len().saturating_sub(context_size);
            let decoder_input = Tensor::new(&output_ids[start_pos..], &self.device)
                .map_err(|e| format!("Decoder input: {}", e))?
                .unsqueeze(0)
                .map_err(|e| format!("Decoder unsqueeze: {}", e))?;

            let logits = model.decode(&decoder_input, &encoder_out, start_pos)
                .map_err(|e| format!("Decoder forward: {}", e))?;
            let logits = logits.squeeze(0)
                .map_err(|e| format!("Squeeze: {}", e))?;
            let logits = logits.get(logits.dim(0).map_err(|e| format!("Dim: {}", e))? - 1)
                .map_err(|e| format!("Get last: {}", e))?;

            let token = logits_processor.sample(&logits)
                .map_err(|e| format!("Sample: {}", e))?;
            output_ids.push(token);

            if token == self.config.eos_token_id as u32
                || token == self.config.forced_eos_token_id as u32
            {
                break;
            }
        }

        // Decode output tokens using vocab
        let translated: String = output_ids[1..]
            .iter()
            .filter(|&&t| {
                t != self.config.eos_token_id as u32
                    && t != self.config.pad_token_id as u32
                    && t != self.config.decoder_start_token_id as u32
            })
            .filter_map(|&t| self.id_to_token.get(t as usize))
            .cloned()
            .collect::<Vec<_>>()
            .join("")
            .replace("▁", " ");

        Ok(translated.trim().to_string())
    }
}

#[cfg(feature = "local-ml")]
impl Translator for MarianTranslator {
    fn translate(&self, text: &str) -> Result<String, String> {
        self.translate(text)
    }
}

/// Pick the best available device + dtype for this platform.
/// candle-transformers' marian module hardcodes F32 masks (breaks F16/BF16) and
/// Metal lacks softmax-last-dim coverage, so CPU + F32 is the only combination
/// that currently works end-to-end.
#[cfg(feature = "local-ml")]
fn select_device_and_dtype() -> (Device, DType) {
    (Device::Cpu, DType::F32)
}

/// Load vocab.json as id → token mapping.
#[cfg(feature = "local-ml")]
fn load_vocab(path: &Path) -> Result<Vec<String>, String> {
    let content = std::fs::read_to_string(path)
        .map_err(|e| format!("Cannot read {}: {}", path.display(), e))?;
    let map: HashMap<String, usize> = serde_json::from_str(&content)
        .map_err(|e| format!("Parse vocab.json: {}", e))?;

    let max_id = map.values().copied().max().unwrap_or(0);
    let mut vocab = vec![String::new(); max_id + 1];
    for (token, id) in map {
        if id < vocab.len() {
            vocab[id] = token;
        }
    }
    info!("Loaded translation vocab: {} tokens", vocab.len());
    Ok(vocab)
}

// === END local-ml =========================================================

// ---------------------------------------------------------------------------
// Global singleton
// ---------------------------------------------------------------------------

use std::sync::Arc;

static TRANSLATOR: OnceLock<Result<Arc<dyn Translator>, String>> = OnceLock::new();

/// Get (or lazily initialize) the global translator.
///
/// Priority:
///   1. RELAY_TRANSLATION_URL env var → HttpTranslator (translation_server.py)
///   2. Local Marian NMT model directory → MarianTranslator (offline fallback)
pub fn get_or_init_translator() -> Result<Arc<dyn Translator>, String> {
    TRANSLATOR
        .get_or_init(|| {
            // 1. HTTP backend (gateway → Modal). Always enabled: release builds
            //    use the baked-in default from config::gateway_url(), dev can
            //    still override via RELAY_TRANSLATION_URL env var.
            let url = crate::config::gateway_url();
            info!("Using HTTP translation backend: {}", url);
            #[cfg(not(feature = "local-ml"))]
            {
                Ok(Arc::new(HttpTranslator::new(&url)) as Arc<dyn Translator>)
            }
            #[cfg(feature = "local-ml")]
            {
                return Ok(Arc::new(HttpTranslator::new(&url)) as Arc<dyn Translator>);

                // Offline Marian fallback (kept for reference but unreachable
                // now that gateway_url() always returns a value).
                #[allow(unreachable_code)]
                {
                    let dir = find_translation_model_dir().ok_or_else(|| {
                        "Translation model not found. Set RELAY_TRANSLATION_URL or run: \
                         python scripts/setup_translation_model.py"
                            .to_string()
                    })?;
                    info!("Using offline Marian NMT translator");
                    MarianTranslator::new(&dir)
                        .map(|t| Arc::new(t) as Arc<dyn Translator>)
                }
            }
        })
        .clone()
}

/// Find the translation model directory.
#[cfg(feature = "local-ml")]
pub fn find_translation_model_dir() -> Option<PathBuf> {
    if let Ok(value) = std::env::var("RELAY_TRANSLATION_MODEL_DIR") {
        let path = PathBuf::from(&value);
        if path.is_dir() {
            return Some(path);
        }
    }

    let prefixes = ["opus-mt-tc-big-en-ko", "opus-mt-en-ko", "marian-en-ko"];

    if let Ok(exe) = std::env::current_exe() {
        if let Some(exe_dir) = exe.parent() {
            let up_dirs = [
                exe_dir.to_path_buf(),
                exe_dir.join(".."),
                exe_dir.join("..").join(".."),
                exe_dir.join("..").join("..").join(".."),
                exe_dir.join("..").join("..").join("..").join(".."),
            ];
            for prefix in &prefixes {
                for dir in &up_dirs {
                    if let Ok(entries) = std::fs::read_dir(dir) {
                        for entry in entries.flatten() {
                            let name = entry.file_name();
                            if name.to_string_lossy().contains(prefix) && entry.path().is_dir() {
                                return Some(entry.path());
                            }
                        }
                    }
                }
            }
        }
    }

    None
}

// ---------------------------------------------------------------------------
// Translate warmup (called when the user toggles translation OFF -> ON)
// ---------------------------------------------------------------------------

/// Kick the gateway to wake the Modal translate container, then poll
/// `/translate/ready/` until it reports ready (or 180s deadline elapses).
/// Called from the frontend translation toggle's OFF→ON handler so the
/// first real translate call doesn't have to absorb the 70s+ cold-start.
#[tauri::command]
pub async fn warmup_translate() -> Result<(), String> {
    let gateway = crate::config::gateway_url();
    let base = gateway.trim_end_matches('/').to_string();
    let warmup_url = format!("{}/translate/warmup/", base);
    let ready_url = format!("{}/translate/ready/", base);

    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(10))
        .build()
        .map_err(|e| format!("reqwest build: {}", e))?;

    // Fire warmup (fire-and-forget — gateway returns 200 immediately and
    // pings Modal in a background thread). Read token per call so the 3-min
    // ready-poll loop picks up any refresh the frontend performs mid-flight.
    let initial_token = crate::config::read_access_token_global()
        .ok_or_else(|| "not_authenticated".to_string())?;
    let _ = client.post(&warmup_url).bearer_auth(&initial_token).send().await;

    let deadline = std::time::Instant::now() + std::time::Duration::from_secs(180);
    loop {
        let token = crate::config::read_access_token_global()
            .ok_or_else(|| "not_authenticated".to_string())?;
        if let Ok(resp) = client.get(&ready_url).bearer_auth(&token).send().await {
            if resp.status().is_success() {
                info!("Translate container ready");
                return Ok(());
            }
        }
        if std::time::Instant::now() >= deadline {
            return Err("warmup_timeout".into());
        }
        tokio::time::sleep(std::time::Duration::from_secs(5)).await;
    }
}

