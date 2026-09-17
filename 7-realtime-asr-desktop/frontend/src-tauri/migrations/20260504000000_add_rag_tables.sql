-- RAG storage for Notion chunks pulled from relay_web's
-- /api/v1/rag/incremental endpoint. The backend owns chunking + embedding;
-- this client mirrors the rows locally so retrieval can happen offline
-- and the user's knowledge never leaves the machine post-sync.
--
-- The vec0 virtual table (rag_chunks_vec) is NOT created here because its
-- declared dimension depends on the embedding model the backend's RunPod
-- endpoint is using — discovered from the first incremental response and
-- bootstrapped at runtime. See rag::repository::ensure_vec_table.

-- Single-row metadata. Tracks the last_synced_at watermark used to drive
-- the incremental cursor, plus the discovered embedding dimension (used
-- to lazily create the vec0 table on first sync and to validate that the
-- backend hasn't silently switched models on us).
CREATE TABLE IF NOT EXISTS rag_sync_state (
    id              INTEGER PRIMARY KEY CHECK (id = 1),
    last_synced_at  TEXT,
    embedding_dim   INTEGER,
    last_full_sync  TEXT
);

INSERT OR IGNORE INTO rag_sync_state (id) VALUES (1);

-- One row per chunk. `id` mirrors the backend NotionChunk PK so re-syncs
-- naturally upsert. We keep page metadata denormalized on the chunk row
-- because the retrieval prompt assembly needs page_title / page_url and
-- we'd otherwise pay a join per result.
CREATE TABLE IF NOT EXISTS rag_chunks (
    id              INTEGER PRIMARY KEY,
    page_id         TEXT NOT NULL,
    page_title      TEXT NOT NULL DEFAULT '',
    page_url        TEXT NOT NULL DEFAULT '',
    chunk_index     INTEGER NOT NULL,
    text            TEXT NOT NULL,
    last_synced_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_rag_chunks_page
    ON rag_chunks(page_id, chunk_index);
CREATE INDEX IF NOT EXISTS idx_rag_chunks_synced
    ON rag_chunks(last_synced_at);
