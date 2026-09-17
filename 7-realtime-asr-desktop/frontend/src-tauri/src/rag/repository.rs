use sqlx::{Row, SqlitePool, Transaction};

use super::models::{IncrementalChunk, SearchHit};

pub struct RagRepository;

#[derive(Debug, Default)]
pub struct SyncState {
    pub last_synced_at: Option<String>,
    pub embedding_dim: Option<i64>,
    pub last_full_sync: Option<String>,
}

impl RagRepository {
    pub async fn get_sync_state(pool: &SqlitePool) -> Result<SyncState, sqlx::Error> {
        let row = sqlx::query(
            "SELECT last_synced_at, embedding_dim, last_full_sync
             FROM rag_sync_state WHERE id = 1",
        )
        .fetch_optional(pool)
        .await?;

        Ok(match row {
            Some(r) => SyncState {
                last_synced_at: r.try_get("last_synced_at").ok(),
                embedding_dim: r.try_get("embedding_dim").ok(),
                last_full_sync: r.try_get("last_full_sync").ok(),
            },
            None => SyncState::default(),
        })
    }

    /// Persist the embedding dimension. Set once on first chunk; never
    /// updated afterwards (a model swap on the backend would silently
    /// corrupt the index — caller must surface that as an error).
    pub async fn set_embedding_dim(pool: &SqlitePool, dim: i64) -> Result<(), sqlx::Error> {
        sqlx::query("UPDATE rag_sync_state SET embedding_dim = ? WHERE id = 1")
            .bind(dim)
            .execute(pool)
            .await?;
        Ok(())
    }

    /// Bump the last_synced_at watermark. The frontend uses this on the next
    /// sync as the `?since=` cursor so we only pull what's new.
    pub async fn set_last_synced_at(pool: &SqlitePool, ts: &str) -> Result<(), sqlx::Error> {
        sqlx::query(
            "UPDATE rag_sync_state SET last_synced_at = ?, last_full_sync = ? WHERE id = 1",
        )
        .bind(ts)
        .bind(chrono::Utc::now().to_rfc3339())
        .execute(pool)
        .await?;
        Ok(())
    }

