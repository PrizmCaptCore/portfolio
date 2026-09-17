use log::{error as log_error, info as log_info, warn as log_warn};
use std::collections::hash_map::DefaultHasher;
use std::collections::HashSet;
use std::hash::{Hash, Hasher};
use tauri::{AppHandle, Runtime};

use super::models::{EmbedResponse, IncrementalResponse, SearchHit, SyncResult};
use super::repository::{vec_f32_to_bytes, RagRepository};
use crate::config;
use crate::database::repositories::summary::SummaryProcessesRepository;
use crate::state::AppState;

// One chunk per summary, capped well below the embedding model's 8192
// max_model_len. Most summaries fit comfortably; pathological cases are
// truncated with the head preserved (executive summary lives at the top).
const SUMMARY_TEXT_CAP: usize = 7500;

/// Pull all new/changed chunks from the backend's incremental endpoint and
/// mirror them into the local sqlite-vec index. Returns a `SyncResult`
/// summarising the batch.
///
/// Flow:
///   1. Read sync state (last_synced_at watermark + known embedding dim).
///   2. Loop: GET /api/v1/rag/incremental?since=<watermark>&after_id=<cursor>
///   3. For each batch: discover dim on first vector, ensure vec0 table,
///      transactional upsert per chunk.
///   4. Advance the cursor; stop when `next_after_id` is null.
///   5. Bump `last_synced_at` to the max we saw.
///
/// Pagination: backend pages by INCREMENTAL_PAGE_SIZE (200) with stable
/// after_id cursor. Whole sync runs to completion in one command call —
/// caller doesn't have to drive the loop.
#[tauri::command]
pub async fn rag_sync<R: Runtime>(
    app: AppHandle<R>,
    state: tauri::State<'_, AppState>,
) -> Result<SyncResult, String> {
    let pool = state.db_manager.pool();

    let token = config::read_access_token(&app).ok_or_else(|| "not_authenticated".to_string())?;

    let mut sync_state = RagRepository::get_sync_state(pool)
        .await
        .map_err(|e| format!("read sync state: {}", e))?;

    let gateway = config::gateway_url();
    // gateway_url() returns ".../api/v1/ai" — we need the sibling /api/v1/rag.
    let rag_base = gateway
        .trim_end_matches('/')
        .trim_end_matches("/ai")
        .to_string()
        + "/rag";

    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(60))
        .build()
        .map_err(|e| format!("reqwest build: {}", e))?;

    let since = sync_state.last_synced_at.clone();
    let mut cursor: Option<i64> = None;
    let mut chunks_inserted: usize = 0;
    let mut pages_seen: HashSet<String> = HashSet::new();
    let mut max_last_synced: Option<String> = since.clone();

    log_info!(
        "rag_sync starting (since={:?}, known_dim={:?})",
        since,
        sync_state.embedding_dim
    );

    loop {
        // Build the URL: encode `since` only when set, and `after_id` only
        // for follow-up pages. Keeping unset params off avoids ambiguity
        // with the backend's empty-string handling.
        let url = format!("{}/incremental/", rag_base);
        let mut query: Vec<(&str, String)> = Vec::new();
        if let Some(s) = &since {
            query.push(("since", s.clone()));
        }
        if let Some(c) = cursor {
            query.push(("after_id", c.to_string()));
        }

        log_info!(
            "rag_sync GET {} (since={:?}, after_id={:?})",
            url,
            since,
            cursor
        );

        let resp = client
            .get(&url)
            .query(&query)
            .bearer_auth(&token)
            .send()
            .await
            .map_err(|e| format!("rag/incremental request: {}", e))?;

        let status = resp.status();
        if !status.is_success() {
            let body = resp.text().await.unwrap_or_default();
            log_error!("rag/incremental {} -> {}: {}", url, status, body);
            return Err(format!("rag/incremental returned {}: {}", status, body));
        }

        let body: IncrementalResponse = resp
            .json()
            .await
            .map_err(|e| format!("rag/incremental json parse: {}", e))?;

        if body.items.is_empty() && cursor.is_none() {
            log_info!("rag_sync: nothing new since watermark");
            break;
        }

        // First-vector dimension discovery. Done lazily so a cold start
        // with an empty backend doesn't try to materialize a 0-dim table.
        for chunk in &body.items {
            let dim = chunk.vector.len() as i64;
            if dim == 0 {
                log_warn!(
                    "rag_sync: chunk id={} has empty vector — skipping",
                    chunk.id
                );
                continue;
            }
            // `Some(0)` is treated as "not set yet" — a real embedding dim
            // is always positive, and a 0 in the row is either NULL coerced
            // by the driver or stale state from a prior partial sync.
            match sync_state.embedding_dim {
                None | Some(0) => {
                    log_info!("rag_sync: discovered embedding dim = {}", dim);
                    RagRepository::set_embedding_dim(pool, dim)
                        .await
                        .map_err(|e| format!("set embedding_dim: {}", e))?;
                    RagRepository::ensure_vec_table(pool, dim)
                        .await
                        .map_err(|e| format!("ensure vec0 table: {}", e))?;
                    sync_state.embedding_dim = Some(dim);
                }
                Some(known) if known != dim => {
                    return Err(format!(
                        "embedding dim drift: expected {}, got {} on chunk {}. \
                         The backend embedding model changed — reset the local \
                         RAG index before continuing.",
                        known, dim, chunk.id
                    ));
                }
                Some(_) => {}
            }

            RagRepository::upsert_chunk(pool, chunk)
                .await
                .map_err(|e| format!("upsert chunk {}: {}", chunk.id, e))?;
            chunks_inserted += 1;
            pages_seen.insert(chunk.page_id.clone());

            // Track the high-water mark so the next sync can resume cleanly
            // even if the backend returns rows out of `last_synced_at` order.
            if max_last_synced
                .as_deref()
                .map(|cur| chunk.last_synced_at.as_str() > cur)
                .unwrap_or(true)
            {
                max_last_synced = Some(chunk.last_synced_at.clone());
            }
        }

        match body.next_after_id {
            Some(next) => cursor = Some(next),
            None => break,
        }
    }

    if let Some(ts) = &max_last_synced {
        RagRepository::set_last_synced_at(pool, ts)
            .await
            .map_err(|e| format!("set last_synced_at: {}", e))?;
    }

    let total = RagRepository::count_chunks(pool)
        .await
        .map_err(|e| format!("count chunks: {}", e))?;

    log_info!(
        "rag_sync done: +{} chunks across {} pages (total in index: {})",
        chunks_inserted,
        pages_seen.len(),
        total
    );

    Ok(SyncResult {
        chunks_inserted,
        pages_seen: pages_seen.len(),
        embedding_dim: sync_state.embedding_dim,
        last_synced_at: max_last_synced,
    })
}

