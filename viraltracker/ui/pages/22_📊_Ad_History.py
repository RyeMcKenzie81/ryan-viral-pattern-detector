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
from viraltracker.ui.utils import require_feature
require_feature("ad_history", "Ad History")

st.title("📊 Ad History")
st.markdown("Review all past ad runs and generated ads.")

def get_supabase_client():
    """Get Supabase client."""
    from viraltracker.core.database import get_supabase_client
    return get_supabase_client()

def _get_product_ids_for_org(db, org_id: str) -> list:
    """Get all product IDs belonging to brands in an organization."""
    brands = db.table("brands").select("id").eq("organization_id", org_id).execute()
    brand_ids = [b['id'] for b in brands.data]
    if not brand_ids:
        return []
    products = db.table("products").select("id").in_("brand_id", brand_ids).execute()
    return [p['id'] for p in products.data]

def _get_product_ids_for_brand(db, brand_id: str) -> list:
    """Get all product IDs for a specific brand."""
    products = db.table("products").select("id").eq("brand_id", brand_id).execute()
    return [p['id'] for p in products.data]

def get_ad_runs_count(brand_id: str = None, org_id: str = None) -> int:
    """Get total count of ad runs for pagination."""
    try:
        db = get_supabase_client()
        query = db.table("ad_runs").select("id", count="exact")

        if brand_id and brand_id != "all":
            product_ids = _get_product_ids_for_brand(db, brand_id)
            if product_ids:
                query = query.in_("product_id", product_ids)
            else:
                return 0
        elif org_id and org_id != "all":
            product_ids = _get_product_ids_for_org(db, org_id)
            if product_ids:
                query = query.in_("product_id", product_ids)
            else:
                return 0

        result = query.execute()
        return result.count if result.count else 0
    except Exception as e:
        return 0

