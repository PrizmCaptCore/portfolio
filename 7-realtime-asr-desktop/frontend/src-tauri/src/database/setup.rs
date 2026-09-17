use log::info;
use std::path::PathBuf;
use std::sync::Once;
use tauri::{AppHandle, Emitter, Manager};

use super::manager::DatabaseManager;
use super::repositories::setting::SettingsRepository;
use crate::state::AppState;
use crate::summary::RelayAIConfig;

/// Register sqlite-vec as an auto-extension so every subsequent sqlite
/// connection — including sqlx's pool — has `vec0`, `vec_f32`, and the
/// MATCH operator available. Must run before the first connection is
/// opened; once a connection exists, registering for *that* connection
/// requires the per-conn API which sqlx doesn't expose ergonomically.
///
/// The two crates (libsqlite3-sys and sqlite-vec) must resolve to the
/// SAME bundled sqlite static lib as sqlx-sqlite's transitive dep —
/// pinned in Cargo.toml to libsqlite3-sys 0.30. If they diverge, the
/// registration silently registers against a different sqlite instance
/// and `vec0` is invisible from sqlx's connections.
pub fn install_sqlite_vec_extension() {
    static INIT: Once = Once::new();
    INIT.call_once(|| unsafe {
        // libsqlite3-sys 0.30 declares the entry point as
        // `unsafe extern "C" fn(*mut sqlite3, *mut *const c_char, *const sqlite3_api_routines) -> c_int`,
        // which matches `sqlite_vec::sqlite3_vec_init`'s ABI exactly — the
        // transmute is just to bridge the two crates' distinct opaque
        // pointer types (libsqlite3-sys::sqlite3 vs sqlite_vec's own
        // re-declaration). Both crates compile against the SAME bundled
        // libsqlite3 (pinned in Cargo.toml), so this is safe.
        type EntryFn = unsafe extern "C" fn(
            *mut libsqlite3_sys::sqlite3,
            *mut *mut std::os::raw::c_char,
            *const libsqlite3_sys::sqlite3_api_routines,
        ) -> std::os::raw::c_int;
        let entry: EntryFn = std::mem::transmute(
            sqlite_vec::sqlite3_vec_init as *const (),
        );
        let rc = libsqlite3_sys::sqlite3_auto_extension(Some(entry));
        if rc != libsqlite3_sys::SQLITE_OK {
            log::error!("sqlite3_auto_extension(sqlite_vec) returned {}", rc);
        } else {
            info!("Registered sqlite-vec as auto-extension");
        }
    });
}

/// Remove orphaned SQLite ancillary files (WAL / SHM / journal) when the
/// main `.sqlite` is known to be absent. ONLY safe to call on the
/// first-launch path: on that path there is no user data to lose, and
/// orphan WAL/SHM left from a prior uninstall would otherwise confuse a
/// fresh DB create. Never call this when the main DB exists — use
/// `quarantine_sqlite_files` instead so the user's history survives.
fn wipe_orphan_ancillary_files(app_data_dir: &PathBuf) {
    let files = [
        app_data_dir.join("meeting_minutes.sqlite-wal"),
        app_data_dir.join("meeting_minutes.sqlite-shm"),
        app_data_dir.join("meeting_minutes.sqlite-journal"),
    ];
    for path in &files {
        if path.exists() {
            match std::fs::remove_file(path) {
                Ok(_) => info!("Removed orphan sqlite file: {:?}", path),
                Err(e) => log::warn!("Could not remove {:?}: {}", path, e),
            }
        }
    }
}

/// Move existing SQLite files into a timestamped backup directory before
/// retrying init from a clean slate. Used when the first DB-open attempt
/// fails on an existing user database — wiping outright would silently
/// destroy meeting history across updates, so we preserve the originals
/// (file rename, not delete) so the user can recover by copying the files
/// back manually after the buggy build is rolled back / patched.
///
/// Returns the backup path on success, or None if nothing existed to
/// move (or every rename failed — in which case the caller's retry will
/// hit the same files again, which is the right behavior: surface the
/// error rather than silently destroy data).
fn quarantine_sqlite_files(app_data_dir: &PathBuf) -> Option<PathBuf> {
    use std::time::{SystemTime, UNIX_EPOCH};
    let ts = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0);
    let backup_dir = app_data_dir.join(format!("db_backup_{}", ts));
    if let Err(e) = std::fs::create_dir_all(&backup_dir) {
        log::error!("Could not create backup dir {:?}: {}", backup_dir, e);
        return None;
    }

    let candidates = [
        "meeting_minutes.sqlite",
        "meeting_minutes.sqlite-wal",
        "meeting_minutes.sqlite-shm",
        "meeting_minutes.sqlite-journal",
    ];
    let mut moved = 0;
    for name in &candidates {
        let src = app_data_dir.join(name);
        if !src.exists() {
            continue;
        }
        let dst = backup_dir.join(name);
        match std::fs::rename(&src, &dst) {
            Ok(_) => {
                log::warn!("Quarantined {:?} -> {:?}", src, dst);
                moved += 1;
            }
            Err(e) => {
                log::error!("Could not quarantine {:?}: {}", src, e);
            }
        }
    }

    if moved == 0 {
        let _ = std::fs::remove_dir(&backup_dir);
        None
    } else {
        Some(backup_dir)
    }
}