/// Trigger a backend-side Notion re-pull (Celery task). Returns immediately
/// with `{status: "queued"}`; the real chunks land in the next `rag_sync`
/// call after the worker finishes.
#[tauri::command]
pub async fn rag_trigger_backend_sync<R: Runtime>(
    app: AppHandle<R>,
) -> Result<serde_json::Value, String> {
    let token = config::read_access_token(&app).ok_or_else(|| "not_authenticated".to_string())?;

    let gateway = config::gateway_url();
    let rag_base = gateway
        .trim_end_matches('/')
        .trim_end_matches("/ai")
        .to_string()
        + "/rag";
    let url = format!("{}/sync/", rag_base);

    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(30))
        .build()
        .map_err(|e| format!("reqwest build: {}", e))?;

    let resp = client
        .post(&url)
        .bearer_auth(&token)
        .send()
        .await
        .map_err(|e| format!("rag/sync request: {}", e))?;

    let status = resp.status();
    let body = resp.text().await.unwrap_or_default();
    if !status.is_success() {
        log_error!("rag/sync {} -> {}: {}", url, status, body);
        return Err(format!("rag/sync returned {}: {}", status, body));
    }

    serde_json::from_str(&body).map_err(|e| format!("rag/sync json parse: {} (body={})", e, body))
}

