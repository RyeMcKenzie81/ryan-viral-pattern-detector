-- Migration: optional per-brand SEO length thresholds (B7)
-- Date: 2026-06-10
-- Purpose: make the single-source-of-truth thresholds brand-configurable. NULL
-- (the default) means "use the module defaults" (50-60 title / 150-160 meta);
-- a JSONB with any subset of keys overrides just those for that brand:
--   {"title_ideal_min":45,"title_ideal_max":65,"meta_ideal_min":140,...}
-- Keys: title_ideal_min/max, title_hard_max, meta_ideal_min/max, meta_hard_max.
--
-- resolve_seo_thresholds() reads this column off the brand policy; an absent
-- column or NULL falls back to the defaults, so the code is fully graceful
-- before this is applied (it just can't store an override yet).
--
-- No UI yet — set an override via SQL. The Content Policies page can expose it
-- later (a thin follow-up).

ALTER TABLE brand_content_policies
    ADD COLUMN IF NOT EXISTS seo_thresholds JSONB;

COMMENT ON COLUMN brand_content_policies.seo_thresholds IS
    'B7: optional per-brand SEO title/meta length threshold overrides (subset of title_ideal_min/max, title_hard_max, meta_ideal_min/max, meta_hard_max). NULL => module defaults.';
