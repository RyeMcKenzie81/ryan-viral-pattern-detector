"""
Ad History - Review all past ad runs and generated ads.

This page allows users to:
- Filter ad runs by brand
- View a summary table of all ad runs
- Expand to see all ads from a specific run
- See approval status for each ad
- Download all images from a run as a zip file
- Create size variants of approved ads
"""

import streamlit as st
import io
import zipfile
import requests
import asyncio
from datetime import datetime
from uuid import UUID

# Page config
st.set_page_config(
    page_title="Ad History",
    page_icon="📊",
    layout="wide"
)

# Authentication
from viraltracker.ui.auth import require_auth
require_auth()

st.title("📊 Ad History")
st.markdown("Review all past ad runs and generated ads.")


def get_supabase_client():
    """Get Supabase client."""
    from viraltracker.core.database import get_supabase_client
    return get_supabase_client()


def get_brands():
    """Fetch all brands from database."""
    try:
        db = get_supabase_client()
        result = db.table("brands").select("id, name").order("name").execute()
        return result.data
    except Exception as e:
        st.error(f"Failed to fetch brands: {e}")
        return []


def get_ad_runs_count(brand_id: str = None) -> int:
    """Get total count of ad runs for pagination."""
    try:
        db = get_supabase_client()
        query = db.table("ad_runs").select("id", count="exact")

        if brand_id and brand_id != "all":
            # Get product IDs for this brand first
            products = db.table("products").select("id").eq("brand_id", brand_id).execute()
            product_ids = [p['id'] for p in products.data]
            if product_ids:
                query = query.in_("product_id", product_ids)
            else:
                return 0

        result = query.execute()
        return result.count if result.count else 0
    except Exception as e:
        return 0


def get_ad_runs(brand_id: str = None, page: int = 1, page_size: int = 25):
    """
    Fetch ad runs with product info and stats (paginated).

    Args:
        brand_id: Optional brand ID to filter by
        page: Page number (1-indexed)
        page_size: Number of records per page

    Returns list of ad runs with:
    - run info (id, created_at, status, reference_ad_storage_path)
    - product info (name, brand_id)
    - counts (total_ads, approved_ads)
    """
    try:
        db = get_supabase_client()

        # Calculate offset
        offset = (page - 1) * page_size

        # Build query for ad_runs with product join (including codes for structured naming)
        query = db.table("ad_runs").select(
            "id, created_at, status, reference_ad_storage_path, product_id, parameters, "
            "products(id, name, brand_id, product_code, brands(id, name, brand_code))"
        ).order("created_at", desc=True)

        # Filter by brand if specified (do this in query for proper pagination)
        if brand_id and brand_id != "all":
            # Get product IDs for this brand first
            products = db.table("products").select("id").eq("brand_id", brand_id).execute()
            product_ids = [p['id'] for p in products.data]
            if product_ids:
                query = query.in_("product_id", product_ids)
            else:
                return []

        # Apply pagination
        query = query.range(offset, offset + page_size - 1)
        result = query.execute()
        runs = result.data

        # Get ad counts for each run (lightweight query - just counts)
        for run in runs:
            ads_result = db.table("generated_ads").select(
                "id, final_status"
            ).eq("ad_run_id", run['id']).execute()

            ads = ads_result.data
            run['total_ads'] = len(ads)
            run['approved_ads'] = len([a for a in ads if a.get('final_status') == 'approved'])

        return runs
    except Exception as e:
        st.error(f"Failed to fetch ad runs: {e}")
        return []


def get_ads_for_run(ad_run_id: str):
    """Fetch all generated ads for a specific run."""
    try:
        db = get_supabase_client()
        result = db.table("generated_ads").select(
            "id, prompt_index, storage_path, hook_text, final_status, "
            "claude_review, gemini_review, reviewers_agree, created_at, "
            "model_requested, model_used, generation_time_ms, generation_retries, "
            "parent_ad_id, variant_size"
        ).eq("ad_run_id", ad_run_id).order("prompt_index").execute()
        return result.data
    except Exception as e:
        st.error(f"Failed to fetch ads: {e}")
        return []


def get_scheduled_job_for_ad_runs(ad_run_ids: list) -> dict:
    """
    Check if any ad_run_ids were created by scheduled jobs.
    Returns dict mapping ad_run_id -> job_name.
    """
    if not ad_run_ids:
        return {}

    try:
        db = get_supabase_client()

        # Get all job runs that contain any of these ad_run_ids
        result = db.table("scheduled_job_runs").select(
            "ad_run_ids, scheduled_job_id, scheduled_jobs(name)"
        ).execute()

        mapping = {}
        for job_run in (result.data or []):
            job_ad_run_ids = job_run.get('ad_run_ids') or []
            job_name = job_run.get('scheduled_jobs', {}).get('name', 'Scheduled Job')

            for ad_run_id in ad_run_ids:
                if ad_run_id in job_ad_run_ids:
                    mapping[ad_run_id] = job_name

        return mapping
    except Exception as e:
        return {}