/// Wipe every Notion chunk from the local sqlite-vec index. Invoked by
/// the desktop client right after a successful Notion disconnect — the
/// backend cascades NotionPage/NotionChunk on its side, this command is
/// the local-side counterpart so the chatbot stops surfacing content
/// the user just severed access to. Meeting chunks survive intact.
#[tauri::command]
pub async fn rag_clear_notion<R: Runtime>(
    _app: AppHandle<R>,
    state: tauri::State<'_, AppState>,
) -> Result<serde_json::Value, String> {
    let pool = state.db_manager.pool();
    let deleted = RagRepository::clear_notion(pool)
        .await
        .map_err(|e| format!("clear_notion: {}", e))?;
    log_info!("rag_clear_notion: {} Notion chunks removed", deleted);
    Ok(serde_json::json!({ "chunks_deleted": deleted }))
}

/// Lightweight introspection for the UI: how many chunks are in the local
/// index, what dimension are they, and when did we last hear from the
/// backend. Intentionally cheap — safe to call on every settings render.
#[tauri::command]
pub async fn rag_get_status<R: Runtime>(
    _app: AppHandle<R>,
    state: tauri::State<'_, AppState>,
) -> Result<serde_json::Value, String> {
    let pool = state.db_manager.pool();

    let sync_state = RagRepository::get_sync_state(pool)
        .await
        .map_err(|e| format!("read sync state: {}", e))?;
    let total = RagRepository::count_chunks(pool)
        .await
        .map_err(|e| format!("count chunks: {}", e))?;
    let meeting_total = RagRepository::count_meeting_chunks(pool)
        .await
        .map_err(|e| format!("count meeting chunks: {}", e))?;

    Ok(serde_json::json!({
        "chunk_count": total,
        "meeting_chunk_count": meeting_total,
        "embedding_dim": sync_state.embedding_dim,
        "last_synced_at": sync_state.last_synced_at,
        "last_full_sync": sync_state.last_full_sync,
    }))
}

