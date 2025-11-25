-- ============================================
-- Facebook Ad Creation Agent - Database Migration
-- Version: 1.0.0
-- Date: 2025-01-24
-- ============================================

-- ============================================
-- AD BRIEF TEMPLATES (create first - referenced by brands)
-- ============================================

CREATE TABLE IF NOT EXISTS ad_brief_templates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    brand_id UUID REFERENCES brands(id) ON DELETE CASCADE,  -- NULL = global template
    name TEXT NOT NULL,
    instructions TEXT NOT NULL,
    active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ad_brief_brand ON ad_brief_templates(brand_id);
CREATE INDEX IF NOT EXISTS idx_ad_brief_active ON ad_brief_templates(active);

COMMENT ON TABLE ad_brief_templates IS 'Templates for ad creation instructions (brand-specific or global)';
COMMENT ON COLUMN ad_brief_templates.brand_id IS 'NULL = global template';

-- ============================================
-- BRANDS & PRODUCTS (extend existing tables)
-- ============================================

-- Add ad-specific columns to brands (now that ad_brief_templates exists)
ALTER TABLE brands
ADD COLUMN IF NOT EXISTS default_ad_brief_id UUID REFERENCES ad_brief_templates(id);

-- Add ad-specific columns to products
ALTER TABLE products
ADD COLUMN IF NOT EXISTS benefits TEXT[],
ADD COLUMN IF NOT EXISTS key_ingredients TEXT[],
ADD COLUMN IF NOT EXISTS target_audience TEXT,
ADD COLUMN IF NOT EXISTS product_url TEXT,
ADD COLUMN IF NOT EXISTS main_image_storage_path TEXT,
ADD COLUMN IF NOT EXISTS reference_image_storage_paths TEXT[];

COMMENT ON TABLE ad_brief_templates IS 'Templates for ad creation instructions (brand-specific or global)';
COMMENT ON COLUMN ad_brief_templates.brand_id IS 'NULL = global template';

-- ============================================
-- HOOKS (product-specific persuasive hooks)
-- ============================================

CREATE TABLE IF NOT EXISTS hooks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product_id UUID REFERENCES products(id) ON DELETE CASCADE NOT NULL,
    text TEXT NOT NULL,
    category TEXT NOT NULL,  -- Universal persuasive principles
    framework TEXT,  -- Original framework name
    impact_score INT CHECK (impact_score >= 0 AND impact_score <= 21),
    emotional_score TEXT CHECK (emotional_score IN ('Very High', 'High', 'Medium', 'Low')),
    active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_hooks_product ON hooks(product_id);
CREATE INDEX idx_hooks_active ON hooks(active);
CREATE INDEX idx_hooks_impact ON hooks(impact_score DESC);
CREATE INDEX idx_hooks_category ON hooks(category);

COMMENT ON TABLE hooks IS 'Persuasive hooks derived from reviews, scored by impact and emotional resonance';
COMMENT ON COLUMN hooks.category IS 'Universal persuasive principle: skepticism_overcome, timeline, authority_validation, value_contrast, bonus_discovery, specificity, transformation, failed_alternatives';
COMMENT ON COLUMN hooks.impact_score IS 'Score 0-21 based on persuasive framework scoring system';

-- ============================================
-- AD GENERATION RUNS
-- ============================================

CREATE TABLE IF NOT EXISTS ad_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID REFERENCES projects(id),
    product_id UUID REFERENCES products(id) ON DELETE CASCADE NOT NULL,
    reference_ad_storage_path TEXT NOT NULL,
    status TEXT DEFAULT 'pending' CHECK (status IN (
        'pending', 'analyzing', 'generating', 'reviewing', 'complete', 'failed'
    )),

    -- Stage outputs (stored as JSONB for flexibility)
    ad_analysis JSONB,
    selected_hooks JSONB,
    selected_product_images TEXT[],

    -- Metadata
    created_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    error_message TEXT
);

CREATE INDEX idx_ad_runs_product ON ad_runs(product_id);
CREATE INDEX idx_ad_runs_status ON ad_runs(status);
CREATE INDEX idx_ad_runs_created ON ad_runs(created_at DESC);