def get_signed_url(storage_path: str, expiry: int = 3600) -> str:
    """Get a signed URL for a storage path."""
    if not storage_path:
        return ""
    try:
        db = get_supabase_client()
        # Parse bucket and path
        parts = storage_path.split('/', 1)
        if len(parts) == 2:
            bucket, path = parts
        else:
            bucket = "generated-ads"
            path = storage_path

        # Get signed URL
        result = db.storage.from_(bucket).create_signed_url(path, expiry)
        return result.get('signedURL', '')
    except Exception as e:
        return ""


def format_date(date_str: str) -> str:
    """Format ISO date string to readable format."""
    if not date_str:
        return "N/A"
    try:
        dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        return dt.strftime("%b %d, %Y %H:%M")
    except:
        return date_str[:19] if date_str else "N/A"


def display_thumbnail(url: str, width: int = 80):
    """Display a thumbnail image."""
    if url:
        st.image(url, width=width)
    else:
        st.markdown(f"<div style='width:{width}px;height:{width}px;background:#333;display:flex;align-items:center;justify-content:center;color:#666;font-size:10px;'>No image</div>", unsafe_allow_html=True)


def get_status_badge(status: str) -> str:
    """Get colored badge HTML for status."""
    colors = {
        'approved': '#28a745',
        'rejected': '#dc3545',
        'flagged': '#ffc107',
        'pending': '#6c757d',
        'complete': '#28a745',
        'failed': '#dc3545',
        'generating': '#17a2b8',
        'reviewing': '#17a2b8',
        'analyzing': '#17a2b8'
    }
    color = colors.get(status, '#6c757d')
    return f"<span style='background:{color};color:white;padding:2px 8px;border-radius:4px;font-size:12px;'>{status}</span>"


def get_ad_creation_service():
    """Get AdCreationService instance."""
    from viraltracker.services.ad_creation_service import AdCreationService
    return AdCreationService()


def fetch_reference_ad_base64(storage_path: str) -> tuple[str, str]:
    """
    Fetch reference ad from storage and convert to base64.

    Returns:
        Tuple of (base64_data, filename)
    """
    import base64

    if not storage_path:
        return None, None

    try:
        db = get_supabase_client()
        # Parse bucket and path
        parts = storage_path.split('/', 1)
        if len(parts) == 2:
            bucket, path = parts
        else:
            bucket = "reference-ads"
            path = storage_path

        # Download the file
        response = db.storage.from_(bucket).download(path)
        base64_data = base64.b64encode(response).decode('utf-8')

        # Extract filename from path
        filename = path.split('/')[-1] if '/' in path else path

        return base64_data, filename
    except Exception as e:
        st.error(f"Failed to fetch reference ad: {e}")
        return None, None


async def retry_ad_run(run: dict) -> dict:
    """
    Retry an ad run with the same parameters.

    Args:
        run: The ad run dict containing parameters and reference_ad_storage_path

    Returns:
        Result from the ad workflow
    """
    from viraltracker.ui.pages import _ad_creator_helpers

    # Get the reference ad
    reference_path = run.get('reference_ad_storage_path')
    if not reference_path:
        raise ValueError("No reference ad found for this run")

    base64_data, filename = fetch_reference_ad_base64(reference_path)
    if not base64_data:
        raise ValueError("Failed to fetch reference ad from storage")

    # Get parameters
    params = run.get('parameters', {}) or {}
    product_id = run.get('product_id')

    if not product_id:
        raise ValueError("No product_id found for this run")

    # Import and call the workflow
    from pydantic_ai import RunContext
    from pydantic_ai.usage import RunUsage
    from viraltracker.agent.agents.ad_creation_agent import complete_ad_workflow
    from viraltracker.agent.dependencies import AgentDependencies

    # Create dependencies
    deps = AgentDependencies.create(project_name="default")

    # Create RunContext
    ctx = RunContext(
        deps=deps,
        model=None,
        usage=RunUsage()
    )

    # Run workflow with same parameters
    result = await complete_ad_workflow(
        ctx=ctx,
        product_id=product_id,
        reference_ad_base64=base64_data,
        reference_ad_filename=filename,
        project_id="",
        num_variations=params.get('num_variations', 5),
        content_source=params.get('content_source', 'hooks'),
        color_mode=params.get('color_mode', 'original'),
        brand_colors=params.get('brand_colors'),
        image_selection_mode=params.get('image_selection_mode', 'auto'),
        selected_image_paths=params.get('selected_image_paths'),
        persona_id=params.get('persona_id'),
        variant_id=params.get('variant_id'),
        additional_instructions=params.get('additional_instructions'),
        angle_data=params.get('angle_data'),
        match_template_structure=params.get('match_template_structure', False),
        offer_variant_id=params.get('offer_variant_id'),
        image_resolution=params.get('image_resolution', '2K')
    )

    return result