/// Embed `query` via the gateway, then run a top-`k` KNN over the local
/// sqlite-vec index. The query MUST be embedded by the same backend
/// model that produced the chunk vectors — that's why we don't have a
/// local-only fallback path.
///
/// Returns an empty Vec when the index is empty (no sync yet) or when
/// the dimension hasn't been discovered. Surfaces an explicit error
/// when the backend returns a vector whose dim disagrees with what's
/// already stored locally — that means the backend swapped models and
/// the local index needs a reset.
#[tauri::command]
pub async fn rag_search<R: Runtime>(
    app: AppHandle<R>,
    state: tauri::State<'_, AppState>,
    query: String,
    k: Option<i64>,
) -> Result<Vec<SearchHit>, String> {
    let trimmed = query.trim();
    if trimmed.is_empty() {
        return Ok(Vec::new());
    }
    let k = k.unwrap_or(8).clamp(1, 50);

    let pool = state.db_manager.pool();

    let sync_state = RagRepository::get_sync_state(pool)
        .await
        .map_err(|e| format!("read sync state: {}", e))?;

    let known_dim = match sync_state.embedding_dim {
        Some(d) if d > 0 => d,
        _ => {
            log_info!("rag_search: index not yet bootstrapped — returning empty");
            return Ok(Vec::new());
        }
    };

    let token = config::read_access_token(&app).ok_or_else(|| "not_authenticated".to_string())?;

    let gateway = config::gateway_url();
    let embed_url = format!("{}/embed/", gateway.trim_end_matches('/'));

    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(60))
        .build()
        .map_err(|e| format!("reqwest build: {}", e))?;

    log_info!(
        "rag_search: embedding query (len={} chars, k={})",
        trimmed.chars().count(),
        k
    );

    let resp = client
        .post(&embed_url)
        .bearer_auth(&token)
        .json(&serde_json::json!({ "texts": [trimmed] }))
        .send()
        .await
        .map_err(|e| format!("embed request: {}", e))?;

    let status = resp.status();
    if !status.is_success() {
        let body = resp.text().await.unwrap_or_default();
        log_error!("rag_search: embed {} -> {}: {}", embed_url, status, body);
        return Err(format!("embed returned {}: {}", status, body));
    }

    let parsed: EmbedResponse = resp
        .json()
        .await
        .map_err(|e| format!("embed json parse: {}", e))?;

    let query_vec = parsed
        .vectors
        .into_iter()
        .next()
        .ok_or_else(|| "embed returned no vectors".to_string())?;

    let got_dim = query_vec.len() as i64;
    if got_dim != known_dim {
        log_warn!(
            "rag_search: dim mismatch (index={}, query={}) — backend model changed?",
            known_dim,
            got_dim
        );
        return Err(format!(
            "embedding dim mismatch: local index is {}, query embedding is {}. \
             Reset the local RAG index to re-sync against the new model.",
            known_dim, got_dim
        ));
    }

    let query_bytes = vec_f32_to_bytes(&query_vec);

    // Run both KNNs and merge by raw distance. Pulling `k` from each side
    // (rather than k/2) means an empty index on one side doesn't starve
    // the result set; the merge below truncates back down to `k`.
    let (notion_res, meeting_res) = tokio::join!(
        RagRepository::knn_search(pool, &query_bytes, k),
        RagRepository::knn_search_meetings(pool, &query_bytes, k),
    );
    let notion_hits = notion_res.map_err(|e| format!("knn_search: {}", e))?;
    let meeting_hits = meeting_res.map_err(|e| format!("knn_search_meetings: {}", e))?;

    let mut combined = notion_hits;
    combined.extend(meeting_hits);
    combined.sort_by(|a, b| {
        a.distance
            .partial_cmp(&b.distance)
            .unwrap_or(std::cmp::Ordering::Equal)
    });
    combined.truncate(k as usize);

    log_info!(
        "rag_search: query='{}' → {} hits (top distance: {:?})",
        trimmed.chars().take(40).collect::<String>(),
        combined.len(),
        combined.first().map(|h| h.distance)
    );

    Ok(combined)
}

// ─── Meeting-summary indexing ───────────────────────────────────────────────

/// Pull the indexable text out of a `summary_processes.result` JSON blob.
///
/// New format: `{ "markdown": "..." }` — used as-is.
/// Legacy format: `{ "key_points": { title, blocks: [{content}] }, ... }`
/// where each top-level value is a section. We flatten it to:
/// `## <title>\n<content>\n<content>\n\n## <next title>...`.
fn extract_summary_text(result_json: &str) -> Option<String> {
    let v: serde_json::Value = serde_json::from_str(result_json).ok()?;

    if let Some(md) = v.get("markdown").and_then(|m| m.as_str()) {
        let trimmed = md.trim();
        if !trimmed.is_empty() {
            return Some(trimmed.to_string());
        }
    }

    let obj = v.as_object()?;
    let mut sections: Vec<String> = Vec::new();
    for (key, val) in obj.iter() {
        let Some(section) = val.as_object() else { continue };
        let title = section
            .get("title")
            .and_then(|t| t.as_str())
            .unwrap_or(key);
        let mut lines: Vec<String> = vec![format!("## {}", title)];
        if let Some(blocks) = section.get("blocks").and_then(|b| b.as_array()) {
            for block in blocks {
                if let Some(content) = block.get("content").and_then(|c| c.as_str()) {
                    let trimmed = content.trim();
                    if !trimmed.is_empty() {
                        lines.push(trimmed.to_string());
                    }
                }
            }
        }
        if lines.len() > 1 {
            sections.push(lines.join("\n"));
        }
    }
    if sections.is_empty() {
        None
    } else {
        Some(sections.join("\n\n"))
    }
}

