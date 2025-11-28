"""
Ad History - Review all past ad runs and generated ads.

This page allows users to:
- Filter ad runs by brand
- View a summary table of all ad runs
- Expand to see all ads from a specific run
- See approval status for each ad
- Download all images from a run as a zip file
"""

import streamlit as st
import io
import zipfile
import requests
from datetime import datetime

# Page config
st.set_page_config(
    page_title="Ad History",
    page_icon="📊",
    layout="wide"
)

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


def get_ad_runs(brand_id: str = None):
    """
    Fetch all ad runs with product info and stats.

    Returns list of ad runs with:
    - run info (id, created_at, status, reference_ad_storage_path)
    - product info (name, brand_id)
    - counts (total_ads, approved_ads)
    """
    try:
        db = get_supabase_client()

        # Build query for ad_runs with product join
        query = db.table("ad_runs").select(
            "id, created_at, status, reference_ad_storage_path, product_id, "
            "products(id, name, brand_id, brands(id, name))"
        ).order("created_at", desc=True)

        result = query.execute()

        # Filter by brand if specified
        runs = result.data
        if brand_id and brand_id != "all":
            runs = [r for r in runs if r.get('products', {}).get('brand_id') == brand_id]

        # Get ad counts for each run
        for run in runs:
            ads_result = db.table("generated_ads").select(
                "id, final_status, storage_path"
            ).eq("ad_run_id", run['id']).execute()

            ads = ads_result.data
            run['total_ads'] = len(ads)
            run['approved_ads'] = len([a for a in ads if a.get('final_status') == 'approved'])
            run['first_ad_path'] = ads[0].get('storage_path') if ads else None

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
            "model_requested, model_used, generation_time_ms, generation_retries"
        ).eq("ad_run_id", ad_run_id).order("prompt_index").execute()
        return result.data
    except Exception as e:
        st.error(f"Failed to fetch ads: {e}")
        return []


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


def create_zip_for_run(ads: list, product_name: str, run_id: str, reference_path: str = None) -> bytes:
    """
    Create a zip file containing all images from an ad run.

    Args:
        ads: List of ad dictionaries with storage_path
        product_name: Name of the product for filename
        run_id: Ad run ID (short version)
        reference_path: Optional path to reference template image

    Returns:
        Bytes of the zip file
    """
    zip_buffer = io.BytesIO()

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
                    ext = ".png"
                    if "jpeg" in response.headers.get('content-type', ''):
                        ext = ".jpg"
                    elif "webp" in response.headers.get('content-type', ''):
                        ext = ".webp"

                    # Create filename with variation number and status
                    variation = ad.get('prompt_index', 0)
                    status = ad.get('final_status', 'unknown')
                    filename = f"{variation:02d}_variation_{status}{ext}"

                    zip_file.writestr(filename, response.content)
            except Exception as e:
                continue  # Skip if download fails

    zip_buffer.seek(0)
    return zip_buffer.getvalue()


# ============================================
# MAIN UI
# ============================================

# Brand filter
brands = get_brands()
brand_options = {"all": "All Brands"}
for b in brands:
    brand_options[b['id']] = b['name']

selected_brand = st.selectbox(
    "Filter by Brand",
    options=list(brand_options.keys()),
    format_func=lambda x: brand_options[x],
    key="brand_filter"
)

st.markdown("---")

# Fetch ad runs
with st.spinner("Loading ad runs..."):
    ad_runs = get_ad_runs(selected_brand if selected_brand != "all" else None)

if not ad_runs:
    st.info("No ad runs found. Create some ads in the Ad Creator page!")
else:
    st.markdown(f"**{len(ad_runs)} ad runs found**")

    # Display each ad run as an expandable card
    for run in ad_runs:
        product_name = run.get('products', {}).get('name', 'Unknown Product')
        brand_name = run.get('products', {}).get('brands', {}).get('name', 'Unknown Brand')
        run_id = run['id'][:8]  # Short ID
        date_str = format_date(run.get('created_at'))
        total_ads = run.get('total_ads', 0)
        approved_ads = run.get('approved_ads', 0)
        status = run.get('status', 'unknown')

        # Create expander header with summary info
        header = f"**{product_name}** | Run: `{run_id}` | {date_str} | {approved_ads}/{total_ads} approved"

        with st.expander(header, expanded=False):
            # Top row with thumbnails and summary
            col1, col2, col3 = st.columns([1, 1, 2])

            with col1:
                st.markdown("**Reference Template**")
                template_url = get_signed_url(run.get('reference_ad_storage_path', ''))
                display_thumbnail(template_url, width=120)

            with col2:
                st.markdown("**First Generated Ad**")
                first_ad_url = get_signed_url(run.get('first_ad_path', ''))
                display_thumbnail(first_ad_url, width=120)

            with col3:
                st.markdown("**Run Details**")
                st.markdown(f"**Product:** {product_name}")
                st.markdown(f"**Brand:** {brand_name}")
                st.markdown(f"**Run ID:** `{run['id']}`")
                st.markdown(f"**Date:** {date_str}")
                st.markdown(f"**Status:** {get_status_badge(status)}", unsafe_allow_html=True)
                st.markdown(f"**Ads Created:** {total_ads}")
                st.markdown(f"**Approved:** {approved_ads} ({int(approved_ads/total_ads*100) if total_ads > 0 else 0}%)")

            st.markdown("---")

            # All ads from this run
            ads = get_ads_for_run(run['id'])

            # Header with download button
            st.markdown("### All Generated Ads")

            # Download all button - prominent placement
            if ads:
                # Create safe filename
                safe_product_name = "".join(c if c.isalnum() or c in (' ', '-', '_') else '_' for c in product_name)
                zip_filename = f"{safe_product_name}_{run_id}_ads.zip"

                # Use session state to track if we should prepare download
                download_key = f"prepare_download_{run['id']}"
                if download_key not in st.session_state:
                    st.session_state[download_key] = False

                col_btn1, col_btn2, col_spacer = st.columns([1, 1, 2])

                with col_btn1:
                    if st.button("📥 Prepare Download", key=f"btn_{run['id']}", use_container_width=True):
                        st.session_state[download_key] = True
                        st.rerun()

                with col_btn2:
                    if st.session_state[download_key]:
                        with st.spinner("Creating ZIP..."):
                            zip_data = create_zip_for_run(
                                ads=ads,
                                product_name=product_name,
                                run_id=run_id,
                                reference_path=run.get('reference_ad_storage_path')
                            )
                        st.download_button(
                            label="💾 Download ZIP",
                            data=zip_data,
                            file_name=zip_filename,
                            mime="application/zip",
                            key=f"save_{run['id']}",
                            use_container_width=True
                        )

                st.markdown("")  # Spacing

            if not ads:
                st.info("No ads found for this run.")
            else:
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

                                st.markdown("---")

# Footer
st.markdown("---")
st.caption("Use the Ad Creator page to generate new ads.")
