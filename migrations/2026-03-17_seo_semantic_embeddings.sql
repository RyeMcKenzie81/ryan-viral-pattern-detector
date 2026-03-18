-- Migration: Add semantic embedding columns to SEO tables
-- Date: 2026-03-17
-- Purpose: Enable Gemini Embedding 2 semantic similarity for keyword matching,
--          replacing Jaccard word-overlap. Requires pgvector >= 0.5.0 (HNSW support).
--          Supabase bundles pgvector 0.7.0+.

-- Keyword embeddings (768-dim Gemini Embedding 2)
ALTER TABLE seo_keywords ADD COLUMN IF NOT EXISTS embedding VECTOR(768);
COMMENT ON COLUMN seo_keywords.embedding
  IS 'Gemini Embedding 2 vector (768d) for semantic similarity';
CREATE INDEX IF NOT EXISTS idx_seo_keywords_embedding
  ON seo_keywords USING hnsw (embedding vector_cosine_ops);

-- Cluster centroid embeddings (mean of spoke keyword embeddings)
ALTER TABLE seo_clusters ADD COLUMN IF NOT EXISTS centroid_embedding VECTOR(768);
COMMENT ON COLUMN seo_clusters.centroid_embedding
  IS 'Mean of spoke keyword embeddings — incrementally updated on spoke changes';
CREATE INDEX IF NOT EXISTS idx_seo_clusters_centroid_embedding
  ON seo_clusters USING hnsw (centroid_embedding vector_cosine_ops);