def get_performance_for_ads(ad_ids: list) -> dict:
    """
    Get Meta performance data for a list of generated ad IDs.

    Returns dict mapping generated_ad_id -> performance summary dict.
    """
    if not ad_ids:
        return {}

    try:
        db = get_supabase_client()

        # Get mappings for these ads
        result = db.table("meta_ad_mapping").select(
            "generated_ad_id, meta_ad_id, meta_ad_account_id"
        ).in_("generated_ad_id", ad_ids).execute()

        if not result.data:
            return {}

        # Get meta_ad_ids
        meta_ad_ids = [r["meta_ad_id"] for r in result.data]
        gen_to_meta = {r["generated_ad_id"]: r["meta_ad_id"] for r in result.data}

        # Get aggregated performance data for these meta ads
        perf_result = db.table("meta_ads_performance").select(
            "meta_ad_id, spend, impressions, link_clicks, purchases, purchase_value"
        ).in_("meta_ad_id", meta_ad_ids).execute()

        if not perf_result.data:
            return {}

        # Aggregate by meta_ad_id
        from collections import defaultdict
        meta_agg = defaultdict(lambda: {
            "spend": 0, "impressions": 0, "clicks": 0, "purchases": 0, "revenue": 0
        })

        for p in perf_result.data:
            mid = p.get("meta_ad_id")
            meta_agg[mid]["spend"] += float(p.get("spend") or 0)
            meta_agg[mid]["impressions"] += int(p.get("impressions") or 0)
            meta_agg[mid]["clicks"] += int(p.get("link_clicks") or 0)
            meta_agg[mid]["purchases"] += int(p.get("purchases") or 0)
            meta_agg[mid]["revenue"] += float(p.get("purchase_value") or 0)

        # Map back to generated_ad_id
        performance = {}
        for gen_id, meta_id in gen_to_meta.items():
            agg = meta_agg.get(meta_id)
            if agg and agg["spend"] > 0:
                roas = agg["revenue"] / agg["spend"] if agg["spend"] > 0 else 0
                ctr = (agg["clicks"] / agg["impressions"] * 100) if agg["impressions"] > 0 else 0
                performance[gen_id] = {
                    "spend": agg["spend"],
                    "impressions": agg["impressions"],
                    "clicks": agg["clicks"],
                    "purchases": agg["purchases"],
                    "roas": roas,
                    "ctr": ctr,
                    "linked": True
                }

        return performance
    except Exception as e:
        return {}


def get_existing_variants(ad_id: str) -> list:
    """Get list of variant sizes that already exist for an ad."""
    try:
        db = get_supabase_client()
        result = db.table("generated_ads").select(
            "variant_size"
        ).eq("parent_ad_id", ad_id).execute()
        return [r["variant_size"] for r in result.data if r.get("variant_size")]
    except Exception as e:
        return []


def get_ad_current_size(ad: dict) -> str:
    """
    Determine the current aspect ratio of an ad from its prompt_spec.

    Returns the size key (e.g., "1:1", "4:5") or None if unknown.
    """
    # Check if it's already a variant with a known size
    if ad.get('variant_size'):
        return ad.get('variant_size')

    # Try to get from prompt_spec canvas
    prompt_spec = ad.get('prompt_spec') or {}
    canvas = prompt_spec.get('canvas', {})

    # Check for aspect_ratio field
    if isinstance(canvas, dict) and canvas.get('aspect_ratio'):
        return canvas.get('aspect_ratio')

    # Try to parse from canvas string (e.g., "1080x1080px, background #F5F0E8")
    if isinstance(canvas, str):
        if '1080x1080' in canvas:
            return "1:1"
        elif '1080x1350' in canvas:
            return "4:5"
        elif '1080x1920' in canvas:
            return "9:16"
        elif '1920x1080' in canvas:
            return "16:9"

    # Check dimensions field
    if isinstance(canvas, dict):
        dims = canvas.get('dimensions', '')
        if '1080x1080' in dims:
            return "1:1"
        elif '1080x1350' in dims:
            return "4:5"
        elif '1080x1920' in dims:
            return "9:16"
        elif '1920x1080' in dims:
            return "16:9"

    # Default assumption for ads without explicit size info is 1:1
    return "1:1"


