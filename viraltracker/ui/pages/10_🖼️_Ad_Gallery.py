"""
Ad Gallery UI

Pinterest-style masonry gallery of all generated ads.
- Filter by product at the top
- Sort by newest first (default)
- Lazy loading after 40 ads
"""

import streamlit as st
import asyncio
from typing import Optional, List, Dict, Any
from datetime import datetime

# Page config (must be first)
st.set_page_config(
    page_title="Ad Gallery",
    page_icon="🖼️",
    layout="wide"
)

# Initialize session state
if 'gallery_product_filter' not in st.session_state:
    st.session_state.gallery_product_filter = "All Products"
if 'gallery_loaded_count' not in st.session_state:
    st.session_state.gallery_loaded_count = 40
if 'gallery_sort' not in st.session_state:
    st.session_state.gallery_sort = "newest"


def get_supabase_client():
    """Get Supabase client."""
    from viraltracker.core.database import get_supabase_client
    return get_supabase_client()


# ============================================================================
# Data Loading
# ============================================================================

@st.cache_data(ttl=60)
def get_products_for_filter() -> List[Dict[str, Any]]:
    """Get all products that have generated ads."""
    db = get_supabase_client()

    # Get products that have at least one ad run with generated ads
    result = db.table("products").select(
        "id, name"
    ).execute()

    return result.data


@st.cache_data(ttl=30)
def get_gallery_ads(
    product_id: Optional[str] = None,
    limit: int = 40,
    offset: int = 0,
    sort: str = "newest"
) -> tuple[List[Dict[str, Any]], int]:
    """
    Get ads for gallery display.

    Returns tuple of (ads_list, total_count)
    """
    db = get_supabase_client()

    # Build query for generated_ads with joins
    # We need: ad image, product name, created date, status
    query = db.table("generated_ads").select(
        "id, storage_path, final_status, created_at, prompt_index, hook_text, "
        "ad_run_id, ad_runs!inner(id, product_id, created_at, products!inner(id, name))"
    )

    # Filter by product if specified
    if product_id:
        query = query.eq("ad_runs.product_id", product_id)

    # Sort order
    if sort == "newest":
        query = query.order("created_at", desc=True)
    elif sort == "oldest":
        query = query.order("created_at", desc=False)

    # Get total count first (separate query)
    count_query = db.table("generated_ads").select(
        "id, ad_runs!inner(product_id)",
        count="exact"
    )
    if product_id:
        count_query = count_query.eq("ad_runs.product_id", product_id)

    count_result = count_query.execute()
    total_count = count_result.count if count_result.count else 0

    # Get paginated results
    result = query.range(offset, offset + limit - 1).execute()

    # Flatten the nested structure for easier use
    ads = []
    for row in result.data:
        ad_run = row.get("ad_runs", {})
        product = ad_run.get("products", {}) if ad_run else {}

        ads.append({
            "id": row["id"],
            "storage_path": row["storage_path"],
            "final_status": row.get("final_status", "pending"),
            "created_at": row["created_at"],
            "prompt_index": row.get("prompt_index"),
            "hook_text": row.get("hook_text"),
            "ad_run_id": row["ad_run_id"],
            "product_id": product.get("id"),
            "product_name": product.get("name", "Unknown")
        })

    return ads, total_count


def get_signed_url(storage_path: str) -> str:
    """Get signed URL for image display."""
    if not storage_path:
        return ""

    db = get_supabase_client()

    # Parse bucket and path
    parts = storage_path.split("/", 1)
    bucket = parts[0]
    path = parts[1] if len(parts) > 1 else storage_path

    try:
        result = db.storage.from_(bucket).create_signed_url(path, 3600)
        return result.get("signedURL", "")
    except Exception:
        return ""


# ============================================================================
# CSS Styles
# ============================================================================

