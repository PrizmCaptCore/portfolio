use crate::database::models::{MeetingEmbeddingInfo, MeetingEmbeddingRow, MeetingForGraph};
use sqlx::SqlitePool;

pub struct GraphRepository;

impl GraphRepository {
    /// All meetings that have a completed summary.
    pub async fn get_meetings_for_graph(
        pool: &SqlitePool,
    ) -> Result<Vec<MeetingForGraph>, sqlx::Error> {
        sqlx::query_as::<_, MeetingForGraph>(
            r#"
            SELECT
                m.id,
                m.title,
                strftime('%Y-%m-%dT%H:%M:%SZ', m.created_at) AS created_at,
                sp.result AS key_points
            FROM meetings m
            JOIN summary_processes sp
              ON sp.meeting_id = m.id
             AND sp.status = 'completed'
             AND sp.result IS NOT NULL
             AND sp.result != ''
            ORDER BY m.created_at DESC
            "#,
        )
        .fetch_all(pool)
        .await
    }

    /// All stored embeddings (for cache invalidation in the frontend).
    pub async fn get_all_embeddings(
        pool: &SqlitePool,
    ) -> Result<Vec<MeetingEmbeddingInfo>, sqlx::Error> {
        let rows = sqlx::query_as::<_, MeetingEmbeddingRow>(
            "SELECT meeting_id, embedding_vector, source_text FROM meeting_embeddings",
        )
        .fetch_all(pool)
        .await?;

        Ok(rows
            .into_iter()
            .map(|r| MeetingEmbeddingInfo {
                meeting_id: r.meeting_id,
                embedding_bytes: r.embedding_vector,
                source_text: r.source_text,
            })
            .collect())
    }

    /// Upsert a precomputed embedding.
    pub async fn save_embedding(
        pool: &SqlitePool,
        meeting_id: &str,
        embedding_bytes: &[u8],
        source_text: &str,
    ) -> Result<(), sqlx::Error> {
        let now = chrono::Utc::now().to_rfc3339();
        sqlx::query(
            r#"
            INSERT INTO meeting_embeddings (meeting_id, embedding_vector, source_text, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(meeting_id) DO UPDATE SET
                embedding_vector = excluded.embedding_vector,
                source_text      = excluded.source_text,
                created_at       = excluded.created_at
            "#,
        )
        .bind(meeting_id)
        .bind(embedding_bytes)
        .bind(source_text)
        .bind(now)
        .execute(pool)
        .await?;
        Ok(())
    }
}