fn hash_source(text: &str) -> String {
    let mut h = DefaultHasher::new();
    text.hash(&mut h);
    format!("{:x}", h.finish())
}

/// POST `/api/v1/ai/embed/` with one text and return its vector.
/// Reused by `rag_index_meeting_summary` — the existing `rag_search`
/// inlines the same flow but the duplication is small enough that a
/// shared helper isn't worth the indirection there.
async fn embed_one_text<R: Runtime>(
    app: &AppHandle<R>,
    text: &str,
) -> Result<Vec<f32>, String> {
    let token = config::read_access_token(app).ok_or_else(|| "not_authenticated".to_string())?;
    let gateway = config::gateway_url();
    let embed_url = format!("{}/embed/", gateway.trim_end_matches('/'));

    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(60))
        .build()
        .map_err(|e| format!("reqwest build: {}", e))?;

    let resp = client
        .post(&embed_url)
        .bearer_auth(&token)
        .json(&serde_json::json!({ "texts": [text] }))
        .send()
        .await
        .map_err(|e| format!("embed request: {}", e))?;

    let status = resp.status();
    if !status.is_success() {
        let body = resp.text().await.unwrap_or_default();
        return Err(format!("embed returned {}: {}", status, body));
    }
    let parsed: EmbedResponse = resp
        .json()
        .await
        .map_err(|e| format!("embed json parse: {}", e))?;
    parsed
        .vectors
        .into_iter()
        .next()
        .ok_or_else(|| "embed returned no vectors".to_string())
}

/// Embed `text` and upsert it as the single chunk for `meeting_id` in the
/// local RAG store. Hash-deduped: same text → no embed call. Shared by the
/// summary-indexing path and the in-progress transcript-indexing path; the
/// caller is responsible for fetching/cleaning the text and supplying a
/// stable title (the `meetings` row may not exist yet for in-progress
/// recordings, so we don't read it from SQLite here).
async fn embed_and_upsert_meeting_chunk<R: Runtime>(
    app: &AppHandle<R>,
    pool: &sqlx::SqlitePool,
    meeting_id: &str,
    title: &str,
    text: &str,
    log_prefix: &str,
) -> Result<serde_json::Value, String> {
    let hash = hash_source(text);

    if let Some(prev) = RagRepository::get_meeting_source_hash(pool, meeting_id)
        .await
        .map_err(|e| format!("get_meeting_source_hash: {}", e))?
    {
        if prev == hash {
            return Ok(serde_json::json!({
                "status": "unchanged",
                "meeting_id": meeting_id,
            }));
        }
    }

    let vector = embed_one_text(app, text).await?;
    let dim = vector.len() as i64;
    if dim == 0 {
        return Err("embed returned empty vector".to_string());
    }

    // Bootstrap or validate `rag_sync_state.embedding_dim`. Without this,
    // a user who only ever indexed meetings (no Notion sync) would have
    // `embedding_dim = NULL` forever, and `rag_search` short-circuits with
    // "index not yet bootstrapped — returning empty" even though the
    // meeting vec table is full. Mirrors the same check `rag_sync` runs
    // when it ingests the first Notion chunk.
    let sync_state = RagRepository::get_sync_state(pool)
        .await
        .map_err(|e| format!("read sync state: {}", e))?;
    match sync_state.embedding_dim {
        None | Some(0) => {
            log_info!("{}: discovered embedding dim = {}", log_prefix, dim);
            RagRepository::set_embedding_dim(pool, dim)
                .await
                .map_err(|e| format!("set embedding_dim: {}", e))?;
        }
        Some(known) if known != dim => {
            return Err(format!(
                "embedding dim drift: index is {}, meeting embed got {}. \
                 The backend embedding model changed — reset the local RAG \
                 index before continuing.",
                known, dim
            ));
        }
        Some(_) => {}
    }

    RagRepository::ensure_meeting_vec_table(pool, dim)
        .await
        .map_err(|e| format!("ensure meeting vec table: {}", e))?;

    let bytes = vec_f32_to_bytes(&vector);
    let now = chrono::Utc::now().to_rfc3339();

    let mut tx = pool
        .begin()
        .await
        .map_err(|e| format!("begin tx: {}", e))?;
    RagRepository::delete_meeting_chunks(&mut tx, meeting_id)
        .await
        .map_err(|e| format!("delete prior chunks: {}", e))?;
    RagRepository::insert_meeting_chunk(&mut tx, meeting_id, title, 0, text, &hash, &now, &bytes)
        .await
        .map_err(|e| format!("insert meeting chunk: {}", e))?;
    tx.commit().await.map_err(|e| format!("commit: {}", e))?;

    log_info!(
        "{}: meeting={} title='{}' chars={} dim={}",
        log_prefix,
        meeting_id,
        title.chars().take(40).collect::<String>(),
        text.chars().count(),
        dim
    );

    Ok(serde_json::json!({
        "status": "indexed",
        "meeting_id": meeting_id,
        "chars": text.chars().count(),
    }))
}

