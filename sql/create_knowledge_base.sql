-- Knowledge Base Tables for RAG System
-- Run this migration in Supabase SQL Editor

-- Enable vector extension (if not already enabled)
CREATE EXTENSION IF NOT EXISTS vector;

-- ============================================================================
-- Table: knowledge_documents
-- Stores document metadata
-- ============================================================================

CREATE TABLE IF NOT EXISTS knowledge_documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title TEXT NOT NULL,
    source TEXT,                    -- URL, file path, or description of origin
    content TEXT NOT NULL,          -- Full document content
    tags TEXT[] DEFAULT '{}',       -- Categories: ['copywriting', 'hooks', 'brand']
    tool_usage TEXT[] DEFAULT '{}', -- Which tools use this: ['hook_selector', 'ad_review']
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Index for tag filtering
CREATE INDEX IF NOT EXISTS idx_knowledge_documents_tags
ON knowledge_documents USING GIN (tags);

-- Index for tool usage filtering
CREATE INDEX IF NOT EXISTS idx_knowledge_documents_tool_usage
ON knowledge_documents USING GIN (tool_usage);

-- ============================================================================
-- Table: knowledge_chunks
-- Stores chunked content with embeddings for semantic search
-- ============================================================================

CREATE TABLE IF NOT EXISTS knowledge_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID REFERENCES knowledge_documents(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    embedding vector(1536),         -- OpenAI text-embedding-3-small dimension
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Vector similarity search index (IVFFlat for performance)
-- Note: Requires at least 100 rows to build effectively
CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_embedding
ON knowledge_chunks
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);

-- Index for document lookup
CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_document_id
ON knowledge_chunks (document_id);

-- ============================================================================
-- Function: match_knowledge
-- Semantic search with optional tag filtering
-- ============================================================================

CREATE OR REPLACE FUNCTION match_knowledge(
    query_embedding vector(1536),
    match_count INT DEFAULT 8,
    filter_tags TEXT[] DEFAULT NULL
)
RETURNS TABLE (
    chunk_id UUID,
    document_id UUID,
    title TEXT,
    chunk_content TEXT,
    tags TEXT[],
    tool_usage TEXT[],
    similarity FLOAT
)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    SELECT
        kc.id as chunk_id,
        kd.id as document_id,
        kd.title,
        kc.content as chunk_content,
        kd.tags,
        kd.tool_usage,
        1 - (kc.embedding <=> query_embedding) as similarity
    FROM knowledge_chunks kc
    JOIN knowledge_documents kd ON kc.document_id = kd.id
    WHERE (filter_tags IS NULL OR kd.tags && filter_tags)
    ORDER BY kc.embedding <=> query_embedding
    LIMIT match_count;
END;
$$;

-- ============================================================================
-- Function: update_updated_at
-- Auto-update updated_at timestamp
-- ============================================================================

CREATE OR REPLACE FUNCTION update_knowledge_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_knowledge_documents_updated_at
    BEFORE UPDATE ON knowledge_documents
    FOR EACH ROW
    EXECUTE FUNCTION update_knowledge_updated_at();

-- ============================================================================
-- RLS Policies (optional - enable if using Supabase Auth)
-- ============================================================================

-- Uncomment these if you want Row Level Security:
-- ALTER TABLE knowledge_documents ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE knowledge_chunks ENABLE ROW LEVEL SECURITY;

-- Allow service role full access:
-- CREATE POLICY "Service role can do anything on knowledge_documents"
--     ON knowledge_documents FOR ALL
--     USING (auth.role() = 'service_role');

-- CREATE POLICY "Service role can do anything on knowledge_chunks"
--     ON knowledge_chunks FOR ALL
--     USING (auth.role() = 'service_role');

-- ============================================================================
-- Sample data for testing (optional)
-- ============================================================================

-- INSERT INTO knowledge_documents (title, content, tags, tool_usage, source)
-- VALUES (
--     'Hook Formula Cheat Sheet',
--     'The best hooks follow these patterns:
--
-- 1. **Problem-Agitation-Solution (PAS)**
--    - Problem: Identify the pain point
--    - Agitation: Make it feel urgent
--    - Solution: Present your product
--
-- 2. **Before-After-Bridge (BAB)**
--    - Before: Current painful state
--    - After: Desired future state
--    - Bridge: How your product gets them there
--
-- 3. **Numbers & Specificity**
--    - "Lost 23 lbs in 6 weeks" beats "Lose weight fast"
--    - Specific claims feel more credible
--
-- 4. **Curiosity Gap**
--    - Open a loop that must be closed
--    - "The one thing successful people never do..."',
--     ARRAY['copywriting', 'hooks'],
--     ARRAY['hook_selector', 'ad_review'],
--     'Internal documentation'
-- );
