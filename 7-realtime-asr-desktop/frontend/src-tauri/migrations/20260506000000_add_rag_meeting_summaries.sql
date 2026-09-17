-- Companion index for the Notion RAG: a parallel store for embedded
-- meeting-summary text. Queried alongside `rag_chunks` by `rag_search`.
-- Kept in a separate table so chunk IDs don't collide with the backend's
-- NotionChunk PKs (positive integers we mirror as-is on the Notion side).

CREATE TABLE IF NOT EXISTS rag_meeting_chunks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    meeting_id      TEXT NOT NULL,
    meeting_title   TEXT NOT NULL DEFAULT '',
    chunk_index     INTEGER NOT NULL DEFAULT 0,
    text            TEXT NOT NULL,
    -- Hash of the indexed source text. Skips re-embedding when the
    -- summary content hasn't changed since the last index pass.
    source_hash     TEXT NOT NULL DEFAULT '',
    indexed_at      TEXT NOT NULL,
    UNIQUE(meeting_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS idx_rag_meeting_chunks_meeting
    ON rag_meeting_chunks(meeting_id);

-- The vec0 sibling (rag_meeting_chunks_vec) is created lazily at first
-- index — the embedding dimension is set by whichever model the backend's
-- RunPod endpoint is currently running. See rag::repository::ensure_meeting_vec_table.
