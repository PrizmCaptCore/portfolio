#[path = "build/ffmpeg.rs"]
mod ffmpeg;

#[path = "build/models.rs"]
mod models;

fn main() {
    #[cfg(target_os = "macos")]
    {
        println!("cargo:rustc-link-lib=framework=AVFoundation");
        println!("cargo:rustc-link-lib=framework=Cocoa");
        println!("cargo:rustc-link-lib=framework=Foundation");
    }

    ffmpeg::ensure_ffmpeg_binary();
    models::ensure_models();
    tauri_build::build()
}
