# Meta Ads Integration - Phase 3.5 Checkpoint

**Date**: 2025-12-18
**Status**: Complete

## Summary

Enhanced the Ad Performance dashboard to match Facebook Ads Manager layout with Campaign/Ad Set/Ads hierarchy, CPM metric, and ad status indicators.

## Completed Features

### 1. CPM Metric
- Added CPM (Cost Per 1000 Impressions) to metric cards
- Added CPM column to ads table
- Formula: `(spend / impressions) * 1000`
- Calculated in normalize_metrics if not returned by API

### 2. Campaign/Ad Set/Ads Hierarchy Tabs
- **Campaigns Tab**: Aggregated metrics by campaign
  - Shows spend, impressions, CPM, clicks, CTR, ATC, purchases, ROAS
  - Displays count of ad sets and ads per campaign
- **Ad Sets Tab**: Aggregated metrics by ad set
  - Shows parent campaign name
  - Displays count of ads per ad set
- **Ads Tab**: Individual ad-level data (existing view)
- **Linked Tab**: Ads linked to ViralTracker generated ads

### 3. Ad Status Indicator
- Visual emoji indicators for ad status:
  - 🟢 ACTIVE
  - ⚪ PAUSED
  - 🔴 DELETED
  - 📦 ARCHIVED
  - 🟡 PENDING_REVIEW
  - ❌ DISAPPROVED
- Status column added to ads table

### 4. Revenue Metric
- Added total revenue display to metric cards

## Database Changes

**Migration**: `migrations/2025-12-18_meta_ads_phase3_5.sql`

```sql
-- New columns on meta_ads_performance
ALTER TABLE meta_ads_performance ADD COLUMN IF NOT EXISTS
    cpm NUMERIC(10, 4);
ALTER TABLE meta_ads_performance ADD COLUMN IF NOT EXISTS
    ad_status TEXT;
ALTER TABLE meta_ads_performance ADD COLUMN IF NOT EXISTS
    meta_adset_id TEXT;
ALTER TABLE meta_ads_performance ADD COLUMN IF NOT EXISTS
    adset_name TEXT;

-- New table for ad set caching
CREATE TABLE IF NOT EXISTS meta_adsets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    meta_ad_account_id TEXT NOT NULL,
    meta_adset_id TEXT NOT NULL,
    meta_campaign_id TEXT NOT NULL,
    name TEXT,
    status TEXT,
    optimization_goal TEXT,
    billing_event TEXT,
    daily_budget NUMERIC(12, 2),
    lifetime_budget NUMERIC(12, 2),
    brand_id UUID REFERENCES brands(id) ON DELETE SET NULL,
    synced_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(meta_ad_account_id, meta_adset_id)
);
```

**User Action Required**: Run this migration in Supabase SQL Editor before syncing ads.

## Model Changes

### MetaAdPerformance (updated)
```python
meta_adset_id: Optional[str] = Field(None, description="Meta ad set ID")
adset_name: Optional[str] = Field(None, description="Ad set name")
ad_status: Optional[str] = Field(None, description="Ad status: ACTIVE, PAUSED, DELETED, etc.")
cpm: Optional[float] = Field(None, ge=0, description="Cost per 1000 impressions")
```

### MetaAdSet (new)
```python
class MetaAdSet(BaseModel):
    """Cached ad set metadata from Meta Ads API."""
    id: Optional[UUID]
    meta_ad_account_id: str
    meta_adset_id: str
    meta_campaign_id: str
    name: Optional[str]
    status: Optional[str]
    optimization_goal: Optional[str]
    billing_event: Optional[str]
    daily_budget: Optional[float]
    lifetime_budget: Optional[float]
    brand_id: Optional[UUID]
    synced_at: Optional[datetime]
```

## Service Changes

### MetaAdsService
- Added to INSIGHT_FIELDS: `adset_id`, `adset_name`, `cpm`
- Updated `normalize_metrics()`:
  - Includes adset_id and adset_name in output
  - Calculates CPM if not returned by API
- Updated `sync_performance_to_db()`:
  - Saves meta_adset_id and adset_name to database

## UI Changes

### 30_📈_Ad_Performance.py

**New Functions**:
- `get_status_emoji(status)` - Maps status to emoji
- `aggregate_by_campaign(data)` - Aggregates metrics by campaign
- `aggregate_by_adset(data)` - Aggregates metrics by ad set
- `render_campaigns_table(data)` - Renders campaign summary table
- `render_adsets_table(data)` - Renders ad set summary table

**Updated Functions**:
- `render_metric_cards()` - Now 5 columns with CPM and Revenue
- `render_ads_table()` - Now includes Status and CPM columns
- `aggregate_metrics()` - Now includes avg_cpm, campaign_count, adset_count

## Known Limitations

1. **Ad Status Not Live**: The `ad_status` field is not currently fetched from Meta API because it requires a separate API call to the Ad object (not available in insights endpoint). Status will show "-" until this is implemented.

2. **Campaign/Ad Set Names**: Names are from the insights data, which is accurate but reflects the name at time of the performance data, not necessarily current name.

## Files Changed

- `viraltracker/services/models.py` - Added MetaAdSet, updated MetaAdPerformance
- `viraltracker/services/__init__.py` - Added MetaAdSet to exports
- `viraltracker/services/meta_ads_service.py` - Updated INSIGHT_FIELDS and normalize_metrics
- `viraltracker/ui/pages/30_📈_Ad_Performance.py` - Major UI enhancements
- `migrations/2025-12-18_meta_ads_phase3_5.sql` - Database migration

## Next Steps (Phase 4)

1. **Ad Mapping & Suggestions**
   - Auto-match algorithm to scan ad names for 8-char ID patterns
   - Match suggestion UI with confirm/reject
   - Manual linking modal

2. **Ad Status Fetching**
   - Add separate API call to fetch ad metadata (including status)
   - Cache in meta_adsets table
   - Update status during sync

3. **Enhanced Hierarchy Views**
   - Click-to-drill-down from campaign to ad sets to ads
   - Breadcrumb navigation
