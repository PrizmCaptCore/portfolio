// audio/transcription/worker.rs
//
// Parallel transcription worker pool and chunk processing logic.

use super::provider::{TranscriptionError, TranscriptionProvider};
use crate::audio::AudioChunk;
use log::{error, info, warn};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Mutex, OnceLock};
use tauri::{AppHandle, Emitter, Runtime};

// ---------------------------------------------------------------------------
// Stable-prefix commit logic for partial transcripts.
//
// CNN STT partials re-transcribe the last 5s of audio every ~600ms,
// so naive rendering causes the entire string to flicker as tail tokens
// re-decode. Instead, we keep the last N tokenizations per `sequence_id`
// and treat the longest common prefix as "committed" (locked, will not
// flicker). Anything past the LCP is "tentative" — frontend renders it
// dimmed so the user sees a stable head and a live tail.
//
// `committed_count` is monotonic within a turn — once a word is committed
// it stays committed even if a later partial flickers. The eventual final
// from the final provider replaces the row entirely, so any committed-but-wrong
// word gets corrected ~1-2s later.
// ---------------------------------------------------------------------------

#[allow(dead_code)]
struct PartialCommitState {}

fn partial_commit_state() -> &'static Mutex<HashMap<u64, PartialCommitState>> {
    static STATE: OnceLock<Mutex<HashMap<u64, PartialCommitState>>> = OnceLock::new();
    STATE.get_or_init(|| Mutex::new(HashMap::new()))
}

/// Drop per-turn commit state once the final transcript replaces the row.
fn drop_partial_commit(sequence_id: u64) {
    if let Ok(mut map) = partial_commit_state().lock() {
        map.remove(&sequence_id);
    }
}

/// Wipe all per-turn commit state. Called when a new recording starts so
/// stale entries from a previous session cannot leak across recordings.
fn reset_partial_commit_state() {
    if let Ok(mut map) = partial_commit_state().lock() {
        map.clear();
    }
}

///
///
fn is_punctuation_only(text: &str) -> bool {
    !text.chars().any(|c| c.is_alphanumeric())
}

/// STT sometimes emits a long plausible paragraph on a 1–2s VAD chunk
///
fn live_transcript_confidence_after_length_sanity(
    transcript: &str,
    chunk_duration_sec: f64,
    reported: Option<f32>,
) -> Option<f32> {
    let base = reported.unwrap_or(0.85);
    let trimmed = transcript.trim();
    if trimmed.is_empty() || chunk_duration_sec < 0.25 {
        return Some(base);
    }
    let word_count = trimmed.split_whitespace().count();
    let max_words = ((chunk_duration_sec * 8.0).ceil() as usize).saturating_add(20);
    if chunk_duration_sec < 4.0 && word_count > max_words {
        warn!(
            " length sanity: suspected hallucination (duration={:.1}s, words={}, max={}) - emitting with reduced confidence",
            chunk_duration_sec, word_count, max_words
        );
        return Some(0.35);
    }
    Some(base)
}

// Speech detection flag - reset per recording session
static SPEECH_DETECTED_EMITTED: AtomicBool = AtomicBool::new(false);

/// Sentence id counter for split sentences (sent_idx > 0).
///
///
///
static SENTENCE_SUB_ID_COUNTER: AtomicU64 = AtomicU64::new(1_000_000_000);

