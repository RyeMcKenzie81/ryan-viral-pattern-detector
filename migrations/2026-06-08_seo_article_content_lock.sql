-- Migration: content_locked flag on seo_articles
-- Date: 2026-06-08
-- Purpose: Protect manual Shopify-side edits from being silently overwritten by
-- our re-render / republish / interlink pushes. The pipeline treats
-- phase_c_output -> content_html -> Shopify as one-directional (we never pull a
-- user's Shopify body edit back), so every push is a blind overwrite. When this
-- flag is TRUE, all body-write paths (publish_article, sync_content_html,
-- repair_markdown_html, and the interlinking pushes) skip the article's body so
-- a human-owned copy is left untouched. The article still remains a valid
-- internal-link TARGET for its siblings.
--
-- Code degrades gracefully if this column is missing (treated as not-locked),
-- so applying the migration is safe to do before or after the code deploy.

ALTER TABLE seo_articles
    ADD COLUMN IF NOT EXISTS content_locked BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN seo_articles.content_locked IS
    'When true, the body is human-owned on the CMS: skip all our body re-renders/pushes (publish, repair, interlink) so we never overwrite a manual Shopify edit. The article can still be a link target.';