def get_ad_runs(brand_id: str = None, org_id: str = None, page: int = 1, page_size: int = 25):
    """
    Fetch ad runs with product info and stats (paginated).

    Args:
        brand_id: Optional brand ID to filter by
        org_id: Organization ID to filter by (used when brand is "all")
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
            "id, created_at, status, error_message, reference_ad_storage_path, product_id, parameters, "
            "products(id, name, brand_id, product_code, brands(id, name, brand_code))"
        ).order("created_at", desc=True)

        # Filter by brand if specified (do this in query for proper pagination)
        if brand_id and brand_id != "all":
            product_ids = _get_product_ids_for_brand(db, brand_id)
            if product_ids:
                query = query.in_("product_id", product_ids)
            else:
                return []
        elif org_id and org_id != "all":
            product_ids = _get_product_ids_for_org(db, org_id)
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
            "parent_ad_id, variant_size, is_imported"
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
    from viraltracker.pipelines.ad_creation.orchestrator import run_ad_creation
    from viraltracker.agent.dependencies import AgentDependencies

    # Create dependencies
    deps = AgentDependencies.create(project_name="default")

    # Run workflow with same parameters
    result = await run_ad_creation(
        product_id=product_id,
        reference_ad_base64=base64_data,
        reference_ad_filename=filename,
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
        image_resolution=params.get('image_resolution', '2K'),
        deps=deps,
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

async def create_edited_ad_async(
    ad_id: str,
    edit_prompt: str,
    temperature: float = 0.3,
    preserve_text: bool = True,
    preserve_colors: bool = True,
    reference_image_ids: list = None
) -> dict:
    """Create an edited ad using the AdCreationService."""
    service = get_ad_creation_service()
    ref_ids = [UUID(rid) for rid in reference_image_ids] if reference_image_ids else None
    return await service.create_edited_ad(
        source_ad_id=UUID(ad_id),
        edit_prompt=edit_prompt,
        temperature=temperature,
        preserve_text=preserve_text,
        preserve_colors=preserve_colors,
        reference_image_ids=ref_ids
    )

async def regenerate_ad_async(ad_id: str) -> dict:
    """Regenerate a rejected/flagged ad using AdCreationService."""
    service = get_ad_creation_service()
    return await service.regenerate_ad(source_ad_id=UUID(ad_id))

def get_edit_presets() -> dict:
    """Get edit preset definitions from the service."""
    service = get_ad_creation_service()
    return service.EDIT_PRESETS

def get_product_images_for_ad(ad_id: str) -> list:
    """Get product images available for the product associated with an ad.

    Returns list of dicts with id, storage_path, image_type, alt_text, signed_url
    """
    import logging
    logger = logging.getLogger(__name__)

    try:
        supabase = get_supabase_client()

        # Step 1: Get ad_run_id from generated_ads
        ad_result = supabase.table("generated_ads").select(
            "ad_run_id"
        ).eq("id", ad_id).execute()

        if not ad_result.data:
            logger.debug(f"No ad found with id {ad_id}")
            return []

        ad_run_id = ad_result.data[0].get("ad_run_id")
        if not ad_run_id:
            logger.debug(f"Ad {ad_id} has no ad_run_id")
            return []

        # Step 2: Get product_id from ad_runs
        run_result = supabase.table("ad_runs").select(
            "product_id"
        ).eq("id", ad_run_id).execute()

        if not run_result.data:
            logger.debug(f"No ad_run found with id {ad_run_id}")
            return []

        product_id = run_result.data[0].get("product_id")
        if not product_id:
            logger.debug(f"Ad run {ad_run_id} has no product_id")
            return []

        logger.debug(f"Found product_id {product_id} for ad {ad_id}")

        # Step 3: Get all images for this product (use same columns as Ad Creator)
        # Supported image formats
        image_extensions = ('.jpg', '.jpeg', '.png', '.webp', '.gif')

        images_result = supabase.table("product_images").select(
            "id, storage_path, image_analysis, analyzed_at, is_main"
        ).eq("product_id", product_id).order("is_main", desc=True).execute()

        if not images_result.data:
            logger.debug(f"No images found for product {product_id}")
            return []

        # Filter to only image files (not PDFs)
        all_images = [
            img for img in images_result.data
            if img.get('storage_path', '').lower().endswith(image_extensions)
        ]

        logger.debug(f"Found {len(all_images)} images for product {product_id}")

        images = []
        for img in all_images:
            # Generate signed URL for display
            try:
                storage_path = img.get("storage_path", "")
                if "/" in storage_path:
                    bucket, path = storage_path.split("/", 1)
                    signed = supabase.storage.from_(bucket).create_signed_url(path, 3600)
                    img["signed_url"] = signed.get("signedURL", "")
                else:
                    img["signed_url"] = ""
            except Exception as e:
                logger.debug(f"Failed to sign URL for image {img.get('id')}: {e}")
                img["signed_url"] = ""
            images.append(img)

        return images
    except Exception as e:
        logger.warning(f"Failed to get product images for ad {ad_id}: {e}")
        return []

def get_brand_logos_for_ad(ad_id: str) -> list:
    """Get brand logos available for the brand associated with an ad.

    Returns list of dicts with id, storage_path, asset_type, is_primary, signed_url
    """
    import logging
    logger = logging.getLogger(__name__)

    try:
        supabase = get_supabase_client()

        # Step 1: Get ad_run_id from generated_ads
        ad_result = supabase.table("generated_ads").select(
            "ad_run_id"
        ).eq("id", ad_id).execute()

        if not ad_result.data:
            return []

        ad_run_id = ad_result.data[0].get("ad_run_id")
        if not ad_run_id:
            return []

        # Step 2: Get product_id from ad_runs
        run_result = supabase.table("ad_runs").select(
            "product_id"
        ).eq("id", ad_run_id).execute()

        if not run_result.data:
            return []

        product_id = run_result.data[0].get("product_id")
        if not product_id:
            return []

        # Step 3: Get brand_id from products
        product_result = supabase.table("products").select(
            "brand_id"
        ).eq("id", product_id).execute()

        if not product_result.data:
            return []

        brand_id = product_result.data[0].get("brand_id")
        if not brand_id:
            return []

        logger.debug(f"Found brand_id {brand_id} for ad {ad_id}")

        # Step 4: Get all logos for this brand from brand_assets
        logos_result = supabase.table("brand_assets").select(
            "id, storage_path, asset_type, is_primary, filename"
        ).eq("brand_id", brand_id).eq("asset_type", "logo").order("is_primary", desc=True).execute()

        if not logos_result.data:
            logger.debug(f"No logos found for brand {brand_id}")
            return []

        logger.debug(f"Found {len(logos_result.data)} logos for brand {brand_id}")

        logos = []
        for logo in logos_result.data:
            # Generate signed URL for display
            try:
                storage_path = logo.get("storage_path", "")
                if "/" in storage_path:
                    bucket, path = storage_path.split("/", 1)
                    signed = supabase.storage.from_(bucket).create_signed_url(path, 3600)
                    logo["signed_url"] = signed.get("signedURL", "")
                else:
                    logo["signed_url"] = ""
            except Exception as e:
                logger.debug(f"Failed to sign URL for logo {logo.get('id')}: {e}")
                logo["signed_url"] = ""
            logos.append(logo)

        return logos
    except Exception as e:
        logger.warning(f"Failed to get brand logos for ad {ad_id}: {e}")
        return []

def update_ad_status(ad_id: str, new_status: str) -> bool:
    """Update the final_status of an ad.

    Args:
        ad_id: UUID string of the ad
        new_status: New status (approved, rejected, flagged, pending)

    Returns:
        True if successful
    """
    try:
        db = get_supabase_client()
        db.table("generated_ads").update({
            "final_status": new_status
        }).eq("id", ad_id).execute()
        return True
    except Exception as e:
        logger.error(f"Failed to update ad status: {e}")
        return False

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

# Smart Edit state
if 'edit_ad_id' not in st.session_state:
    st.session_state.edit_ad_id = None
if 'edit_generating' not in st.session_state:
    st.session_state.edit_generating = False
if 'edit_result' not in st.session_state:
    st.session_state.edit_result = None

# Rerun (regenerate) state
if 'rerun_generating' not in st.session_state:
    st.session_state.rerun_generating = False
if 'rerun_result' not in st.session_state:
    st.session_state.rerun_result = None

# Winner Evolution state (Phase 7A)
if 'evolve_ad_id' not in st.session_state:
    st.session_state.evolve_ad_id = None
if 'evolve_options' not in st.session_state:
    st.session_state.evolve_options = None
if 'evolve_submitting' not in st.session_state:
    st.session_state.evolve_submitting = False
if 'evolve_result' not in st.session_state:
    st.session_state.evolve_result = None

PAGE_SIZE = 25

# Show rerun result from previous run
if st.session_state.rerun_result:
    result = st.session_state.rerun_result
    new_status = result.get('final_status', 'unknown')
    st.success(f"Regenerated! New ad: {result['ad_id'][:8]} ({new_status})")
    st.session_state.rerun_result = None

# Organization context (selector rendered once in app.py sidebar)
from viraltracker.ui.utils import get_current_organization_id, get_brands as get_org_brands
org_id = get_current_organization_id()
if not org_id:
    st.warning("Please select a workspace.")
    st.stop()

# Brand filter (filtered by org)
brands = get_org_brands(org_id)
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
total_count = get_ad_runs_count(brand_filter, org_id=org_id)
total_pages = max(1, (total_count + PAGE_SIZE - 1) // PAGE_SIZE)

# Ensure current page is valid
if st.session_state.ad_history_page > total_pages:
    st.session_state.ad_history_page = 1

with st.spinner("Loading ad runs..."):
    ad_runs = get_ad_runs(brand_filter, org_id=org_id, page=st.session_state.ad_history_page, page_size=PAGE_SIZE)

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
            if status == 'failed':
                error_msg = run.get('error_message', '')
                # Show truncated error in summary row
                short_error = (error_msg[:80] + '...') if len(error_msg) > 80 else error_msg
                st.markdown(f"{get_status_badge(status)} {short_error}", unsafe_allow_html=True)
            else:
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
                    if status == 'failed' and run.get('error_message'):
                        st.error(f"Error: {run['error_message']}")
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

                    # Toggle to hide/show rejected ads
                    show_rejected = st.checkbox(
                        "Show rejected ads", value=True,
                        key=f"show_rejected_{run.get('id', 'x')}",
                        help="Hide ads rejected by both reviewers. Flagged ads are always shown."
                    )
                    display_ads = ads if show_rejected else [
                        a for a in ads if a.get('final_status') != 'rejected'
                    ]

                    # Display ads in a grid
                    cols_per_row = 3
                    for i in range(0, len(display_ads), cols_per_row):
                        cols = st.columns(cols_per_row)
                        for j, col in enumerate(cols):
                            if i + j < len(display_ads):
                                ad = display_ads[i + j]
                                with col:
                                    # Ad image
                                    ad_url = get_signed_url(ad.get('storage_path', ''))
                                    if ad_url:
                                        st.image(ad_url, use_container_width=True)
                                    else:
                                        st.markdown("<div style='height:200px;background:#333;display:flex;align-items:center;justify-content:center;color:#666;'>Image not available</div>", unsafe_allow_html=True)

                                    # Ad info
                                    ad_status = ad.get('final_status', 'pending')
                                    imported_badge = " `[Imported]`" if ad.get('is_imported') else ""
                                    variant_size = ad.get('variant_size')
                                    if variant_size:
                                        # This is a size variant
                                        st.markdown(f"**{variant_size} Variant** - {get_status_badge(ad_status)}{imported_badge}", unsafe_allow_html=True)
                                    else:
                                        st.markdown(f"**Variation {ad.get('prompt_index', '?')}** - {get_status_badge(ad_status)}{imported_badge}", unsafe_allow_html=True)

                                    # Hook text (truncated)
                                    hook_text = ad.get('hook_text', '')
                                    if hook_text:
                                        display_text = hook_text[:80] + "..." if len(hook_text) > 80 else hook_text
                                        st.caption(f"_{display_text}_")

                                    # Review scores
                                    claude_review = ad.get('claude_review') or {}
                                    gemini_review = ad.get('gemini_review') or {}

                                    claude_score = claude_review.get('overall_quality', 'N/A')
                                    gemini_score = gemini_review.get('overall_quality', 'N/A')

                                    agree_icon = "✅" if ad.get('reviewers_agree') else "⚠️"
                                    st.caption(f"Claude: {claude_score} | Gemini: {gemini_score} {agree_icon}")

                                    # Show rejection/flagged reasons
                                    if ad_status in ('rejected', 'flagged', 'needs_revision'):
                                        with st.expander("Review Details"):
                                            for label, rev in [("Claude", claude_review), ("Gemini", gemini_review)]:
                                                if not rev:
                                                    continue
                                                rev_status = rev.get('status', 'N/A')
                                                st.markdown(f"**{label}:** {rev_status}")
                                                if rev.get('notes'):
                                                    st.caption(rev['notes'])
                                                for key, heading in [('product_issues', 'Product Issues'),
                                                                     ('text_issues', 'Text Issues'),
                                                                     ('ai_artifacts', 'AI Artifacts')]:
                                                    items = rev.get(key, [])
                                                    if items:
                                                        st.markdown(f"_{heading}:_ " + ", ".join(items))

                                    # Rerun button for rejected/flagged non-variant ads
                                    if ad_status in ('rejected', 'flagged') and ad.get('id') and not ad.get('parent_ad_id'):
                                        rerun_ad_id = ad['id']
                                        if st.button(
                                            "🔄 Rerun",
                                            key=f"rerun_{rerun_ad_id}",
                                            help="Regenerate with same hook and re-review"
                                        ):
                                            st.session_state.rerun_generating = True
                                            with st.spinner("Regenerating ad..."):
                                                try:
                                                    rerun_result = asyncio.run(
                                                        regenerate_ad_async(rerun_ad_id)
                                                    )
                                                    new_status = rerun_result.get('final_status', 'unknown')
                                                    st.session_state.rerun_result = rerun_result
                                                    st.session_state.rerun_generating = False
                                                    st.rerun()
                                                except Exception as e:
                                                    st.session_state.rerun_generating = False
                                                    st.error(f"Regeneration failed: {e}")

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

                                        # Smart Edit button for approved ads (non-variants only)
                                        is_edit_modal_open = st.session_state.edit_ad_id == ad_id

                                        if st.button("✏️ Smart Edit", key=f"smart_edit_{ad_id}"):
                                            if is_edit_modal_open:
                                                st.session_state.edit_ad_id = None
                                            else:
                                                st.session_state.edit_ad_id = ad_id
                                                st.session_state.edit_result = None
                                            st.rerun()

                                        # Show edit modal
                                        if is_edit_modal_open:
                                            st.markdown("**Smart Edit**")
                                            st.caption("Edit this ad with specific instructions")

                                            # Edit prompt input
                                            edit_prompt = st.text_area(
                                                "What would you like to change?",
                                                placeholder="e.g., Make the headline text larger, Add more contrast...",
                                                key=f"edit_prompt_{ad_id}",
                                                height=80
                                            )

                                            # Quick presets
                                            st.markdown("**Quick Presets:**")
                                            presets = get_edit_presets()
                                            preset_cols = st.columns(3)
                                            selected_preset = None

                                            for idx, (preset_key, preset_desc) in enumerate(presets.items()):
                                                col_idx = idx % 3
                                                with preset_cols[col_idx]:
                                                    preset_label = preset_key.replace("_", " ").title()
                                                    if st.button(preset_label, key=f"preset_{ad_id}_{preset_key}",
                                                                help=preset_desc, use_container_width=True):
                                                        selected_preset = preset_desc

                                            # Reference Images Selection
                                            product_images = get_product_images_for_ad(ad_id)
                                            brand_logos = get_brand_logos_for_ad(ad_id)
                                            selected_ref_images = []

                                            with st.expander("📷 Add Reference Images (e.g., correct logo)", expanded=False):
                                                # Brand Logos Section
                                                if brand_logos:
                                                    st.markdown("**Brand Logos**")
                                                    logo_cols = st.columns(4)
                                                    for idx, logo in enumerate(brand_logos):
                                                        with logo_cols[idx % 4]:
                                                            if logo.get("signed_url"):
                                                                st.image(logo["signed_url"], width=80)
                                                            # Build label
                                                            if logo.get("is_primary"):
                                                                logo_label = "⭐ Primary Logo"
                                                            else:
                                                                logo_label = logo.get("filename", f"Logo {idx + 1}")
                                                            if st.checkbox(
                                                                logo_label,
                                                                key=f"ref_logo_{ad_id}_{logo['id']}",
                                                                help="Select to use this logo as reference"
                                                            ):
                                                                selected_ref_images.append(logo["id"])

                                                # Product Images Section
                                                if product_images:
                                                    if brand_logos:
                                                        st.markdown("**Product Images**")
                                                    else:
                                                        st.caption("Select images to include as references for the edit")

                                                    # Create grid of images with checkboxes
                                                    img_cols = st.columns(4)
                                                    for idx, img in enumerate(product_images):
                                                        with img_cols[idx % 4]:
                                                            if img.get("signed_url"):
                                                                st.image(img["signed_url"], width=80)
                                                            # Build label from available data
                                                            if img.get("is_main"):
                                                                img_label = "⭐ Main"
                                                            else:
                                                                img_label = f"Image {idx + 1}"
                                                            # Add analysis info if available
                                                            analysis = img.get("image_analysis")
                                                            help_text = ""
                                                            if analysis:
                                                                use_cases = analysis.get("best_use_cases", [])[:2]
                                                                if use_cases:
                                                                    help_text = ", ".join(use_cases)
                                                            if st.checkbox(
                                                                img_label,
                                                                key=f"ref_img_{ad_id}_{img['id']}",
                                                                help=help_text if help_text else "Select to include as reference"
                                                            ):
                                                                selected_ref_images.append(img["id"])

                                                if not product_images and not brand_logos:
                                                    st.info("No reference images available. Upload logos in Brand Manager or product images to use as references.")

                                            # Preservation options
                                            st.markdown("**Preservation Options:**")
                                            preserve_text = st.checkbox(
                                                "Keep text identical",
                                                value=True,
                                                key=f"preserve_text_{ad_id}",
                                                help="Keep all text exactly the same unless editing it"
                                            )
                                            preserve_colors = st.checkbox(
                                                "Keep colors identical",
                                                value=True,
                                                key=f"preserve_colors_{ad_id}",
                                                help="Keep all colors exactly the same unless editing them"
                                            )

                                            # Temperature slider
                                            temperature = st.slider(
                                                "Faithfulness",
                                                min_value=0.1,
                                                max_value=0.8,
                                                value=0.3,
                                                step=0.1,
                                                key=f"edit_temp_{ad_id}",
                                                help="Lower = more faithful to original, Higher = more creative"
                                            )

                                            # Show result if available
                                            if st.session_state.edit_result:
                                                result = st.session_state.edit_result
                                                if "ad_id" in result:
                                                    st.success(f"✅ Edit created! New ad ID: {result['ad_id'][:8]}")
                                                    st.caption(f"Generation time: {result.get('generation_time_ms', 0)}ms")
                                                elif "error" in result:
                                                    st.error(f"❌ Edit failed: {result['error']}")

                                            # Action buttons
                                            edit_btn_col1, edit_btn_col2 = st.columns(2)
                                            with edit_btn_col1:
                                                # Use preset if selected, otherwise use text input
                                                final_prompt = selected_preset or edit_prompt
                                                can_generate = bool(final_prompt) and not st.session_state.edit_generating

                                                if st.button(
                                                    "🎨 Generate Edit",
                                                    key=f"generate_edit_{ad_id}",
                                                    disabled=not can_generate,
                                                    type="primary"
                                                ):
                                                    st.session_state.edit_generating = True
                                                    with st.spinner("Creating edited ad..."):
                                                        try:
                                                            result = asyncio.run(
                                                                create_edited_ad_async(
                                                                    ad_id=ad_id,
                                                                    edit_prompt=final_prompt,
                                                                    temperature=temperature,
                                                                    preserve_text=preserve_text,
                                                                    preserve_colors=preserve_colors,
                                                                    reference_image_ids=selected_ref_images if selected_ref_images else None
                                                                )
                                                            )
                                                            st.session_state.edit_result = result
                                                        except Exception as e:
                                                            st.session_state.edit_result = {"error": str(e)}
                                                    st.session_state.edit_generating = False
                                                    st.rerun()

                                            with edit_btn_col2:
                                                if st.button("Cancel", key=f"cancel_edit_{ad_id}"):
                                                    st.session_state.edit_ad_id = None
                                                    st.session_state.edit_result = None
                                                    st.rerun()

                                    # Winner Evolution button for approved ads (Phase 7A)
                                    if ad_status == 'approved' and ad_id and not is_variant:
                                        is_evolve_modal_open = st.session_state.evolve_ad_id == ad_id

                                        if st.button("✨ Evolve This Ad", key=f"evolve_{ad_id}"):
                                            if is_evolve_modal_open:
                                                st.session_state.evolve_ad_id = None
                                                st.session_state.evolve_options = None
                                                st.session_state.evolve_result = None
                                            else:
                                                st.session_state.evolve_ad_id = ad_id
                                                st.session_state.evolve_options = None
                                                st.session_state.evolve_result = None
                                                # Fetch evolution options
                                                try:
                                                    from viraltracker.services.winner_evolution_service import WinnerEvolutionService
                                                    from uuid import UUID as _EUUID
                                                    evo_svc = WinnerEvolutionService()
                                                    import asyncio as _evo_asyncio
                                                    options = _evo_asyncio.run(evo_svc.get_evolution_options(_EUUID(ad_id)))
                                                    st.session_state.evolve_options = options
                                                except Exception as evo_err:
                                                    st.session_state.evolve_options = {"error": str(evo_err)}
                                            st.rerun()

                                        # Show evolution modal
                                        if is_evolve_modal_open and st.session_state.evolve_options:
                                            options = st.session_state.evolve_options

                                            if options.get("error"):
                                                st.error(f"Failed to check evolution options: {options['error']}")
                                            elif not options.get("is_winner"):
                                                details = options.get("winner_details", {})
                                                st.warning(f"Not eligible for evolution: {details.get('reason', 'Does not meet winner criteria')}")
                                                if details.get("reward_score") is not None:
                                                    st.caption(f"Reward: {details['reward_score']:.3f} | "
                                                               f"Impressions: {details.get('impressions', 'N/A')} | "
                                                               f"Threshold: 0.65")
                                            else:
                                                winner_details = options.get("winner_details", {})
                                                st.success(f"Winner! Reward: {winner_details.get('reward_score', 0):.3f}")
                                                st.caption(
                                                    f"Iterations: {options.get('iteration_count', 0)}/{options.get('iteration_limit', 5)} | "
                                                    f"Ancestor rounds: {options.get('ancestor_round', 0)}/{options.get('ancestor_round_limit', 3)}"
                                                )

                                                # Mode selection
                                                available_modes = options.get("available_modes", [])
                                                mode_options = {}
                                                for m in available_modes:
                                                    mode_name = m["mode"].replace("_", " ").title()
                                                    status = "available" if m["available"] else m.get("reason", "unavailable")
                                                    est = m.get("estimated_variants", 0)
                                                    label = f"{mode_name} (~{est} variants)" if m["available"] else f"{mode_name} ({status})"
                                                    mode_options[label] = m

                                                if not any(m["available"] for m in available_modes):
                                                    st.info("No evolution modes currently available for this ad.")
                                                else:
                                                    selected_label = st.radio(
                                                        "Select Evolution Mode",
                                                        options=[k for k, v in mode_options.items() if v["available"]],
                                                        key=f"evolve_mode_{ad_id}",
                                                    )

                                                    if selected_label:
                                                        selected_mode = mode_options[selected_label]
                                                        st.caption(selected_mode.get("reason", ""))

                                                        if selected_mode["mode"] == "cross_size_expansion":
                                                            untested = selected_mode.get("untested_sizes", [])
                                                            if untested:
                                                                st.caption(f"Untested sizes: {', '.join(untested)}")

                                                    # Show result if available
                                                    if st.session_state.evolve_result:
                                                        result = st.session_state.evolve_result
                                                        if result.get("success"):
                                                            st.success(
                                                                f"Evolution submitted! "
                                                                f"Variable: {result.get('variable_changed', 'N/A')} | "
                                                                f"Children: {len(result.get('child_ad_ids', []))}"
                                                            )
                                                        elif result.get("error"):
                                                            st.error(f"Evolution failed: {result['error']}")

                                                    # Submit button
                                                    evo_btn_col1, evo_btn_col2 = st.columns(2)
                                                    with evo_btn_col1:
                                                        can_submit = (
                                                            selected_label is not None
                                                            and not st.session_state.evolve_submitting
                                                        )
                                                        if st.button(
                                                            "🚀 Evolve",
                                                            key=f"submit_evolve_{ad_id}",
                                                            disabled=not can_submit,
                                                            type="primary"
                                                        ):
                                                            st.session_state.evolve_submitting = True
                                                            selected_mode_val = mode_options[selected_label]
                                                            with st.spinner("Submitting evolution job..."):
                                                                try:
                                                                    from viraltracker.services.winner_evolution_service import WinnerEvolutionService
                                                                    from uuid import UUID as _EUUID2
                                                                    import asyncio as _evo_asyncio2
                                                                    evo_svc2 = WinnerEvolutionService()
                                                                    evo_result = _evo_asyncio2.run(
                                                                        evo_svc2.evolve_winner(
                                                                            parent_ad_id=_EUUID2(ad_id),
                                                                            mode=selected_mode_val["mode"],
                                                                        )
                                                                    )
                                                                    st.session_state.evolve_result = {
                                                                        "success": True, **evo_result
                                                                    }
                                                                except Exception as evo_err2:
                                                                    st.session_state.evolve_result = {
                                                                        "success": False,
                                                                        "error": str(evo_err2),
                                                                    }
                                                            st.session_state.evolve_submitting = False
                                                            st.rerun()

                                                    with evo_btn_col2:
                                                        if st.button("Cancel", key=f"cancel_evolve_{ad_id}"):
                                                            st.session_state.evolve_ad_id = None
                                                            st.session_state.evolve_options = None
                                                            st.session_state.evolve_result = None
                                                            st.rerun()

                                    # Approve/Reject buttons for pending ads
                                    if ad_id and ad_status == 'pending':
                                        st.markdown("**Review:**")
                                        review_cols = st.columns(2)
                                        with review_cols[0]:
                                            if st.button("✅ Approve", key=f"approve_{ad_id}", type="primary"):
                                                if update_ad_status(ad_id, "approved"):
                                                    st.success("Approved!")
                                                    st.rerun()
                                                else:
                                                    st.error("Failed to approve")
                                        with review_cols[1]:
                                            if st.button("❌ Reject", key=f"reject_{ad_id}"):
                                                if update_ad_status(ad_id, "rejected"):
                                                    st.warning("Rejected")
                                                    st.rerun()
                                                else:
                                                    st.error("Failed to reject")

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
