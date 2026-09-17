use crate::database::repositories::{
    meeting::MeetingsRepository, setting::SettingsRepository, summary::SummaryProcessesRepository,
};
use crate::summary::llm_client::{generate_summary, normalize_provider_name, LLMProvider};
use crate::summary::processor::{extract_meeting_name_from_markdown, generate_meeting_summary};
use crate::summary::LiveAssistResult;
use once_cell::sync::Lazy;
use regex::Regex;
use serde::Deserialize;
use sqlx::SqlitePool;
use std::collections::HashMap;
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};
use tauri::AppHandle;
use tokio_util::sync::CancellationToken;
use tracing::{error, info, warn};

// Global registry for cancellation tokens (thread-safe)
static CANCELLATION_REGISTRY: Lazy<Arc<Mutex<HashMap<String, CancellationToken>>>> =
    Lazy::new(|| Arc::new(Mutex::new(HashMap::new())));

/// Reused client so repeated live-assist calls keep HTTP/TLS connection pools warm.
static LIVE_ASSIST_HTTP_CLIENT: Lazy<reqwest::Client> = Lazy::new(|| {
    reqwest::Client::builder()
        .build()
        .expect("live assist reqwest client")
});

#[derive(Deserialize)]
struct LiveAssistJson {
    #[serde(default)]
    translation: String,
    #[serde(default, rename = "intentSummary", alias = "intent_summary")]
    intent_summary: String,
    #[serde(default, rename = "replyIdeas", alias = "reply_ideas")]
    reply_ideas: Vec<String>,
}

/// Remove ```json ... ``` wrappers models often add despite instructions.
fn strip_code_fence(raw: &str) -> &str {
    let s = raw.trim();
    let Some(after_ticks) = s.strip_prefix("```") else {
        return s;
    };
    let after_ticks = after_ticks.trim_start();
    let body = if let Some(nl) = after_ticks.find('\n') {
        after_ticks[nl + 1..].trim_start_matches('\r')
    } else {
        after_ticks
    };
    if let Some(end) = body.rfind("```") {
        body[..end].trim()
    } else {
        body.trim()
    }
}

/// First top-level `{ ... }` slice, respecting strings so inner `}` in text does not break.
fn extract_first_json_object(s: &str) -> Option<&str> {
    let start = s.find('{')?;
    let mut depth = 0i32;
    let mut in_string = false;
    let mut escape = false;
    for (rel, ch) in s[start..].char_indices() {
        let abs = start + rel;
        if in_string {
            if escape {
                escape = false;
                continue;
            }
            match ch {
                '\\' => escape = true,
                '"' => in_string = false,
                _ => {}
            }
            continue;
        }
        match ch {
            '"' => in_string = true,
            '{' => depth += 1,
            '}' => {
                depth -= 1;
                if depth == 0 {
                    return Some(&s[start..=abs]);
                }
            }
            _ => {}
        }
    }
    None
}

/// Models often emit 'curly' quotes; normalize so JSON / loose parsers see ASCII ".
fn normalize_typographic_quotes(input: &str) -> String {
    input
        .chars()
        .map(|c| match c {
            '\u{201c}' | '\u{201d}' | '\u{201e}' | '\u{00ab}' | '\u{00bb}' | '\u{2033}'
            | '\u{2036}' | '\u{2039}' | '\u{203a}' | '\u{ff02}' => '"',
            '\u{2018}' | '\u{2019}' | '\u{201a}' | '\u{2032}' => '\'',
            _ => c,
        })
        .collect()
}

/// En/em dashes and unicode minus often appear instead of ASCII `-` in markdown bullets.
fn normalize_markdown_dashes(input: &str) -> String {
    input
        .chars()
        .map(|c| match c {
            '\u{2013}' | '\u{2014}' | '\u{2212}' => '-',
            _ => c,
        })
        .collect()
}

fn normalize_live_assist_raw(raw: &str) -> String {
    normalize_markdown_dashes(&normalize_typographic_quotes(raw))
}

fn live_assist_from_parsed(p: LiveAssistJson) -> LiveAssistResult {
    LiveAssistResult {
        translation: p.translation.trim().to_string(),
        intent_summary: p.intent_summary.trim().to_string(),
        reply_ideas: p
            .reply_ideas
            .into_iter()
            .map(|s| s.trim().to_string())
            .filter(|s| !s.is_empty())
            .collect(),
    }
}

