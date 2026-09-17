use reqwest::{header, Client};
use serde::{Deserialize, Serialize};
use std::time::Duration;
use tokio_util::sync::CancellationToken;
use tracing::info;

/// Read JWT access token from Tauri store (auth.json written by AuthContext).
fn read_gateway_jwt() -> Option<String> {
    crate::config::read_access_token_global()
}

const REQUEST_TIMEOUT_DURATION: Duration = Duration::from_secs(300);

// Generic structure for OpenAI-compatible API chat messages
#[derive(Debug, Serialize)]
pub struct ChatMessage {
    pub role: String,
    pub content: String,
}

// Generic structure for OpenAI-compatible API chat requests
#[derive(Debug, Serialize)]
pub struct ChatRequest {
    pub model: String,
    pub messages: Vec<ChatMessage>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub max_tokens: Option<u32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub temperature: Option<f32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub top_p: Option<f32>,
}

// Generic structure for OpenAI-compatible API chat responses
#[derive(Deserialize, Debug)]
pub struct ChatResponse {
    pub choices: Vec<Choice>,
}

#[derive(Deserialize, Debug)]
pub struct Choice {
    pub message: MessageContent,
}

#[derive(Deserialize, Debug)]
pub struct MessageContent {
    pub content: String,
}

// Claude-specific request structure
#[derive(Debug, Serialize)]
pub struct ClaudeRequest {
    pub model: String,
    pub max_tokens: u32,
    pub system: String,
    pub messages: Vec<ChatMessage>,
}

// Claude-specific response structure
#[derive(Deserialize, Debug)]
pub struct ClaudeChatResponse {
    pub content: Vec<ClaudeChatContent>,
}

#[derive(Deserialize, Debug)]
pub struct ClaudeChatContent {
    pub text: String,
}

/// LLM Provider enumeration for multi-provider support
#[derive(Debug, Clone, PartialEq)]
pub enum LLMProvider {
    OpenAI,
    Claude,
    Groq,
    OpenRouter,
    RelayAI,
}

impl LLMProvider {
    /// Parse provider from string (case-insensitive)
    pub fn from_str(s: &str) -> Result<Self, String> {
        match s.to_lowercase().as_str() {
            "openai" => Ok(Self::OpenAI),
            "claude" => Ok(Self::Claude),
            "groq" => Ok(Self::Groq),
            "openrouter" => Ok(Self::OpenRouter),
            "relay-ai" | "custom-openai" => Ok(Self::RelayAI),
            _ => Err(format!("Unsupported LLM provider: {}", s)),
        }
    }
}

pub fn normalize_provider_name(provider: &str) -> String {
    match provider.trim().to_ascii_lowercase().as_str() {
        "openai" => "openai".to_string(),
        "claude" => "claude".to_string(),
        "groq" => "groq".to_string(),
        "openrouter" => "openrouter".to_string(),
        "relay-ai" => "relay-ai".to_string(),
        // Legacy alias: rows written before the rename store "custom-openai".
        "custom-openai" => "relay-ai".to_string(),
        _ => "relay-ai".to_string(),
    }
}

/// Newer OpenAI models require `max_completion_tokens` instead of `max_tokens`.
/// The exact cutoff varies by model, but these families need the new field:
///
///   - o1, o3, and o4 series (reasoning models)
///   - gpt-5 series
///   - gpt-4.1 series
///   - some `-latest` aliases such as `chatgpt-4o-latest`
///
/// Prefix matching is used conservatively. If we guess wrong, OpenAI returns a
/// clear error, so new prefixes can be added here safely.
pub fn model_uses_completion_tokens(model_name: &str) -> bool {
    let m = model_name.trim().to_ascii_lowercase();
    m.starts_with("o1")
        || m.starts_with("o3")
        || m.starts_with("o4")
        || m.starts_with("gpt-5")
        || m.starts_with("gpt-4.1")
        || m.starts_with("chatgpt-")
}

