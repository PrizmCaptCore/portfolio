pub fn format_timestamp(seconds: f64) -> String {
    let total_seconds = seconds as u64;
    let hours = total_seconds / 3600;
    let minutes = (total_seconds % 3600) / 60;
    let secs = total_seconds % 60;
    format!("{:02}:{:02}:{:02}", hours, minutes, secs)
}

#[tauri::command]
pub fn copy_to_clipboard(text: String) -> Result<(), String> {
    use std::process::{Command, Stdio};
    use std::io::Write;

    #[cfg(target_os = "macos")]
    {
        let mut child = Command::new("pbcopy")
            .stdin(Stdio::piped())
            .spawn()
            .map_err(|e| format!("Failed to spawn pbcopy: {}", e))?;
        child.stdin.take().unwrap().write_all(text.as_bytes())
            .map_err(|e| format!("Failed to write to pbcopy: {}", e))?;
        child.wait().map_err(|e| format!("pbcopy failed: {}", e))?;
        return Ok(());
    }

    #[cfg(target_os = "windows")]
    {
        // clip.exe reads from stdin
        let mut child = Command::new("clip")
            .stdin(Stdio::piped())
            .spawn()
            .map_err(|e| format!("Failed to spawn clip: {}", e))?;
        child.stdin.take().unwrap().write_all(text.as_bytes())
            .map_err(|e| format!("Failed to write to clip: {}", e))?;
        child.wait().map_err(|e| format!("clip failed: {}", e))?;
        return Ok(());
    }

    #[cfg(target_os = "linux")]
    {
        let mut child = Command::new("xclip")
            .args(["-selection", "clipboard"])
            .stdin(Stdio::piped())
            .spawn()
            .map_err(|e| format!("Failed to spawn xclip: {}", e))?;
        child.stdin.take().unwrap().write_all(text.as_bytes())
            .map_err(|e| format!("Failed to write to xclip: {}", e))?;
        child.wait().map_err(|e| format!("xclip failed: {}", e))?;
        return Ok(());
    }
}

/// Opens macOS System Settings to a specific privacy preference pane
#[cfg(target_os = "macos")]
#[tauri::command]
pub async fn open_system_settings(preference_pane: String) -> Result<(), String> {
    use std::process::Command;

    // Construct the URL for System Settings
    let url = format!(
        "x-apple.systempreferences:com.apple.preference.security?{}",
        preference_pane
    );

    // Use the 'open' command on macOS to open the URL
    Command::new("open")
        .arg(&url)
        .spawn()
        .map_err(|e| format!("Failed to open system settings: {}", e))?;

    Ok(())
}
