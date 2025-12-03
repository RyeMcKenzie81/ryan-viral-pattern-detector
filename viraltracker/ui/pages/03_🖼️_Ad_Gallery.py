"""
Ad Gallery UI

Pinterest-style masonry gallery of all generated ads.
- Filter by product at the top
- Sort by newest first (default)
- Lazy loading after 40 ads
- Create size variants of approved ads
"""

import streamlit as st
import streamlit.components.v1 as components
import asyncio
import base64
from typing import Optional, List, Dict, Any
from datetime import datetime

# Meta ad size definitions
META_AD_SIZES = {
    "1:1": {"dimensions": "1080x1080", "name": "Square", "use_case": "Feed posts"},
    "4:5": {"dimensions": "1080x1350", "name": "Portrait", "use_case": "Feed (optimal)"},
    "9:16": {"dimensions": "1080x1920", "name": "Story", "use_case": "Stories, Reels"},
    "16:9": {"dimensions": "1920x1080", "name": "Landscape", "use_case": "Video, links"},
}

# Page config (must be first)
st.set_page_config(
    page_title="Ad Gallery",
    page_icon="🖼️",
    layout="wide"
)

# Authentication
from viraltracker.ui.auth import require_auth
require_auth()

# Initialize session state
if 'gallery_product_filter' not in st.session_state:
    st.session_state.gallery_product_filter = "All Products"
if 'gallery_loaded_count' not in st.session_state:
    st.session_state.gallery_loaded_count = 40
if 'gallery_sort' not in st.session_state:
    st.session_state.gallery_sort = "newest"

# Size variant state
if 'gallery_show_variant_panel' not in st.session_state:
    st.session_state.gallery_show_variant_panel = False
if 'gallery_selected_ad_id' not in st.session_state:
    st.session_state.gallery_selected_ad_id = None
if 'gallery_variant_generating' not in st.session_state:
    st.session_state.gallery_variant_generating = False
