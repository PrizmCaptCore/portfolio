-- Meeting embeddings for semantic graph
-- embedding_vector: raw f32 LE bytes (384 dims = 1536 bytes for all-MiniLM-L6-v2)
-- source_text: the key_points text that was embedded (used for cache invalidation)
CREATE TABLE IF NOT EXISTS meeting_embeddings (
    meeting_id    TEXT PRIMARY KEY,
    embedding_vector BLOB NOT NULL,
    source_text   TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    FOREIGN KEY (meeting_id) REFERENCES meetings(id) ON DELETE CASCADE
);