MASONRY_CSS = """
<style>
/* Pinterest-style masonry grid */
.masonry-grid {
    column-count: 4;
    column-gap: 16px;
    padding: 16px;
}

@media (max-width: 1400px) {
    .masonry-grid {
        column-count: 3;
    }
}

@media (max-width: 1000px) {
    .masonry-grid {
        column-count: 2;
    }
}

@media (max-width: 600px) {
    .masonry-grid {
        column-count: 1;
    }
}

.masonry-item {
    break-inside: avoid;
    margin-bottom: 16px;
    background: #1e1e1e;
    border-radius: 16px;
    overflow: hidden;
    transition: transform 0.2s ease, box-shadow 0.2s ease;
}

.masonry-item:hover {
    transform: translateY(-4px);
    box-shadow: 0 12px 24px rgba(0,0,0,0.3);
}

.masonry-item img {
    width: 100%;
    height: auto;
    display: block;
}

.masonry-item-info {
    padding: 12px;
}

.masonry-item-product {
    font-weight: 600;
    font-size: 14px;
    color: #ffffff;
    margin-bottom: 4px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}

.masonry-item-date {
    font-size: 12px;
    color: #888;
}

.masonry-item-status {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 12px;
    font-size: 11px;
    font-weight: 500;
    margin-top: 6px;
}

.status-approved {
    background: #1a472a;
    color: #4ade80;
}

.status-rejected {
    background: #472a2a;
    color: #f87171;
}

.status-pending {
    background: #3d3d00;
    color: #facc15;
}

.status-flagged {
    background: #472a1a;
    color: #fb923c;
}

.masonry-item-hook {
    font-size: 12px;
    color: #aaa;
    margin-top: 8px;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
}

/* Filter bar styling */
.filter-bar {
    background: #1e1e1e;
    padding: 16px;
    border-radius: 12px;
    margin-bottom: 16px;
}

/* Load more button */
.load-more-container {
    text-align: center;
    padding: 24px;
}

/* Stats bar */
.stats-bar {
    display: flex;
    gap: 24px;
    padding: 12px 16px;
    background: #262626;
    border-radius: 8px;
    margin-bottom: 16px;
}

.stat-item {
    text-align: center;
}

.stat-value {
    font-size: 24px;
    font-weight: 700;
    color: #ffffff;
}

.stat-label {
    font-size: 12px;
    color: #888;
}
</style>
"""


# ============================================================================
# UI Components
# ============================================================================

def render_filter_bar(products: List[Dict[str, Any]]):
    """Render the filter bar at the top."""
    col1, col2, col3 = st.columns([2, 1, 1])

    with col1:
        # Product filter
        product_options = ["All Products"] + [p["name"] for p in products]
        selected = st.selectbox(
            "Filter by Product",
            product_options,
            index=product_options.index(st.session_state.gallery_product_filter)
                if st.session_state.gallery_product_filter in product_options else 0,
            key="product_filter_select",
            label_visibility="collapsed"
        )

        if selected != st.session_state.gallery_product_filter:
            st.session_state.gallery_product_filter = selected
            st.session_state.gallery_loaded_count = 40  # Reset on filter change
            st.rerun()

    with col2:
        # Sort order
        sort_options = {"Newest First": "newest", "Oldest First": "oldest"}
        sort_labels = list(sort_options.keys())
        current_sort_label = next(
            (k for k, v in sort_options.items() if v == st.session_state.gallery_sort),
            "Newest First"
        )

        selected_sort = st.selectbox(
            "Sort",
            sort_labels,
            index=sort_labels.index(current_sort_label),
            key="sort_select",
            label_visibility="collapsed"
        )

        new_sort = sort_options[selected_sort]
        if new_sort != st.session_state.gallery_sort:
            st.session_state.gallery_sort = new_sort
            st.session_state.gallery_loaded_count = 40
            st.rerun()

    with col3:
        # Refresh button
        if st.button("Refresh", use_container_width=True):
            st.cache_data.clear()
            st.rerun()


