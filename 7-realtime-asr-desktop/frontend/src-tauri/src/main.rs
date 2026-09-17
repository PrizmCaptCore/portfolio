#![cfg_attr(
    all(not(debug_assertions), target_os = "windows"),
    windows_subsystem = "windows"
)]

use std::fs;
use std::path::PathBuf;

use log::{self, LevelFilter};

fn install_panic_logging_hook() {
    let previous = std::panic::take_hook();
    std::panic::set_hook(Box::new(move |panic_info| {
        let location = panic_info
            .location()
            .map(|loc| format!("{}:{}:{}", loc.file(), loc.line(), loc.column()))
            .unwrap_or_else(|| "<unknown>".to_string());

        let payload = if let Some(s) = panic_info.payload().downcast_ref::<&str>() {
            (*s).to_string()
        } else if let Some(s) = panic_info.payload().downcast_ref::<String>() {
            s.clone()
        } else {
            "<non-string panic payload>".to_string()
        };

        let backtrace = std::backtrace::Backtrace::force_capture();
        log::error!(
            "panic captured at {}: {}\nbacktrace:\n{}",
            location,
            payload,
            backtrace
        );

        previous(panic_info);
    }));
}

fn default_log_dir() -> PathBuf {
    #[cfg(target_os = "macos")]
    {
        if let Some(home) = dirs::home_dir() {
            return home.join("Library").join("Logs").join("Relay Assistant");
        }
    }

    if let Some(dir) = dirs::data_local_dir() {
        return dir.join("Relay Assistant").join("logs");
    }

    std::env::temp_dir().join("relay-assistant-logs")
}

fn init_logging() -> Result<PathBuf, Box<dyn std::error::Error>> {
    let log_dir = default_log_dir();
    fs::create_dir_all(&log_dir)?;

    let log_file = log_dir.join("relay-assistant.log");
    let file_dispatch = fern::log_file(&log_file)?;

    fern::Dispatch::new()
        .level(LevelFilter::Info)
        .level_for("sqlx", LevelFilter::Warn)
        .level_for("wry", LevelFilter::Warn)
        .level_for("tao", LevelFilter::Warn)
        .format(|out, message, record| {
            out.finish(format_args!(
                "{} [{}] {}",
                chrono::Local::now().format("%Y-%m-%d %H:%M:%S%.3f"),
                record.level(),
                message
            ))
        })
        .chain(std::io::stdout())
        .chain(file_dispatch)
        .apply()?;

    Ok(log_file)
}

fn main() {
    std::env::set_var("RUST_LOG", "info");
    if std::env::var_os("RUST_BACKTRACE").is_none() {
        std::env::set_var("RUST_BACKTRACE", "full");
    }

    let log_file = init_logging().ok();
    install_panic_logging_hook();

    // Async logger will be initialized lazily when first needed (after Tauri runtime starts)
    log::info!("Starting application...");
    if let Some(path) = log_file {
        log::info!("File log path: {}", path.display());
    }

    app_lib::run();
}