if 'gallery_variant_results' not in st.session_state:
    st.session_state.gallery_variant_results = None


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
    # We need: ad image, product name, created date, status, variant info
    query = db.table("generated_ads").select(
        "id, storage_path, final_status, created_at, prompt_index, hook_text, "
        "parent_ad_id, variant_size, "
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
            "product_name": product.get("name", "Unknown"),
            "variant_size": row.get("variant_size"),
            "parent_ad_id": row.get("parent_ad_id")
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


@st.cache_data(ttl=60)
def get_approved_ads_for_variant() -> List[Dict[str, Any]]:
    """Get all approved ads for the variant creator dropdown."""
    db = get_supabase_client()

    result = db.table("generated_ads").select(
        "id, storage_path, hook_text, created_at, prompt_index, "
        "ad_run_id, ad_runs!inner(id, product_id, products!inner(id, name))"
    ).eq("final_status", "approved").order("created_at", desc=True).limit(100).execute()

    ads = []
    for row in result.data:
        ad_run = row.get("ad_runs", {})
        product = ad_run.get("products", {}) if ad_run else {}

        # Create display label
        created = datetime.fromisoformat(row["created_at"].replace('Z', '+00:00'))
        date_str = created.strftime("%b %d")
        hook_preview = row.get("hook_text", "")[:40] + "..." if len(row.get("hook_text", "") or "") > 40 else row.get("hook_text", "")

        ads.append({
            "id": row["id"],
            "storage_path": row["storage_path"],
            "product_name": product.get("name", "Unknown"),
            "display": f"{product.get('name', 'Unknown')} - V{row.get('prompt_index', '?')} - {date_str} - {hook_preview}"
        })

    return ads


def get_existing_variants_gallery(ad_id: str) -> list:
    """Get list of variant sizes that already exist for an ad."""
    try:
        db = get_supabase_client()
        result = db.table("generated_ads").select(
            "variant_size"
        ).eq("parent_ad_id", ad_id).execute()
        return [r["variant_size"] for r in result.data if r.get("variant_size")]
    except Exception as e:
        return []


def get_ad_image_base64_gallery(storage_path: str) -> str:
    """Download ad image and return as base64 string."""
    if not storage_path:
        return ""
    try:
        db = get_supabase_client()
        parts = storage_path.split('/', 1)
        if len(parts) == 2:
            bucket, path = parts
        else:
            bucket = "generated-ads"
            path = storage_path

        image_data = db.storage.from_(bucket).download(path)
        return base64.b64encode(image_data).decode('utf-8')
    except Exception as e:
        st.error(f"Failed to download image: {e}")
        return ""


async def create_size_variants_gallery_async(ad_id: str, target_sizes: list, source_image_base64: str) -> dict:
    """Create size variants for gallery."""
    from viraltracker.services.ad_creation_service import AdCreationService
    import time

    service = AdCreationService()
    results = {"successful": [], "failed": []}

    # Get source ad data
    ad_data = await service.get_ad_for_variant(ad_id)
    if not ad_data:
        return {"successful": [], "failed": target_sizes, "error": "Source ad not found"}

    ad_run_id = ad_data.get("ad_run_id")
    prompt_spec = ad_data.get("prompt_spec", {})
    hook_text = ad_data.get("hook_text", "")
    hook_id = ad_data.get("hook_id")

    for size in target_sizes:
        try:
            size_info = META_AD_SIZES.get(size)
            if not size_info:
                results["failed"].append({"size": size, "error": "Unknown size"})
                continue

            # Update prompt spec for new dimensions
            new_prompt_spec = prompt_spec.copy() if prompt_spec else {}
            new_prompt_spec["canvas"] = {
                "dimensions": size_info["dimensions"],
                "aspect_ratio": size
            }

            # Build the generation prompt
            prompt_text = f"""Recreate this EXACT ad at {size_info['dimensions']} ({size} aspect ratio).

CRITICAL INSTRUCTIONS:
- Keep ALL text exactly the same (same words, same fonts)
- Keep ALL colors exactly the same
- Keep the product image(s) exactly the same
- Keep the overall visual style and layout matching the original
- Only reposition/resize elements as needed to fit the new {size} canvas
- The hook text is: "{hook_text}"

This is a SIZE VARIANT - the content should be IDENTICAL, only the canvas dimensions change."""

            # Generate with Gemini using reference image
            start_time = time.time()

            from google import genai
            from google.genai import types
            import os

            client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

            # Create image part from base64
            image_bytes = base64.b64decode(source_image_base64)
            reference_image = types.Part.from_bytes(data=image_bytes, mime_type="image/png")

            response = client.models.generate_content(
                model="gemini-2.0-flash-exp",
                contents=[reference_image, prompt_text],
                config=types.GenerateContentConfig(
                    response_modalities=["IMAGE", "TEXT"],
                    temperature=0.1,
                )
            )

            generation_time_ms = int((time.time() - start_time) * 1000)

            # Extract generated image
            generated_image_base64 = None
            for part in response.candidates[0].content.parts:
                if hasattr(part, 'inline_data') and part.inline_data:
                    generated_image_base64 = base64.b64encode(part.inline_data.data).decode('utf-8')
                    break

            if not generated_image_base64:
                results["failed"].append({"size": size, "error": "No image generated"})
                continue

            # Upload to storage
            import uuid
            storage_path = f"{ad_run_id}/variant_{size.replace(':', 'x')}_{uuid.uuid4().hex[:8]}.png"

            image_data = base64.b64decode(generated_image_base64)
            db = get_supabase_client()
            db.storage.from_("generated-ads").upload(
                storage_path,
                image_data,
                {"content-type": "image/png"}
            )

            full_storage_path = f"generated-ads/{storage_path}"

            # Save to database
            variant_id = await service.save_size_variant(
                parent_ad_id=ad_id,
                ad_run_id=ad_run_id,
                variant_size=size,
                storage_path=full_storage_path,
                prompt_text=prompt_text,
                prompt_spec=new_prompt_spec,
                hook_text=hook_text,
                hook_id=hook_id,
                model_used="gemini-2.0-flash-exp",
                generation_time_ms=generation_time_ms
            )

            results["successful"].append({
                "size": size,
                "variant_id": str(variant_id),
                "storage_path": full_storage_path
            })

        except Exception as e:
            results["failed"].append({"size": size, "error": str(e)})

    return results


# ============================================================================
# CSS Styles (for non-gallery elements)
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
    """Render Pinterest-style masonry gallery using components.html for proper rendering."""
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

        # Variant badge
        variant_html = ""
        variant_size = ad.get("variant_size")
        if variant_size:
            variant_html = f'<span class="gallery-item-variant">📐 {variant_size}</span>'

        # Hook text (truncated) - escape quotes for HTML
        hook_html = ""
        if ad.get("hook_text"):
            hook_text = ad["hook_text"][:100] + "..." if len(ad.get("hook_text", "")) > 100 else ad.get("hook_text", "")
            hook_text = hook_text.replace('"', '&quot;').replace("'", "&#39;")
            hook_html = f'<div class="gallery-item-hook">"{hook_text}"</div>'

        # Escape product name for HTML
        product_name = ad['product_name'].replace('"', '&quot;').replace("'", "&#39;")

        html_items.append(f"""
        <div class="gallery-item">
            <img src="{image_url}" alt="Ad for {product_name}" loading="lazy">
            <div class="gallery-item-info">
                <div class="gallery-item-product">{product_name}</div>
                <div class="gallery-item-date">{date_str}</div>
                <span class="gallery-item-status {status_class}">{status_display}</span>
                {variant_html}
                {hook_html}
            </div>
        </div>
        """)

    # Calculate height based on number of items (rough estimate)
    # Each item is roughly 300-400px, 4 columns, so rows = items/4, height = rows * 350
    num_items = len(html_items)
    estimated_rows = (num_items + 3) // 4  # Ceiling division
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
            .status-rejected {{
                background: #472a2a;
                color: #f87171;
            }}
            .status-pending {{
                background: #3d3d00;
                color: #facc15;
            }}
            .status-flagged {{
                background: #472a1a;
                color: #fb923c;
            }}
            .gallery-item-variant {{
                display: inline-block;
                padding: 2px 8px;
                border-radius: 12px;
                font-size: 11px;
                font-weight: 500;
                margin-top: 6px;
                margin-left: 4px;
                background: #2a3a4a;
                color: #60a5fa;
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
            st.session_state.gallery_loaded_count += 40
            st.rerun()


# ============================================================================
# Main
# ============================================================================

st.title("Ad Gallery")
st.markdown("**Browse all generated ads in a grid layout**")

# Inject CSS
st.markdown(STATS_CSS, unsafe_allow_html=True)

# Load products for filter
products = get_products_for_filter()

# Render filter bar
render_filter_bar(products)

# Size Variant Panel
col_variant_btn, col_spacer = st.columns([1, 3])
with col_variant_btn:
    if st.button("📐 Create Size Variants", use_container_width=True):
        st.session_state.gallery_show_variant_panel = not st.session_state.gallery_show_variant_panel
        st.session_state.gallery_variant_results = None
        st.rerun()

if st.session_state.gallery_show_variant_panel:
    with st.expander("Create Size Variants", expanded=True):
        st.markdown("Select an approved ad and choose target sizes to create variants.")

        # Get approved ads
        approved_ads = get_approved_ads_for_variant()

        if not approved_ads:
            st.warning("No approved ads found. Approve some ads first!")
        else:
            # Ad selector
            ad_options = {ad["id"]: ad["display"] for ad in approved_ads}
            ad_storage_paths = {ad["id"]: ad["storage_path"] for ad in approved_ads}

            selected_ad_id = st.selectbox(
                "Select Ad",
                options=list(ad_options.keys()),
                format_func=lambda x: ad_options[x],
                key="gallery_ad_selector"
            )

            if selected_ad_id:
                # Show preview
                col_preview, col_sizes = st.columns([1, 2])

                with col_preview:
                    st.markdown("**Preview:**")
                    preview_url = get_signed_url(ad_storage_paths.get(selected_ad_id, ""))
                    if preview_url:
                        st.image(preview_url, width=150)

                with col_sizes:
                    st.markdown("**Target Sizes:**")

                    # Get existing variants
                    existing_variants = get_existing_variants_gallery(selected_ad_id)

                    # Size checkboxes
                    selected_sizes = []
                    for size, info in META_AD_SIZES.items():
                        already_exists = size in existing_variants
                        label = f"{info['name']} ({size}) - {info['use_case']}"
                        if already_exists:
                            label += " ✓ exists"

                        is_selected = st.checkbox(
                            label,
                            value=False,
                            disabled=already_exists,
                            key=f"gallery_size_{size}"
                        )
                        if is_selected:
                            selected_sizes.append(size)

                # Results
                if st.session_state.gallery_variant_results:
                    results = st.session_state.gallery_variant_results
                    if results.get("successful"):
                        success_sizes = ', '.join([r['size'] for r in results['successful']])
                        st.success(f"✅ Created {len(results['successful'])} variant(s): {success_sizes}")
                    if results.get("failed"):
                        failed_msgs = [f"{r['size']}: {r.get('error', 'Unknown error')}" for r in results['failed']]
                        st.error(f"❌ Failed: {', '.join(failed_msgs)}")

                # Generate button
                btn_col1, btn_col2 = st.columns(2)
                with btn_col1:
                    generate_clicked = st.button(
                        "🚀 Generate Variants",
                        key="gallery_generate_variants",
                        disabled=len(selected_sizes) == 0 or st.session_state.gallery_variant_generating,
                        use_container_width=True
                    )

                with btn_col2:
                    if st.button("Close", key="gallery_close_panel", use_container_width=True):
                        st.session_state.gallery_show_variant_panel = False
                        st.session_state.gallery_variant_results = None
                        st.rerun()

                # Handle generation
                if generate_clicked and selected_sizes:
                    st.session_state.gallery_variant_generating = True
                    with st.spinner(f"Generating {len(selected_sizes)} size variant(s)..."):
                        # Get source image
                        source_image_base64 = get_ad_image_base64_gallery(ad_storage_paths.get(selected_ad_id, ""))
                        if source_image_base64:
                            results = asyncio.run(
                                create_size_variants_gallery_async(
                                    ad_id=selected_ad_id,
                                    target_sizes=selected_sizes,
                                    source_image_base64=source_image_base64
                                )
                            )
                            st.session_state.gallery_variant_results = results
                            # Clear cache to show new variants
                            st.cache_data.clear()
                        else:
                            st.session_state.gallery_variant_results = {
                                "successful": [],
                                "failed": [{"size": s, "error": "Could not load source image"} for s in selected_sizes]
                            }

                    st.session_state.gallery_variant_generating = False
                    st.rerun()

    st.markdown("---")

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
