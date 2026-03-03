-- ============================================================================
-- SEO Pipeline Tables Migration
-- ============================================================================
-- Purpose: Create tables for the SEO content pipeline
-- Date: 2026-03-02
-- Branch: worktree-seo-pipeline-port
--
-- Tables: seo_projects, seo_authors, seo_keywords, seo_clusters,
--         seo_competitor_analyses, seo_articles, seo_article_rankings,
--         seo_internal_links, brand_integrations
--
-- Note: Circular FK (seo_keywords→seo_clusters→seo_articles→seo_keywords)
--       resolved by creating tables first, then adding FKs via ALTER TABLE.

-- ============================================================================
-- 1. seo_projects - SEO campaign per brand
-- ============================================================================

CREATE TABLE IF NOT EXISTS seo_projects (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    brand_id UUID NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    config JSONB DEFAULT '{}',
    workflow_state TEXT DEFAULT 'pending',
    workflow_data JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_seo_projects_brand_id ON seo_projects(brand_id);
CREATE INDEX IF NOT EXISTS idx_seo_projects_organization_id ON seo_projects(organization_id);
CREATE INDEX IF NOT EXISTS idx_seo_projects_status ON seo_projects(status);

COMMENT ON TABLE seo_projects IS 'SEO pipeline projects per brand with workflow state';

-- ============================================================================
-- 2. seo_authors - Multi-author per brand
-- ============================================================================

CREATE TABLE IF NOT EXISTS seo_authors (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    brand_id UUID NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    bio TEXT,
    image_url TEXT,
    job_title TEXT,
    author_url TEXT,
    persona_id UUID REFERENCES personas_4d(id) ON DELETE SET NULL,
    schema_data JSONB,
    is_default BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(brand_id, name)
);

CREATE INDEX IF NOT EXISTS idx_seo_authors_brand_id ON seo_authors(brand_id);
CREATE INDEX IF NOT EXISTS idx_seo_authors_organization_id ON seo_authors(organization_id);

COMMENT ON TABLE seo_authors IS 'Authors for SEO articles, optionally linked to personas for voice/style';

-- ============================================================================
-- 3. seo_clusters - Topic clusters (created before seo_keywords for FK)
-- ============================================================================

CREATE TABLE IF NOT EXISTS seo_clusters (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES seo_projects(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    pillar_keyword TEXT,
    pillar_article_id UUID, -- FK added later (circular)
    spoke_count INT DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_seo_clusters_project_id ON seo_clusters(project_id);

COMMENT ON TABLE seo_clusters IS 'Topic clusters for organizing related keywords and articles';

-- ============================================================================
-- 4. seo_keywords - Discovered keywords
-- ============================================================================

CREATE TABLE IF NOT EXISTS seo_keywords (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES seo_projects(id) ON DELETE CASCADE,
    keyword TEXT NOT NULL,
    word_count INT DEFAULT 0,
    seed_keyword TEXT,
    search_volume INT,
    keyword_difficulty FLOAT,
    search_intent TEXT,
    status TEXT DEFAULT 'discovered',
    cluster_id UUID REFERENCES seo_clusters(id) ON DELETE SET NULL,
    found_in_seeds INT DEFAULT 1,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_seo_keywords_project_id ON seo_keywords(project_id);
CREATE INDEX IF NOT EXISTS idx_seo_keywords_status ON seo_keywords(status);
CREATE INDEX IF NOT EXISTS idx_seo_keywords_cluster_id ON seo_keywords(cluster_id);

COMMENT ON TABLE seo_keywords IS 'Discovered keywords with metadata and status tracking';

-- ============================================================================
-- 5. seo_articles - Articles through full lifecycle
-- ============================================================================

CREATE TABLE IF NOT EXISTS seo_articles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES seo_projects(id) ON DELETE CASCADE,
    brand_id UUID NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    author_id UUID REFERENCES seo_authors(id) ON DELETE SET NULL,
    keyword_id UUID REFERENCES seo_keywords(id) ON DELETE SET NULL,
    keyword TEXT NOT NULL,
    title TEXT,
    content_markdown TEXT,
    content_html TEXT,
    seo_title TEXT,
    meta_description TEXT,
    schema_markup JSONB,
    slug TEXT,
    tags TEXT[] DEFAULT '{}',
    cms_article_id TEXT,
    published_url TEXT,
    published_at TIMESTAMPTZ,
    status TEXT DEFAULT 'draft',
    phase TEXT DEFAULT 'a',
    phase_a_output TEXT,
    phase_b_output TEXT,
    phase_c_output TEXT,
    winning_formula JSONB,
    qa_report JSONB,
    word_count INT DEFAULT 0,
    reading_time_minutes INT DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_seo_articles_project_id ON seo_articles(project_id);
CREATE INDEX IF NOT EXISTS idx_seo_articles_brand_id ON seo_articles(brand_id);
CREATE INDEX IF NOT EXISTS idx_seo_articles_organization_id ON seo_articles(organization_id);
CREATE INDEX IF NOT EXISTS idx_seo_articles_keyword_id ON seo_articles(keyword_id);
CREATE INDEX IF NOT EXISTS idx_seo_articles_status ON seo_articles(status);
CREATE INDEX IF NOT EXISTS idx_seo_articles_slug ON seo_articles(slug);

COMMENT ON TABLE seo_articles IS 'SEO articles through full lifecycle from draft to published';

-- ============================================================================
-- 6. seo_competitor_analyses - SERP results per keyword
-- ============================================================================

CREATE TABLE IF NOT EXISTS seo_competitor_analyses (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    keyword_id UUID NOT NULL REFERENCES seo_keywords(id) ON DELETE CASCADE,
    url TEXT NOT NULL,
    position INT,
    title TEXT,
    meta_description TEXT,
    word_count INT DEFAULT 0,
    h1_count INT DEFAULT 0,
    h2_count INT DEFAULT 0,
    h3_count INT DEFAULT 0,
    h4_count INT DEFAULT 0,
    paragraph_count INT DEFAULT 0,
    avg_paragraph_length FLOAT DEFAULT 0,
    flesch_reading_ease FLOAT,
    internal_link_count INT DEFAULT 0,
    external_link_count INT DEFAULT 0,
    image_count INT DEFAULT 0,
    images_with_alt INT DEFAULT 0,
    has_toc BOOLEAN DEFAULT FALSE,
    has_faq BOOLEAN DEFAULT FALSE,
    has_schema BOOLEAN DEFAULT FALSE,
    has_author BOOLEAN DEFAULT FALSE,
    has_breadcrumbs BOOLEAN DEFAULT FALSE,
    schema_types TEXT[] DEFAULT '{}',
    cta_count INT DEFAULT 0,
    has_tables BOOLEAN DEFAULT FALSE,
    table_count INT DEFAULT 0,
    video_embeds INT DEFAULT 0,
    raw_analysis JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_seo_competitor_analyses_keyword_id ON seo_competitor_analyses(keyword_id);

COMMENT ON TABLE seo_competitor_analyses IS 'Competitor page analysis results per keyword';

-- ============================================================================
-- 7. seo_article_rankings - Ranking history
-- ============================================================================

CREATE TABLE IF NOT EXISTS seo_article_rankings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    article_id UUID NOT NULL REFERENCES seo_articles(id) ON DELETE CASCADE,
    keyword TEXT NOT NULL,
    position INT,
    snippet_featured BOOLEAN DEFAULT FALSE,
    indexed BOOLEAN DEFAULT TRUE,
    checked_at TIMESTAMPTZ DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_seo_article_rankings_article_id ON seo_article_rankings(article_id);
CREATE INDEX IF NOT EXISTS idx_seo_article_rankings_checked_at ON seo_article_rankings(checked_at);

COMMENT ON TABLE seo_article_rankings IS 'Keyword ranking history per article';

-- ============================================================================
-- 8. seo_internal_links - Link suggestions & tracking
-- ============================================================================

CREATE TABLE IF NOT EXISTS seo_internal_links (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_article_id UUID NOT NULL REFERENCES seo_articles(id) ON DELETE CASCADE,
    target_article_id UUID NOT NULL REFERENCES seo_articles(id) ON DELETE CASCADE,
    anchor_text TEXT NOT NULL,
    similarity_score FLOAT DEFAULT 0,
    link_type TEXT DEFAULT 'suggested',
    status TEXT DEFAULT 'pending',
    placement TEXT DEFAULT 'end',
    priority TEXT DEFAULT 'medium',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_seo_internal_links_source ON seo_internal_links(source_article_id);
CREATE INDEX IF NOT EXISTS idx_seo_internal_links_target ON seo_internal_links(target_article_id);

COMMENT ON TABLE seo_internal_links IS 'Internal link suggestions and implemented links between articles';

-- ============================================================================
-- 9. brand_integrations - Per-brand CMS credentials
-- ============================================================================

CREATE TABLE IF NOT EXISTS brand_integrations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    brand_id UUID NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    platform TEXT NOT NULL,
    config JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(brand_id, platform)
);

CREATE INDEX IF NOT EXISTS idx_brand_integrations_brand_id ON brand_integrations(brand_id);
CREATE INDEX IF NOT EXISTS idx_brand_integrations_organization_id ON brand_integrations(organization_id);

COMMENT ON TABLE brand_integrations IS 'Per-brand CMS and platform integrations with JSONB config';

-- ============================================================================
-- CIRCULAR FK: Add deferred foreign keys
-- ============================================================================

ALTER TABLE seo_clusters
    ADD CONSTRAINT fk_seo_clusters_pillar_article
    FOREIGN KEY (pillar_article_id) REFERENCES seo_articles(id) ON DELETE SET NULL;

-- ============================================================================
-- TRIGGER FUNCTIONS (table-specific per codebase pattern)
-- ============================================================================

CREATE OR REPLACE FUNCTION update_seo_projects_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION update_seo_authors_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION update_seo_clusters_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION update_seo_keywords_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION update_seo_articles_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION update_seo_internal_links_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION update_brand_integrations_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- TRIGGERS
-- ============================================================================

DROP TRIGGER IF EXISTS update_seo_projects_updated_at ON seo_projects;
CREATE TRIGGER update_seo_projects_updated_at
    BEFORE UPDATE ON seo_projects
    FOR EACH ROW EXECUTE FUNCTION update_seo_projects_updated_at();

DROP TRIGGER IF EXISTS update_seo_authors_updated_at ON seo_authors;
CREATE TRIGGER update_seo_authors_updated_at
    BEFORE UPDATE ON seo_authors
    FOR EACH ROW EXECUTE FUNCTION update_seo_authors_updated_at();

DROP TRIGGER IF EXISTS update_seo_clusters_updated_at ON seo_clusters;
CREATE TRIGGER update_seo_clusters_updated_at
    BEFORE UPDATE ON seo_clusters
    FOR EACH ROW EXECUTE FUNCTION update_seo_clusters_updated_at();

DROP TRIGGER IF EXISTS update_seo_keywords_updated_at ON seo_keywords;
CREATE TRIGGER update_seo_keywords_updated_at
    BEFORE UPDATE ON seo_keywords
    FOR EACH ROW EXECUTE FUNCTION update_seo_keywords_updated_at();

DROP TRIGGER IF EXISTS update_seo_articles_updated_at ON seo_articles;
CREATE TRIGGER update_seo_articles_updated_at
    BEFORE UPDATE ON seo_articles
    FOR EACH ROW EXECUTE FUNCTION update_seo_articles_updated_at();

DROP TRIGGER IF EXISTS update_seo_internal_links_updated_at ON seo_internal_links;
CREATE TRIGGER update_seo_internal_links_updated_at
    BEFORE UPDATE ON seo_internal_links
    FOR EACH ROW EXECUTE FUNCTION update_seo_internal_links_updated_at();

DROP TRIGGER IF EXISTS update_brand_integrations_updated_at ON brand_integrations;
CREATE TRIGGER update_brand_integrations_updated_at
    BEFORE UPDATE ON brand_integrations
    FOR EACH ROW EXECUTE FUNCTION update_brand_integrations_updated_at();

-- ============================================================================
-- ROW LEVEL SECURITY
-- ============================================================================

ALTER TABLE seo_projects ENABLE ROW LEVEL SECURITY;
ALTER TABLE seo_authors ENABLE ROW LEVEL SECURITY;
ALTER TABLE seo_clusters ENABLE ROW LEVEL SECURITY;
ALTER TABLE seo_keywords ENABLE ROW LEVEL SECURITY;
ALTER TABLE seo_articles ENABLE ROW LEVEL SECURITY;
ALTER TABLE seo_competitor_analyses ENABLE ROW LEVEL SECURITY;
ALTER TABLE seo_article_rankings ENABLE ROW LEVEL SECURITY;
ALTER TABLE seo_internal_links ENABLE ROW LEVEL SECURITY;
ALTER TABLE brand_integrations ENABLE ROW LEVEL SECURITY;

-- RLS Policies (permissive - application handles authorization)
CREATE POLICY seo_projects_policy ON seo_projects FOR ALL TO authenticated USING (true) WITH CHECK (true);
CREATE POLICY seo_authors_policy ON seo_authors FOR ALL TO authenticated USING (true) WITH CHECK (true);
CREATE POLICY seo_clusters_policy ON seo_clusters FOR ALL TO authenticated USING (true) WITH CHECK (true);
CREATE POLICY seo_keywords_policy ON seo_keywords FOR ALL TO authenticated USING (true) WITH CHECK (true);
CREATE POLICY seo_articles_policy ON seo_articles FOR ALL TO authenticated USING (true) WITH CHECK (true);
CREATE POLICY seo_competitor_analyses_policy ON seo_competitor_analyses FOR ALL TO authenticated USING (true) WITH CHECK (true);
CREATE POLICY seo_article_rankings_policy ON seo_article_rankings FOR ALL TO authenticated USING (true) WITH CHECK (true);
CREATE POLICY seo_internal_links_policy ON seo_internal_links FOR ALL TO authenticated USING (true) WITH CHECK (true);
CREATE POLICY brand_integrations_policy ON brand_integrations FOR ALL TO authenticated USING (true) WITH CHECK (true);