async def create_size_variants_async(ad_id: str, target_sizes: list) -> dict:
    """Create size variants using the AdCreationService."""
    service = get_ad_creation_service()
    return await service.create_size_variants_batch(
        source_ad_id=UUID(ad_id),
        target_sizes=target_sizes
    )


async def delete_ad_async(ad_id: str, delete_variants: bool = True) -> dict:
    """Delete an ad using the AdCreationService."""
    service = get_ad_creation_service()
    return await service.delete_generated_ad(
        ad_id=UUID(ad_id),
        delete_variants=delete_variants
    )


def get_format_code_from_spec(prompt_spec: dict) -> str:
    """Determine format code from prompt_spec canvas dimensions."""
    if not prompt_spec:
        return "SQ"

    canvas = prompt_spec.get("canvas", {})
    dimensions = canvas.get("dimensions", "")

    # Parse dimensions like "1080x1080" or "1080 x 1350"
    import re
    match = re.search(r'(\d+)\s*x\s*(\d+)', dimensions.lower())
    if not match:
        return "SQ"

    width = int(match.group(1))
    height = int(match.group(2))
    ratio = width / height if height > 0 else 1

    if 0.95 <= ratio <= 1.05:
        return "SQ"  # Square
    elif ratio < 0.7:
        if ratio < 0.65:
            return "ST"  # Story (9:16)
        else:
            return "PT"  # Portrait (4:5)
    else:
        return "LS"  # Landscape


def generate_structured_filename(brand_code: str, product_code: str, run_id: str,
                                  ad_id: str, format_code: str, ext: str = "png") -> str:
    """Generate structured filename like WP-C3-a1b2c3-d4e5f6-SQ.png"""
    run_short = run_id.replace("-", "")[:6]
    ad_short = ad_id.replace("-", "")[:6]
    bc = (brand_code or "XX").upper()
    pc = (product_code or "XX").upper()
    return f"{bc}-{pc}-{run_short}-{ad_short}-{format_code}.{ext}"


def create_zip_for_run(ads: list, product_name: str, run_id: str, reference_path: str = None,
                       brand_code: str = None, product_code: str = None) -> bytes:
    """
    Create a zip file containing all images from an ad run.

    Args:
        ads: List of ad dictionaries with storage_path
        product_name: Name of the product for filename
        run_id: Ad run ID (full UUID)
        reference_path: Optional path to reference template image
        brand_code: Brand code for structured naming (e.g., "WP")
        product_code: Product code for structured naming (e.g., "C3")

    Returns:
        Bytes of the zip file
    """
    zip_buffer = io.BytesIO()
    use_structured_naming = brand_code and product_code

    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        # Add reference template if available
        if reference_path:
            ref_url = get_signed_url(reference_path)
            if ref_url:
                try:
                    response = requests.get(ref_url, timeout=30)
                    if response.status_code == 200:
                        # Determine extension from content type or path
                        ext = ".png"
                        if "jpeg" in response.headers.get('content-type', ''):
                            ext = ".jpg"
                        elif "webp" in response.headers.get('content-type', ''):
                            ext = ".webp"
                        zip_file.writestr(f"00_reference_template{ext}", response.content)
                except Exception as e:
                    pass  # Skip if download fails

        # Add each generated ad
        for ad in ads:
            storage_path = ad.get('storage_path', '')
            if not storage_path:
                continue

            ad_url = get_signed_url(storage_path)
            if not ad_url:
                continue

            try:
                response = requests.get(ad_url, timeout=30)
                if response.status_code == 200:
                    # Determine extension
                    ext = "png"
                    if "jpeg" in response.headers.get('content-type', ''):
                        ext = "jpg"
                    elif "webp" in response.headers.get('content-type', ''):
                        ext = "webp"

                    # Use structured naming if codes are available
                    if use_structured_naming:
                        ad_id = ad.get('id', '')
                        prompt_spec = ad.get('prompt_spec', {})
                        format_code = get_format_code_from_spec(prompt_spec)
                        filename = generate_structured_filename(
                            brand_code, product_code, run_id, ad_id, format_code, ext
                        )
                    else:
                        # Fallback to legacy naming
                        variation = ad.get('prompt_index', 0)
                        status = ad.get('final_status', 'unknown')
                        filename = f"{variation:02d}_variation_{status}.{ext}"

                    zip_file.writestr(filename, response.content)
            except Exception as e:
                continue  # Skip if download fails

    zip_buffer.seek(0)
    return zip_buffer.getvalue()


# ============================================
# MAIN UI
# ============================================

# Initialize pagination state
if 'ad_history_page' not in st.session_state:
    st.session_state.ad_history_page = 1
if 'expanded_run_id' not in st.session_state:
    st.session_state.expanded_run_id = None

# Size variant state
if 'size_variant_ad_id' not in st.session_state:
    st.session_state.size_variant_ad_id = None
