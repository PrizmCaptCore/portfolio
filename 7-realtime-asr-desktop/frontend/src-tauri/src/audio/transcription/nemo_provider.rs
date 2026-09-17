// audio/transcription/nemo_provider.rs
//
// WebSocket client that connects to the Python cnn_stt_server.py process and
// implements TranscriptionProvider.
//
// Protocol:
//   Client → Server : binary frame  — f32 LE PCM 16 kHz mono
//   Server → Client : JSON text     — {"text":"…", "is_partial": bool}
//   Client → Server : JSON text     — {"cmd":"reset"}

use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc,
};

use async_trait::async_trait;
use futures_util::{SinkExt, StreamExt};
use log::{error, info, warn};
use tokio::sync::{mpsc, Mutex, Notify};
use tokio_tungstenite::{connect_async, tungstenite::Message};

use super::provider::{TranscriptResult, TranscriptionError, TranscriptionProvider};

pub const DEFAULT_NEMO_URL: &str = "ws://localhost:8765";

// ---------------------------------------------------------------------------
// NemoProvider
// ---------------------------------------------------------------------------

enum WsMessage {
    Audio(Vec<u8>),
    Text(String),
    /// Request graceful shutdown: ws_task sends Close frame, stops
    /// reconnecting, and exits the task.
    Shutdown,
}

pub struct NemoProvider {
    url: String,
    /// Send audio bytes or text commands to the background WS task
    audio_tx: mpsc::UnboundedSender<WsMessage>,
    /// Receive transcript results from the background WS task
    result_rx: Arc<Mutex<mpsc::UnboundedReceiver<TranscriptResult>>>,
    /// True while the WebSocket is connected
    connected: Arc<AtomicBool>,
    /// Notified by ws_task once the Close frame has been sent and the
    /// task has exited. Lets `close()` await actual teardown.
    shutdown_complete: Arc<Notify>,
}

unsafe impl Send for NemoProvider {}
unsafe impl Sync for NemoProvider {}

impl NemoProvider {
    /// Connect (lazily, in background) to `url`.
    /// Falls back to `DEFAULT_NEMO_URL` when `url` is None.
    pub fn new(url: Option<&str>) -> Self {
        let url = url
            .map(|s| s.to_string())
            .unwrap_or_else(|| {
                std::env::var("RELAY_NEMO_STT_URL")
                    .unwrap_or_else(|_| DEFAULT_NEMO_URL.to_string())
            });

        let (audio_tx, audio_rx) = mpsc::unbounded_channel::<WsMessage>();
        let (result_tx, result_rx) = mpsc::unbounded_channel::<TranscriptResult>();
        let connected = Arc::new(AtomicBool::new(false));
        let shutdown_complete = Arc::new(Notify::new());

        tokio::spawn(ws_task(
            url.clone(),
            audio_rx,
            result_tx,
            connected.clone(),
            shutdown_complete.clone(),
        ));

        info!("NemoProvider: will connect to {}", url);
        Self {
            url,
            audio_tx,
            result_rx: Arc::new(Mutex::new(result_rx)),
            connected,
            shutdown_complete,
        }
    }

    pub fn url(&self) -> &str {
        &self.url
    }
}

// ---------------------------------------------------------------------------
// TranscriptionProvider impl
// ---------------------------------------------------------------------------

#[async_trait]
impl TranscriptionProvider for NemoProvider {
    async fn transcribe(
        &self,
        audio: Vec<f32>,
        _language: Option<String>,
    ) -> Result<TranscriptResult, TranscriptionError> {
        if !self.connected.load(Ordering::SeqCst) {
            return Err(TranscriptionError::ModelNotLoaded);
        }

        // Encode f32 → raw bytes (LE) and send to background task
        let bytes: Vec<u8> = audio
            .iter()
            .flat_map(|&f| f.to_le_bytes())
            .collect();

        if self.audio_tx.send(WsMessage::Audio(bytes)).is_err() {
            return Err(TranscriptionError::EngineFailed(
                "NeMo audio channel closed".to_string(),
            ));
        }

        // Drain any results the server has sent back (non-blocking)
        let mut rx = self.result_rx.lock().await;
        match rx.try_recv() {
            Ok(result) => Ok(result),
            Err(_) => Ok(TranscriptResult {
                text: String::new(),
                confidence: None,
                is_partial: true,
                detected_language: None,
            }),
        }
    }

    async fn is_model_loaded(&self) -> bool {
        self.connected.load(Ordering::SeqCst)
    }

    fn supports_partial(&self) -> bool {
        true
    }

    async fn get_current_model(&self) -> Option<String> {
        Some("cnn-stt-0.6b".to_string())
    }

