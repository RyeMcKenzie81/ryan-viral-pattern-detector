"""
Public Product Gallery

Client-facing gallery for a single product - no authentication required.
Access via: /Public_Gallery?product=product-slug

Shows only approved ads for the specified product.
"""

import streamlit as st
import streamlit.components.v1 as components
from typing import Optional, List, Dict, Any
from datetime import datetime

# Page config (must be first)
st.set_page_config(
    page_title="Product Gallery",
    page_icon="🖼️",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# NO AUTHENTICATION - This is a public page
# Hide the sidebar completely for cleaner client view
st.markdown("""
<style>
    [data-testid="stSidebar"] {display: none;}
    [data-testid="stSidebarNav"] {display: none;}
    .stDeployButton {display: none;}
    #MainMenu {display: none;}
    header {display: none;}
    footer {display: none;}
</style>
""", unsafe_allow_html=True)

# Initialize session state
if 'public_gallery_loaded_count' not in st.session_state:
    st.session_state.public_gallery_loaded_count = 40
if 'public_gallery_sort' not in st.session_state:
    st.session_state.public_gallery_sort = "newest"


def get_supabase_client():
    """Get Supabase client."""
    from viraltracker.core.database import get_supabase_client
    return get_supabase_client()


# ============================================================================
# Data Loading
# ============================================================================

@st.cache_data(ttl=60)
def get_product_by_slug(slug: str) -> Optional[Dict[str, Any]]:
    """Get product details by slug."""
    if not slug:
        return None

    db = get_supabase_client()

    try:
        result = db.table("products").select(
            "id, name, slug, description, brand_id, brands(name, brand_colors)"
        ).eq("slug", slug).execute()

        if result.data:
            return result.data[0]
        return None
    except Exception:
        return None


@st.cache_data(ttl=30)
def get_approved_ads(
    product_id: str,
    limit: int = 40,
    offset: int = 0,
    sort: str = "newest"
) -> tuple[List[Dict[str, Any]], int]:
    """
    Get APPROVED ads only for a specific product.

    Returns tuple of (ads_list, total_count)
    """
    db = get_supabase_client()

    # Build query - ONLY approved ads
    query = db.table("generated_ads").select(
        "id, storage_path, created_at, hook_text, "
        "ad_runs!inner(id, product_id)"
    ).eq("ad_runs.product_id", product_id
    ).eq("final_status", "approved")  # Only approved

    # Sort order
    if sort == "newest":
        query = query.order("created_at", desc=True)
    elif sort == "oldest":
        query = query.order("created_at", desc=False)

    # Get total count first
    count_query = db.table("generated_ads").select(
        "id, ad_runs!inner(product_id)",
        count="exact"
    ).eq("ad_runs.product_id", product_id
    ).eq("final_status", "approved")

    count_result = count_query.execute()
    total_count = count_result.count if count_result.count else 0

    # Get paginated results
    result = query.range(offset, offset + limit - 1).execute()

    # Flatten structure
    ads = []
    for row in result.data:
        ads.append({
            "id": row["id"],
            "storage_path": row["storage_path"],
            "created_at": row["created_at"],
            "hook_text": row.get("hook_text"),
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
# CSS Styles (matching internal gallery)
# ============================================================================

STATS_CSS = """
<style>
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
.load-more-container {
    text-align: center;
    padding: 24px;
}
</style>
"""


# ============================================================================
# UI Components
# ============================================================================

def render_filter_bar(product_name: str):
    """Render the filter bar at the top (no product selector, just sort)."""
    col1, col2, col3 = st.columns([2, 1, 1])

    with col1:
        # Just show the product name instead of a selector
        st.markdown(f"**{product_name}**")

    with col2:
        # Sort order
        sort_options = {"Newest First": "newest", "Oldest First": "oldest"}
        sort_labels = list(sort_options.keys())
        current_sort_label = next(
            (k for k, v in sort_options.items() if v == st.session_state.public_gallery_sort),
            "Newest First"
        )

        selected_sort = st.selectbox(
            "Sort",
            sort_labels,
            index=sort_labels.index(current_sort_label),
            key="public_sort_select",
            label_visibility="collapsed"
        )

        new_sort = sort_options[selected_sort]
        if new_sort != st.session_state.public_gallery_sort:
            st.session_state.public_gallery_sort = new_sort
            st.session_state.public_gallery_loaded_count = 40
            st.rerun()

    with col3:
        # Refresh button
        if st.button("Refresh", use_container_width=True):
            st.cache_data.clear()
            st.rerun()


def render_stats_bar(total_count: int, loaded_count: int, product_name: str):
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
            <div class="stat-value">{product_name}</div>
            <div class="stat-label">Product</div>
        </div>
    </div>
    """, unsafe_allow_html=True)


def render_masonry_gallery(ads: List[Dict[str, Any]], product_name: str):
    """Render Pinterest-style masonry gallery using components.html for proper rendering."""
    if not ads:
        st.info("No approved ads yet. Check back soon!")
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

        # Hook text (truncated) - escape quotes for HTML
        hook_html = ""
        if ad.get("hook_text"):
            hook_text = ad["hook_text"][:100] + "..." if len(ad.get("hook_text", "")) > 100 else ad.get("hook_text", "")
            hook_text = hook_text.replace('"', '&quot;').replace("'", "&#39;")
            hook_html = f'<div class="gallery-item-hook">"{hook_text}"</div>'

        # Escape product name for HTML
        product_name_escaped = product_name.replace('"', '&quot;').replace("'", "&#39;")

        html_items.append(f"""
        <div class="gallery-item">
            <img src="{image_url}" alt="Ad for {product_name_escaped}" loading="lazy">
            <div class="gallery-item-info">
                <div class="gallery-item-product">{product_name_escaped}</div>
                <div class="gallery-item-date">{date_str}</div>
                <span class="gallery-item-status status-approved">Approved</span>
                {hook_html}
            </div>
        </div>
        """)

    # Calculate height based on number of items (rough estimate)
    num_items = len(html_items)
    estimated_rows = (num_items + 3) // 4
    estimated_height = max(600, min(3000, estimated_rows * 380))

    # Complete HTML with embedded CSS - using CSS Grid for row-based layout
    full_html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            * {{
                margin: 0;
                padding: 0;
                box-sizing: border-box;
            }}
            body {{
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                background: transparent;
            }}
            .gallery-grid {{
                display: grid;
                grid-template-columns: repeat(4, 1fr);
                gap: 16px;
                padding: 8px;
            }}
            @media (max-width: 1400px) {{
                .gallery-grid {{ grid-template-columns: repeat(3, 1fr); }}
            }}
            @media (max-width: 1000px) {{
                .gallery-grid {{ grid-template-columns: repeat(2, 1fr); }}
            }}
            @media (max-width: 600px) {{
                .gallery-grid {{ grid-template-columns: 1fr; }}
            }}
            .gallery-item {{
                background: #1e1e1e;
                border-radius: 16px;
                overflow: hidden;
                transition: transform 0.2s ease, box-shadow 0.2s ease;
            }}
            .gallery-item:hover {{
                transform: translateY(-4px);
                box-shadow: 0 12px 24px rgba(0,0,0,0.3);
            }}
            .gallery-item img {{
                width: 100%;
                height: auto;
                display: block;
            }}
            .gallery-item-info {{
                padding: 12px;
            }}
            .gallery-item-product {{
                font-weight: 600;
                font-size: 14px;
                color: #ffffff;
                margin-bottom: 4px;
                white-space: nowrap;
                overflow: hidden;
                text-overflow: ellipsis;
            }}
            .gallery-item-date {{
                font-size: 12px;
                color: #888;
            }}
            .gallery-item-status {{
                display: inline-block;
                padding: 2px 8px;
                border-radius: 12px;
                font-size: 11px;
                font-weight: 500;
                margin-top: 6px;
            }}
            .status-approved {{
                background: #1a472a;
                color: #4ade80;
            }}
            .gallery-item-hook {{
                font-size: 12px;
                color: #aaa;
                margin-top: 8px;
                display: -webkit-box;
                -webkit-line-clamp: 2;
                -webkit-box-orient: vertical;
                overflow: hidden;
            }}
        </style>
    </head>
    <body>
        <div class="gallery-grid">
            {''.join(html_items)}
        </div>
    </body>
    </html>
    """

    # Render using components.html for proper iframe rendering
    components.html(full_html, height=estimated_height, scrolling=True)


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
            st.session_state.public_gallery_loaded_count += 40
            st.rerun()


# ============================================================================
# Main
# ============================================================================

# Get product slug from query params
query_params = st.query_params
product_slug = query_params.get("product", None)

if not product_slug:
    # No product specified - show error
    st.error("Missing product parameter. Please provide a product slug in the URL: `?product=your-product-slug`")
    st.stop()

# Load product
product = get_product_by_slug(product_slug)

if not product:
    # Product not found
    st.error(f"Product not found: `{product_slug}`")
    st.stop()

# Get brand info for display
brand_info = product.get("brands", {}) or {}
brand_name = brand_info.get("name", "")

# Title
st.title(f"{product['name']} Gallery")
if brand_name:
    st.markdown(f"**{brand_name}**")

# Inject CSS
st.markdown(STATS_CSS, unsafe_allow_html=True)

# Render filter bar (no product selector, just sort + refresh)
render_filter_bar(product["name"])

# Load ads
ads, total_count = get_approved_ads(
    product_id=product["id"],
    limit=st.session_state.public_gallery_loaded_count,
    offset=0,
    sort=st.session_state.public_gallery_sort
)

# Render stats
render_stats_bar(total_count, len(ads), product["name"])

# Render gallery
render_masonry_gallery(ads, product["name"])

# Load more button
render_load_more_button(len(ads), total_count)
