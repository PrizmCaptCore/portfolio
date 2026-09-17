//! Local RAG state — mirrors backend Notion chunks into sqlite-vec.
//!
//! See `migrations/20260504000000_add_rag_tables.sql` for the schema and
//! `repository::ensure_vec_table` for the runtime vec0 bootstrap that
//! happens once we know the embedding dimension.

pub mod commands;
pub mod models;
pub mod repository;
