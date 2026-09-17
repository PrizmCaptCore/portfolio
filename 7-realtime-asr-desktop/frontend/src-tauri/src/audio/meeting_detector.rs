// Detects whether a *meeting* (i.e. a known meeting/communication app is
// actively capturing the microphone) is happening, regardless of whether
// Relay itself is also recording.
//
// macOS-only. Uses the CoreAudio process inspection API introduced in macOS
// 14 (`kAudioHardwarePropertyProcessObjectList` +
// `kAudioProcessPropertyIsRunningInput`). The project's deployment target is
// already 14.2+, so no runtime version gating is needed.
//
// We poll once every `POLL_INTERVAL` and emit a Tauri event whenever the set
// of "meeting apps currently capturing input" changes. Non-meeting processes
// (System Settings, coreaudiod, Relay itself, etc.) are filtered out via the
// allowlist below so they never trigger detection.
//
// Frontend listens to `meeting-status-changed` with payload:
//   { active: bool, bundle_ids: string[] }

use std::time::Duration;

use serde::Serialize;
use tauri::{AppHandle, Emitter, Runtime};

pub const MEETING_STATUS_EVENT: &str = "meeting-status-changed";
const INITIAL_DELAY: Duration = Duration::from_secs(3);
const POLL_INTERVAL: Duration = Duration::from_secs(2);

// Allowlist of bundle IDs considered "meeting apps". Only processes matching
// one of these trigger detection — this prevents false positives from System
// Settings, coreaudiod, and other non-meeting processes that legitimately
// open the input device.
#[cfg(target_os = "macos")]
const MEETING_APP_BUNDLE_IDS: &[&str] = &[
    "us.zoom.xos",                  // Zoom
    "com.microsoft.teams",          // Microsoft Teams (classic)
    "com.microsoft.teams2",         // Microsoft Teams (new)
    "com.google.Chrome",            // Google Meet / web conferencing via Chrome
    "com.apple.Safari",             // Google Meet / web conferencing via Safari
    "com.microsoft.edgemac",        // Google Meet / web conferencing via Edge
    "company.thebrowser.Browser",   // Arc
    "com.tinyspeck.slackmacgap",    // Slack (huddle)
    "com.hnc.Discord",              // Discord
    "Cisco-Systems.Spark",          // Webex
    "com.cisco.webexmeetingsapp",   // Webex Meetings
    "us.zoom.ringcentral",          // RingCentral
    "com.skype.skype",              // Skype
    "com.gotomeeting.GoToMeeting",  // GoTo Meeting
];

#[derive(Debug, Clone, Serialize)]
pub struct MeetingStatusPayload {
    pub active: bool,
    pub bundle_ids: Vec<String>,
}

/// Spawn the meeting detector. Safe to call once during app setup; the spawned
/// task lives for the lifetime of the process.
pub fn spawn<R: Runtime>(app: AppHandle<R>) {
    #[cfg(target_os = "macos")]
    {
        tauri::async_runtime::spawn(async move {
            run_loop(app).await;
        });
    }

    #[cfg(not(target_os = "macos"))]
    {
        // No implementation on non-macOS platforms yet. Relay's primary target
        // is macOS; Windows could be added later via WASAPI session
        // notifications. We accept the AppHandle to keep the call site
        // platform-agnostic.
        let _ = app;
        log::info!("meeting_detector: not supported on this platform, skipping");
    }
}

#[cfg(target_os = "macos")]
async fn run_loop<R: Runtime>(app: AppHandle<R>) {
    let self_pid = std::process::id() as i32;
    let mut last_bundle_ids: Vec<String> = Vec::new();
    log::info!(
        "meeting_detector: started (self pid={}, initial_delay={:?}, poll={:?})",
        self_pid,
        INITIAL_DELAY,
        POLL_INTERVAL
    );

    tokio::time::sleep(INITIAL_DELAY).await;

    loop {
        let bundle_ids = match probe_active_input_processes(self_pid) {
            Ok(ids) => ids,
            Err(e) => {
                log::warn!("meeting_detector: probe failed: {}", e);
                tokio::time::sleep(POLL_INTERVAL).await;
                continue;
            }
        };

        if bundle_ids != last_bundle_ids {
            let active = !bundle_ids.is_empty();
            let payload = MeetingStatusPayload {
                active,
                bundle_ids: bundle_ids.clone(),
            };
            log::info!(
                "meeting_detector: status changed active={} bundles={:?}",
                active,
                bundle_ids
            );
            if let Err(e) = app.emit(MEETING_STATUS_EVENT, &payload) {
                log::warn!("meeting_detector: failed to emit event: {}", e);
            }
            last_bundle_ids = bundle_ids;
        }

        tokio::time::sleep(POLL_INTERVAL).await;
    }
}

/// Returns the sorted, deduplicated list of bundle IDs (or PID strings, if
/// bundle ID is unavailable) for processes currently capturing audio input,
/// excluding our own process.
#[cfg(target_os = "macos")]
fn probe_active_input_processes(self_pid: i32) -> Result<Vec<String>, String> {
    use cidre::core_audio as ca;

    let processes = ca::Process::list().map_err(|e| format!("Process::list: {:?}", e))?;

    let mut ids: Vec<String> = Vec::new();
    for process in processes {
        // Skip processes that are not actively capturing input. Errors here
        // are common for transient/system processes — treat them as "not
        // capturing" and move on.
        match process.is_running_input() {
            Ok(true) => {}
            Ok(false) => continue,
            Err(_) => continue,
        }

        let pid = match process.pid() {
            Ok(p) => p,
            Err(_) => continue,
        };
        if pid == self_pid {
            continue;
        }

        // Only consider processes with a known meeting-app bundle ID.
        // Anything without a bundle ID (transient/system processes) or with
        // an unrecognized bundle ID is ignored.
        let label = match process.bundle_id() {
            Ok(s) => s.to_string(),
            Err(_) => continue,
        };
        if !MEETING_APP_BUNDLE_IDS.contains(&label.as_str()) {
            continue;
        }
        ids.push(label);
    }

    ids.sort();
    ids.dedup();
    Ok(ids)
}
