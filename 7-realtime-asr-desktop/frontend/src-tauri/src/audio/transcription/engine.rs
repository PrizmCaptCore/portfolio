// audio/transcription/engine.rs
//
// TranscriptionEngine: gateway-mediated NeMo STT over WebSocket.

use super::nemo_provider::NemoProvider;
use super::provider::TranscriptionProvider;
use log::info;
use std::sync::{Arc, Mutex};
use tauri::{AppHandle, Runtime};

// NemoProvider is created per recording session. stop_recording drops it via
// `close_nemo_provider` so Modal can start its scaledown-window timer
// — keeping a long-lived WS would pin containers open indefinitely.
static NEMO_PROVIDER: Mutex<Option<Arc<dyn TranscriptionProvider>>> = Mutex::new(None);

/// Return the cached NemoProvider or create+cache a new one for the given URL.
fn get_or_create_nemo(url: &str) -> Arc<dyn TranscriptionProvider> {
    let mut slot = NEMO_PROVIDER.lock().expect("NEMO_PROVIDER mutex poisoned");
    if let Some(p) = slot.as_ref() {
        return p.clone();
    }
    let p: Arc<dyn TranscriptionProvider> =
        Arc::new(NemoProvider::new(Some(url)));
    *slot = Some(p.clone());
    p
}

/// Close and drop the cached NemoProvider. Called from `stop_recording` and
/// the Tauri Exit hook so Modal's idle-scaledown timer can actually start.
pub async fn close_nemo_provider() {
    let taken = {
        let mut slot = NEMO_PROVIDER.lock().expect("NEMO_PROVIDER mutex poisoned");
        slot.take()
    };
    if let Some(provider) = taken {
        provider.close().await;
    }
}

pub struct TranscriptionEngine {
    pub partial_provider: Option<Arc<dyn TranscriptionProvider>>,
    pub final_provider: Arc<dyn TranscriptionProvider>,
}

impl TranscriptionEngine {
    pub async fn is_model_loaded(&self) -> bool {
        self.final_provider.is_model_loaded().await
    }

    pub async fn get_current_model(&self) -> Option<String> {
        self.final_provider.get_current_model().await
    }

    pub fn provider_name(&self) -> &str {
        self.final_provider.provider_name()
    }
}

pub async fn validate_transcription_model_ready<R: Runtime>(
    app: &AppHandle<R>,
) -> Result<(), String> {
    // Gateway-mediated STT is the only supported path in production. The
    // URL comes from config::gateway_url() which bakes in the default for
    // release builds and lets dev override via RELAY_TRANSLATION_URL.
    //
    // Two-phase readiness:
    //  1. Hit /health/ once — returns 200 immediately and fires Modal warmup
    //     threads on the gateway (fire-and-forget).
    //  2. Poll /ready/ — gateway probes Modal /health synchronously and
    //     returns 503 until STT + translate containers are actually up.
    let gateway = crate::config::gateway_url();
    let base = gateway.trim_end_matches('/');
    let health_url = format!("{}/health/", base);
    let ready_url = format!("{}/ready/", base);
    info!("Kicking gateway warmup: {}", health_url);
    poll_http_health_authed(app, &health_url, 30).await?;
    info!("Waiting for Modal ready: {}", ready_url);
    poll_ready_authed(app, &ready_url, 240).await?;
    info!("Modal containers ready");
    Ok(())
}

async fn poll_http_health_authed<R: Runtime>(
    app: &AppHandle<R>,
    url: &str,
    timeout_secs: u64,
) -> Result<(), String> {
    let deadline = std::time::Instant::now() + std::time::Duration::from_secs(timeout_secs);
    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(10))
        .build()
        .map_err(|e| format!("reqwest client build: {}", e))?;

    loop {
        // Re-read the JWT on every attempt so a frontend refresh mid-poll
        // propagates to the next iteration instead of us looping on a stale
        // token until the deadline.
        let mut req = client.get(url);
        if let Some(tok) = crate::config::read_access_token(app) {
            req = req.bearer_auth(tok);
        }
        match req.send().await {
            Ok(resp) if resp.status().is_success() => return Ok(()),
            _ => {}
        }
        if std::time::Instant::now() >= deadline {
            return Err(format!(
                "Server did not become ready within {}s ({})",
                timeout_secs, url
            ));
        }
        tokio::time::sleep(std::time::Duration::from_secs(90)).await;
    }
}

