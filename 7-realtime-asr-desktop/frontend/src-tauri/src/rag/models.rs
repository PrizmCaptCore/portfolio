use serde::{Deserialize, Serialize};

/// One incremental chunk as returned by the backend
/// `GET /api/v1/rag/incremental`. The vector arrives as a JSON list of
/// floats; we re-encode it to f32 LE bytes for sqlite-vec's BLOB format.
#[derive(Debug, Deserialize)]
pub struct IncrementalChunk {
    pub id: i64,
    pub page_id: String,
    #[serde(default)]
    pub page_title: String,
    #[serde(default)]
    pub page_url: String,
    pub chunk_index: i64,
    pub text: String,
    pub vector: Vec<f32>,
    pub last_synced_at: String,
}

#[derive(Debug, Deserialize)]
pub struct IncrementalResponse {
    pub items: Vec<IncrementalChunk>,
    /// Cursor for the next page; `None` once we've drained the backlog.
    pub next_after_id: Option<i64>,
}

/// Result returned from `rag_sync` to the frontend.
#[derive(Debug, Serialize)]
pub struct SyncResult {
    pub chunks_inserted: usize,
    pub pages_seen: usize,
    pub embedding_dim: Option<i64>,
    pub last_synced_at: Option<String>,
}

/// One retrieved chunk from `rag_search`. `distance` is whatever metric
/// sqlite-vec's vec0 default uses (L2 squared for FLOAT[N]); smaller =
/// more similar. The frontend uses these for ranking display only — we
/// don't surface the raw number to the user.
///
/// `source` distinguishes Notion page chunks ("notion") from local meeting
/// summary chunks ("meeting"). For meeting hits, `page_id`/`page_title`
/// hold the meeting's ID/title and `page_url` is empty.
#[derive(Debug, Serialize)]
pub struct SearchHit {
    pub chunk_id: i64,
    pub source: String,
    pub page_id: String,
    pub page_title: String,
    pub page_url: String,
    pub chunk_index: i64,
    pub text: String,
    pub distance: f64,
}

/// Backend `/api/v1/ai/embed/` response shape.
#[derive(Debug, Deserialize)]
pub struct EmbedResponse {
    pub vectors: Vec<Vec<f32>>,
}
