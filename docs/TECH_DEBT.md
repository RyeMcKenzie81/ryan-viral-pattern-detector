# Tech Debt & Future Improvements

This document tracks technical debt and planned future enhancements that aren't urgent but shouldn't be forgotten.

## How This Works

- **Add items** when you identify improvements that can wait but should be done eventually
- **Include context** - why it matters, rough complexity, and any relevant links
- **Remove items** when completed (or move to a "Completed" section if you want history)
- **Review periodically** when starting new work to see if anything should be prioritized

---

## Backlog

### 1. Meta Ads OAuth Per-Brand Authentication

**Priority**: Low (only needed for external client accounts)
**Complexity**: Medium-High
**Added**: 2025-12-20

**Context**: Currently using a single System User token for all ad accounts in the Business Manager. This works fine for internal brands but won't work for external client accounts.

**What's needed**:
1. Database migration - Add token columns to `brand_ad_accounts`:
   ```sql
   ALTER TABLE brand_ad_accounts ADD COLUMN IF NOT EXISTS
       access_token TEXT,
       token_expires_at TIMESTAMPTZ,
       refresh_token TEXT,
       auth_method TEXT DEFAULT 'system_user';
   ```

2. OAuth flow implementation:
   - "Connect Facebook" button in brand settings
   - Redirect to Facebook OAuth dialog
   - Handle callback, store tokens per-brand
   - Token refresh logic (60-day tokens)

3. Service updates:
   - `_get_access_token(brand_id)` - Check DB first, fallback to env var
   - Token expiry checking and refresh

4. UI:
   - Connection status indicator per brand
   - "Reconnect" button when token expires

**Reference**:
- Plan: `~/.claude/plans/rippling-cuddling-summit.md` (Phase 7)
- Checkpoint: `docs/archive/CHECKPOINT_meta_ads_phase6_final.md`

---

### 2. Pattern Discovery - Suggested Actions for Low Confidence

**Priority**: Medium
**Complexity**: Low-Medium
**Added**: 2026-01-06

**Context**: When Pattern Discovery finds clusters with low confidence scores (10-20%), users don't know what action to take. The system should suggest specific data sources to scrape to improve confidence.

**What's needed**:
1. Analyze which source types are missing from the pattern's `source_breakdown`
2. Show contextual suggestions in the Research Insights UI:
   - **Low confidence** → "Add more sources" with specific suggestions (Reddit, competitor ads, more reviews)
   - **Low novelty** → "Similar to existing angle X" with link
   - **High confidence + High novelty** → "🎯 Strong candidate for promotion!"

3. Potentially link to the relevant scraping pages (Competitor Research, URL Mapping, etc.)

**Example UI**:
```
💡 Low confidence (20%) - This pattern needs more evidence. Try:
  • Scrape Reddit discussions about joint supplements
  • Analyze competitor Facebook ads
  • Add more Amazon reviews
```

---

## Completed

_Move items here when done, with completion date._

