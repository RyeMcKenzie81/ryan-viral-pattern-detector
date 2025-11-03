-- Migration: Add generated_content table for Phase 3
-- Date: 2025-10-31
-- Purpose: Store AI-generated content (threads, blogs, etc.) from viral hooks

-- Create generated_content table
CREATE TABLE generated_content (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id UUID NOT NULL REFERENCES projects(id),

    -- Source
    source_tweet_id VARCHAR REFERENCES posts(post_id),

    -- Hook analysis
    hook_type VARCHAR,
    emotional_trigger VARCHAR,
    content_pattern VARCHAR,
    hook_explanation TEXT,

    -- Generated content
    content_type VARCHAR,  -- 'thread', 'blog', 'linkedin', 'newsletter'
    content_title TEXT,
    content_body TEXT,
    content_metadata JSONB,

    -- Adaptation
    adaptation_notes TEXT,
    project_context TEXT,

    -- Tracking
    api_cost_usd NUMERIC(10, 8),
    model_used VARCHAR DEFAULT 'gemini-2.0-flash-exp',
    status VARCHAR DEFAULT 'pending',

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    published_at TIMESTAMPTZ
);

-- Create indexes
CREATE INDEX idx_generated_content_project ON generated_content(project_id);
CREATE INDEX idx_generated_content_source ON generated_content(source_tweet_id);
CREATE INDEX idx_generated_content_status ON generated_content(status);
CREATE INDEX idx_generated_content_type ON generated_content(content_type);

-- Add comments
COMMENT ON TABLE generated_content IS 'AI-generated long-form content from viral hooks';
COMMENT ON COLUMN generated_content.source_tweet_id IS 'Original viral tweet that inspired this content';
COMMENT ON COLUMN generated_content.hook_type IS 'Type of hook from Phase 2B analysis';
COMMENT ON COLUMN generated_content.content_type IS 'Format: thread, blog, linkedin, or newsletter';
COMMENT ON COLUMN generated_content.content_metadata IS 'Format-specific data (e.g., thread structure)';
COMMENT ON COLUMN generated_content.status IS 'Lifecycle: pending, reviewed, published';
