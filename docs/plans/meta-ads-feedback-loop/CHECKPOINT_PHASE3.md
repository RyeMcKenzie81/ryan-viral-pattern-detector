# Meta Ads Feedback Loop - Phase 3 Checkpoint

**Date**: 2025-12-18
**Status**: Complete
**Phase**: UI Performance Dashboard

---

## Summary

Phase 3 created the Streamlit UI for viewing and syncing Meta Ads performance data. The page includes brand selection, date range filtering, sync functionality, metric cards, and tabbed views for all ads vs linked ads.

---

## Files Created/Modified

| File | Action | Description |
|------|--------|-------------|
| `/viraltracker/ui/pages/30_📈_Ad_Performance.py` | Created | Main performance dashboard page |
| `/requirements.txt` | Modified | Added `facebook-business>=24.0.0` |

---

## UI Features Implemented

### 1. Brand Selector
- Uses shared `render_brand_selector()` from `viraltracker/ui/utils.py`
- Persists selection across pages via session state

### 2. Ad Account Connection
- Checks `brand_ad_accounts` table for linked Meta account
- Shows setup instructions if not connected
- Displays account name/ID when connected

### 3. Date Range Picker
- Default: Last 30 days
- Two date inputs (From/To)
- Filters performance data by date range

### 4. Sync Section
- Expandable "Sync from Meta" section
- Separate date range for sync operation
- "🔄 Sync Ads" button triggers API call
- Progress spinner during sync
- Success/error feedback

### 5. Metric Cards (2 rows x 4 cards)

| Row 1 | Row 2 |
|-------|-------|
| Total Spend | Impressions |
| ROAS | Link Clicks |
| Link CTR | Add to Carts |
| CPC | Purchases |

### 6. Tabbed Views

**Tab 1: All Meta Ads**
- Shows all ads from the Meta account
- Sortable table with columns:
  - Date, Ad Name, Spend, Impressions, Clicks
  - CTR, CPC, ATC, Purchases, ROAS, Meta Ad ID

**Tab 2: Linked Ads**
- Shows only ads linked to ViralTracker generated ads
- Same table format
- Instructions for linking when empty

### 7. Data Footer
- Shows "Data last synced" timestamp

---

## Page Structure

```
📈 Ad Performance
├── Brand Selector (shared component)
├── Ad Account Status (connected/setup needed)
├── Date Range Picker (From/To)
├── Sync Section (expandable)
│   ├── Sync Date Range
│   └── Sync Button
├── Metric Cards (8 metrics in 2 rows)
├── Tabs
│   ├── All Meta Ads (table)
│   └── Linked Ads (table + instructions)
└── Footer (last sync time)
```

---

## Helper Functions

| Function | Purpose |
|----------|---------|
| `get_brand_ad_account()` | Fetch linked Meta account for brand |
| `get_performance_data()` | Query `meta_ads_performance` table |
| `get_linked_ads()` | Query `meta_ad_mapping` table |
| `aggregate_metrics()` | Calculate totals and averages |
| `sync_ads_from_meta()` | Call MetaAdsService to sync data |

---

## Dependencies

```
facebook-business>=24.0.0  # Added to requirements.txt
```

---

## Setup Required

Before using the page:

1. **Link brand to ad account** (SQL):
   ```sql
   INSERT INTO brand_ad_accounts (brand_id, meta_ad_account_id, account_name, is_primary)
   VALUES ('brand-uuid', 'act_123456789', 'My Account', true);
   ```

2. **Set environment variable**:
   ```bash
   META_GRAPH_API_TOKEN=your_token_here
   ```

---

## Next Steps (Phase 4)

1. **Auto-match algorithm**: Scan ad names for 8-char ID patterns
2. **Match suggestion UI**: Table showing suggested matches with confirm/reject
3. **Manual linking modal**: Searchable list of generated ads
4. Store confirmed links in `meta_ad_mapping` table
5. Show link status indicator on all ads

---

## Syntax Verified

```bash
python3 -m py_compile viraltracker/ui/pages/30_📈_Ad_Performance.py
# ✓ No errors
```