/// Initialize the database, register AppState, and optionally emit first-launch event.
///
/// Strategy:
///   1. Try to open / create the database normally.
///   2. If that fails on a non-first-launch DB, QUARANTINE all sqlite-related
///      files into a timestamped backup directory and retry once with a fresh
///      database. We never delete the user's existing DB — silent data loss
///      across updates (reported across multiple builds) is worse than a
///      startup that comes up with empty history but preserves the old files
///      for manual recovery.
///   3. If this is a true first launch (main `.sqlite` absent), only wipe
///      orphan WAL/SHM/journal files; there's nothing else to lose.
///   4. If the retry also fails, return Err — caller logs it but the app
///      continues (commands that need AppState will return "state not managed").
pub async fn initialize_database_on_startup(app: &AppHandle) -> Result<(), String> {
    let is_first_launch = DatabaseManager::is_first_launch(app)
        .await
        .map_err(|e| format!("Failed to check first launch status: {}", e))?;

    // First-launch only: clear orphan WAL/SHM/journal so a fresh DB doesn't
    // inherit them. Main `.sqlite` is known absent here, so nothing to lose.
    if is_first_launch {
        if let Ok(app_data_dir) = app.path().app_data_dir() {
            wipe_orphan_ancillary_files(&app_data_dir);
        }
    }

    let db_manager = match DatabaseManager::new_from_app_handle(app).await {
        Ok(m) => {
            info!("Database opened successfully (first_launch={})", is_first_launch);
            m
        }
        Err(first_err) => {
            log::error!(
                "Database init failed (first_launch={}): {}. Quarantining existing files and retrying with a fresh DB...",
                is_first_launch,
                first_err
            );
            // Move the existing files aside instead of deleting them. If
            // the user had meeting history, it's preserved on disk under
            // db_backup_<ts>/ for recovery. Never `remove_file` here.
            if let Ok(app_data_dir) = app.path().app_data_dir() {
                if let Some(dir) = quarantine_sqlite_files(&app_data_dir) {
                    log::warn!(
                        "Existing DB quarantined to {:?}. If this is an upgraded \
                         install, prior meeting history is in that folder — do NOT \
                         auto-delete; leave it for the user to recover.",
                        dir
                    );
                }
            }
            DatabaseManager::new_from_app_handle(app)
                .await
                .map_err(|retry_err| {
                    format!(
                        "Database init failed even after quarantine: {}",
                        retry_err
                    )
                })?
        }
    };

    app.manage(AppState { db_manager });
    info!("AppState registered successfully");

    if is_first_launch {
        // Seed a placeholder summary-model config so the UI's "has-model"
        // gates pass and summary generation routes through the gateway
        // fallback in llm_client.rs. The real backing model tag is never
        // written here — llm_client substitutes it server-side when the
        // gateway /summarize/ endpoint is hit.
        let state: tauri::State<'_, AppState> = app.state();
        let pool = state.db_manager.pool();
        let default_config = RelayAIConfig {
            endpoint: String::new(),
            api_key: None,
            model: "relay-ai".to_string(),
            max_tokens: None,
            temperature: None,
            top_p: None,
        };
        if let Err(e) = SettingsRepository::save_relay_ai_config(pool, &default_config).await {
            log::warn!("Failed to seed default summary config on first launch: {}", e);
        } else {
            info!("Seeded default summary config (provider=relay-ai, model=relay-ai)");
        }

        let app_handle = app.clone();
        tauri::async_runtime::spawn(async move {
            tokio::time::sleep(tokio::time::Duration::from_millis(500)).await;
            match app_handle.emit("first-launch-detected", ()) {
                Ok(_) => info!("Emitted first-launch-detected"),
                Err(e) => log::warn!("Failed to emit first-launch-detected: {}", e),
            }
        });
    }

    Ok(())
}
