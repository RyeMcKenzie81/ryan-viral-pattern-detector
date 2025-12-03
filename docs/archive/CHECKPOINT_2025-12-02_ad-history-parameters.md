# CHECKPOINT: Ad History Parameters Display

**Date**: December 2, 2025
**Status**: ✅ Feature Complete
**Feature**: Store and display generation parameters in Ad History

---

## Overview

Added tracking and display of generation parameters for ad runs. When viewing an ad run in Ad History, users can now see what settings were used to generate those ads.

---

## Database Migration

```sql
ALTER TABLE ad_runs ADD COLUMN parameters JSONB;
```

---

## Parameters Tracked

| Parameter | Type | Description |
|-----------|------|-------------|
| `num_variations` | int | Number of ad variations generated (1-15) |
| `content_source` | string | "hooks" or "recreate_template" |
| `color_mode` | string | "original", "complementary", or "brand" |
| `image_selection_mode` | string | "auto" or "manual" |
| `selected_image_paths` | array | Manual image paths when mode is "manual" |
| `brand_colors` | object | Brand color data when color_mode is "brand" |

---

## Files Modified

### 1. `viraltracker/services/ad_creation_service.py`

Updated `create_ad_run()` to accept and store parameters:

```python
async def create_ad_run(
    self,
    product_id: UUID,
    reference_ad_storage_path: str,
    project_id: Optional[UUID] = None,
    parameters: Optional[Dict] = None  # NEW
) -> UUID:
```

### 2. `viraltracker/agent/agents/ad_creation_agent.py`

**Tool update** - `create_ad_run` tool accepts parameters:
```python
async def create_ad_run(
    ctx: RunContext[AgentDependencies],
    product_id: str,
    reference_ad_storage_path: str,
    project_id: Optional[str] = None,
    parameters: Optional[Dict] = None  # NEW
) -> str:
```

**Workflow update** - `complete_ad_workflow` builds and passes parameters:
```python
run_parameters = {
    "num_variations": num_variations,
    "content_source": content_source,
    "color_mode": color_mode,
    "image_selection_mode": image_selection_mode,
    "selected_image_paths": selected_image_paths,
    "brand_colors": brand_colors
}

ad_run_id_str = await create_ad_run(
    ctx=ctx,
    product_id=product_id,
    reference_ad_storage_path="temp",
    project_id=project_id,
    parameters=run_parameters  # NEW
)
```

### 3. `viraltracker/ui/pages/02_📊_Ad_History.py`

**Query update** - Fetches parameters column:
```python
query = db.table("ad_runs").select(
    "id, created_at, status, reference_ad_storage_path, product_id, parameters, "
    "products(id, name, brand_id, brands(id, name))"
)
```

**Display update** - Shows parameters in expanded run view:
```
Generation Parameters
─────────────────────────────────────────────────────
Variations: 5    Content: Hooks    Colors: Original    Images: Auto
```

---

## UI Display

When expanding an ad run in Ad History, parameters display in a 4-column layout:

| Column | Display |
|--------|---------|
| Variations | Number (e.g., "5") |
| Content | "Hooks" or "Recreate Template" |
| Colors | "Original", "Complementary", or "Brand" |
| Images | "Auto" or "Manual" |

Parameters only display if they exist (older runs without parameters show nothing).

---

## Data Flow

```
Ad Creator UI
    ↓
run_workflow() with parameters
    ↓
complete_ad_workflow() builds run_parameters dict
    ↓
create_ad_run() tool passes parameters
    ↓
ad_creation_service.create_ad_run() stores in DB
    ↓
Ad History queries parameters column
    ↓
Expanded view displays formatted parameters
```

---

## Notes

- Existing ad runs will not have parameters (backward compatible)
- Parameters are stored as JSONB for flexibility
- New runs automatically track all generation settings
- Scheduled jobs also benefit from this (same workflow)
