-- Migration: SEO Content Autopilot — brand content policies, evaluation results, publish queue
-- Date: 2026-03-30
-- Purpose: Enable automated content evaluation, staggered publishing, and auto-interlinking
-- per brand. Articles flow: qa_passed → eval_passed → publish_queued → publishing → published.
-- Failed evaluations surface in the Exceptions Dashboard for human review.

-- =============================================================================
-- 1. Brand Content Policies — per-brand automation configuration
-- =============================================================================
-- Populated by UI (Brand Manager / Content Policies page).
-- Read by ContentEvalService, PublishQueueService, and scheduler jobs.

CREATE TABLE IF NOT EXISTS brand_content_policies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    brand_id UUID NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,

    -- Image evaluation rules (AI vision via Claude)
    image_eval_enabled BOOLEAN DEFAULT true,
    image_eval_rules JSONB DEFAULT '[]',
    -- Example rules:
    -- [
    --   {"rule": "Characters must be facing the viewer/camera", "severity": "error"},
    --   {"rule": "Product packaging should not dominate more than 30% of the image", "severity": "error"},
    --   {"rule": "Brand colors should be visible in the image", "severity": "warning"},
    --   {"rule": "No text overlays on images", "severity": "warning"}
    -- ]

    -- Image eval confidence threshold (0-1). Rules failing below this
    -- threshold are "uncertain" and surfaced for human review.
    image_eval_min_confidence FLOAT DEFAULT 0.8,

    -- Publish cadence
    publish_enabled BOOLEAN DEFAULT false,
    publish_times_per_day INTEGER DEFAULT 2,
    publish_window_start TIME DEFAULT '09:00',
    publish_window_end TIME DEFAULT '17:00',
    publish_timezone TEXT DEFAULT 'America/New_York',
    publish_days_of_week INTEGER[] DEFAULT '{1,2,3,4,5}',  -- 1=Mon, 7=Sun

    -- Auto-interlinking
    interlink_enabled BOOLEAN DEFAULT true,
    interlink_modes TEXT[] DEFAULT '{auto_link,bidirectional}',
    -- Mode mapping to InterlinkingService methods:
    --   'suggest'       → suggest_links()
    --   'auto_link'     → auto_link_article()
    --   'bidirectional' → add_related_section()

    -- Content evaluation overrides
    max_warnings_for_auto_publish INTEGER DEFAULT 0,
    -- 0 = zero tolerance (must pass everything)
    -- N = allow up to N warnings (errors always block)

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(brand_id)
);

CREATE INDEX IF NOT EXISTS idx_brand_content_policies_brand
    ON brand_content_policies(brand_id);
CREATE INDEX IF NOT EXISTS idx_brand_content_policies_org
    ON brand_content_policies(organization_id);

ALTER TABLE brand_content_policies ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'brand_content_policies_org_access') THEN
        CREATE POLICY brand_content_policies_org_access ON brand_content_policies
            FOR ALL USING (true);
    END IF;
END
$$;

-- =============================================================================
-- 2. Content Evaluation Results — stores eval verdicts per article
-- =============================================================================
-- Populated by ContentEvalService (via seo_content_eval scheduler job).
-- Read by PublishQueueService, Exceptions Dashboard UI.

CREATE TABLE IF NOT EXISTS seo_content_eval_results (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    article_id UUID NOT NULL REFERENCES seo_articles(id) ON DELETE CASCADE,
    brand_id UUID NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,

    -- Aggregate result
    verdict TEXT NOT NULL CHECK (verdict IN ('passed', 'failed', 'skipped')),
    total_checks INTEGER DEFAULT 0,
    passed_checks INTEGER DEFAULT 0,
    failed_checks INTEGER DEFAULT 0,
    warning_count INTEGER DEFAULT 0,

    -- Detailed results
    qa_result JSONB,          -- From qa_validation_service
    checklist_result JSONB,   -- From pre_publish_checklist_service
    image_eval_result JSONB,  -- From AI vision evaluation
    -- image_eval_result structure:
    -- {
    --   "images_evaluated": int,
    --   "images_passed": int,
    --   "images_failed": int,
    --   "uncertain_count": int,
    --   "evaluations": [
    --     {
    --       "image_url": "...",
    --       "image_type": "hero" | "inline",
    --       "passed": bool,
    --       "rules": [
    --         {"rule": "...", "passed": bool, "confidence": float, "explanation": "..."}
    --       ]
    --     }
    --   ]
    -- }

    -- Action tracking
    auto_published BOOLEAN DEFAULT false,
    manually_overridden BOOLEAN DEFAULT false,
    override_reason TEXT,

    evaluated_at TIMESTAMPTZ DEFAULT NOW(),
    evaluated_by TEXT DEFAULT 'scheduler',  -- 'scheduler' or 'manual'

    -- Allow re-evaluation (e.g., after image regeneration)
    superseded_by UUID REFERENCES seo_content_eval_results(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_seo_eval_results_article
    ON seo_content_eval_results(article_id);
CREATE INDEX IF NOT EXISTS idx_seo_eval_results_brand
    ON seo_content_eval_results(brand_id);
CREATE INDEX IF NOT EXISTS idx_seo_eval_results_verdict
    ON seo_content_eval_results(verdict, evaluated_at DESC);
CREATE INDEX IF NOT EXISTS idx_seo_eval_results_org
    ON seo_content_eval_results(organization_id);

ALTER TABLE seo_content_eval_results ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'seo_content_eval_results_org_access') THEN
        CREATE POLICY seo_content_eval_results_org_access ON seo_content_eval_results
            FOR ALL USING (true);
    END IF;
END
$$;

-- =============================================================================
-- 3. Publish Queue — scheduled article publishing with idempotency
-- =============================================================================
-- Populated by ContentEvalService (on eval pass) via PublishQueueService.
-- Consumed by seo_publish scheduler job.

CREATE TABLE IF NOT EXISTS seo_publish_queue (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    article_id UUID NOT NULL REFERENCES seo_articles(id) ON DELETE CASCADE,
    brand_id UUID NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,

    -- Scheduling
    publish_at TIMESTAMPTZ NOT NULL,
    published_at TIMESTAMPTZ,

    -- Status
    status TEXT NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'publishing', 'published', 'failed', 'cancelled')),

    -- Idempotency: content_hash = SHA256(content_html + hero_image_url + inline_image_urls)
    -- Set once at enqueue time, not re-checked at publish time.
    idempotency_key TEXT NOT NULL UNIQUE,

    -- Error tracking
    error_message TEXT,
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 3,

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_publish_queue_due
    ON seo_publish_queue(status, publish_at)
    WHERE status = 'queued';
CREATE INDEX IF NOT EXISTS idx_publish_queue_brand
    ON seo_publish_queue(brand_id, status);
CREATE INDEX IF NOT EXISTS idx_publish_queue_article
    ON seo_publish_queue(article_id);
CREATE INDEX IF NOT EXISTS idx_publish_queue_org
    ON seo_publish_queue(organization_id);

ALTER TABLE seo_publish_queue ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'seo_publish_queue_org_access') THEN
        CREATE POLICY seo_publish_queue_org_access ON seo_publish_queue
            FOR ALL USING (true);
    END IF;
END
$$;

COMMENT ON TABLE brand_content_policies IS 'Per-brand automation config: image eval rules, publish cadence, interlink modes';
COMMENT ON TABLE seo_content_eval_results IS 'Content evaluation verdicts with QA, checklist, and AI image eval results';
COMMENT ON TABLE seo_publish_queue IS 'Scheduled article publishing queue with staggered slots and idempotency';
