// audio/onnx_runtime.rs
//
// Tauri resource path utilities.

#![allow(dead_code)]

use std::path::PathBuf;

/// Locate the Tauri resource directory.
/// - macOS: `Relay Assistant.app/Contents/Resources/`
/// - Other: `<exe_dir>/resources/`
pub fn tauri_resource_dir() -> Option<PathBuf> {
    let exe = std::env::current_exe().ok()?;
    let exe_dir = exe.parent()?;

    #[cfg(target_os = "macos")]
    {
        let candidate = exe_dir.join("..").join("Resources");
        if candidate.exists() {
            return Some(candidate);
        }
    }

    let candidate = exe_dir.join("resources");
    if candidate.exists() {
        return Some(candidate);
    }

    None
}

/// Resolve a relative path against known bundled resource locations.
pub fn bundled_resource_path(rel: &str) -> Option<PathBuf> {
    let base = tauri_resource_dir()?;

    [
        base.join(rel),
        base.join("bundled-resources").join(rel),
        base.join("_up_").join(rel),
        base.join("_up_").join("_up_").join(rel),
    ]
    .into_iter()
    .find(|path| path.exists())
}