if 'size_variant_generating' not in st.session_state:
    st.session_state.size_variant_generating = False
if 'size_variant_results' not in st.session_state:
    st.session_state.size_variant_results = None

# Delete ad state
if 'delete_confirm_ad_id' not in st.session_state:
    st.session_state.delete_confirm_ad_id = None

PAGE_SIZE = 25

# Brand filter
brands = get_brands()
brand_options = {"all": "All Brands"}
for b in brands:
    brand_options[b['id']] = b['name']

selected_brand = st.selectbox(
    "Filter by Brand",
    options=list(brand_options.keys()),
    format_func=lambda x: brand_options[x],
    key="brand_filter",
    on_change=lambda: setattr(st.session_state, 'ad_history_page', 1)  # Reset to page 1 on filter change
)

st.markdown("---")

# Get total count and fetch paginated ad runs
brand_filter = selected_brand if selected_brand != "all" else None
total_count = get_ad_runs_count(brand_filter)
total_pages = max(1, (total_count + PAGE_SIZE - 1) // PAGE_SIZE)

# Ensure current page is valid
if st.session_state.ad_history_page > total_pages:
    st.session_state.ad_history_page = 1

with st.spinner("Loading ad runs..."):
    ad_runs = get_ad_runs(brand_filter, page=st.session_state.ad_history_page, page_size=PAGE_SIZE)

if not ad_runs:
    st.info("No ad runs found. Create some ads in the Ad Creator page!")
else:
    # Show pagination info
    start_idx = (st.session_state.ad_history_page - 1) * PAGE_SIZE + 1
    end_idx = min(st.session_state.ad_history_page * PAGE_SIZE, total_count)
    st.markdown(f"**Showing {start_idx}-{end_idx} of {total_count} ad runs** (Page {st.session_state.ad_history_page} of {total_pages})")

    # Get scheduled job info for all runs on this page
    ad_run_ids = [run['id'] for run in ad_runs]
    scheduled_job_mapping = get_scheduled_job_for_ad_runs(ad_run_ids)

    # Display each ad run as a row with expand button
    for run in ad_runs:
        product_name = run.get('products', {}).get('name', 'Unknown Product')
        brand_name = run.get('products', {}).get('brands', {}).get('name', 'Unknown Brand')
        run_id_short = run['id'][:8]  # Short ID
        run_id_full = run['id']
        date_str = format_date(run.get('created_at'))
        total_ads = run.get('total_ads', 0)
        approved_ads = run.get('approved_ads', 0)
        status = run.get('status', 'unknown')
        is_expanded = st.session_state.expanded_run_id == run_id_full

        # Summary row with expand button
        col_expand, col_info, col_stats = st.columns([0.5, 3, 1.5])

        with col_expand:
            btn_label = "▼" if is_expanded else "▶"
            if st.button(btn_label, key=f"expand_{run_id_full}", help="Click to expand/collapse"):
                if is_expanded:
                    st.session_state.expanded_run_id = None
                else:
                    st.session_state.expanded_run_id = run_id_full
                st.rerun()

        with col_info:
            # Check if this run was from a scheduled job
            job_name = scheduled_job_mapping.get(run_id_full)
            if job_name:
                st.markdown(f"**{product_name}** | `{run_id_short}` | {date_str} | 📅 _{job_name}_")
            else:
                st.markdown(f"**{product_name}** | `{run_id_short}` | {date_str}")

        with col_stats:
            approval_pct = int(approved_ads/total_ads*100) if total_ads > 0 else 0
            st.markdown(f"{get_status_badge(status)} {approved_ads}/{total_ads} ({approval_pct}%)", unsafe_allow_html=True)

        # Expanded content - ONLY load images when expanded
        if is_expanded:
            with st.container():
                st.markdown("---")

                # Top row with thumbnails and summary
                col1, col2, col3 = st.columns([1, 1, 2])

                with col1:
                    st.markdown("**Reference Template**")
                    template_url = get_signed_url(run.get('reference_ad_storage_path', ''))
                    display_thumbnail(template_url, width=120)

                with col2:
                    st.markdown("**First Generated Ad**")
                    # Only fetch first ad path when expanded
                    ads_for_thumb = get_ads_for_run(run_id_full)
                    first_ad_path = ads_for_thumb[0].get('storage_path') if ads_for_thumb else None
                    first_ad_url = get_signed_url(first_ad_path) if first_ad_path else ""
                    display_thumbnail(first_ad_url, width=120)

                with col3:
                    st.markdown("**Run Details**")
                    st.markdown(f"**Product:** {product_name}")
                    st.markdown(f"**Brand:** {brand_name}")
                    st.markdown(f"**Run ID:** `{run_id_full}`")
                    st.markdown(f"**Date:** {date_str}")
                    st.markdown(f"**Status:** {get_status_badge(status)}", unsafe_allow_html=True)
                    st.markdown(f"**Ads Created:** {total_ads}")
                    st.markdown(f"**Approved:** {approved_ads} ({approval_pct}%)")

                # Display generation parameters if available
                params = run.get('parameters')
                if params:
                    st.markdown("---")
                    st.markdown("**Generation Parameters**")
                    param_cols = st.columns(4)

                    with param_cols[0]:
                        st.markdown(f"**Variations:** {params.get('num_variations', 'N/A')}")

                    with param_cols[1]:
                        content_src = params.get('content_source', 'N/A')
                        content_display = "Hooks" if content_src == "hooks" else "Recreate Template" if content_src == "recreate_template" else content_src
                        st.markdown(f"**Content:** {content_display}")

                    with param_cols[2]:
                        color = params.get('color_mode', 'N/A')
                        color_display = color.replace('_', ' ').title() if color else 'N/A'
                        st.markdown(f"**Colors:** {color_display}")

                    with param_cols[3]:
                        img_mode = params.get('image_selection_mode', 'N/A')
                        img_display = "Auto" if img_mode == "auto" else "Manual" if img_mode == "manual" else img_mode
                        st.markdown(f"**Images:** {img_display}")

                st.markdown("---")

                # All ads from this run (already fetched above)
                ads = ads_for_thumb

                # Header with download button
                st.markdown("### All Generated Ads")

                # Action buttons - Download and Retry
                # Create safe filename
                safe_product_name = "".join(c if c.isalnum() or c in (' ', '-', '_') else '_' for c in product_name)
                zip_filename = f"{safe_product_name}_{run_id_short}_ads.zip"

                # Use session state to track if we should prepare download
                download_key = f"prepare_download_{run_id_full}"
                retry_key = f"retrying_{run_id_full}"
                if download_key not in st.session_state:
                    st.session_state[download_key] = False
                if retry_key not in st.session_state:
                    st.session_state[retry_key] = False

                col_btn1, col_btn2, col_btn3, col_spacer = st.columns([1, 1, 1, 1])

                with col_btn1:
                    if ads:
                        if st.button("📥 Prepare Download", key=f"btn_{run_id_full}", use_container_width=True):
                            st.session_state[download_key] = True
                            st.rerun()

                with col_btn2:
                    if ads and st.session_state[download_key]:
                        # Get codes for structured naming
                        product_data = run.get('products', {}) or {}
                        brand_data = product_data.get('brands', {}) or {}
                        brand_code = brand_data.get('brand_code')
                        product_code = product_data.get('product_code')

                        with st.spinner("Creating ZIP..."):
                            zip_data = create_zip_for_run(
                                ads=ads,
                                product_name=product_name,
                                run_id=run_id_full,  # Use full UUID for structured naming
                                reference_path=run.get('reference_ad_storage_path'),
                                brand_code=brand_code,
                                product_code=product_code
                            )
                        st.download_button(
                            label="💾 Download ZIP",
                            data=zip_data,
                            file_name=zip_filename,
                            mime="application/zip",
                            key=f"save_{run_id_full}",
                            use_container_width=True
                        )

                with col_btn3:
                    # Retry button - only show if run has parameters and reference ad
                    if run.get('reference_ad_storage_path') and run.get('parameters'):
                        if st.session_state[retry_key]:
                            st.info("🔄 Retrying...")
                        else:
                            if st.button("🔄 Retry Run", key=f"retry_{run_id_full}", use_container_width=True,
                                        help="Re-run with same parameters"):
                                st.session_state[retry_key] = True
                                try:
                                    with st.spinner("Starting new ad run with same parameters..."):
                                        result = asyncio.run(retry_ad_run(run))
                                    if result:
                                        new_run_id = result.get('ad_run_id', 'unknown')[:8]
                                        st.success(f"✅ New run started: `{new_run_id}`")
                                        st.session_state[retry_key] = False
                                        st.cache_data.clear()
                                        st.rerun()
                                except Exception as e:
                                    st.error(f"Retry failed: {e}")
                                    st.session_state[retry_key] = False

                st.markdown("")  # Spacing

                if not ads:
                    st.info("No ads found for this run.")
                else:
                    # Fetch performance data for these ads
                    ad_ids = [str(a.get('id')) for a in ads if a.get('id')]
                    performance_data = get_performance_for_ads(ad_ids) if ad_ids else {}

                    # Show performance summary if any ads have data
                    if performance_data:
                        linked_count = len(performance_data)
                        total_spend = sum(p.get("spend", 0) for p in performance_data.values())
                        total_purchases = sum(p.get("purchases", 0) for p in performance_data.values())
                        st.info(f"📊 **Performance:** {linked_count} ads linked · ${total_spend:,.2f} spend · {total_purchases} purchases")

                    # Display ads in a grid
                    cols_per_row = 3
                    for i in range(0, len(ads), cols_per_row):
                        cols = st.columns(cols_per_row)
                        for j, col in enumerate(cols):
                            if i + j < len(ads):
                                ad = ads[i + j]
                                with col:
                                    # Ad image
                                    ad_url = get_signed_url(ad.get('storage_path', ''))
                                    if ad_url:
                                        st.image(ad_url, use_container_width=True)
                                    else:
                                        st.markdown("<div style='height:200px;background:#333;display:flex;align-items:center;justify-content:center;color:#666;'>Image not available</div>", unsafe_allow_html=True)

                                    # Ad info
                                    ad_status = ad.get('final_status', 'pending')
                                    variant_size = ad.get('variant_size')
                                    if variant_size:
                                        # This is a size variant
                                        st.markdown(f"**{variant_size} Variant** - {get_status_badge(ad_status)}", unsafe_allow_html=True)
                                    else:
                                        st.markdown(f"**Variation {ad.get('prompt_index', '?')}** - {get_status_badge(ad_status)}", unsafe_allow_html=True)

                                    # Hook text (truncated)
                                    hook_text = ad.get('hook_text', '')
                                    if hook_text:
                                        display_text = hook_text[:80] + "..." if len(hook_text) > 80 else hook_text
                                        st.caption(f"_{display_text}_")

                                    # Review scores
                                    claude_review = ad.get('claude_review') or {}
                                    gemini_review = ad.get('gemini_review') or {}

                                    claude_score = claude_review.get('overall_score', 'N/A')
                                    gemini_score = gemini_review.get('overall_score', 'N/A')

                                    agree_icon = "✅" if ad.get('reviewers_agree') else "⚠️"
                                    st.caption(f"Claude: {claude_score} | Gemini: {gemini_score} {agree_icon}")

                                    # Performance data (if linked to Meta)
                                    ad_id = ad.get('id')
                                    perf = performance_data.get(str(ad_id)) if ad_id else None
                                    if perf:
                                        roas = perf.get("roas", 0)
                                        spend = perf.get("spend", 0)
                                        purchases = perf.get("purchases", 0)
                                        roas_color = "green" if roas >= 2 else "orange" if roas >= 1 else "red"
                                        st.markdown(
                                            f"<span style='color:{roas_color};font-weight:bold;'>📈 ROAS: {roas:.2f}x</span> · ${spend:,.0f} · {purchases} purch",
                                            unsafe_allow_html=True
                                        )

                                    # Model info (if available)
                                    model_used = ad.get('model_used')
                                    model_requested = ad.get('model_requested')
                                    gen_time = ad.get('generation_time_ms')
                                    retries = ad.get('generation_retries', 0)

                                    if model_used:
                                        # Check if fallback occurred
                                        fallback_warning = ""
                                        if model_requested and model_used != model_requested:
                                            fallback_warning = " ⚠️ FALLBACK"

                                        # Format model name (extract just the model part)
                                        model_short = model_used.split('/')[-1] if '/' in model_used else model_used

                                        time_str = f" | {gen_time}ms" if gen_time else ""
                                        retry_str = f" | {retries} retries" if retries > 0 else ""

                                        st.caption(f"🤖 {model_short}{time_str}{retry_str}{fallback_warning}")

                                    # Get ad_id for buttons
                                    ad_id = ad.get('id')
                                    is_variant = ad.get('parent_ad_id') is not None

                                    # Create Sizes button for approved ads (non-variants only)
                                    if ad_status == 'approved' and ad_id and not is_variant:
                                        # Check if size modal is open for this ad
                                        is_size_modal_open = st.session_state.size_variant_ad_id == ad_id

                                        if st.button("📐 Create Sizes", key=f"create_sizes_{ad_id}"):
                                            if is_size_modal_open:
                                                st.session_state.size_variant_ad_id = None
                                            else:
                                                st.session_state.size_variant_ad_id = ad_id
                                                st.session_state.size_variant_results = None
                                            st.rerun()

                                        # Show size selection modal
                                        if is_size_modal_open:
                                            st.markdown("**Select Target Sizes:**")

                                            # Get current size, existing variants, and size definitions
                                            current_size = get_ad_current_size(ad)
                                            existing_variants = get_existing_variants(ad_id)
                                            service = get_ad_creation_service()
                                            meta_sizes = service.META_AD_SIZES

                                            # Size checkboxes (skip current size)
                                            selected_sizes = []
                                            for size, info in meta_sizes.items():
                                                # Skip the source ad's current size
                                                if size == current_size:
                                                    continue

                                                already_exists = size in existing_variants
                                                label = f"{info['name']} ({size}) - {info['use_case']}"
                                                if already_exists:
                                                    label += " ✓ exists"

                                                is_selected = st.checkbox(
                                                    label,
                                                    value=False,
                                                    disabled=already_exists,
                                                    key=f"size_{ad_id}_{size}"
                                                )
                                                if is_selected:
                                                    selected_sizes.append(size)

                                            # Show results if available
                                            if st.session_state.size_variant_results:
                                                results = st.session_state.size_variant_results
                                                if results.get("successful"):
                                                    success_sizes = ', '.join([r['variant_size'] for r in results['successful']])
                                                    st.success(f"✅ Created {len(results['successful'])} variant(s): {success_sizes}")
                                                if results.get("failed"):
                                                    failed_msgs = [f"{r['size']}: {r.get('error', 'Unknown error')}" for r in results['failed']]
                                                    st.error(f"❌ Failed: {', '.join(failed_msgs)}")

                                            # Generate button
                                            btn_col1, btn_col2 = st.columns(2)
                                            with btn_col1:
                                                if st.button(
                                                    "🚀 Generate Variants",
                                                    key=f"generate_variants_{ad_id}",
                                                    disabled=len(selected_sizes) == 0 or st.session_state.size_variant_generating
                                                ):
                                                    st.session_state.size_variant_generating = True
                                                    st.rerun()

                                            with btn_col2:
                                                if st.button("Cancel", key=f"cancel_sizes_{ad_id}"):
                                                    st.session_state.size_variant_ad_id = None
                                                    st.session_state.size_variant_results = None
                                                    st.rerun()

                                            # Handle generation - service handles everything
                                            if st.session_state.size_variant_generating and selected_sizes:
                                                with st.spinner(f"Generating {len(selected_sizes)} size variant(s)..."):
                                                    # Run async generation via service
                                                    results = asyncio.run(
                                                        create_size_variants_async(
                                                            ad_id=ad_id,
                                                            target_sizes=selected_sizes
                                                        )
                                                    )
                                                    st.session_state.size_variant_results = results

                                                st.session_state.size_variant_generating = False
                                                st.rerun()

                                    # Delete button for all ads
                                    if ad_id:
                                        is_delete_confirm = st.session_state.delete_confirm_ad_id == ad_id

                                        if not is_delete_confirm:
                                            if st.button("🗑️ Delete", key=f"delete_{ad_id}", type="secondary"):
                                                st.session_state.delete_confirm_ad_id = ad_id
                                                st.rerun()
                                        else:
                                            # Confirmation UI
                                            st.warning("⚠️ Delete this ad?")
                                            if is_variant:
                                                st.caption("This will delete this size variant.")
                                            else:
                                                variant_count = len([a for a in ads if a.get('parent_ad_id') == ad_id])
                                                if variant_count > 0:
                                                    st.caption(f"This will also delete {variant_count} size variant(s).")

                                            del_col1, del_col2 = st.columns(2)
                                            with del_col1:
                                                if st.button("✅ Confirm Delete", key=f"confirm_delete_{ad_id}", type="primary"):
                                                    with st.spinner("Deleting..."):
                                                        try:
                                                            result = asyncio.run(delete_ad_async(ad_id))
                                                            st.session_state.delete_confirm_ad_id = None
                                                            st.success(f"Deleted ad" + (f" and {result['deleted_variants']} variant(s)" if result['deleted_variants'] > 0 else ""))
                                                            st.rerun()
                                                        except Exception as e:
                                                            st.error(f"Failed to delete: {e}")
                                            with del_col2:
                                                if st.button("Cancel", key=f"cancel_delete_{ad_id}"):
                                                    st.session_state.delete_confirm_ad_id = None
                                                    st.rerun()

                                    st.markdown("---")

                st.markdown("---")  # End of expanded section

    # Pagination controls
    st.markdown("---")
    col_prev, col_page_info, col_next = st.columns([1, 2, 1])

    with col_prev:
        if st.session_state.ad_history_page > 1:
            if st.button("← Previous", use_container_width=True):
                st.session_state.ad_history_page -= 1
                st.session_state.expanded_run_id = None  # Collapse when changing pages
                st.rerun()

    with col_page_info:
        st.markdown(f"<div style='text-align: center; padding-top: 5px;'>Page {st.session_state.ad_history_page} of {total_pages}</div>", unsafe_allow_html=True)

    with col_next:
        if st.session_state.ad_history_page < total_pages:
            if st.button("Next →", use_container_width=True):
                st.session_state.ad_history_page += 1
                st.session_state.expanded_run_id = None  # Collapse when changing pages
                st.rerun()

# Footer
st.markdown("---")
st.caption("Use the Ad Creator page to generate new ads.")