/// Reasoning models consume internal reasoning tokens before visible output.
/// That means `max_completion_tokens` covers both reasoning and visible output.
/// Reusing a cap tuned for non-reasoning models can yield an empty response.
///
/// When this returns true, callers should:
///   1. raise `max_completion_tokens` to leave reasoning headroom
///   2. send `reasoning_effort: "minimal"` to keep reasoning overhead low
pub fn model_is_reasoning(model_name: &str) -> bool {
    let m = model_name.trim().to_ascii_lowercase();
    m.starts_with("o1")
        || m.starts_with("o3")
        || m.starts_with("o4")
        // The entire gpt-5 family, including mini/nano variants, uses reasoning.
        || m.starts_with("gpt-5")
}

/// Generates a summary using the specified LLM provider
///
/// # Arguments
/// * `client` - Reqwest HTTP client (reused for performance)
/// * `provider` - The LLM provider to use
/// * `model_name` - The specific model to use (e.g., "gpt-4", "claude-3-opus")
/// * `api_key` - API key for the provider
/// * `system_prompt` - System instructions for the LLM
/// * `user_prompt` - User query/content to process
/// * `relay_ai_endpoint` - Optional Relay AI-compatible endpoint
/// * `max_tokens` - Optional max tokens (for RelayAI provider)
/// * `temperature` - Optional temperature (for RelayAI provider)
/// * `top_p` - Optional top_p (for RelayAI provider)
/// * `cancellation_token` - Optional token to cancel the request
/// * `request_timeout` - Optional HTTP timeout (defaults to 300s for summaries)
///
/// # Returns
/// The generated summary text or an error message
pub async fn generate_summary(
    client: &Client,
    provider: &LLMProvider,
    model_name: &str,
    api_key: &str,
    system_prompt: &str,
    user_prompt: &str,
    relay_ai_endpoint: Option<&str>,
    max_tokens: Option<u32>,
    temperature: Option<f32>,
    top_p: Option<f32>,
    cancellation_token: Option<&CancellationToken>,
    request_timeout: Option<Duration>,
) -> Result<String, String> {
    let timeout_dur = request_timeout.unwrap_or(REQUEST_TIMEOUT_DURATION);
    // Check if cancelled before starting
    if let Some(token) = cancellation_token {
        if token.is_cancelled() {
            return Err("Summary generation was cancelled".to_string());
        }
    }

    let (api_url, mut headers) = match provider {
        LLMProvider::OpenAI => (
            "https://api.openai.com/v1/chat/completions".to_string(),
            header::HeaderMap::new(),
        ),
        LLMProvider::Groq => (
            "https://api.groq.com/openai/v1/chat/completions".to_string(),
            header::HeaderMap::new(),
        ),
        LLMProvider::OpenRouter => (
            "https://openrouter.ai/api/v1/chat/completions".to_string(),
            header::HeaderMap::new(),
        ),
        LLMProvider::RelayAI => {
            // The summary provider UI was removed — users no longer configure
            // an endpoint. When nothing has been persisted yet (fresh install,
            // or a legacy install whose saved provider got normalized onto
            // relay-ai), fall back to the baked-in Relay gateway URL.
            // `config::gateway_url()` itself honors the RELAY_TRANSLATION_URL
            // env override used by `make dev-cloud`.
            let endpoint_owned = relay_ai_endpoint
                .map(|s| s.to_string())
                .filter(|s| !s.trim().is_empty())
                .unwrap_or_else(crate::config::gateway_url);
            let base = endpoint_owned.trim_end_matches('/');
            // Gateway uses /summarize/ (Django trailing slash), raw OpenAI-compatible uses /chat/completions
            let url = if base.ends_with("/ai") || base.ends_with("/v1/ai") {
                format!("{}/summarize/", base)
            } else {
                format!("{}/chat/completions", base)
            };
            (url, header::HeaderMap::new())
        }
        LLMProvider::Claude => {
            let mut header_map = header::HeaderMap::new();
            header_map.insert(
                "x-api-key",
                api_key
                    .parse()
                    .map_err(|_| "Invalid API key format".to_string())?,
            );
            header_map.insert(
                "anthropic-version",
                "2023-06-01"
                    .parse()
                    .map_err(|_| "Invalid anthropic version".to_string())?,
            );
            (
                "https://api.anthropic.com/v1/messages".to_string(),
                header_map,
            )
        }
    };

    // Add authorization header for non-Claude providers
    if provider != &LLMProvider::Claude {
        // When routing through our own gateway, prefer the user's JWT from the
        // Tauri store (auth.json) over whatever api_key was saved in settings
        // (which is just a placeholder for relay-ai).
        let token = if provider == &LLMProvider::RelayAI && api_url.contains("/ai/summarize") {
            read_gateway_jwt().unwrap_or_else(|| api_key.to_string())
        } else {
            api_key.to_string()
        };
        headers.insert(
            header::AUTHORIZATION,
            format!("Bearer {}", token)
                .parse()
                .map_err(|_| "Invalid authorization header".to_string())?,
        );
    }
    headers.insert(
        header::CONTENT_TYPE,
        "application/json"
            .parse()
            .map_err(|_| "Invalid content type".to_string())?,
    );

    // Build request body based on provider
    let request_body = if provider != &LLMProvider::Claude {
        // For RelayAI, apply optional parameters if provided
        // RelayAI uses caller temperature/top_p; max_tokens may be set for any OpenAI-compatible API
        // (e.g. live assist JSON) when provided.
        let (max_tokens_val, temperature_val, top_p_val) = if provider == &LLMProvider::RelayAI
        {
            (max_tokens, temperature, top_p)
        } else {
            (max_tokens, None, None)
        };

        // OpenAI newer models reject `max_tokens` and require
        // `max_completion_tokens`. Other OpenAI-compatible providers still use
        // `max_tokens`, so only branch for OpenAI itself.
        let is_openai = provider == &LLMProvider::OpenAI;
        let uses_completion_tokens = is_openai && model_uses_completion_tokens(model_name);
        let is_reasoning = is_openai && model_is_reasoning(model_name);

        // Routing through the Relay gateway /summarize/: omit `model`
        // entirely. The gateway strips it anyway and the Pod server fills
        // in its own tag, so the real backing model identifier never
        // travels on the wire between the app and the gateway. Non-gateway
        // providers (OpenAI / Groq / OpenRouter) still need `model` set.
        let is_gateway_summary =
            provider == &LLMProvider::RelayAI && api_url.contains("/ai/summarize");
        let mut body = serde_json::json!({
            "messages": [
                { "role": "system", "content": system_prompt },
                { "role": "user", "content": user_prompt },
            ],
        });
        if !is_gateway_summary {
            body["model"] = serde_json::Value::String(model_name.to_string());
        }

        if let Some(mt) = max_tokens_val {
            let key = if uses_completion_tokens {
                "max_completion_tokens"
            } else {
                "max_tokens"
            };
            // Reasoning models can spend most of the cap internally before
            // generating visible output, so expand the budget to leave headroom.
            let effective_mt = if is_reasoning {
                std::cmp::max(mt.saturating_mul(4), 4096)
            } else {
                mt
            };
            body[key] = serde_json::Value::from(effective_mt);
        } else if is_reasoning {
            // Even without an explicit caller cap, reasoning models need a large one.
            body["max_completion_tokens"] = serde_json::Value::from(4096u32);
        }

        // Live assist wants short, fast responses, so reasoning effort should be
        // minimized on reasoning models.
        if is_reasoning {
            body["reasoning_effort"] = serde_json::Value::String("minimal".to_string());
        }

        // Reasoning models may ignore or reject temperature/top_p, so omit them.
        if !is_reasoning {
            if let Some(t) = temperature_val {
                body["temperature"] = serde_json::Value::from(t);
            }
            if let Some(tp) = top_p_val {
                body["top_p"] = serde_json::Value::from(tp);
            }
        }
        body
    } else {
        serde_json::json!(ClaudeRequest {
            system: system_prompt.to_string(),
            model: model_name.to_string(),
            max_tokens: 2048,
            messages: vec![ChatMessage {
                role: "user".to_string(),
                content: user_prompt.to_string(),
            }]
        })
    };

    info!(
        " LLM Request to {}: model={}",
        provider_name(provider),
        model_name
    );

    // When routing through our own gateway, pre-warm the Modal summary
    // container so the actual /summarize/ call doesn't have to absorb the
    // 70s+ cold-start (which would also blow past CloudFront's 30s origin
    // response timeout). Best-effort: failures fall through to the real
    // request which may still cold-start.
    if provider == &LLMProvider::RelayAI && api_url.contains("/ai/summarize") {
        let base = api_url.trim_end_matches("/summarize/");
        await_summary_ready(client, base, cancellation_token).await;
    }

    // Serialize up front so the body size is visible in logs — a silent empty
    // 200 with nothing in the gateway log is otherwise indistinguishable from
    // "POST never left the client".
    let body_bytes = serde_json::to_vec(&request_body)
        .map_err(|e| format!("Failed to serialize request body: {}", e))?;
    info!(
        " LLM POST {} (body={} bytes, timeout={}s)",
        api_url,
        body_bytes.len(),
        timeout_dur.as_secs()
    );

    // Send request with timeout and cancellation support. Content-Type is
    // already on `headers` from earlier — `.body(Vec<u8>)` doesn't overwrite
    // caller-set headers, so no duplicate.
    let request_future = client
        .post(&api_url)
        .headers(headers)
        .body(body_bytes)
        .timeout(timeout_dur)
        .send();

    let timeout_secs = timeout_dur.as_secs();
    let on_send_err = move |e: reqwest::Error| -> String {
        if e.is_timeout() {
            format!("LLM request timed out after {}s", timeout_secs)
        } else if e.is_connect() {
            format!("Failed to connect to LLM ({}): {}", api_url, e)
        } else if e.is_request() {
            format!("LLM request was rejected before send ({}): {}", api_url, e)
        } else {
            format!("Failed to send request to LLM ({}): {}", api_url, e)
        }
    };

    // Use tokio::select to race between cancellation and request completion
    let response = if let Some(token) = cancellation_token {
        tokio::select! {
            result = request_future => {
                result.map_err(on_send_err)?
            }
            _ = token.cancelled() => {
                return Err("Summary generation was cancelled".to_string());
            }
        }
    } else {
        request_future.await.map_err(on_send_err)?
    };

    let status = response.status();
    // Read the body as text first so we can surface useful diagnostics when
    // the gateway or an intermediate proxy returns non-JSON (HTML error page,
    // empty body, plain-text "Internal Server Error") even on a 2xx status —
    // the cause of the user-visible "Failed to parse LLM response: expected
    // value at line 1 column 1" error we used to hit during 401/503/504
    // cascades on the gateway.
    let body = response
        .text()
        .await
        .map_err(|e| format!("Failed to read LLM response body: {}", e))?;
    info!(
        " LLM Response: status={} body={} bytes preview={:?}",
        status,
        body.len(),
        body.chars().take(80).collect::<String>()
    );

    if !status.is_success() {
        return Err(format!(
            "LLM API request failed ({}): {}",
            status,
            snippet(&body)
        ));
    }

    // Parse response based on provider
    if provider == &LLMProvider::Claude {
        let chat_response: ClaudeChatResponse =
            parse_llm_body(&body).map_err(|e| format!("Failed to parse LLM response: {}", e))?;

        info!(" LLM Response received from Claude");

        let content = chat_response
            .content
            .get(0)
            .ok_or("No content in LLM response")?
            .text
            .trim();
        Ok(content.to_string())
    } else {
        let chat_response: ChatResponse =
            parse_llm_body(&body).map_err(|e| format!("Failed to parse LLM response: {}", e))?;

        info!(" LLM Response received from {}", provider_name(provider));

        let content = chat_response
            .choices
            .get(0)
            .ok_or("No content in LLM response")?
            .message
            .content
            .trim();
        Ok(content.to_string())
    }
}

