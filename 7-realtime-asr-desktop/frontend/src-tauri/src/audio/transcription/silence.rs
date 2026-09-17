// audio/transcription/silence.rs
//
// Tracks "time since last speech" and auto-stops recording after extended
// silence. Avoids paying for warm Modal containers (STT/translate/summary)
// when the user has effectively walked away from the meeting.
//
// Lifecycle:
//   - start_silence_monitor() spawned by start_recording
//   - worker calls mark_speech() on every transcript event
//   - monitor task polls every 10s:
//       * 120s elapsed -> emit "recording-silence-warning" once
//       * 180s elapsed -> emit "recording-auto-stopped-silence" + invoke stop_recording
//   - dismissed by user (frontend invokes dismiss_silence_warning) -> resets clock
//   - stop_recording aborts the monitor (avoids double-stop after explicit stop)

use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Mutex;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use log::{info, warn};
use tauri::{AppHandle, Emitter, Runtime};
use tokio::task::JoinHandle;

const WARNING_AT_SECS: u64 = 120;
const AUTOSTOP_AT_SECS: u64 = 180;
const POLL_INTERVAL_SECS: u64 = 10;

/// Unix timestamp (seconds) of the last detected speech event, or 0 if none yet.
static LAST_SPEECH_AT: AtomicU64 = AtomicU64::new(0);

/// Active monitor task (set by start_silence_monitor, cleared by abort).
static MONITOR_TASK: Mutex<Option<JoinHandle<()>>> = Mutex::new(None);

fn now_secs() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0)
}

/// Reset the speech clock to "now". Called by transcription worker when a
/// non-empty transcript arrives, and by the dismiss-warning Tauri command.
pub fn mark_speech() {
    LAST_SPEECH_AT.store(now_secs(), Ordering::Relaxed);
}

fn seconds_since_last_speech() -> u64 {
    let last = LAST_SPEECH_AT.load(Ordering::Relaxed);
    if last == 0 {
        return 0;
    }
    now_secs().saturating_sub(last)
}

/// Spawn the silence-monitor task. Aborts any previous monitor first.
pub fn start_silence_monitor<R: Runtime>(app: AppHandle<R>) {
    abort_silence_monitor();
    mark_speech();
    let handle = tokio::spawn(silence_monitor_loop(app));
    *MONITOR_TASK.lock().expect("MONITOR_TASK poisoned") = Some(handle);
}

/// Cancel the silence monitor (called from stop_recording).
pub fn abort_silence_monitor() {
    if let Some(h) = MONITOR_TASK
        .lock()
        .expect("MONITOR_TASK poisoned")
        .take()
    {
        h.abort();
    }
}

async fn silence_monitor_loop<R: Runtime>(app: AppHandle<R>) {
    let mut warned = false;
    loop {
        tokio::time::sleep(Duration::from_secs(POLL_INTERVAL_SECS)).await;

        let elapsed = seconds_since_last_speech();

        if elapsed >= AUTOSTOP_AT_SECS {
            info!(
                "Silence monitor: {}s elapsed, auto-stopping recording",
                elapsed
            );
            let _ = app.emit(
                "recording-auto-stopped-silence",
                serde_json::json!({ "elapsed_secs": elapsed }),
            );
            // Trigger the same shutdown path as a manual stop. Detach so we
            // don't deadlock waiting on stop_recording (which itself may emit
            // events the frontend is listening for).
            let app_for_stop = app.clone();
            tokio::spawn(async move {
                if let Err(e) = crate::audio::recording_commands::stop_recording(
                    app_for_stop,
                    crate::audio::recording_commands::RecordingArgs {
                        save_path: String::new(),
                    },
                )
                .await
                {
                    warn!("Silence auto-stop failed: {}", e);
                }
            });
            return;
        }

        if elapsed >= WARNING_AT_SECS && !warned {
            warned = true;
            let seconds_until_stop = AUTOSTOP_AT_SECS.saturating_sub(elapsed);
            info!(
                "Silence monitor: {}s elapsed, warning user ({}s until stop)",
                elapsed, seconds_until_stop
            );
            let _ = app.emit(
                "recording-silence-warning",
                serde_json::json!({
                    "elapsed_secs": elapsed,
                    "seconds_until_stop": seconds_until_stop,
                }),
            );
        } else if elapsed < WARNING_AT_SECS {
            warned = false;
        }
    }
}