    /// Lazily create the vec0 virtual table. The dimension can't be baked
    /// into the migration because it's set by whichever embedding model
    /// the backend's RunPod endpoint is currently running.
    ///
    /// Idempotent: safe to call before every batch insert.
    pub async fn ensure_vec_table(pool: &SqlitePool, dim: i64) -> Result<(), sqlx::Error> {
        let sql = format!(
            "CREATE VIRTUAL TABLE IF NOT EXISTS rag_chunks_vec USING vec0(
                chunk_id INTEGER PRIMARY KEY,
                embedding FLOAT[{}]
            )",
            dim
        );
        sqlx::query(&sql).execute(pool).await?;
        Ok(())
    }

    /// Upsert a chunk's metadata + vector in a single transaction.
    ///
    /// vec0 doesn't support UPSERT syntax, so we DELETE then INSERT for
    /// the vector side. The metadata row uses ON CONFLICT for atomicity
    /// against re-syncs of the same chunk_id.
    pub async fn upsert_chunk(
        pool: &SqlitePool,
        chunk: &IncrementalChunk,
    ) -> Result<(), sqlx::Error> {
        let mut tx = pool.begin().await?;

        sqlx::query(
            r#"
            INSERT INTO rag_chunks
                (id, page_id, page_title, page_url, chunk_index, text, last_synced_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                page_id        = excluded.page_id,
                page_title     = excluded.page_title,
                page_url       = excluded.page_url,
                chunk_index    = excluded.chunk_index,
                text           = excluded.text,
                last_synced_at = excluded.last_synced_at
            "#,
        )
        .bind(chunk.id)
        .bind(&chunk.page_id)
        .bind(&chunk.page_title)
        .bind(&chunk.page_url)
        .bind(chunk.chunk_index)
        .bind(&chunk.text)
        .bind(&chunk.last_synced_at)
        .execute(&mut *tx)
        .await?;

        // vec0: drop existing row for this chunk_id (no-op if missing),
        // then insert the new vector. Done inside the same tx so a crash
        // mid-batch can't desync the metadata and the vector store.
        sqlx::query("DELETE FROM rag_chunks_vec WHERE chunk_id = ?")
            .bind(chunk.id)
            .execute(&mut *tx)
            .await?;

        let bytes = vec_f32_to_bytes(&chunk.vector);
        sqlx::query("INSERT INTO rag_chunks_vec(chunk_id, embedding) VALUES (?, ?)")
            .bind(chunk.id)
            .bind(&bytes)
            .execute(&mut *tx)
            .await?;

        tx.commit().await?;
        Ok(())
    }

    /// Diagnostic count for UI / logs. Cheap (uses the rowid index).
    pub async fn count_chunks(pool: &SqlitePool) -> Result<i64, sqlx::Error> {
        let row = sqlx::query("SELECT COUNT(*) AS c FROM rag_chunks")
            .fetch_one(pool)
            .await?;
        row.try_get::<i64, _>("c")
    }

    /// Top-k nearest chunks for `query_vec`. Vector arrives as f32 LE bytes
    /// already encoded by the caller (so the embedding-dim validation +
    /// allocation happens once in `commands::rag_search`, not per-row).
    ///
    /// Uses a CTE so vec0's MATCH operator runs in isolation before the
    /// JOIN — vec0 doesn't accept arbitrary JOIN predicates as constraints
    /// and falls back to a full scan otherwise.
    pub async fn knn_search(
        pool: &SqlitePool,
        query_bytes: &[u8],
        k: i64,
    ) -> Result<Vec<SearchHit>, sqlx::Error> {
        let rows = sqlx::query(
            r#"
            WITH matches AS (
                SELECT chunk_id, distance
                FROM rag_chunks_vec
                WHERE embedding MATCH ?
                ORDER BY distance
                LIMIT ?
            )
            SELECT
                m.chunk_id     AS chunk_id,
                m.distance     AS distance,
                c.page_id      AS page_id,
                c.page_title   AS page_title,
                c.page_url     AS page_url,
                c.chunk_index  AS chunk_index,
                c.text         AS text
            FROM matches m
            JOIN rag_chunks c ON c.id = m.chunk_id
            ORDER BY m.distance
            "#,
        )
        .bind(query_bytes)
        .bind(k)
        .fetch_all(pool)
        .await?;

        let hits = rows
            .into_iter()
            .map(|row| SearchHit {
                chunk_id: row.try_get("chunk_id").unwrap_or_default(),
                source: "notion".to_string(),
                distance: row.try_get("distance").unwrap_or_default(),
                page_id: row.try_get("page_id").unwrap_or_default(),
                page_title: row.try_get("page_title").unwrap_or_default(),
                page_url: row.try_get("page_url").unwrap_or_default(),
                chunk_index: row.try_get("chunk_index").unwrap_or_default(),
                text: row.try_get("text").unwrap_or_default(),
            })
            .collect();
        Ok(hits)
    }

    // ─── Meeting summary index ──────────────────────────────────────────────

    /// Lazy creation of the vec0 sibling for meeting-summary chunks. Same
    /// dim-discovery pattern as `ensure_vec_table` for Notion: idempotent,
    /// safe to call before every batch insert. The dim is shared with the
    /// Notion index in practice (same backend embedding model), but we
    /// don't enforce that at the schema level — sqlite-vec just refuses a
    /// `MATCH` against a wrong-dim vector at query time.
    pub async fn ensure_meeting_vec_table(
        pool: &SqlitePool,
        dim: i64,
    ) -> Result<(), sqlx::Error> {
        let sql = format!(
            "CREATE VIRTUAL TABLE IF NOT EXISTS rag_meeting_chunks_vec USING vec0(
                chunk_id INTEGER PRIMARY KEY,
                embedding FLOAT[{}]
            )",
            dim
        );
        sqlx::query(&sql).execute(pool).await?;
        Ok(())
    }

    /// Returns (source_hash, _) for the most recent indexed chunk of a
    /// meeting, or None if never indexed. Used by the index command to
    /// short-circuit when the summary text hasn't changed.
    pub async fn get_meeting_source_hash(
        pool: &SqlitePool,
        meeting_id: &str,
    ) -> Result<Option<String>, sqlx::Error> {
        let row = sqlx::query(
            "SELECT source_hash FROM rag_meeting_chunks
             WHERE meeting_id = ? ORDER BY chunk_index LIMIT 1",
        )
        .bind(meeting_id)
        .fetch_optional(pool)
        .await?;
        Ok(row.and_then(|r| r.try_get::<String, _>("source_hash").ok()))
    }

    /// Wipe every Notion chunk + its vector from this user's local index.
    /// Used on Notion disconnect so the chatbot can no longer surface
    /// content the user has chosen to sever access from. Resets the
    /// `last_synced_at` watermark so a future re-connect starts from
    /// scratch instead of skipping unchanged-by-our-stale-stamps pages.
    /// Meeting chunks (`rag_meeting_chunks*`) are intentionally left
    /// untouched — they were never sourced from Notion.
    pub async fn clear_notion(pool: &SqlitePool) -> Result<i64, sqlx::Error> {
        let mut tx = pool.begin().await?;
        // vec0 first — cheap, and avoids leaving orphan vector rows if
        // the metadata delete fails.
        sqlx::query("DELETE FROM rag_chunks_vec").execute(&mut *tx).await?;
        let res = sqlx::query("DELETE FROM rag_chunks").execute(&mut *tx).await?;
        // Reset the sync watermark; embedding_dim stays so the meeting
        // search path doesn't trip over its bootstrap check.
        sqlx::query("UPDATE rag_sync_state SET last_synced_at = NULL, last_full_sync = NULL WHERE id = 1")
            .execute(&mut *tx)
            .await?;
        tx.commit().await?;
        Ok(res.rows_affected() as i64)
    }

    /// Drop both metadata + vec0 rows for a meeting. Run inside `tx` so the
    /// re-index is all-or-nothing against the search index.
    pub async fn delete_meeting_chunks(
        tx: &mut Transaction<'_, sqlx::Sqlite>,
        meeting_id: &str,
    ) -> Result<(), sqlx::Error> {
        let ids: Vec<i64> =
            sqlx::query_scalar("SELECT id FROM rag_meeting_chunks WHERE meeting_id = ?")
                .bind(meeting_id)
                .fetch_all(&mut **tx)
                .await?;
        for id in &ids {
            sqlx::query("DELETE FROM rag_meeting_chunks_vec WHERE chunk_id = ?")
                .bind(id)
                .execute(&mut **tx)
                .await?;
        }
        sqlx::query("DELETE FROM rag_meeting_chunks WHERE meeting_id = ?")
            .bind(meeting_id)
            .execute(&mut **tx)
            .await?;
        Ok(())
    }

    /// Insert one summary chunk + its vector. Caller is responsible for
    /// having dropped any previous chunks for this meeting (typically via
    /// `delete_meeting_chunks` in the same transaction).
    pub async fn insert_meeting_chunk(
        tx: &mut Transaction<'_, sqlx::Sqlite>,
        meeting_id: &str,
        meeting_title: &str,
        chunk_index: i64,
        text: &str,
        source_hash: &str,
        indexed_at: &str,
        vector_bytes: &[u8],
    ) -> Result<(), sqlx::Error> {
        let row_id: i64 = sqlx::query_scalar(
            r#"
            INSERT INTO rag_meeting_chunks
                (meeting_id, meeting_title, chunk_index, text, source_hash, indexed_at)
            VALUES (?, ?, ?, ?, ?, ?)
            RETURNING id
            "#,
        )
        .bind(meeting_id)
        .bind(meeting_title)
        .bind(chunk_index)
        .bind(text)
        .bind(source_hash)
        .bind(indexed_at)
        .fetch_one(&mut **tx)
        .await?;

        sqlx::query("INSERT INTO rag_meeting_chunks_vec(chunk_id, embedding) VALUES (?, ?)")
            .bind(row_id)
            .bind(vector_bytes)
            .execute(&mut **tx)
            .await?;
        Ok(())
    }

    pub async fn count_meeting_chunks(pool: &SqlitePool) -> Result<i64, sqlx::Error> {
        let row = sqlx::query("SELECT COUNT(*) AS c FROM rag_meeting_chunks")
            .fetch_one(pool)
            .await?;
        row.try_get::<i64, _>("c")
    }

    /// KNN over the meeting-summary index. Mirrors `knn_search` but joins
    /// against `rag_meeting_chunks` and tags each hit with `source="meeting"`.
    /// Returns an empty Vec if the vec0 table doesn't exist yet (no summary
    /// has ever been indexed).
    pub async fn knn_search_meetings(
        pool: &SqlitePool,
        query_bytes: &[u8],
        k: i64,
    ) -> Result<Vec<SearchHit>, sqlx::Error> {
        // Probe table existence — vec0 raises a hard error if queried before
        // first creation, and the empty-index case shouldn't surface as a
        // failure to the caller.
        let exists: Option<i64> = sqlx::query_scalar(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='rag_meeting_chunks_vec'",
        )
        .fetch_optional(pool)
        .await?;
        if exists.is_none() {
            return Ok(Vec::new());
        }

        let rows = sqlx::query(
            r#"
            WITH matches AS (
                SELECT chunk_id, distance
                FROM rag_meeting_chunks_vec
                WHERE embedding MATCH ?
                ORDER BY distance
                LIMIT ?
            )
            SELECT
                m.chunk_id        AS chunk_id,
                m.distance        AS distance,
                c.meeting_id      AS meeting_id,
                c.meeting_title   AS meeting_title,
                c.chunk_index     AS chunk_index,
                c.text            AS text
            FROM matches m
            JOIN rag_meeting_chunks c ON c.id = m.chunk_id
            ORDER BY m.distance
            "#,
        )
        .bind(query_bytes)
        .bind(k)
        .fetch_all(pool)
        .await?;

        let hits = rows
            .into_iter()
            .map(|row| SearchHit {
                chunk_id: row.try_get("chunk_id").unwrap_or_default(),
                source: "meeting".to_string(),
                distance: row.try_get("distance").unwrap_or_default(),
                page_id: row.try_get("meeting_id").unwrap_or_default(),
                page_title: row.try_get("meeting_title").unwrap_or_default(),
                page_url: String::new(),
                chunk_index: row.try_get("chunk_index").unwrap_or_default(),
                text: row.try_get("text").unwrap_or_default(),
            })
            .collect();
        Ok(hits)
    }
}


/// Encode `Vec<f32>` into the raw little-endian byte layout that sqlite-vec's
/// `FLOAT[N]` columns expect. 4 bytes per element, host endianness must be LE
/// (true on every platform we ship: x86_64 Win/Linux/macOS, aarch64 macOS).
pub(super) fn vec_f32_to_bytes(v: &[f32]) -> Vec<u8> {
    let mut out = Vec::with_capacity(v.len() * 4);
    for &x in v {
        out.extend_from_slice(&x.to_le_bytes());
    }
    out
}