/// Shrink a possibly-huge response body to something safe to embed in an
/// error message or log line. Keeps the leading portion intact since that's
/// where error fields usually live.
fn snippet(body: &str) -> String {
    const MAX: usize = 500;
    let trimmed = body.trim();
    if trimmed.is_empty() {
        return "<empty body>".to_string();
    }
    if trimmed.len() <= MAX {
        trimmed.to_string()
    } else {
        format!("{}… (truncated, {} bytes total)", &trimmed[..MAX], trimmed.len())
    }
}

/// Deserialize an LLM response body into `T`, but if the body isn't shaped
/// like `T`, try to extract a human-readable error instead of leaking a
/// cryptic serde diagnostic to the UI. Common shapes we see on failure:
///   { "detail": "..." }          — Django/FastAPI gateway error
///   { "error": "..." }            — generic proxy error
///   { "error": { "message": "..." } } — OpenAI-style error envelope
///   "<html>..."                   — CDN/CloudFront error page
fn parse_llm_body<T: for<'de> serde::Deserialize<'de>>(body: &str) -> Result<T, String> {
    // Happy path first so well-formed responses don't pay the double parse.
    if let Ok(v) = serde_json::from_str::<T>(body) {
        return Ok(v);
    }

    let trimmed = body.trim();
    if trimmed.is_empty() {
        return Err("backend returned empty response body".to_string());
    }
    if !trimmed.starts_with('{') && !trimmed.starts_with('[') {
        return Err(format!(
            "backend returned non-JSON response: {}",
            snippet(body)
        ));
    }

    // Valid JSON but wrong shape — try to pull the error message out.
    match serde_json::from_str::<serde_json::Value>(body) {
        Ok(v) => {
            for field in ["detail", "message", "error"] {
                if let Some(s) = v.get(field).and_then(|x| x.as_str()) {
                    return Err(format!("backend error ({}): {}", field, s));
                }
            }
            if let Some(msg) = v.get("error").and_then(|e| e.get("message")).and_then(|m| m.as_str()) {
                return Err(format!("backend error (error.message): {}", msg));
            }
            Err(format!("unexpected response shape: {}", snippet(body)))
        }
        Err(e) => Err(format!(
            "response is not valid JSON ({}): {}",
            e,
            snippet(body)
        )),
    }
}

