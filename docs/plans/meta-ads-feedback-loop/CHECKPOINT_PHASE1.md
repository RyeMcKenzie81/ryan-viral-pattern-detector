# Meta Ads Feedback Loop - Phase 1 Checkpoint

**Date**: 2025-12-18
**Status**: Complete (Updated with per-brand accounts)
**Phase**: Core Infrastructure

---

## Summary

Phase 1 established the core infrastructure for the Meta Ads performance feedback loop. This includes database schema, Pydantic models, service skeleton, and configuration updates.

---

## Completed Tasks

### 1. Filename Format Update
**File**: `/viraltracker/services/ad_creation_service.py`

Changed `generate_ad_filename()` to put the ad_id first (8 chars):
- **Before**: `WP-C3-a1b2c3-d4e5f6-SQ.png` (ID buried, 6 chars)
- **After**: `d4e5f6a7-WP-C3-SQ.png` (ID first, 8 chars)

This enables users to easily copy the ID when uploading to Meta.

### 2. Configuration Updates
**File**: `/viraltracker/core/config.py`

Added:
```python
META_GRAPH_API_TOKEN: str = os.getenv('META_GRAPH_API_TOKEN', '')
META_AD_ACCOUNT_ID: str = os.getenv('META_AD_ACCOUNT_ID', '')
```

### 3. Database Migration
**File**: `/migrations/2025-12-18_meta_ads_performance.sql`

Created 4 tables:
- `brand_ad_accounts` - Links brands to Meta ad accounts (1:many ready)
- `meta_ads_performance` - Time-series performance snapshots
- `meta_ad_mapping` - Links generated_ads to Meta ads
- `meta_campaigns` - Campaign metadata cache

Key features:
- All tables include `meta_ad_account_id` for multi-account support
- `raw_actions` and `raw_costs` JSONB fields for extensibility
- Proper indexes on `brand_id`, `date`, `ad_name`
- `UNIQUE(meta_ad_id, date)` for upsert support

### 4. Pydantic Models
**File**: `/viraltracker/services/models.py`

Added 4 models:
- `MetaAdPerformance` - Performance snapshot with all metrics
- `MetaAdMapping` - Generated ad to Meta ad link
- `MetaCampaign` - Campaign metadata
- `BrandAdAccount` - Brand to account link

### 5. MetaAdsService
**File**: `/viraltracker/services/meta_ads_service.py`

Created service with:
- Rate limiting (100 req/min, configurable)
- Exponential backoff on rate limit errors
- Lazy SDK loading (avoids import errors if SDK not installed)
- Key methods:
  - `get_ad_insights()` - Fetch performance data with date range
  - `normalize_metrics()` - Parse arrays to flat dict
  - `sync_performance_to_db()` - Save to database
  - `find_matching_generated_ad_id()` - Extract 8-char ID from ad name
  - `auto_match_ads()` - Suggest matches for linking
  - `create_ad_mapping()` - Create link between ads

### 6. Service Exports
**File**: `/viraltracker/services/__init__.py`

Added exports for:
- `MetaAdsService`
- `MetaAdPerformance`
- `MetaAdMapping`
- `MetaCampaign`
- `BrandAdAccount`

---

## Files Modified/Created

| File | Action | Description |
|------|--------|-------------|
| `/viraltracker/services/ad_creation_service.py` | Modified | ID-first filename format |
| `/viraltracker/core/config.py` | Modified | Added META_* env vars |
| `/migrations/2025-12-18_meta_ads_performance.sql` | Created | Database tables |
| `/viraltracker/services/models.py` | Modified | Added 4 Pydantic models |
| `/viraltracker/services/meta_ads_service.py` | Created | Meta Ads API service |
| `/viraltracker/services/__init__.py` | Modified | Added exports |

---

## Environment Variables Required

```bash
META_GRAPH_API_TOKEN=your_system_user_token
META_AD_ACCOUNT_ID=act_123456789  # Include "act_" prefix
```

---

## Dependencies Required

```
facebook-business>=19.0.0
```

Install with: `pip install facebook-business`

---

## Next Steps (Phase 2)

1. Test `get_ad_insights()` with real API call
2. Verify rate limiting works correctly
3. Test `normalize_metrics()` with actual Meta response data
4. Test database upsert logic

---

## Syntax Verification

All modified files passed `python3 -m py_compile`:
- [x] ad_creation_service.py
- [x] config.py
- [x] models.py
- [x] meta_ads_service.py
- [x] __init__.py

---

## Update: Per-Brand Ad Accounts (Added)

After Phase 1 initial completion, updated `MetaAdsService` to support per-brand ad accounts:

### New Methods Added

1. **`get_ad_account_for_brand(brand_id)`** - Looks up ad account from `brand_ad_accounts` table
2. **`link_brand_to_ad_account(brand_id, meta_ad_account_id, ...)`** - Links brand to Meta account
3. **`_get_ad_account_id()`** - Helper to resolve account ID with fallback logic

### Updated Methods

- **`get_ad_insights()`** - Now accepts `brand_id` or `ad_account_id` parameters
- **`sync_performance_to_db()`** - Uses account ID from insight data
- **`create_ad_mapping()`** - Accepts explicit `meta_ad_account_id`

### Flow

1. User links brand to ad account (via `link_brand_to_ad_account()` or future UI)
2. When fetching insights, pass `brand_id` → service looks up account automatically
3. Config `META_AD_ACCOUNT_ID` is now just a fallback for testing