/// Reset the speech detected flag for a new recording session
pub fn reset_speech_detected_flag() {
    SPEECH_DETECTED_EMITTED.store(false, Ordering::SeqCst);
    // Drop stable-prefix commit state from any prior recording so committed
    // words from an old turn cannot leak into a new sequence_id collision.
    reset_partial_commit_state();
    info!(
        " SPEECH_DETECTED_EMITTED reset to: {}",
        SPEECH_DETECTED_EMITTED.load(Ordering::SeqCst)
    );
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct TranscriptUpdate {
    pub text: String,
    pub timestamp: String, // Wall-clock time for reference (e.g., "14:30:05")
    pub source: String,
    pub sequence_id: u64,
    pub chunk_start_time: f64, // Legacy field, kept for compatibility
    pub is_partial: bool,
    pub confidence: f32,
    // Recording-relative timestamps for playback sync
    pub audio_start_time: f64, // Seconds from recording start (e.g., 125.3)
    pub audio_end_time: f64,   // Seconds from recording start (e.g., 128.6)
    pub duration: f64,         // Segment duration in seconds (e.g., 3.3)
    // ISO 639-1 language code detected by the provider (auto-detect, etc.).
    // None if the provider doesn't expose detection. Frontend uses this to decide
    // whether to auto-translate (only when this differs from the user's language).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub detected_language: Option<String>,
    /// Trailing portion of `text` that is still volatile (re-decoded each
    /// partial). Frontend renders this dimmed; the prefix in `text` minus
    /// this suffix is the stable committed portion. Always `None` for finals.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub tentative_text: Option<String>,
    /// Translated text (e.g., English → Korean). None if translation unavailable.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub translated_text: Option<String>,
}

// NOTE: get_transcript_history and get_recording_meeting_name functions
// have been moved to recording_commands.rs where they have access to RECORDING_MANAGER

/// Optimized parallel transcription task ensuring ZERO chunk loss
pub fn start_transcription_task<R: Runtime>(
    app: AppHandle<R>,
    transcription_receiver: tokio::sync::mpsc::UnboundedReceiver<AudioChunk>,
) -> tokio::task::JoinHandle<()> {
    tokio::spawn(async move {
        info!(" Starting optimized parallel transcription task - guaranteeing zero chunk loss");

        // Initialize transcription engine
        // CNN STT = local standalone STT for both partials and finals
        let transcription_engine = match super::engine::get_or_init_transcription_engine(&app).await
        {
            Ok(engine) => engine,
            Err(e) => {
                error!("Failed to initialize transcription engine: {}", e);
                let _ = app.emit("transcription-error", serde_json::json!({
                    "error": e,
                    "userMessage": "Recording failed: Unable to initialize speech recognition. Please check your model settings.",
                    "actionable": true
                }));
                return;
            }
        };

        // Reset server-side session state so previous meeting's audio doesn't bleed in
        transcription_engine.final_provider.reset_session().await;

        // Extract providers as Arc clones for worker threads
        let partial_provider: Option<Arc<dyn TranscriptionProvider>> =
            transcription_engine.partial_provider.clone();
        let final_provider = transcription_engine.final_provider.clone();

        // Initialize EN→KO translator (optional — skipped if unavailable)
        let translator: Option<Arc<dyn crate::audio::translation::Translator>> =
            match crate::audio::translation::get_or_init_translator() {
                Ok(t) => {
                    info!("EN→KO translator ready");
                    Some(t)
                }
                Err(e) => {
                    warn!("EN→KO translator unavailable: {}", e);
                    info!("Translation disabled");
                    None
                }
            };

        // Punctuation processor disabled — TDT output is raw subword tokens.
        // A punctuation model could be added later if needed.
        let _punctuation_processor: Option<Arc<String>> = None; // placeholder, punctuation disabled

        // Create parallel workers for faster processing while preserving ALL chunks
        const NUM_WORKERS: usize = 1; // Serial processing ensures transcripts emit in chronological order
        let (work_sender, work_receiver) = tokio::sync::mpsc::unbounded_channel::<AudioChunk>();
        let work_receiver = Arc::new(tokio::sync::Mutex::new(work_receiver));

        // Track completion: AtomicU64 for chunks queued, AtomicU64 for chunks completed
        let chunks_queued = Arc::new(AtomicU64::new(0));
        let chunks_completed = Arc::new(AtomicU64::new(0));
        let input_finished = Arc::new(AtomicBool::new(false));

        // Streaming sequence ID: shared across worker iterations.
        // Partials share the same ID (frontend updates one line).
        // Bumped on endpoint (final) so next utterance gets a new line.
        let streaming_sequence_id = Arc::new(AtomicU64::new(1));

        info!(
            " Starting {} transcription worker{} (serial mode for ordered emission)",
            NUM_WORKERS,
            if NUM_WORKERS == 1 { "" } else { "s" }
        );

        // Spawn worker tasks
        let mut worker_handles = Vec::new();
        for worker_id in 0..NUM_WORKERS {
            let partial_provider_clone = partial_provider.clone();
            let final_provider_clone = final_provider.clone();
            let app_clone = app.clone();
            let work_receiver_clone = work_receiver.clone();
            let work_sender_clone = work_sender.clone();
            let chunks_completed_clone = chunks_completed.clone();
            let input_finished_clone = input_finished.clone();
            let chunks_queued_clone = chunks_queued.clone();
            let streaming_sequence_id = streaming_sequence_id.clone();
            let translator_clone = translator.clone();

            let worker_handle = tokio::spawn(async move {
                info!(
                    " Worker {} started (final=TDT, partial={})",
                    worker_id,
                    if partial_provider_clone.is_some() {
                        "TDT"
                    } else {
                        "disabled"
                    }
                );

                // PRE-VALIDATE final model state
                let final_loaded = final_provider_clone.is_model_loaded().await;
                if final_loaded {
                    info!(
                        " Worker {} final provider ({}) ready",
                        worker_id,
                        final_provider_clone.provider_name()
                    );
                } else {
                    warn!(
                        " Worker {} final provider not loaded - chunks may be skipped",
                        worker_id
                    );
                }

                loop {
                    // Try to get a chunk to process (with timeout to avoid deadlock).
                    // The worker holds work_sender_clone for partial coalescing,
                    // which prevents the channel from closing even after the main
                    // dispatcher exits. A timeout lets us check input_finished.
                    let chunk = {
                        let mut receiver = work_receiver_clone.lock().await;
                        match tokio::time::timeout(
                            tokio::time::Duration::from_millis(200),
                            receiver.recv(),
                        )
                        .await
                        {
                            Ok(result) => result,
                            Err(_) => None, // timeout — will check input_finished below
                        }
                    };

                    match chunk {
                        Some(mut chunk) => {
                            // STREAMING OPTIMIZATION: If this is a partial (live preview),
                            // drain any newer partials from the queue and only process
                            // the latest one. This prevents queue buildup when STT is
                            // slower than the preview emission rate.
                            // Skip merging for providers that prefer raw small chunks
                            // (e.g. NemoProvider), since merging large blobs breaks
                            // server-side VAD timing.
                            let skip_merge = partial_provider_clone
                                .as_ref()
                                .map(|p| p.prefers_raw_chunks())
                                .unwrap_or(false);

                            if chunk.is_partial && !skip_merge {
                                let mut receiver_guard = work_receiver_clone.lock().await;
                                loop {
                                    match receiver_guard.try_recv() {
                                        Ok(next) if next.is_partial => {
                                            // Newer partial available — merge audio then advance.
                                            // We MUST preserve every audio sample: the provider
                                            // accumulates audio in a stateful streaming buffer, so
                                            // discarding chunk.data would silently drop speech.
                                            let mut merged = chunk.data;
                                            merged.extend_from_slice(&next.data);
                                            chunk = next;
                                            chunk.data = merged;
                                            chunks_completed_clone.fetch_add(1, Ordering::SeqCst);
                                        }
                                        Ok(next) => {
                                            // Next chunk is a final — we must not skip it.
                                            // Process the current partial first, then this
                                            // final will be picked up in the next loop iteration.
                                            // Put it back by re-sending (safe because unbounded).
                                            let _ = work_sender_clone.send(next);
                                            break;
                                        }
                                        Err(_) => break, // Queue empty
                                    }
                                }
                                drop(receiver_guard);
                            }

                            // PERFORMANCE OPTIMIZATION: Reduce logging in hot path
                            let should_log_this_chunk = chunk.chunk_id % 10 == 0;

                            if should_log_this_chunk {
                                info!(
                                    " Worker {} processing chunk {} with {} samples (partial: {})",
                                    worker_id,
                                    chunk.chunk_id,
                                    chunk.data.len(),
                                    chunk.is_partial
                                );
                            }

                            // STREAMING: feed audio to provider, emit partial/final results.
                            // Provider (NeMo over WSS) maintains internal streaming session.
                            // When provider returns is_partial=false (endpoint), emit final
                            // and bump sequence_id so next utterance starts a new line.
                            if chunk.is_partial {
                                let Some(provider) = partial_provider_clone.clone() else {
                                    chunks_completed_clone.fetch_add(1, Ordering::SeqCst);
                                    continue;
                                };
                                let chunk_timestamp = chunk.timestamp;
                                let chunk_duration =
                                    chunk.data.len() as f64 / chunk.sample_rate as f64;

                                // Process directly (no spawn_blocking) to guarantee audio ordering.
                                // spawn_blocking fire-and-forget lets tasks run out of order: a
                                // later task can finish first and emit shorter text that overwrites
                                // the longer result, making words appear to vanish.
                                // With MAX_FORCED_CUT_SECS capping the buffer, inference is
                                // bounded so blocking the worker for one chunk is safe.
                                if !provider.is_model_loaded().await {
                                    chunks_completed_clone.fetch_add(1, Ordering::SeqCst);
                                    continue;
                                }
                                match transcribe_chunk_with_provider(&provider, chunk, &app_clone).await {
                                    Ok((transcript, confidence_opt, provider_partial, detected_language)) => {
                                        if !transcript.trim().is_empty()
                                            && !is_punctuation_only(transcript.trim())
                                        {
                                            let seq_id = streaming_sequence_id.load(Ordering::SeqCst);
                                            let is_partial = provider_partial;

                                            let update = TranscriptUpdate {
                                                text: transcript.trim().to_string(),
                                                timestamp: format_current_timestamp(),
                                                source: "Audio".to_string(),
                                                sequence_id: seq_id,
                                                chunk_start_time: chunk_timestamp,
                                                is_partial,
                                                confidence: confidence_opt.unwrap_or(0.85),
                                                audio_start_time: chunk_timestamp,
                                                audio_end_time: chunk_timestamp + chunk_duration,
                                                duration: chunk_duration,
                                                detected_language,
                                                tentative_text: None,
                                                translated_text: None,
                                            };
                                            super::silence::mark_speech();
                                            let _ = app_clone.emit("transcript-update", &update);

                                            // Translate asynchronously — doesn't block STT
                                            if !is_partial {
                                                if let Some(translator) = translator_clone.clone() {
                                                    let text_for_translation = transcript.trim().to_string();
                                                    let app_tr = app_clone.clone();
                                                    let tr_seq_id = seq_id;
                                                    std::thread::spawn(move || {
                                                        match translator.translate(&text_for_translation) {
                                                            Ok(tr) if !tr.is_empty() => {
                                                                info!("Translation: '{}' → '{}'", text_for_translation, tr);
                                                                let _ = app_tr.emit("translation-update", serde_json::json!({
                                                                    "sequence_id": tr_seq_id,
                                                                    "translated_text": tr,
                                                                }));
                                                            }
                                                            Ok(_) => {}
                                                            Err(e) => {
                                                                warn!("Translation failed: {}", e);
                                                            }
                                                        }
                                                    });
                                                }
                                            }

                                            if !is_partial {
                                                streaming_sequence_id.fetch_add(1, Ordering::SeqCst);
                                                drop_partial_commit(seq_id);
                                            }
                                        }
                                    }
                                    Err(e) => {
                                        info!("Streaming transcription skipped: {}", e);
                                    }
                                }
                                chunks_completed_clone.fetch_add(1, Ordering::SeqCst);
                                continue;
                            }

                            // FINAL: process inline (TDT local inference)
                            let provider: &Arc<dyn TranscriptionProvider> = &final_provider_clone;

                            if !provider.is_model_loaded().await {
                                warn!(
                                    " Worker {}: {} not loaded, skipping chunk {}",
                                    worker_id,
                                    provider.provider_name(),
                                    chunk.chunk_id
                                );
                                chunks_completed_clone.fetch_add(1, Ordering::SeqCst);
                                continue;
                            }

                            let chunk_timestamp = chunk.timestamp;
                            let chunk_duration = chunk.data.len() as f64 / chunk.sample_rate as f64;
                            let sequence_id = chunk.chunk_id;
                            let requested_partial = chunk.is_partial;
                            // Speaker label from pipeline's channel energy analysis
                            let speaker_source = match chunk.device_type {
                                crate::audio::recording_state::DeviceType::Microphone => "Me",
                                crate::audio::recording_state::DeviceType::System => "Speaker",
                            };

                            // Transcribe final with TDT (local)
                            match transcribe_chunk_with_provider(provider, chunk, &app_clone).await
                            {
                                Ok((
                                    transcript,
                                    confidence_opt,
                                    provider_partial,
                                    detected_language,
                                )) => {
                                    // Punctuation restoration disabled — gateway handles text directly.

                                    let is_partial = requested_partial || provider_partial;
                                    let confidence_threshold = if is_partial { 0.15 } else { 0.3 };
                                    let confidence_effective =
                                        live_transcript_confidence_after_length_sanity(
                                            transcript.trim(),
                                            chunk_duration,
                                            confidence_opt,
                                        );

                                    let confidence_str = match confidence_effective {
                                        Some(c) => format!("{:.2}", c),
                                        None => "N/A".to_string(),
                                    };

                                    info!(" Worker {} transcription result: text='{}', confidence={}, partial={}, threshold={:.2}",
                                          worker_id, transcript, confidence_str, is_partial, confidence_threshold);

                                    // Check confidence threshold (or accept if no confidence provided)
                                    let meets_threshold = confidence_effective
                                        .map_or(true, |c| c >= confidence_threshold);

                                    // Filter out punctuation-only "transcripts" (e.g. ". . .") that
                                    // STT often produces over silence/very weak noise.
                                    if !transcript.trim().is_empty()
                                        && is_punctuation_only(transcript.trim())
                                    {
                                        info!(
                                            " Worker {} dropping punctuation-only transcript: '{}' (duration={:.2}s, partial={})",
                                            worker_id, transcript, chunk_duration, is_partial
                                        );
                                        chunks_completed_clone.fetch_add(1, Ordering::SeqCst);
                                        continue;
                                    }

                                    if !transcript.trim().is_empty() && meets_threshold {
                                        // PERFORMANCE: Only log transcription results, not every processing step
                                        info!(" Worker {} transcribed: {} (confidence: {}, partial: {})",
                                              worker_id, transcript, confidence_str, is_partial);

                                        // Emit speech-detected event for frontend UX (only on first detection per session)
                                        // This is lightweight and provides better user feedback
                                        let current_flag =
                                            SPEECH_DETECTED_EMITTED.load(Ordering::SeqCst);
                                        info!(" Checking speech-detected flag: current={}, will_emit={}", current_flag, !current_flag);

                                        if !current_flag {
                                            SPEECH_DETECTED_EMITTED.store(true, Ordering::SeqCst);
                                            match app_clone.emit("speech-detected", serde_json::json!({
                                                "message": "Speech activity detected"
                                            })) {
                                                Ok(_) => info!("  First speech detected - successfully emitted speech-detected event"),
                                                Err(e) => error!("  Failed to emit speech-detected event: {}", e),
                                            }
                                        } else {
                                            info!(" Speech already detected in this session, not re-emitting");
                                        }

                                        // Generate sequence ID and calculate timestamps FIRST
                                        let audio_start_time = chunk_timestamp; // Already in seconds from recording start

                                        // Save structured transcript segment to recording manager (only final results)
                                        // Save ALL segments (partial and final) to ensure complete JSON
                                        // Create structured segment with full timestamp data
                                        // NOTE: This is now handled via the transcript-update event emission below
                                        // The recording_commands module listens to these events and saves them
                                        // This decouples the transcription worker from direct RECORDING_MANAGER access

                                        // Split final results by sentence boundaries.
                                        // Partials are emitted as-is for real-time feedback only.
                                        let sentences = if !is_partial {
                                            split_into_sentences(&transcript)
                                        } else {
                                            vec![transcript]
                                        };

                                        let sentence_count = sentences.len();
                                        for (sent_idx, sentence) in
                                            sentences.into_iter().enumerate()
                                        {
                                            if sentence.trim().is_empty() {
                                                continue;
                                            }

                                            // Distribute timestamps proportionally across sentences
                                            let frac_start =
                                                sent_idx as f64 / sentence_count as f64;
                                            let frac_end =
                                                (sent_idx + 1) as f64 / sentence_count as f64;
                                            let sent_start =
                                                audio_start_time + chunk_duration * frac_start;
                                            let sent_end =
                                                audio_start_time + chunk_duration * frac_end;

                                            // Each sentence gets a unique sequence_id so the frontend
                                            // doesn't overwrite earlier sentences from the same chunk.
                                            // First sentence keeps the original sequence_id to replace
                                            // the partial preview that used the same id.
                                            let sent_sequence_id = if sent_idx == 0 {
                                                sequence_id
                                            } else {
                                                SENTENCE_SUB_ID_COUNTER
                                                    .fetch_add(1, Ordering::SeqCst)
                                            };

                                            let update = TranscriptUpdate {
                                                text: sentence,
                                                timestamp: format_current_timestamp(),
                                                source: speaker_source.to_string(),
                                                sequence_id: sent_sequence_id,
                                                chunk_start_time: chunk_timestamp,
                                                is_partial,
                                                confidence: confidence_effective.unwrap_or(0.85),
                                                audio_start_time: sent_start,
                                                audio_end_time: sent_end,
                                                duration: sent_end - sent_start,
                                                detected_language: detected_language.clone(),
                                                tentative_text: None,
                                                translated_text: None,
                                            };

                                            super::silence::mark_speech();
                                            if let Err(e) =
                                                app_clone.emit("transcript-update", &update)
                                            {
                                                error!(
                                                    "Worker {}: Failed to emit transcript update: {}",
                                                    worker_id, e
                                                );
                                            }
                                        }
                                        // Final result replaced the row entirely — drop the
                                        // per-turn stable-prefix state so the next turn that
                                        // happens to reuse this sequence_id starts fresh.
                                        if !is_partial {
                                            drop_partial_commit(sequence_id);
                                        }
                                        // PERFORMANCE: Removed verbose logging of every emission
                                    } else if !transcript.trim().is_empty() {
                                        warn!(
                                            " Worker {} DROPPED transcript: '{}' (confidence={}, threshold={:.2}, partial={}, duration={:.2}s)",
                                            worker_id,
                                            transcript,
                                            confidence_str,
                                            confidence_threshold,
                                            is_partial,
                                            chunk_duration
                                        );
                                    } else {
                                        info!(
                                            "Worker {} empty transcript (duration={:.2}s, partial={})",
                                            worker_id, chunk_duration, is_partial
                                        );
                                    }
                                }
                                Err(e) => {
                                    // Improved error handling with specific cases
                                    match e {
                                        TranscriptionError::AudioTooShort { .. } => {
                                            // Skip silently, this is expected for very short chunks
                                            info!("Worker {}: {}", worker_id, e);
                                            chunks_completed_clone.fetch_add(1, Ordering::SeqCst);
                                            continue;
                                        }
                                        TranscriptionError::ModelNotLoaded => {
                                            warn!(
                                                "Worker {}: Model unloaded during transcription",
                                                worker_id
                                            );
                                            chunks_completed_clone.fetch_add(1, Ordering::SeqCst);
                                            continue;
                                        }
                                        _ => {
                                            warn!(
                                                "Worker {}: Transcription failed: {}",
                                                worker_id, e
                                            );
                                            let _ = app_clone
                                                .emit("transcription-warning", e.to_string());
                                        }
                                    }
                                }
                            }

                            // Mark chunk as completed
                            let completed =
                                chunks_completed_clone.fetch_add(1, Ordering::SeqCst) + 1;
                            let queued = chunks_queued_clone.load(Ordering::SeqCst);

                            // PERFORMANCE: Only log progress every 5th chunk to reduce I/O overhead
                            if completed % 5 == 0 || should_log_this_chunk {
                                info!(
                                    "Worker {}: Progress {}/{} chunks ({:.1}%)",
                                    worker_id,
                                    completed,
                                    queued,
                                    (completed as f64 / queued.max(1) as f64 * 100.0)
                                );
                            }

                            // Emit progress event for frontend
                            let progress_percentage = if queued > 0 {
                                (completed as f64 / queued as f64 * 100.0) as u32
                            } else {
                                100
                            };

                            let _ = app_clone.emit("transcription-progress", serde_json::json!({
                                "worker_id": worker_id,
                                "chunks_completed": completed,
                                "chunks_queued": queued,
                                "progress_percentage": progress_percentage,
                                "message": format!("Worker {} processing... ({}/{})", worker_id, completed, queued)
                            }));
                        }
                        None => {
                            // No more chunks available (timeout or channel drained)
                            if input_finished_clone.load(Ordering::SeqCst) {
                                let final_queued = chunks_queued_clone.load(Ordering::SeqCst);
                                let final_completed = chunks_completed_clone.load(Ordering::SeqCst);

                                if final_completed >= final_queued {
                                    info!(
                                        " Worker {} finishing - all {}/{} chunks processed",
                                        worker_id, final_completed, final_queued
                                    );
                                    break;
                                } else {
                                    // Still waiting for chunks — the 200ms recv timeout
                                    // already provides the polling delay
                                    warn!(
                                        " Worker {} waiting: {}/{} completed",
                                        worker_id, final_completed, final_queued
                                    );
                                }
                            } else {
                                // Not finished yet — recv timeout provides the delay
                            }
                        }
                    }
                }

                info!(" Worker {} completed", worker_id);
            });

            worker_handles.push(worker_handle);
        }

        // Main dispatcher: receive chunks and distribute to workers
        let mut receiver = transcription_receiver;
        while let Some(chunk) = receiver.recv().await {
            let queued = chunks_queued.fetch_add(1, Ordering::SeqCst) + 1;
            info!(
                " Dispatching chunk {} to workers (total queued: {})",
                chunk.chunk_id, queued
            );

            if let Err(_) = work_sender.send(chunk) {
                error!(" Failed to send chunk to workers - this should not happen!");
                break;
            }
        }

        // Signal that input is finished
        input_finished.store(true, Ordering::SeqCst);
        drop(work_sender); // Close the channel to signal workers

        let total_chunks_queued = chunks_queued.load(Ordering::SeqCst);
        info!(" Input finished with {} total chunks queued. Waiting for all {} workers to complete...",
              total_chunks_queued, NUM_WORKERS);

        // Emit final chunk count to frontend
        let _ = app.emit("transcription-queue-complete", serde_json::json!({
            "total_chunks": total_chunks_queued,
            "message": format!("{} chunks queued for processing - waiting for completion", total_chunks_queued)
        }));

        // Wait for all workers to complete
        for (worker_id, handle) in worker_handles.into_iter().enumerate() {
            if let Err(e) = handle.await {
                error!(" Worker {} panicked: {:?}", worker_id, e);
            } else {
                info!(" Worker {} completed successfully", worker_id);
            }
        }

        // Final verification with retry logic to catch any stragglers
        let mut verification_attempts = 0;
        const MAX_VERIFICATION_ATTEMPTS: u32 = 10;

        loop {
            let final_queued = chunks_queued.load(Ordering::SeqCst);
            let final_completed = chunks_completed.load(Ordering::SeqCst);

            if final_queued == final_completed {
                info!(
                    " ALL {} chunks processed successfully - ZERO chunks lost!",
                    final_completed
                );
                break;
            } else if verification_attempts < MAX_VERIFICATION_ATTEMPTS {
                verification_attempts += 1;
                warn!(" Chunk count mismatch (attempt {}): {} queued, {} completed - waiting for stragglers...",
                     verification_attempts, final_queued, final_completed);

                // Wait a bit for any remaining chunks to be processed
                tokio::time::sleep(tokio::time::Duration::from_millis(100)).await;
            } else {
                error!(
                    " CRITICAL: After {} attempts, chunk loss detected: {} queued, {} completed",
                    MAX_VERIFICATION_ATTEMPTS, final_queued, final_completed
                );

                // Emit critical error event
                let _ = app.emit(
                    "transcript-chunk-loss-detected",
                    serde_json::json!({
                        "chunks_queued": final_queued,
                        "chunks_completed": final_completed,
                        "chunks_lost": final_queued - final_completed,
                        "message": "Some transcript chunks may have been lost during shutdown"
                    }),
                );
                break;
            }
        }

        info!(
            " Parallel transcription task completed - all workers finished, ready for model unload"
        );
    })
}

/// Transcribe audio chunk using the given provider.
/// Returns: (text, confidence, is_partial, detected_language)
async fn transcribe_chunk_with_provider<R: Runtime>(
    provider: &Arc<dyn TranscriptionProvider>,
    chunk: AudioChunk,
    app: &AppHandle<R>,
) -> std::result::Result<(String, Option<f32>, bool, Option<String>), TranscriptionError> {
    // Convert to 16kHz mono for transcription
    let transcription_data = if chunk.sample_rate != 16000 {
        crate::audio::audio_processing::resample_audio(&chunk.data, chunk.sample_rate, 16000)
    } else {
        chunk.data.clone()
    };

    let speech_samples = transcription_data;

    if speech_samples.is_empty() {
        warn!(
            "Audio chunk {} is empty, skipping transcription",
            chunk.chunk_id
        );
        return Err(TranscriptionError::AudioTooShort {
            samples: 0,
            minimum: 1600,
        });
    }

    let energy: f32 =
        speech_samples.iter().map(|&x| x * x).sum::<f32>() / speech_samples.len() as f32;
    info!(
        "Processing chunk {} with {} ({} samples, energy: {:.6}, partial: {})",
        chunk.chunk_id,
        provider.provider_name(),
        speech_samples.len(),
        energy,
        chunk.is_partial
    );

    let language = crate::get_language_preference_internal();

    match provider.transcribe(speech_samples, language).await {
        Ok(result) => {
            let cleaned_text = result.text.trim().to_string();
            if cleaned_text.is_empty() {
                return Ok((
                    String::new(),
                    result.confidence,
                    result.is_partial,
                    result.detected_language,
                ));
            }

            info!(
                "{} transcription complete for chunk {}: '{}' (partial: {}, lang: {:?})",
                provider.provider_name(),
                chunk.chunk_id,
                cleaned_text,
                chunk.is_partial,
                result.detected_language,
            );

            Ok((
                cleaned_text,
                result.confidence,
                result.is_partial,
                result.detected_language,
            ))
        }
        Err(e) => {
            error!(
                "{} transcription failed for chunk {}: {}",
                provider.provider_name(),
                chunk.chunk_id,
                e
            );

            let _ = app.emit(
                "transcription-error",
                &serde_json::json!({
                    "error": e.to_string(),
                    "userMessage": format!("Transcription failed: {}", e),
                    "actionable": false
                }),
            );

            Err(e)
        }
    }
}

/// Format current timestamp (wall-clock time)
fn format_current_timestamp() -> String {
    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default();

    let hours = (now.as_secs() / 3600) % 24;
    let minutes = (now.as_secs() / 60) % 60;
    let seconds = now.as_secs() % 60;

    format!("{:02}:{:02}:{:02}", hours, minutes, seconds)
}

/// Format recording-relative time as [MM:SS]
#[allow(dead_code)]
fn format_recording_time(seconds: f64) -> String {
    let total_seconds = seconds.floor() as u64;
    let minutes = total_seconds / 60;
    let secs = total_seconds % 60;

    format!("[{:02}:{:02}]", minutes, secs)
}

/// Split punctuated text into sentences at `.` `?` `!` boundaries.
/// Keeps the punctuation attached to each sentence.
fn split_into_sentences(text: &str) -> Vec<String> {
    let mut sentences = Vec::new();
    let mut current = String::new();

    for ch in text.chars() {
        current.push(ch);
        if matches!(ch, '.' | '?' | '!') {
            let trimmed = current.trim().to_string();
            if !trimmed.is_empty() {
                sentences.push(trimmed);
            }
            current.clear();
        }
    }

    // Remaining text without sentence-ending punctuation
    let trimmed = current.trim().to_string();
    if !trimmed.is_empty() {
        sentences.push(trimmed);
    }

    // If no split happened, return original
    if sentences.is_empty() {
        sentences.push(text.trim().to_string());
    }

    sentences
}