/// Internal worker shared by `rag_index_meeting_summary` (single) and
/// `rag_reindex_all_meeting_summaries` (bulk). Returns the same JSON
/// status payload as the wrapper so the bulk loop can pivot on `status`.
async fn index_meeting_summary_inner<R: Runtime>(
    app: &AppHandle<R>,
    pool: &sqlx::SqlitePool,
    meeting_id: &str,
) -> Result<serde_json::Value, String> {
    let summary = SummaryProcessesRepository::get_summary_data(pool, meeting_id)
        .await
        .map_err(|e| format!("get_summary_data: {}", e))?;

    let Some(process) = summary else {
        return Ok(serde_json::json!({"status": "no_summary"}));
    };
    if process.status != "completed" {
        return Ok(serde_json::json!({
            "status": "not_completed",
            "process_status": process.status,
        }));
    }
    let Some(result_json) = process.result.as_deref() else {
        return Ok(serde_json::json!({"status": "no_result"}));
    };

    let Some(mut text) = extract_summary_text(result_json) else {
        return Ok(serde_json::json!({"status": "empty_summary"}));
    };
    if text.chars().count() > SUMMARY_TEXT_CAP {
        let cap = text
            .char_indices()
            .nth(SUMMARY_TEXT_CAP)
            .map(|(i, _)| i)
            .unwrap_or(text.len());
        text.truncate(cap);
    }

    let title: String = sqlx::query_scalar("SELECT title FROM meetings WHERE id = ?")
        .bind(meeting_id)
        .fetch_optional(pool)
        .await
        .map_err(|e| format!("read meeting title: {}", e))?
        .unwrap_or_else(|| meeting_id.to_string());

    embed_and_upsert_meeting_chunk(
        app,
        pool,
        meeting_id,
        &title,
        &text,
        "rag_index_meeting_summary",
    )
    .await
}

/// Index (or re-index) a single completed meeting summary into the local
/// RAG store. No-op when the summary text hasn't changed since the last
/// index pass (`source_hash` match). Skips meetings without a `completed`
/// summary so the caller doesn't need to filter ahead of time.
#[tauri::command]
pub async fn rag_index_meeting_summary<R: Runtime>(
    app: AppHandle<R>,
    state: tauri::State<'_, AppState>,
    meeting_id: String,
) -> Result<serde_json::Value, String> {
    let pool = state.db_manager.pool();
    index_meeting_summary_inner(&app, pool, &meeting_id).await
}