fn finish_live_assist_parse(
    p: LiveAssistJson,
    normalized: &str,
    ctx: LiveAssistParseContext<'_>,
) -> LiveAssistResult {
    let mut r = live_assist_from_parsed(p);
    if ctx.allow_plaintext_translation && r.translation.trim().is_empty() {
        if let Some(t) = parse_loose_field_string(normalized, "translation")
            .or_else(|| parse_loose_translation_unquoted(normalized))
        {
            r.translation = t;
        }
    }
    r
}

/// Pull `"key": ... "value"` when the model used markdown bullets instead of JSON.
fn parse_loose_field_string(s: &str, key: &str) -> Option<String> {
    let escaped = regex::escape(key);
    let patterns = [
        format!(r#"(?is)-?\s*"{}"\s*:\s*-?\s*"((?:[^"\\]|\\.)*)""#, escaped),
        format!(r#"(?is)\b{}\b\s*:\s*-?\s*"((?:[^"\\]|\\.)*)""#, escaped),
    ];
    for p in patterns {
        if let Ok(re) = Regex::new(&p) {
            if let Some(c) = re.captures(s) {
                if let Some(m) = c.get(1) {
                    let v = m.as_str().trim();
                    if !v.is_empty() {
                        return Some(v.to_string());
                    }
                }
            }
        }
    }
    None
}

/// `translation: some text intentSummary:` (no quotes around the value) - common model mistake.
fn parse_loose_translation_unquoted(s: &str) -> Option<String> {
    let re =
        Regex::new(r#"(?is)translation\s*:\s*(.+?)\s*(?:intentSummary|intent_summary)\s*:\s*"#)
            .ok()?;
    let v = re.captures(s)?.get(1)?.as_str().trim();
    let v = v.trim_matches(|c| c == '"' || c == '\u{201c}' || c == '\u{201d}');
    let v = v.trim();
    if v.is_empty() {
        None
    } else {
        Some(v.to_string())
    }
}

fn parse_loose_intent_unquoted(s: &str) -> Option<String> {
    let re = Regex::new(r#"(?is)intentSummary\s*:\s*(.+?)\s*replyIdeas\s*:\s*"#).ok()?;
    let v = re.captures(s)?.get(1)?.as_str().trim();
    let v = v.trim_matches(|c| c == '"' || c == '\u{201c}' || c == '\u{201d}');
    let v = v.trim();
    if v.is_empty() {
        None
    } else {
        Some(v.to_string())
    }
}

/// After `replyIdeas":`, collect every ASCII-quoted segment (handles `- "a"` lists and `["a","b"]`).
fn scan_quoted_strings(s: &str) -> Vec<String> {
    let mut out = Vec::new();
    let b = s.as_bytes();
    let mut i = 0usize;
    while i < s.len() {
        while i < s.len()
            && (b[i] == b'-'
                || b[i] == b','
                || b[i] == b'['
                || b[i] == b']'
                || b[i].is_ascii_whitespace())
        {
            i += 1;
        }
        if i >= s.len() {
            break;
        }
        if b[i] == b'"' {
            i += 1;
            let start = i;
            let mut escaped = false;
            while i < s.len() {
                if escaped {
                    escaped = false;
                    i += 1;
                    continue;
                }
                if b[i] == b'\\' {
                    escaped = true;
                    i += 1;
                    continue;
                }
                if b[i] == b'"' {
                    let chunk = s[start..i].trim();
                    if !chunk.is_empty() {
                        out.push(chunk.to_string());
                    }
                    i += 1;
                    break;
                }
                let c = s[i..].chars().next().unwrap();
                i += c.len_utf8();
            }
        } else {
            let c = s[i..].chars().next().unwrap();
            i += c.len_utf8();
        }
    }
    out
}

fn parse_loose_reply_ideas(s: &str) -> Vec<String> {
    // Avoid greedy `.+` across the whole response; scan only after the key.
    let patterns = [r#"(?i)"replyideas"\s*:\s*"#, r#"(?i)\breplyideas\s*:\s*"#];
    for pat in patterns {
        let Ok(re) = Regex::new(pat) else {
            continue;
        };
        if let Some(m) = re.find(s) {
            return scan_quoted_strings(&s[m.end()..]);
        }
    }
    vec![]
}

/// Recover from markdown-style pseudo-JSON (no `{`...`}`) and smart quotes.
fn parse_live_assist_loose(s: &str) -> Option<LiveAssistResult> {
    let translation = parse_loose_field_string(s, "translation")
        .or_else(|| parse_loose_translation_unquoted(s))
        .unwrap_or_default();
    let intent_summary = parse_loose_field_string(s, "intentSummary")
        .or_else(|| parse_loose_field_string(s, "intent_summary"))
        .or_else(|| parse_loose_intent_unquoted(s))
        .unwrap_or_default();
    let reply_ideas = parse_loose_reply_ideas(s);
    if translation.is_empty() && intent_summary.is_empty() && reply_ideas.is_empty() {
        return None;
    }
    Some(LiveAssistResult {
        translation,
        intent_summary,
        reply_ideas,
    })
}

/// How to recover when the model ignores JSON shape.
struct LiveAssistParseContext<'a> {
    /// If true, a brace-less reply may still be used as translation when it plausibly matches the target language.
    allow_plaintext_translation: bool,
    target_language_name: &'a str,
}

fn is_obvious_meta_refusal(s: &str) -> bool {
    let l = s.to_lowercase();
    if l.len() > 900 {
        return false;
    }
    l.contains("provide the audio")
        || l.contains("send the audio")
        || (l.contains("upload") && l.contains("audio"))
        || l.contains("paste your")
        || l.contains("i cannot hear")
        || l.contains("i can't hear")
        || l.contains("cannot process audio")
        || ((l.contains("let's begin") || l.contains("lets begin")) && l.len() < 160)
}

fn response_may_be_plain_translation(s: &str, target_lang: &str) -> bool {
    let tl = target_lang.to_lowercase();
    let has_hangul = s.chars().any(|c| ('\u{ac00}'..='\u{d7af}').contains(&c));
    let has_cjk = s.chars().any(|c| {
        ('\u{4e00}'..='\u{9fff}').contains(&c)
            || ('\u{3040}'..='\u{30ff}').contains(&c)
            || ('\u{31f0}'..='\u{31ff}').contains(&c)
    });
    if tl.contains("korean") {
        return has_hangul;
    }
    if tl.contains("japanese") {
        return has_cjk;
    }
    if tl.contains("chinese") {
        return has_cjk;
    }
    if tl.contains("english") {
        return !has_hangul || s.len() < 400;
    }
    true
}

fn parse_live_assist_json(
    raw: &str,
    ctx: LiveAssistParseContext<'_>,
) -> Result<LiveAssistResult, String> {
    let stripped = strip_code_fence(raw).trim().trim_start_matches('\u{feff}');
    let normalized = normalize_live_assist_raw(stripped);

    if let Some(slice) = extract_first_json_object(&normalized) {
        if let Ok(p) = serde_json::from_str::<LiveAssistJson>(slice) {
            return Ok(finish_live_assist_parse(p, &normalized, ctx));
        }
    }

    if let Ok(p) = serde_json::from_str::<LiveAssistJson>(normalized.trim()) {
        return Ok(finish_live_assist_parse(p, &normalized, ctx));
    }

    // Markdown pseudo-JSON (bullets, smart quotes) - also if a bogus `{` made strict parse fail.
    if let Some(fallback) = parse_live_assist_loose(&normalized) {
        return Ok(fallback);
    }

    // Model sometimes chats instead of JSON, or returns only a translated sentence with no braces.
    if !normalized.contains('{') {
        if ctx.allow_plaintext_translation
            && !is_obvious_meta_refusal(&normalized)
            && response_may_be_plain_translation(&normalized, ctx.target_language_name)
        {
            return Ok(LiveAssistResult {
                translation: normalized.trim().to_string(),
                intent_summary: String::new(),
                reply_ideas: Vec::new(),
            });
        }
        let preview_one_line: String = normalized
            .chars()
            .take(160)
            .collect::<String>()
            .replace('\n', " ");
        warn!(
            target: "app_lib::summary",
            "Live assist returned plain text without JSON object; treating as empty. Preview: {}",
            preview_one_line
        );
        return Ok(LiveAssistResult {
            translation: String::new(),
            intent_summary: String::new(),
            reply_ideas: Vec::new(),
        });
    }

    let preview: String = normalized.chars().take(180).collect();
    let dots = if normalized.chars().count() > 180 {
        "..."
    } else {
        ""
    };
    Err(format!(
        "Assistant model did not return JSON (no parseable object). Preview: {}{}",
        preview.replace('\n', " "),
        dots
    ))
}

/// Earlier finalized captions from the same session (may end mid-sentence).
fn live_assist_prior_trimmed(prior: Option<&str>) -> Option<&str> {
    prior.map(str::trim).filter(|s| !s.is_empty())
}

fn live_assist_labeled_user_body(prior: Option<&str>, current: &str) -> String {
    match live_assist_prior_trimmed(prior) {
        Some(p) => format!(
            "PRIOR_LINES (earlier finalized caption from the same meeting; may end mid-sentence):\n{p}\n\nCURRENT_LINE (speech-to-text chunk to translate/analyze; may continue PRIOR):\n{current}"
        ),
        None => current.to_string(),
    }
}

/// Heuristic: very short tails from segmented ASR (e.g. "Or presentations.").
fn looks_like_caption_fragment(line: &str) -> bool {
    let t = line.trim();
    let words = t.split_whitespace().count();
    if words == 0 || words > 10 {
        return false;
    }
    let lower = t.to_lowercase();
    if lower.starts_with("or ")
        || lower.starts_with("and ")
        || lower.starts_with("but ")
        || lower.starts_with("so ")
        || lower.starts_with("also ")
        || lower.starts_with("plus ")
        || lower.starts_with("then ")
        || lower.starts_with("like ")
        || lower.starts_with("i mean ")
        || lower.starts_with("you know ")
    {
        return true;
    }
    t.chars().next().is_some_and(|c| c.is_ascii_lowercase())
}

const LIVE_ASSIST_PRIOR_RULES: &str = "\n\nContinuation: When PRIOR_LINES is present, it is consecutive speech from the same meeting and may be incomplete. CURRENT_LINE may be a short fragment completing it. Use PRIOR only to interpret CURRENT. \"intentSummary\" may reflect the combined intent of PRIOR+CURRENT only when CURRENT clearly continues PRIOR. \"replyIdeas\" must fit that same thread: plausible next things someone could say after PRIOR+CURRENT (complete an unfinished thought, answer the question actually asked, or add a concrete follow-up tied to their topic) - not generic lines that ignore PRIOR. Never invent meetings, teams, plans, or topics not grounded in PRIOR or CURRENT.";

const LIVE_ASSIST_FRAGMENT_NO_PRIOR: &str = "\n\nShort line without PRIOR: May be an isolated caption fragment. Keep intentSummary very short and literal; do not invent a scenario, meeting, or story.";

/// Summary service - handles all summary generation logic
pub struct SummaryService;

impl SummaryService {
    /// Registers a new cancellation token for a meeting
    fn register_cancellation_token(meeting_id: &str) -> CancellationToken {
        let token = CancellationToken::new();
        if let Ok(mut registry) = CANCELLATION_REGISTRY.lock() {
            registry.insert(meeting_id.to_string(), token.clone());
            info!("Registered cancellation token for meeting: {}", meeting_id);
        }
        token
    }

    /// Cancels the summary generation for a meeting
    pub fn cancel_summary(meeting_id: &str) -> bool {
        if let Ok(registry) = CANCELLATION_REGISTRY.lock() {
            if let Some(token) = registry.get(meeting_id) {
                info!("Cancelling summary generation for meeting: {}", meeting_id);
                token.cancel();
                return true;
            }
        }
        warn!(
            "No active summary generation found for meeting: {}",
            meeting_id
        );
        false
    }

    /// Cleans up the cancellation token after processing completes
    fn cleanup_cancellation_token(meeting_id: &str) {
        if let Ok(mut registry) = CANCELLATION_REGISTRY.lock() {
            if registry.remove(meeting_id).is_some() {
                info!("Cleaned up cancellation token for meeting: {}", meeting_id);
            }
        }
    }

    /// Processes transcript in the background and generates summary
    ///
    /// This function is designed to be spawned as an async task and does not block
    /// the main thread. It updates the database with progress and results.
    ///
    /// # Arguments
    /// * `_app` - Tauri app handle (for future use)
    /// * `pool` - SQLx connection pool
    /// * `meeting_id` - Unique identifier for the meeting
    /// * `text` - Full transcript text
    /// * `model_provider` - LLM provider name (e.g., "openai", "relay-ai")
    /// * `model_name` - Specific model (e.g., "gpt-4", "llama3.2:latest")
    /// * `custom_prompt` - Optional user-provided context
    /// * `template_id` - Template identifier (e.g., "daily_standup", "standard_meeting")
    pub async fn process_transcript_background<R: tauri::Runtime>(
        _app: AppHandle<R>,
        pool: SqlitePool,
        meeting_id: String,
        text: String,
        model_provider: String,
        model_name: String,
        custom_prompt: String,
        template_id: String,
        language: Option<String>,
    ) {
        let start_time = Instant::now();
        info!(
            "Starting background processing for meeting_id: {}",
            meeting_id
        );

        // Register cancellation token for this meeting
        let cancellation_token = Self::register_cancellation_token(&meeting_id);

        // Parse provider
        let normalized_provider = normalize_provider_name(&model_provider);
        let provider = match LLMProvider::from_str(&normalized_provider) {
            Ok(p) => p,
            Err(e) => {
                Self::update_process_failed(&pool, &meeting_id, &e).await;
                return;
            }
        };

        // Relay AI stores credentials in its JSON config instead of the API-key table.
        let api_key = if provider == LLMProvider::RelayAI {
            String::new()
        } else {
            match SettingsRepository::get_api_key(&pool, &normalized_provider).await {
                Ok(Some(key)) if !key.is_empty() => key,
                Ok(None) | Ok(Some(_)) => {
                    let err_msg = format!("API key not found for {}", &model_provider);
                    Self::update_process_failed(&pool, &meeting_id, &err_msg).await;
                    return;
                }
                Err(e) => {
                    let err_msg = format!(
                        "Failed to retrieve API key for {}: {}",
                        &normalized_provider, e
                    );
                    Self::update_process_failed(&pool, &meeting_id, &err_msg).await;
                    return;
                }
            }
        };

        // RelayAI is the fixed production provider. The per-install
        // customOpenAIConfig row is optional now that the summary-provider UI
        // was removed — when it's missing we just fall through with `None`
        // fields and `llm_client::generate_summary` falls back to the baked-in
        // gateway URL (+ JWT from disk). Legacy installs that still carry a
        // saved row keep using its endpoint/credentials as before.
        let (
            relay_ai_endpoint,
            relay_ai_api_key,
            relay_ai_max_tokens,
            relay_ai_temperature,
            relay_ai_top_p,
        ) = if provider == LLMProvider::RelayAI {
            match SettingsRepository::get_relay_ai_config(&pool).await {
                Ok(Some(config)) => {
                    info!("Using Relay AI endpoint: {}", config.endpoint);
                    (
                        Some(config.endpoint),
                        config.api_key,
                        config.max_tokens.map(|t| t as u32),
                        config.temperature,
                        config.top_p,
                    )
                }
                Ok(None) => {
                    info!("No Relay AI config row — falling back to gateway defaults");
                    (None, None, None, None, None)
                }
                Err(e) => {
                    let err_msg = format!("Failed to retrieve Relay AI config: {}", e);
                    Self::update_process_failed(&pool, &meeting_id, &err_msg).await;
                    return;
                }
            }
        } else {
            (None, None, None, None, None)
        };

        // For RelayAI, use its API key (if any) instead of the empty string
        let final_api_key = if provider == LLMProvider::RelayAI {
            relay_ai_api_key.unwrap_or_default()
        } else {
            api_key
        };

        // Hosted providers usually handle large contexts; only chunk very large transcripts.
        let token_threshold = 100000usize;

        // Generate summary
        let client = reqwest::Client::new();
        let result = generate_meeting_summary(
            &client,
            &provider,
            &model_name,
            &final_api_key,
            &text,
            &custom_prompt,
            &template_id,
            token_threshold,
            relay_ai_endpoint.as_deref(),
            relay_ai_max_tokens,
            relay_ai_temperature,
            relay_ai_top_p,
            Some(&cancellation_token),
            language.as_deref(),
        )
        .await;

        let duration = start_time.elapsed().as_secs_f64();

        // Clean up cancellation token regardless of outcome
        Self::cleanup_cancellation_token(&meeting_id);

        match result {
            Ok((mut final_markdown, num_chunks)) => {
                if num_chunks == 0 && final_markdown.is_empty() {
                    Self::update_process_failed(
                        &pool,
                        &meeting_id,
                        "Summary generation failed: No content was processed.",
                    )
                    .await;
                    return;
                }

                info!(
                    "Successfully processed {} chunks for meeting_id: {}. Duration: {:.2}s",
                    num_chunks, meeting_id, duration
                );
                info!("final markdown is {}", &final_markdown);

                // Extract and update meeting name if present
                if let Some(name) = extract_meeting_name_from_markdown(&final_markdown) {
                    if !name.is_empty() {
                        info!(
                            "Updating meeting name to '{}' for meeting_id: {}",
                            name, meeting_id
                        );
                        if let Err(e) =
                            MeetingsRepository::update_meeting_title(&pool, &meeting_id, &name)
                                .await
                        {
                            error!("Failed to update meeting name for {}: {}", meeting_id, e);
                        }

                        // Strip the title line from markdown
                        info!("Stripping title from final_markdown");
                        if let Some(hash_pos) = final_markdown.find('#') {
                            // Find end of first line after '#'
                            let body_start =
                                if let Some(line_end) = final_markdown[hash_pos..].find('\n') {
                                    hash_pos + line_end
                                } else {
                                    final_markdown.len() // No newline, whole string is title
                                };

                            final_markdown = final_markdown[body_start..].trim_start().to_string();
                        } else {
                            // No '#' found, clear the string
                            final_markdown.clear();
                        }
                    }
                }

                // Create result JSON with markdown only (summary_json will be added on first edit)
                let result_json = serde_json::json!({
                    "markdown": final_markdown,
                });

                // Update database with completed status
                if let Err(e) = SummaryProcessesRepository::update_process_completed(
                    &pool,
                    &meeting_id,
                    result_json,
                    num_chunks,
                    duration,
                )
                .await
                {
                    error!("Failed to save completed process for {}: {}", meeting_id, e);
                } else {
                    info!("Summary saved successfully for meeting_id: {}", meeting_id);
                }
            }
            Err(e) => {
                // Check if error is due to cancellation
                if e.contains("cancelled") {
                    info!(
                        "Summary generation was cancelled for meeting_id: {}",
                        meeting_id
                    );
                    if let Err(db_err) =
                        SummaryProcessesRepository::update_process_cancelled(&pool, &meeting_id)
                            .await
                    {
                        error!(
                            "Failed to update DB status to cancelled for {}: {}",
                            meeting_id, db_err
                        );
                    }
                } else {
                    Self::update_process_failed(&pool, &meeting_id, &e).await;
                }
            }
        }
    }

    /// Live assistant: intent summary + reply ideas (same LLM as summaries). Live line translation was removed.
    ///
    /// `prior_transcript_context`: earlier finalized caption lines from the same session when ASR splits mid-utterance.
    pub async fn live_assist_segment<R: tauri::Runtime>(
        _app: &tauri::AppHandle<R>,
        pool: &SqlitePool,
        text: &str,
        prior_transcript_context: Option<&str>,
        target_language_name: &str,
    ) -> Result<LiveAssistResult, String> {
        let trimmed = text.trim();
        if trimmed.is_empty() {
            return Ok(LiveAssistResult {
                translation: String::new(),
                intent_summary: String::new(),
                reply_ideas: Vec::new(),
            });
        }

        let prior_opt = live_assist_prior_trimmed(prior_transcript_context);
        let short_fragment_no_prior = prior_opt.is_none() && looks_like_caption_fragment(trimmed);
        let labeled_user_body = live_assist_labeled_user_body(prior_opt, trimmed);

        // Fall back to relay-ai when no settings row exists. The gateway
        // resolves the real backing model server-side (`/summarize/` ignores
        // the `model` field), so a fresh install with an empty `settings`
        // table can still serve live intent without forcing the user to
        // open Preferences first.
        let setting = SettingsRepository::get_model_config(pool)
            .await
            .map_err(|e| e.to_string())?;

        let (provider_name, mut model_name) = match setting {
            Some(s) => (s.provider, s.model),
            None => ("relay-ai".to_string(), String::new()),
        };

        let model_provider = normalize_provider_name(&provider_name);
        let provider = LLMProvider::from_str(&model_provider)?;

        let api_key = if provider == LLMProvider::RelayAI {
            String::new()
        } else {
            match SettingsRepository::get_api_key(pool, &model_provider).await {
                Ok(Some(key)) if !key.is_empty() => key,
                Ok(None) | Ok(Some(_)) => {
                    return Err(format!(
                        "API key not found for provider {}. Add it in Model Settings.",
                        model_provider
                    ));
                }
                Err(e) => return Err(format!("Failed to read API key: {}", e)),
            }
        };

        let (
            relay_ai_endpoint,
            relay_ai_api_key,
            relay_ai_max_tokens,
            relay_ai_temperature,
            relay_ai_top_p,
        ) = if provider == LLMProvider::RelayAI {
            match SettingsRepository::get_relay_ai_config(pool).await {
                Ok(Some(config)) => {
                    model_name = config.model.clone();
                    (
                        Some(config.endpoint),
                        config.api_key,
                        config.max_tokens.map(|t| t as u32),
                        config.temperature,
                        config.top_p,
                    )
                }
                // No saved row is fine — the summary-provider UI was removed,
                // so installs without a legacy config just route through the
                // gateway defaults that `llm_client::generate_summary`
                // already falls back to.
                Ok(None) => (None, None, None, None, None),
                Err(e) => return Err(format!("Failed to load Relay AI config: {}", e)),
            }
        } else {
            (None, None, None, None, None)
        };

        let final_api_key = if provider == LLMProvider::RelayAI {
            relay_ai_api_key.unwrap_or_default()
        } else {
            api_key
        };

        let client = &*LIVE_ASSIST_HTTP_CLIENT;
        let timeout = Duration::from_secs(28);
        // Headroom for intent + 2-3 substantive English reply lines
        let live_assist_cap: u32 = 896;
        let live_llm_max_tokens = match provider {
            LLMProvider::RelayAI => Some(
                relay_ai_max_tokens
                    .unwrap_or(live_assist_cap)
                    .clamp(128, live_assist_cap),
            ),
            _ => Some(live_assist_cap),
        };

        let system_prompt = format!(
            r#"Live meeting assistant. ONE JSON object, no markdown, first char {{. camelCase, straight ASCII " only.

You only ever receive meeting speech-to-text caption(s). Never ask for audio, files, or more input. Never chat - JSON only.

"translation": "" (always empty string - do not translate)
"intentSummary": 1-2 sentences in {} capturing what the speaker is doing (question, proposal, concern, update, small talk, etc.).

"replyIdeas": exactly 2-3 strings in English. Each must be a natural, complete sentence (or two tight clauses) that a real participant could say next in this meeting - polished enough to use with light edits. Infer context from the caption(s): stand-up, planning, client sync, retro, 1:1, etc., and match a professional spoken tone.

Reply quality: Ground every line in the actual words and topic of CURRENT_LINE (and PRIOR_LINES when provided). Prefer concrete wording (reuse their subject matter - e.g. conferences, deadlines, metrics - when present) over vague filler. If they asked a question, include at least one reply that substantively engages (reasonable answer, trade-off, or one sharp clarifying question) - not empty deferral unless they clearly asked for time. If they stated something, vary stance: acknowledge, build on it, polite pushback, or a specific next step. Do not use the same opening for all three lines. Avoid generic chatbot lines ("Let me get back to you", "I'll look into that") unless the utterance clearly calls for follow-up later.

Length: about 8-14 words per string when that reads natural; slightly longer is fine if it stays one speakable sentence.

Strict source fidelity: No invented people, numbers, deliverables, or topics absent from CURRENT_LINE (and PRIOR_LINES when present). Brief caption - brief intent - not a long narrative.{}{}"#,
            target_language_name,
            if prior_opt.is_some() {
                LIVE_ASSIST_PRIOR_RULES
            } else {
                ""
            },
            if short_fragment_no_prior {
                LIVE_ASSIST_FRAGMENT_NO_PRIOR
            } else {
                ""
            }
        );

        let user_prompt = if prior_opt.is_some() {
            format!(
                "Draft JSON. intentSummary in {}; replyIdeas in English.\n\
Read PRIOR_LINES then CURRENT_LINE as one timeline: infer what was being said and recommend replies that fit that conversational moment.\n\n{}",
                target_language_name,
                labeled_user_body
            )
        } else {
            format!(
                "Draft JSON. intentSummary in {}; replyIdeas in English.\n\
Infer the situation from this single caption and suggest replies a teammate could say next - specific to their topic, not generic.\n\n{}",
                target_language_name,
                trimmed
            )
        };

        let raw = generate_summary(
            client,
            &provider,
            &model_name,
            &final_api_key,
            &system_prompt,
            &user_prompt,
            relay_ai_endpoint.as_deref(),
            live_llm_max_tokens,
            relay_ai_temperature,
            relay_ai_top_p,
            None,
            Some(timeout),
        )
        .await?;

        let mut out = parse_live_assist_json(
            &raw,
            LiveAssistParseContext {
                allow_plaintext_translation: false,
                target_language_name,
            },
        )?;
        out.translation = String::new();
        Ok(out)
    }

    /// Updates the summary process status to failed with error message
    ///
    /// # Arguments
    /// * `pool` - SQLx connection pool
    /// * `meeting_id` - Meeting identifier
    /// * `error_msg` - Error message to store
    async fn update_process_failed(pool: &SqlitePool, meeting_id: &str, error_msg: &str) {
        error!(
            "Processing failed for meeting_id {}: {}",
            meeting_id, error_msg
        );
        if let Err(e) =
            SummaryProcessesRepository::update_process_failed(pool, meeting_id, error_msg).await
        {
            error!(
                "Failed to update DB status to failed for {}: {}",
                meeting_id, e
            );
        }
    }
}

#[cfg(test)]
mod live_assist_parse_tests {
    use super::{parse_live_assist_json, LiveAssistParseContext};

    fn ctx_ko_no_plain() -> LiveAssistParseContext<'static> {
        LiveAssistParseContext {
            allow_plaintext_translation: false,
            target_language_name: "Korean",
        }
    }

    #[test]
    fn parse_markdown_bullet_pseudo_json() {
        let raw = "- \"translation\": \"hello\" - \"intentSummary\": \"The speaker is advertising their services.\" - \"replyIdeas\": - \"Yes, we do.\"";
        let out = parse_live_assist_json(raw, ctx_ko_no_plain()).expect("loose parse");
        assert_eq!(out.translation, "hello");
        assert!(out.intent_summary.contains("advertising"));
        assert_eq!(out.reply_ideas.len(), 1);
        assert!(out.reply_ideas[0].contains("Yes"));
    }

    #[test]
    fn parse_en_dash_bullets() {
        let raw =
            "\"translation\": \"hello\" - \"intentSummary\": \"test\" - \"replyIdeas\": - \"ok\"";
        let out = parse_live_assist_json(raw, ctx_ko_no_plain()).expect("en-dash bullets");
        assert_eq!(out.translation, "hello");
        assert_eq!(out.intent_summary, "test");
        assert_eq!(out.reply_ideas, vec!["ok".to_string()]);
    }

    #[test]
    fn parse_unquoted_translation_and_intent() {
        let raw =
            "translation: translated text intentSummary: They mean well replyIdeas: \"Hi there\"";
        let out = parse_live_assist_json(raw, ctx_ko_no_plain()).expect("unquoted keys");
        assert_eq!(out.translation, "translated text");
        assert_eq!(out.intent_summary, "They mean well");
        assert_eq!(out.reply_ideas.len(), 1);
    }

    #[test]
    fn plain_line_used_as_translation_when_allowed() {
        let raw = "simple translated line";
        let out = parse_live_assist_json(
            raw,
            LiveAssistParseContext {
                allow_plaintext_translation: true,
                target_language_name: "English",
            },
        )
        .expect("plain recovery");
        assert_eq!(out.translation, raw);
        assert!(out.intent_summary.is_empty());
    }
}
