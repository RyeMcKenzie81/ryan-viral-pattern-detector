# Shared Brand Selector Plan

**Date:** 2025-12-17
**Goal:** Keep the same brand selected when switching between tools/pages

## Problem

Currently 14 pages have independent brand selection:
- Each page initializes its own session state key
- 4 different keys used: `selected_brand_id`, `research_brand_id`, `executor_selected_brand`, `pipeline_brand_id`
- Switching pages loses the brand selection

## Solution: Shared Utility Function (Option 2)

Create `viraltracker/ui/utils.py` with a `render_brand_selector()` function that:
1. Uses a single session state key (`selected_brand_id`) across all pages
2. Restores the previously selected brand when navigating between pages
3. Provides consistent UI and behavior

## Implementation

### Step 1: Create `viraltracker/ui/utils.py`

```python
import streamlit as st
from typing import Optional
from uuid import UUID

def get_brands():
    """Fetch brands from database."""
    from viraltracker.core.database import get_supabase_client
    db = get_supabase_client()
    result = db.table("brands").select("id, name").order("name").execute()
    return result.data or []

def render_brand_selector(
    key: str = "brand_selector",
    show_label: bool = True,
    label: str = "Select Brand"
) -> Optional[str]:
    """
    Render a brand selector that persists across pages.

    Uses st.session_state.selected_brand_id to maintain selection
    when switching between pages.

    Args:
        key: Unique key for the selectbox widget
        show_label: Whether to show the label
        label: Label text for the selectbox

    Returns:
        Selected brand ID as string, or None if no brands
    """
    brands = get_brands()

    if not brands:
        st.warning("No brands found. Create a brand first.")
        return None

    # Build options
    brand_options = {b['name']: b['id'] for b in brands}
    brand_names = list(brand_options.keys())

    # Find current index based on session state
    current_index = 0
    if st.session_state.get('selected_brand_id'):
        current_id = st.session_state.selected_brand_id
        for i, name in enumerate(brand_names):
            if brand_options[name] == current_id:
                current_index = i
                break

    # Render selector
    selected_name = st.selectbox(
        label if show_label else "",
        options=brand_names,
        index=current_index,
        key=key,
        label_visibility="visible" if show_label else "collapsed"
    )

    # Update session state
    selected_id = brand_options[selected_name]
    st.session_state.selected_brand_id = selected_id

    return selected_id
```

### Step 2: Update Pages

Replace brand selection code in each page with:

```python
from viraltracker.ui.utils import render_brand_selector

# In the page body:
selected_brand_id = render_brand_selector()
if not selected_brand_id:
    st.stop()
```

### Pages to Update (14 total)

| Page | Current Key | File |
|------|-------------|------|
| Brand Manager | `selected_brand_id` | `02_🏢_Brand_Manager.py` |
| Personas | `selected_brand_id` | `03_👤_Personas.py` |
| URL Mapping | `selected_brand_id` | `04_🔗_URL_Mapping.py` |
| Brand Research | `research_brand_id` | `05_🔬_Brand_Research.py` |
| Competitors | `selected_brand_id` | `11_🎯_Competitors.py` |
| Competitor Research | `research_brand_id` | `12_🔍_Competitor_Research.py` |
| Ad Creator | (none) | `21_🎨_Ad_Creator.py` |
| Ad History | (varies) | `22_📊_Ad_History.py` |
| Ad Scheduler | (varies) | `24_📅_Ad_Scheduler.py` |
| Ad Planning | `selected_brand_id` | `25_📋_Ad_Planning.py` |
| Plan List | (varies) | `26_📊_Plan_List.py` |
| Plan Executor | `executor_selected_brand` | `27_🎯_Plan_Executor.py` |
| Content Pipeline | `pipeline_brand_id` | `41_📝_Content_Pipeline.py` |
| Public Gallery | (varies) | `66_🌐_Public_Gallery.py` |

## Benefits

1. **Persistence**: Brand selection survives page navigation
2. **DRY**: Single source of truth for brand selection logic
3. **Consistency**: Same UI/behavior across all pages
4. **Maintainability**: Add features (search, favorites) in one place

## Testing

1. Select a brand on Brand Manager
2. Navigate to Competitor Research - should show same brand
3. Navigate to Ad Creator - should show same brand
4. Refresh browser - brand resets (expected, session-based)