/// Index (or re-index) the running transcript of an in-progress meeting.
/// Called on-demand right before retrieval (drag-suggest 의도 분석, chat
/// query) so that whatever has been said so far in the current meeting is
/// searchable in the RAG store.
///
/// Title is supplied by the caller because in-progress meetings don't yet
/// have a row in the `meetings` table (that's created on save). After the
/// meeting is saved + summarized, `rag_index_meeting_summary` will index
/// under the *final* meeting id; this in-progress chunk lives under the
/// frontend-generated ephemeral id and is left in place — at worst the
/// user gets a duplicate hit, which the LLM dedupes naturally.
///
/// Hash-deduped via `embed_and_upsert_meeting_chunk`, so calling on every
/// keystroke costs at most one SELECT per call (no embed) until the
/// transcript actually grows.
#[tauri::command]
pub async fn rag_index_current_meeting_transcript<R: Runtime>(
    app: AppHandle<R>,
    state: tauri::State<'_, AppState>,
    meeting_id: String,
    title: String,
    text: String,
) -> Result<serde_json::Value, String> {
    let trimmed = text.trim();
    if trimmed.is_empty() {
        return Ok(serde_json::json!({"status": "empty_text"}));
    }

    // Same per-chunk cap as summary indexing so a long meeting doesn't blow
    // through the embedding model's max_model_len.
    let mut capped = trimmed.to_string();
    if capped.chars().count() > SUMMARY_TEXT_CAP {
        let cap = capped
            .char_indices()
            .nth(SUMMARY_TEXT_CAP)
            .map(|(i, _)| i)
            .unwrap_or(capped.len());
        capped.truncate(cap);
    }

    let title = if title.trim().is_empty() {
        meeting_id.clone()
    } else {
        title
    };

    let pool = state.db_manager.pool();
    embed_and_upsert_meeting_chunk(
        &app,
        pool,
        &meeting_id,
        &title,
        &capped,
        "rag_index_current_meeting_transcript",
    )
    .await
}

/// Iterate every completed summary and (re)index any whose source text has
/// changed since the last pass. Safe to call repeatedly — the per-meeting
/// `source_hash` short-circuit makes a no-op pass cost ~one SELECT per
/// meeting and zero embed calls.
#[tauri::command]
pub async fn rag_reindex_all_meeting_summaries<R: Runtime>(
    app: AppHandle<R>,
    state: tauri::State<'_, AppState>,
) -> Result<serde_json::Value, String> {
    let pool = state.db_manager.pool();

    let meeting_ids: Vec<String> =
        sqlx::query_scalar("SELECT meeting_id FROM summary_processes WHERE status = 'completed'")
            .fetch_all(pool)
            .await
            .map_err(|e| format!("list completed summaries: {}", e))?;

    log_info!(
        "rag_reindex_all_meeting_summaries: {} completed summaries to consider",
        meeting_ids.len()
    );

    let mut indexed = 0usize;
    let mut unchanged = 0usize;
    let mut skipped = 0usize;
    let mut failed = 0usize;

    for meeting_id in &meeting_ids {
        match index_meeting_summary_inner(&app, pool, meeting_id).await {
            Ok(v) => match v.get("status").and_then(|s| s.as_str()) {
                Some("indexed") => indexed += 1,
                Some("unchanged") => unchanged += 1,
                _ => skipped += 1,
            },
            Err(e) => {
                log_warn!("reindex {} failed: {}", meeting_id, e);
                failed += 1;
            }
        }
    }

    Ok(serde_json::json!({
        "total": meeting_ids.len(),
        "indexed": indexed,
        "unchanged": unchanged,
        "skipped": skipped,
        "failed": failed,
    }))
}

/// Remove a meeting's chunks from the RAG index. Wired so that deleting a
/// meeting (or wiping a summary) doesn't leave orphan vectors behind.
#[tauri::command]
pub async fn rag_remove_meeting_summary(
    state: tauri::State<'_, AppState>,
    meeting_id: String,
) -> Result<(), String> {
    let pool = state.db_manager.pool();
    let mut tx = pool
        .begin()
        .await
        .map_err(|e| format!("begin tx: {}", e))?;
    RagRepository::delete_meeting_chunks(&mut tx, &meeting_id)
        .await
        .map_err(|e| format!("delete meeting chunks: {}", e))?;
    tx.commit().await.map_err(|e| format!("commit: {}", e))?;
    Ok(())
}