/// Fire-and-forget warmup of the Modal summary container, then poll
/// `/summary/ready/` until 200 or a soft deadline passes. Best-effort —
/// returns without surfacing errors so the caller can still attempt the
/// actual /summarize/ request.
///
/// `gateway_base` is the gateway URL up to (but not including) `/summarize/`,
/// e.g. `https://api.example.com/api/v1/ai`.
async fn await_summary_ready(
    client: &Client,
    gateway_base: &str,
    cancellation_token: Option<&CancellationToken>,
) {
    let warmup_url = format!("{}/summary/warmup/", gateway_base);
    let ready_url = format!("{}/summary/ready/", gateway_base);

    // Read the JWT per HTTP call: this poll can run for up to 3 minutes, long
    // enough to cross a 30-min token boundary near end-of-life. Reading fresh
    // lets proactive frontend refreshes take effect without a cold 401.
    let mut warmup = client.post(&warmup_url);
    if let Some(t) = read_gateway_jwt() {
        warmup = warmup.bearer_auth(t);
    }
    let _ = warmup.timeout(Duration::from_secs(5)).send().await;

    let deadline = std::time::Instant::now() + Duration::from_secs(180);
    loop {
        if let Some(token) = cancellation_token {
            if token.is_cancelled() {
                return;
            }
        }
        let mut req = client.get(&ready_url);
        if let Some(t) = read_gateway_jwt() {
            req = req.bearer_auth(t);
        }
        if let Ok(resp) = req.timeout(Duration::from_secs(10)).send().await {
            if resp.status().is_success() {
                info!(" Summary container ready");
                return;
            }
        }
        if std::time::Instant::now() >= deadline {
            info!(" Summary readiness timeout, proceeding anyway");
            return;
        }
        tokio::time::sleep(Duration::from_secs(5)).await;
    }
}

/// Helper function to get provider name for logging
fn provider_name(provider: &LLMProvider) -> &str {
    match provider {
        LLMProvider::OpenAI => "OpenAI",
        LLMProvider::Claude => "Claude",
        LLMProvider::Groq => "Groq",
        LLMProvider::OpenRouter => "OpenRouter",
        LLMProvider::RelayAI => "Relay AI",
    }
}