def render_stats_bar(total_count: int, loaded_count: int, product_filter: str):
    """Render statistics bar."""
    st.markdown(f"""
    <div class="stats-bar">
        <div class="stat-item">
            <div class="stat-value">{total_count:,}</div>
            <div class="stat-label">Total Ads</div>
        </div>
        <div class="stat-item">
            <div class="stat-value">{loaded_count:,}</div>
            <div class="stat-label">Showing</div>
        </div>
        <div class="stat-item">
            <div class="stat-value">{product_filter}</div>
            <div class="stat-label">Filter</div>
        </div>
    </div>
    """, unsafe_allow_html=True)


def render_masonry_gallery(ads: List[Dict[str, Any]]):
    """Render Pinterest-style masonry gallery."""
    if not ads:
        st.info("No ads found. Create some ads first!")
        return

    # Build HTML for masonry grid
    html_items = []

    for ad in ads:
        # Get signed URL for image
        image_url = get_signed_url(ad["storage_path"])
        if not image_url:
            continue

        # Format date
        try:
            created = datetime.fromisoformat(ad["created_at"].replace('Z', '+00:00'))
            date_str = created.strftime("%b %d, %Y")
        except Exception:
            date_str = "Unknown"

        # Status badge
        status = ad.get("final_status", "pending")
        status_class = f"status-{status}"
        status_display = status.title()

        # Hook text (truncated)
        hook_html = ""
        if ad.get("hook_text"):
            hook_text = ad["hook_text"][:100] + "..." if len(ad.get("hook_text", "")) > 100 else ad.get("hook_text", "")
            hook_html = f'<div class="masonry-item-hook">"{hook_text}"</div>'

        html_items.append(f"""
        <div class="masonry-item">
            <img src="{image_url}" alt="Ad for {ad['product_name']}" loading="lazy">
            <div class="masonry-item-info">
                <div class="masonry-item-product">{ad['product_name']}</div>
                <div class="masonry-item-date">{date_str}</div>
                <span class="masonry-item-status {status_class}">{status_display}</span>
                {hook_html}
            </div>
        </div>
        """)

    # Combine into masonry grid
    masonry_html = f"""
    <div class="masonry-grid">
        {''.join(html_items)}
    </div>
    """

    st.markdown(masonry_html, unsafe_allow_html=True)


def render_load_more_button(current_count: int, total_count: int):
    """Render load more button if there are more ads."""
    if current_count >= total_count:
        st.markdown("""
        <div class="load-more-container">
            <p style="color: #666;">You've seen all the ads!</p>
        </div>
        """, unsafe_allow_html=True)
        return

    remaining = total_count - current_count

    col1, col2, col3 = st.columns([1, 1, 1])
    with col2:
        if st.button(
            f"Load More ({remaining:,} remaining)",
            use_container_width=True,
            type="primary"
        ):
            st.session_state.gallery_loaded_count += 40
            st.rerun()


# ============================================================================
# Main
# ============================================================================

st.title("Ad Gallery")
st.markdown("**Browse all generated ads in a Pinterest-style layout**")

# Inject CSS
st.markdown(MASONRY_CSS, unsafe_allow_html=True)

# Load products for filter
products = get_products_for_filter()

# Render filter bar
render_filter_bar(products)

# Get selected product ID
product_id = None
if st.session_state.gallery_product_filter != "All Products":
    matching = [p for p in products if p["name"] == st.session_state.gallery_product_filter]
    if matching:
        product_id = matching[0]["id"]

# Load ads
ads, total_count = get_gallery_ads(
    product_id=product_id,
    limit=st.session_state.gallery_loaded_count,
    offset=0,
    sort=st.session_state.gallery_sort
)

# Render stats
render_stats_bar(total_count, len(ads), st.session_state.gallery_product_filter)

# Render gallery
render_masonry_gallery(ads)

# Load more button
render_load_more_button(len(ads), total_count)