COMMENT ON TABLE ad_runs IS 'Tracks ad generation workflow runs from reference ad to final output';
COMMENT ON COLUMN ad_runs.ad_analysis IS 'JSON: AdAnalysis model (format_type, layout, colors, etc.)';
COMMENT ON COLUMN ad_runs.selected_hooks IS 'JSON array: SelectedHook models with adaptations';

-- ============================================
-- GENERATED ADS
-- ============================================

CREATE TABLE IF NOT EXISTS generated_ads (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ad_run_id UUID REFERENCES ad_runs(id) ON DELETE CASCADE NOT NULL,
    prompt_index INT NOT NULL CHECK (prompt_index >= 1 AND prompt_index <= 5),

    -- Prompt details
    prompt_text TEXT NOT NULL,
    prompt_spec JSONB NOT NULL,
    hook_id UUID REFERENCES hooks(id),
    hook_text TEXT,

    -- Generated image
    storage_path TEXT NOT NULL,

    -- AI Reviews
    claude_review JSONB,
    gemini_review JSONB,
    reviewers_agree BOOLEAN,
    final_status TEXT DEFAULT 'pending' CHECK (final_status IN (
        'pending', 'approved', 'rejected', 'flagged'
    )),

    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_generated_ads_run ON generated_ads(ad_run_id);
CREATE INDEX idx_generated_ads_status ON generated_ads(final_status);
CREATE INDEX idx_generated_ads_hook ON generated_ads(hook_id);
CREATE UNIQUE INDEX idx_generated_ads_run_index ON generated_ads(ad_run_id, prompt_index);

COMMENT ON TABLE generated_ads IS 'Individual generated ad images with prompts and AI review results';
COMMENT ON COLUMN generated_ads.prompt_spec IS 'JSON spec passed to Nano Banana (canvas, colors, text elements)';
COMMENT ON COLUMN generated_ads.claude_review IS 'JSON: ReviewResult from Claude (product_accuracy, text_accuracy, etc.)';
COMMENT ON COLUMN generated_ads.gemini_review IS 'JSON: ReviewResult from Gemini';
COMMENT ON COLUMN generated_ads.final_status IS 'approved = either reviewer approved, rejected = both rejected, flagged = disagreement';

-- ============================================
-- SEED DATA: Global Ad Brief Template
-- ============================================

INSERT INTO ad_brief_templates (brand_id, name, instructions, active)
VALUES (
    NULL,  -- Global template
    'Default Ad Brief Template',
    '## How to Generate Social Media Ad Briefs

When creating social media ads based on user-provided examples, follow this approach:

### Core Concept
Analyze the uploaded ad example FIRST to understand its format, then create 5 variations using proven hooks from our database while maintaining the same visual structure.

### Process

1. **ANALYZE THE UPLOADED AD EXAMPLE**
   - Identify the format (testimonial, quote style, before/after, etc.)
   - Note the layout structure (single image, two-panel, carousel, etc.)
   - Extract visual elements (text placement, image sections, colors)
   - Identify authenticity markers (timestamps, usernames, emojis, etc.)
   - Determine what stays constant vs. what changes between variations

2. **Identify Production Efficiencies**
   - Look for elements that can be created once and reused
   - Example: If it has a product shot, make that fixed across all variations
   - Determine what MUST change for each variation (usually the main visual/photo)

3. **Select 5 Hooks**
   - Use diverse persuasive principles (mix categories for variety)
   - Prioritize "High" and "Very High" emotional scores
   - Mix frameworks (Cost Comparison, Skepticism Overcome, etc.)

4. **Transform Hooks to Match Ad Style**
   - Adapt hooks to match the tone/format of the example
   - If testimonial style: Add timeframes, names, emojis
   - If quote style: Keep it punchy and direct
   - If before/after: Focus on transformation
   - Match the language style of the original

5. **Define Visual Structure**
   - Use same dimensions as example (usually 1080x1080px)
   - Maintain same layout structure
   - Identify fixed elements (use across all 5)
   - Identify variable elements (change for each)

### Remember
- Start by analyzing what they upload - don''t assume format
- Find ways to reuse elements across all 5 variations
- Use actual customer language from reviews
- Match the authenticity level of the example',
    true
) ON CONFLICT DO NOTHING;