    fn provider_name(&self) -> &'static str {
        "NeMo"
    }

    fn prefers_raw_chunks(&self) -> bool {
        true
    }

    async fn reset_session(&self) {
        let cmd = r#"{"cmd":"reset"}"#.to_string();
        let _ = self.audio_tx.send(WsMessage::Text(cmd));
        info!("NeMo WS: sent session reset");
    }

    async fn close(&self) {
        if self.audio_tx.send(WsMessage::Shutdown).is_err() {
            // ws_task already exited; nothing to wait for.
            return;
        }
        // Bound the wait: server may be slow to ack the Close frame, and
        // we don't want stop_recording to hang on network pathology.
        let _ = tokio::time::timeout(
            std::time::Duration::from_secs(3),
            self.shutdown_complete.notified(),
        )
        .await;
        info!("NeMo WS: closed");
    }
}

// ---------------------------------------------------------------------------
// Background WebSocket task
// ---------------------------------------------------------------------------

async fn ws_task(
    url: String,
    mut audio_rx: mpsc::UnboundedReceiver<WsMessage>,
    result_tx: mpsc::UnboundedSender<TranscriptResult>,
    connected: Arc<AtomicBool>,
    shutdown_complete: Arc<Notify>,
) {
    let connect_url = {
        let key = std::env::var("RELAY_STT_TOKEN").unwrap_or_default();
        if key.is_empty() {
            url.clone()
        } else {
            let sep = if url.contains('?') { "&" } else { "?" };
            format!("{}{sep}key={key}", url)
        }
    };

    // Tracks whether we've been asked to shut down. Set by the inner loop
    // when a Shutdown message arrives; the outer loop consults it to skip
    // the reconnect.
    let mut shutdown_requested = false;

    loop {
        info!("NeMo WS: connecting to {}", url);

        match connect_async(&connect_url).await {
            Err(e) => {
                error!("NeMo WS: connection failed: {}", e);
            }
            Ok((ws, _)) => {
                connected.store(true, Ordering::SeqCst);
                info!("NeMo WS: connected");

                let (mut ws_tx, mut ws_rx) = ws.split();

                loop {
                    tokio::select! {
                        // Send audio or commands to the server
                        msg = audio_rx.recv() => {
                            match msg {
                                Some(WsMessage::Audio(bytes)) => {
                                    if ws_tx.send(Message::Binary(bytes)).await.is_err() {
                                        warn!("NeMo WS: send error, reconnecting");
                                        break;
                                    }
                                }
                                Some(WsMessage::Text(text)) => {
                                    if ws_tx.send(Message::Text(text)).await.is_err() {
                                        warn!("NeMo WS: send error, reconnecting");
                                        break;
                                    }
                                }
                                Some(WsMessage::Shutdown) => {
                                    info!("NeMo WS: shutdown requested, sending close frame");
                                    let _ = ws_tx.send(Message::Close(None)).await;
                                    let _ = ws_tx.close().await;
                                    shutdown_requested = true;
                                    break;
                                }
                                None => {
                                    // Channel closed (app shutting down / provider dropped)
                                    let _ = ws_tx.send(Message::Close(None)).await;
                                    let _ = ws_tx.close().await;
                                    shutdown_requested = true;
                                    break;
                                }
                            }
                        }

                        // Receive results from server
                        msg = ws_rx.next() => {
                            match msg {
                                Some(Ok(Message::Text(text))) => {
                                    if let Ok(v) = serde_json::from_str::<serde_json::Value>(&text) {
                                        let transcript = v["text"]
                                            .as_str()
                                            .unwrap_or("")
                                            .to_string();
                                        let is_partial = v["is_partial"]
                                            .as_bool()
                                            .unwrap_or(true);

                                        if !transcript.is_empty() {
                                            let _ = result_tx.send(TranscriptResult {
                                                text: transcript,
                                                confidence: None,
                                                is_partial,
                                                detected_language: None,
                                            });
                                        }
                                    }
                                }
                                Some(Err(e)) => {
                                    warn!("NeMo WS: receive error: {}", e);
                                    break;
                                }
                                None => {
                                    warn!("NeMo WS: server closed connection");
                                    break;
                                }
                                _ => {}
                            }
                        }
                    }
                }

                connected.store(false, Ordering::SeqCst);
                // Drain stale messages before reconnecting
                while audio_rx.try_recv().is_ok() {}
            }
        }

        if shutdown_requested {
            shutdown_complete.notify_waiters();
            info!("NeMo WS: task exiting (shutdown)");
            return;
        }

        tokio::time::sleep(tokio::time::Duration::from_secs(2)).await;
    }
}