/// Poll `/ready/` every 5s until it returns HTTP 200, or until `timeout_secs` elapses.
/// Separate from `poll_http_health_authed` because cold-start readiness requires a
/// tighter retry cadence than the 90s liveness poll.
async fn poll_ready_authed<R: Runtime>(
    app: &AppHandle<R>,
    url: &str,
    timeout_secs: u64,
) -> Result<(), String> {
    let deadline = std::time::Instant::now() + std::time::Duration::from_secs(timeout_secs);
    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(10))
        .build()
        .map_err(|e| format!("reqwest client build: {}", e))?;

    loop {
        let mut req = client.get(url);
        if let Some(tok) = crate::config::read_access_token(app) {
            req = req.bearer_auth(tok);
        }
        match req.send().await {
            Ok(resp) if resp.status().is_success() => return Ok(()),
            _ => {}
        }
        if std::time::Instant::now() >= deadline {
            return Err(format!(
                "Modal did not become ready within {}s ({})",
                timeout_secs, url
            ));
        }
        tokio::time::sleep(std::time::Duration::from_secs(5)).await;
    }
}

#[derive(serde::Deserialize)]
struct SttSessionResponse {
    url: String,
    token: String,
}

/// Call relay_web `/ai/stt/session/` and return a fully-qualified WSS URL
/// (`wss://.../?key=<signed-token>`) that the NemoProvider can connect to.
async fn fetch_stt_session<R: Runtime>(
    app: &AppHandle<R>,
    gateway_base: &str,
) -> Result<String, String> {
    let access = crate::config::read_access_token(app)
        .ok_or_else(|| "not_authenticated".to_string())?;

    let url = format!("{}/stt/session/", gateway_base.trim_end_matches('/'));
    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(30))
        .build()
        .map_err(|e| format!("reqwest build: {}", e))?;

    let resp = client
        .post(&url)
        .bearer_auth(&access)
        .send()
        .await
        .map_err(|e| format!("stt session http: {}", e))?;

    if !resp.status().is_success() {
        return Err(format!("stt session status: {}", resp.status()));
    }

    let session: SttSessionResponse = resp
        .json()
        .await
        .map_err(|e| format!("stt session parse: {}", e))?;

    // Rewrite https→wss, ensure the URL has a path (Modal's WS is mounted at "/"),
    // then append the session token as a query param.
    let wss = session.url.replacen("https://", "wss://", 1);
    let after_scheme = wss.splitn(2, "://").nth(1).unwrap_or("");
    let has_path = after_scheme.contains('/');
    let base = if has_path { wss } else { format!("{wss}/") };
    let sep = if base.contains('?') { "&" } else { "?" };
    Ok(format!("{base}{sep}key={}", session.token))
}

pub async fn get_or_init_transcription_engine<R: Runtime>(
    app: &AppHandle<R>,
) -> Result<TranscriptionEngine, String> {
    // Gateway-mediated STT is the only supported production path: fetch a
    // signed session from relay_web, then connect to Modal WSS with the
    // returned token. Keeps Modal URL private and JWT-gated. Failure here
    // should surface as an error, not silently fall back to a local model
    // the release build doesn't ship anymore.
    let gateway = crate::config::gateway_url();
    let wss_url = fetch_stt_session(app, &gateway).await?;
    info!("Using gateway-mediated NeMo STT");
    let provider = get_or_create_nemo(&wss_url);
    Ok(TranscriptionEngine {
        partial_provider: Some(provider.clone()),
        final_provider: provider,
    })
}
