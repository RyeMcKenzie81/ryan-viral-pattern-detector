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
from datetime import datetime, timedelta
from uuid import UUID

# Initialize export list
if "export_ads" not in st.session_state:
    st.session_state.export_ads = []

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

# Export count indicator in sidebar
_export_count = len(st.session_state.get("export_ads", []))
if _export_count > 0:
    st.sidebar.markdown(f"📦 **Export List: {_export_count}** item{'s' if _export_count != 1 else ''}")

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

def get_ad_runs_count(
    brand_id: str = None,
    org_id: str = None,
    angle_id: str = None,
    date_range: tuple = None,
    product_id: str = None,
) -> int:
    """Get total count of ad runs for pagination.

    Args:
        brand_id: Optional brand UUID to scope (or 'all' / None for no scope)
        org_id: Org UUID to scope when brand_id is 'all' / None
        angle_id: Optional belief_angles.id to filter to runs testing one angle
        date_range: Optional (start_date, end_date) tuple of datetime.date
            objects to filter ad_runs.created_at server-side.
        product_id: Optional product UUID to filter to runs for one specific
            product. When set, takes precedence over the brand/org product scope.
    """
    try:
        db = get_supabase_client()
        query = db.table("ad_runs").select("id", count="exact")

        # Product filter wins over brand/org scope when set — it's the more
        # specific constraint and Martin Clinic users picking "Big Three" don't
        # also need their brand_id re-applied (it's a subset).
        if product_id and product_id != "all":
            query = query.eq("product_id", product_id)
        elif brand_id and brand_id != "all":
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

        if angle_id:
            query = query.eq("angle_id", angle_id)

        if date_range and len(date_range) == 2 and all(date_range):
            start, end = date_range
            query = query.gte("created_at", start.isoformat()).lte(
                "created_at", (end.isoformat() + "T23:59:59")
            )

        result = query.execute()
        return result.count if result.count else 0
    except Exception as e:
        return 0

def get_ad_runs(
    brand_id: str = None,
    org_id: str = None,
    page: int = 1,
    page_size: int = 25,
    angle_id: str = None,
    date_range: tuple = None,
    product_id: str = None,
):
    """
    Fetch ad runs with product info and stats (paginated).

    Args:
        brand_id: Optional brand ID to filter by
        org_id: Organization ID to filter by (used when brand is "all")
        page: Page number (1-indexed)
        page_size: Number of records per page
        angle_id: Optional belief_angles.id to filter to runs testing one angle
        date_range: Optional (start_date, end_date) tuple of datetime.date
            objects to filter ad_runs.created_at server-side.

    Returns list of ad runs with:
    - run info (id, created_at, status, reference_ad_storage_path, angle_id)
    - product info (name, brand_id)
    - angle info (id, name) — None when ad_run was not angle-driven
    - counts (total_ads, approved_ads)
    """
    try:
        db = get_supabase_client()

        # Calculate offset
        offset = (page - 1) * page_size

        # Build query for ad_runs with product + angle join.
        # belief_angles join uses the angle_id FK added in PR #196 migration.
        query = db.table("ad_runs").select(
            "id, created_at, status, error_message, reference_ad_storage_path, "
            "product_id, parameters, angle_id, "
            "belief_angles(id, name), "
            "products(id, name, brand_id, product_code, brands(id, name, brand_code))"
        ).order("created_at", desc=True)

        # Product filter wins over brand/org scope when set — same reasoning as
        # in get_ad_runs_count above.
        if product_id and product_id != "all":
            query = query.eq("product_id", product_id)
        elif brand_id and brand_id != "all":
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

        if angle_id:
            query = query.eq("angle_id", angle_id)

        if date_range and len(date_range) == 2 and all(date_range):
            start, end = date_range
            query = query.gte("created_at", start.isoformat()).lte(
                "created_at", (end.isoformat() + "T23:59:59")
            )

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

def get_angles_with_runs(
    org_id: str = None,
    brand_id: str = None,
    product_id: str = None,
) -> list:
    """
    Return the distinct belief_angles that have at least one ad_run in the
    user's scope. Powers the "Filter by angle" dropdown on Ad History.

    Sorted alphabetically by angle name. Excludes angles with no runs so the
    dropdown stays useful (no dead "angle exists but no ads tested it" entries).

    Scope narrowing (most-specific wins): product_id > brand_id > org_id.

    Returns: List[{"id": str, "name": str, "status": str}]
    """
    try:
        db = get_supabase_client()

        # Step 1: figure out the product_ids in scope (mirrors get_ad_runs).
        # Product_id takes precedence: when a specific product is selected, the
        # angle dropdown should only show angles tested on that product.
        product_ids: list | None = None
        if product_id and product_id != "all":
            product_ids = [product_id]
        elif brand_id and brand_id != "all":
            product_ids = _get_product_ids_for_brand(db, brand_id)
            if not product_ids:
                return []
        elif org_id and org_id != "all":
            product_ids = _get_product_ids_for_org(db, org_id)
            if not product_ids:
                return []

        # Step 2: pull distinct angle_ids from ad_runs in scope (NULL excluded).
        # PostgREST doesn't expose DISTINCT, so we pull a bounded set and dedupe
        # in Python — fine because most users have <100 angles.
        runs_query = db.table("ad_runs").select("angle_id").not_.is_("angle_id", "null")
        if product_ids is not None:
            runs_query = runs_query.in_("product_id", product_ids)
        runs_rows = runs_query.limit(5000).execute().data or []
        angle_ids = sorted({r["angle_id"] for r in runs_rows if r.get("angle_id")})
        if not angle_ids:
            return []

        # Step 3: hydrate the names from belief_angles
        angles_rows = (
            db.table("belief_angles")
            .select("id, name, status")
            .in_("id", angle_ids)
            .execute()
            .data
            or []
        )
        return sorted(angles_rows, key=lambda a: (a.get("name") or "").lower())
    except Exception as e:
        st.warning(f"Could not load angle list: {e}")
        return []


def get_ads_for_run(ad_run_id: str):
    """Fetch all generated ads for a specific run."""
    try:
        db = get_supabase_client()
        result = db.table("generated_ads").select(
            "id, prompt_index, storage_path, hook_text, final_status, "
            "claude_review, gemini_review, reviewers_agree, created_at, "
            "model_requested, model_used, generation_time_ms, generation_retries, "
            "parent_ad_id, edit_parent_id, variant_size, is_imported, canvas_size"
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

# =====================================================================
# Review-detail rendering
#
# Two review schemas exist on generated_ads.claude_review / .gemini_review:
#
#   Legacy V1 shape:
#       {overall_quality, status, notes, product_issues[], text_issues[], ai_artifacts[]}
#
#   V2 shape (current — all angle-driven ads land here):
#       {final_status, weighted_score, auto_rejected_check,
#        review_check_scores: {V1-V9, C1-C5, G1-G2},
#        stage2_result: {scores, weighted}, stage3_result: {...} | null}
#
# The old renderer assumed V1, so V2 ads showed "Claude: N/A" with no
# explanation. _render_review_details below dispatches on shape and shows
# the right thing — weighted score, the auto-reject reason translated to
# human language, and weak dimensions for V2; the original fields for V1.
#
# Check codes come from viraltracker/pipelines/ad_creation_v2/services/review_service.py:493-516
# =====================================================================

CHECK_LABELS = {
    # Visual checks
    "V1": "Product accuracy",
    "V2": "Text readability",
    "V3": "Layout accuracy",
    "V4": "Color consistency",
    "V5": "Spacing/alignment",
    "V6": "Image resolution",
    "V7": "Background quality",
    "V8": "Font quality",
    "V9": "AI artifacts (extra fingers, distortions)",
    # Content checks
    "C1": "Hook effectiveness",
    "C2": "Brand consistency",
    "C3": "CTA clarity",
    "C4": "Message coherence",
    "C5": "Offer accuracy (no hallucinated discounts)",
    # Congruence checks
    "G1": "Headline-offer alignment",
    "G2": "Visual-message alignment",
}

WEAK_SCORE_THRESHOLD = 5.0


def _is_v2_review(review: dict) -> bool:
    """Detect the V2 staged-review schema by looking for its load-bearing keys."""
    if not review:
        return False
    return (
        review.get("weighted_score") is not None
        or review.get("review_check_scores")
        or review.get("stage2_result")
    )


def _review_score(review: dict) -> str:
    """Single short display string for the review's headline score.

    V2: 'weighted_score' (or stage2_result.weighted). V1: 'overall_quality'.
    Returns '—' when no review, 'N/A' when neither shape resolves.
    """
    if not review:
        return "—"
    v2 = review.get("weighted_score")
    if v2 is None:
        v2 = (review.get("stage2_result") or {}).get("weighted")
    if isinstance(v2, (int, float)):
        return f"{v2:.1f}"
    v1 = review.get("overall_quality")
    if isinstance(v1, (int, float)):
        return f"{v1:.1f}"
    return str(v1) if v1 else "N/A"


def _render_v2_review(label: str, review: dict) -> None:
    """Render a V2 staged review with weighted score, auto-reject reason, weak dimensions."""
    weighted = review.get("weighted_score")
    if weighted is None:
        weighted = (review.get("stage2_result") or {}).get("weighted")
    scores = review.get("review_check_scores") or (review.get("stage2_result") or {}).get("scores", {})
    auto_reject = review.get("auto_rejected_check")
    final_status = review.get("final_status")

    header = f"**{label}**"
    if isinstance(weighted, (int, float)):
        header += f": {weighted:.2f}/10"
    if final_status:
        header += f"  ·  status: `{final_status}`"
    st.markdown(header)

    if auto_reject:
        reason = CHECK_LABELS.get(auto_reject, auto_reject)
        score = scores.get(auto_reject)
        score_str = f"(scored {score:.1f}/10)" if isinstance(score, (int, float)) else ""
        st.error(f"🚫 Auto-rejected on **{auto_reject}** — {reason} {score_str}")

    weak = sorted(
        [(k, v) for k, v in (scores or {}).items()
         if isinstance(v, (int, float)) and v < WEAK_SCORE_THRESHOLD],
        key=lambda x: x[1],
    )
    if weak:
        st.markdown(f"**Weak dimensions (scored < {WEAK_SCORE_THRESHOLD:.0f}/10):**")
        for k, v in weak:
            human = CHECK_LABELS.get(k, k)
            st.markdown(f"- **{k}** — {human}: {v:.1f}/10")

    stage3 = review.get("stage3_result")
    if isinstance(stage3, dict):
        notes = stage3.get("notes") or stage3.get("explanation") or stage3.get("analysis")
        if notes:
            st.markdown("**Detailed analysis:**")
            st.caption(str(notes))


def _render_v1_review(label: str, review: dict) -> None:
    """Render the legacy V1 review shape (overall_quality + categorical issue lists)."""
    rev_status = review.get("status", "N/A")
    st.markdown(f"**{label}:** {rev_status}")
    if review.get("notes"):
        st.caption(review["notes"])
    for key, heading in [("product_issues", "Product Issues"),
                         ("text_issues", "Text Issues"),
                         ("ai_artifacts", "AI Artifacts")]:
        items = review.get(key, [])
        if items:
            st.markdown(f"_{heading}:_ " + ", ".join(items))


def _render_review_details(claude_review: dict, gemini_review: dict) -> None:
    """Render the body of the 'Review Details' expander.

    Dispatches each review to the right renderer based on shape. Skips reviews
    that are entirely empty (e.g. V2 doesn't use Gemini → gemini_review is null,
    no point showing 'Gemini: nothing').
    """
    for label, rev in [("Claude", claude_review), ("Gemini", gemini_review)]:
        if not rev:
            continue
        if _is_v2_review(rev):
            _render_v2_review(label, rev)
        else:
            _render_v1_review(label, rev)
        st.write("")  # vertical breathing room between reviewer blocks


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

    # Check canvas_size column (set by V2 pipeline)
    canvas_size = ad.get('canvas_size')
    if canvas_size:
        size_map = {
            "1080x1080px": "1:1", "1080x1350px": "4:5",
            "1080x1920px": "9:16", "1920x1080px": "16:9",
        }
        if canvas_size in size_map:
            return size_map[canvas_size]

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

def queue_size_variant_job(ad_id: str, target_sizes: list, brand_id: str = None) -> str:
    """Queue a size variant job for background processing. Returns job ID."""
    import pytz
    PST = pytz.timezone('US/Pacific')
    run_now_time = datetime.now(PST) + timedelta(minutes=1)
    size_label = "/".join(target_sizes)
    job_data = {
        'job_type': 'size_variant',
        'brand_id': brand_id,
        'name': f'Size variants ({size_label}) for {ad_id[:8]}',
        'schedule_type': 'one_time',
        'cron_expression': None,
        'scheduled_at': run_now_time.isoformat(),
        'next_run_at': run_now_time.isoformat(),
        'max_runs': None,
        'parameters': {
            'source_ad_id': ad_id,
            'target_sizes': target_sizes,
        },
    }
    try:
        db = get_supabase_client()
        result = db.table("scheduled_jobs").insert(job_data).execute()
        return result.data[0]['id'] if result.data else None
    except Exception as e:
        st.error(f"Failed to queue size variant job: {e}")
        return None

def queue_smart_edit_job(
    ad_id: str, edit_prompt: str, temperature: float = 0.3,
    preserve_text: bool = True, preserve_colors: bool = True,
    reference_image_ids: list = None, brand_id: str = None,
) -> str:
    """Queue a smart edit job for background processing. Returns job ID."""
    import pytz
    PST = pytz.timezone('US/Pacific')
    run_now_time = datetime.now(PST) + timedelta(minutes=1)
    short_prompt = edit_prompt[:40].replace('\n', ' ')
    job_data = {
        'job_type': 'smart_edit',
        'brand_id': brand_id,
        'name': f'Smart Edit: "{short_prompt}" on {ad_id[:8]}',
        'schedule_type': 'one_time',
        'cron_expression': None,
        'scheduled_at': run_now_time.isoformat(),
        'next_run_at': run_now_time.isoformat(),
        'max_runs': None,
        'parameters': {
            'source_ad_id': ad_id,
            'edit_prompt': edit_prompt,
            'temperature': temperature,
            'preserve_text': preserve_text,
            'preserve_colors': preserve_colors,
            'reference_image_ids': reference_image_ids,
        },
    }
    try:
        db = get_supabase_client()
        result = db.table("scheduled_jobs").insert(job_data).execute()
        return result.data[0]['id'] if result.data else None
    except Exception as e:
        st.error(f"Failed to queue smart edit job: {e}")
        return None


def queue_evolution_job(ad_id: str, mode: str, brand_id: str = None) -> str:
    """Queue a winner evolution job for background processing. Returns job ID."""
    import pytz
    PST = pytz.timezone('US/Pacific')
    run_now_time = datetime.now(PST) + timedelta(minutes=1)
    mode_label = mode.replace("_", " ").title()
    job_data = {
        'job_type': 'winner_evolution',
        'brand_id': brand_id,
        'name': f'{mode_label} for {ad_id[:8]}',
        'schedule_type': 'one_time',
        'cron_expression': None,
        'scheduled_at': run_now_time.isoformat(),
        'next_run_at': run_now_time.isoformat(),
        'max_runs': None,
        'parameters': {
            'parent_ad_id': ad_id,
            'evolution_mode': mode,
        },
    }
    try:
        db = get_supabase_client()
        result = db.table("scheduled_jobs").insert(job_data).execute()
        return result.data[0]['id'] if result.data else None
    except Exception as e:
        st.error(f"Failed to queue evolution job: {e}")
        return None


async def delete_ad_async(ad_id: str, delete_variants: bool = True, unlink_edits: bool = False) -> dict:
    """Delete an ad using the AdCreationService."""
    service = get_ad_creation_service()
    return await service.delete_generated_ad(
        ad_id=UUID(ad_id),
        delete_variants=delete_variants,
        unlink_edits=unlink_edits
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

# Initialize pagination + filter state
if 'ad_history_page' not in st.session_state:
    st.session_state.ad_history_page = 1
if 'expanded_run_id' not in st.session_state:
    st.session_state.expanded_run_id = None
if 'ad_history_angle_filter' not in st.session_state:
    st.session_state.ad_history_angle_filter = "all"
if 'ad_history_date_range' not in st.session_state:
    st.session_state.ad_history_date_range = ()
if 'ad_history_product_filter' not in st.session_state:
    st.session_state.ad_history_product_filter = "all"

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

# Brand + Product as primary scope (cascading: product list narrows by brand).
# Filters apply server-side and AND together with the angle/date filters below.
bcol, pcol = st.columns(2)

with bcol:
    selected_brand = st.selectbox(
        "Filter by Brand",
        options=list(brand_options.keys()),
        format_func=lambda x: brand_options[x],
        key="brand_filter",
        on_change=lambda: (
            setattr(st.session_state, 'ad_history_page', 1),
            # Reset product selection when brand changes — old product may not
            # belong to new brand
            setattr(st.session_state, 'ad_history_product_filter', "all"),
        )
    )

brand_filter = selected_brand if selected_brand != "all" else None

with pcol:
    # Product list scoped by selected brand. If no brand selected, list spans
    # the whole org (could be long — same as the Ad Scheduler / AC2 pattern).
    db_for_products = get_supabase_client()
    if brand_filter:
        product_ids_in_scope = _get_product_ids_for_brand(db_for_products, brand_filter)
    else:
        product_ids_in_scope = _get_product_ids_for_org(db_for_products, org_id)

    product_rows = []
    if product_ids_in_scope:
        product_rows = (
            db_for_products.table("products")
            .select("id, name")
            .in_("id", product_ids_in_scope)
            .order("name")
            .execute()
            .data
            or []
        )

    product_options = {"all": "All Products"}
    for p in product_rows:
        product_options[p["id"]] = p["name"]

    # Guard stale selection (brand changed → product may not be in new scope)
    if st.session_state.ad_history_product_filter not in product_options:
        st.session_state.ad_history_product_filter = "all"

    st.selectbox(
        "Filter by Product",
        options=list(product_options.keys()),
        format_func=lambda x: product_options[x],
        key="ad_history_product_filter",
        help=f"{len(product_rows)} product(s) in scope. Pick one to narrow further.",
        on_change=lambda: setattr(st.session_state, 'ad_history_page', 1),
    )

product_filter = (
    st.session_state.ad_history_product_filter
    if st.session_state.ad_history_product_filter != "all"
    else None
)

# Advanced filters — angle + date range. Collapsed by default so the page
# doesn't grow taller for users who don't need filtering. Both filters reset
# pagination to page 1 on change to avoid landing on an empty page N.
with st.expander("🔍 Advanced filters", expanded=False):
    fcol1, fcol2 = st.columns(2)
    with fcol1:
        # Angle filter — populated from belief_angles that have at least one
        # ad_run in the user's CURRENT scope (brand + product). Switching either
        # narrows / widens the dropdown accordingly.
        angles_with_runs = get_angles_with_runs(
            org_id=org_id, brand_id=brand_filter, product_id=product_filter,
        )
        angle_options = {"all": "All angles"}
        for a in angles_with_runs:
            angle_options[a["id"]] = a["name"]

        # Guard stale selection when scope changes
        if st.session_state.ad_history_angle_filter not in angle_options:
            st.session_state.ad_history_angle_filter = "all"

        st.selectbox(
            "Filter by angle",
            options=list(angle_options.keys()),
            format_func=lambda x: angle_options[x],
            key="ad_history_angle_filter",
            help=f"{len(angles_with_runs)} angle(s) have at least one ad_run in scope. "
                 "Pick one to see only runs testing it.",
            on_change=lambda: setattr(st.session_state, 'ad_history_page', 1),
        )
    with fcol2:
        st.date_input(
            "Filter by date range (optional)",
            value=st.session_state.ad_history_date_range or (),
            key="ad_history_date_range",
            help="Pick start + end dates to scope runs to a window. Leave empty for all time.",
            on_change=lambda: setattr(st.session_state, 'ad_history_page', 1),
        )

# Resolve filter values for the query (None = no filter)
angle_filter = (
    st.session_state.ad_history_angle_filter
    if st.session_state.ad_history_angle_filter != "all"
    else None
)
_dr = st.session_state.ad_history_date_range
date_filter = _dr if isinstance(_dr, (tuple, list)) and len(_dr) == 2 and all(_dr) else None

st.markdown("---")

# Get total count and fetch paginated ad runs
total_count = get_ad_runs_count(
    brand_filter,
    org_id=org_id,
    angle_id=angle_filter,
    date_range=date_filter,
    product_id=product_filter,
)
total_pages = max(1, (total_count + PAGE_SIZE - 1) // PAGE_SIZE)

# Ensure current page is valid
if st.session_state.ad_history_page > total_pages:
    st.session_state.ad_history_page = 1

with st.spinner("Loading ad runs..."):
    ad_runs = get_ad_runs(
        brand_filter,
        org_id=org_id,
        page=st.session_state.ad_history_page,
        page_size=PAGE_SIZE,
        angle_id=angle_filter,
        date_range=date_filter,
        product_id=product_filter,
    )

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
            # Show belief angle name when run was angle-driven (PR #196 stamping)
            angle_info = run.get("belief_angles") or {}
            angle_name = angle_info.get("name") if isinstance(angle_info, dict) else None
            angle_chip = f" | 🎯 _{angle_name}_" if angle_name else ""

            if job_name:
                st.markdown(
                    f"**{product_name}** | `{run_id_short}` | {date_str} | "
                    f"📅 _{job_name}_{angle_chip}"
                )
            else:
                st.markdown(f"**{product_name}** | `{run_id_short}` | {date_str}{angle_chip}")

        with col_stats:
            approval_pct = int(approved_ads/total_ads*100) if total_ads > 0 else 0
            if status == 'failed':
                error_msg = run.get('error_message') or ''
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

                col_btn1, col_btn2, col_btn3, col_btn4 = st.columns([1, 1, 1, 1])

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

                with col_btn4:
                    if ads:
                        _existing_ad_ids = {e.get("ad_id") for e in st.session_state.export_ads}
                        _exportable = [a for a in ads if a.get('storage_path') and str(a.get('id', '')) not in _existing_ad_ids]
                        if _exportable:
                            if st.button(f"📦 Add {len(_exportable)} to Export", key=f"export_run_{run_id_full}", use_container_width=True):
                                product_data = run.get('products', {}) or {}
                                brand_data = product_data.get('brands', {}) or {}
                                bc = brand_data.get('brand_code', 'XX')
                                pc = product_data.get('product_code', 'XX')
                                from viraltracker.ui.export_utils import get_format_code_from_spec
                                for ad in _exportable:
                                    st.session_state.export_ads.append({
                                        "storage_path": ad['storage_path'],
                                        "brand_code": bc,
                                        "product_code": pc,
                                        "run_id": str(run_id_full),
                                        "ad_id": str(ad.get('id', '')),
                                        "format_code": get_format_code_from_spec(ad.get('prompt_spec', {})),
                                        "ext": "png",
                                    })
                                st.rerun()
                        else:
                            st.caption("✅ All in export")

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

                                    # Review scores — shape-aware. V2 reviews (current pipeline)
                                    # use weighted_score; legacy V1 uses overall_quality.
                                    # _review_score / _render_review_details handle both.
                                    # V2 has Claude only (no Gemini), so the summary line skips
                                    # Gemini entirely when its review is empty to avoid noisy
                                    # "Gemini: N/A" on every modern ad.
                                    claude_review = ad.get('claude_review') or {}
                                    gemini_review = ad.get('gemini_review') or {}

                                    claude_str = _review_score(claude_review)
                                    summary_parts = [f"Claude: {claude_str}"]
                                    if gemini_review:
                                        summary_parts.append(f"Gemini: {_review_score(gemini_review)}")
                                    agree_icon = "✅" if ad.get('reviewers_agree') else "⚠️"
                                    st.caption(" | ".join(summary_parts) + f" {agree_icon}")

                                    # Show rejection/flagged reasons
                                    if ad_status in ('rejected', 'flagged', 'needs_revision'):
                                        with st.expander("Review Details"):
                                            _render_review_details(claude_review, gemini_review)

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

                                    # Export button
                                    if ad_id and ad.get('storage_path'):
                                        _already_exported = any(e.get("ad_id") == str(ad_id) for e in st.session_state.export_ads)
                                        if _already_exported:
                                            st.caption("✅ In export list")
                                        elif st.button("📦 Export", key=f"export_ad_{ad_id}"):
                                            product_data = run.get('products', {}) or {}
                                            brand_data = product_data.get('brands', {}) or {}
                                            from viraltracker.ui.export_utils import get_format_code_from_spec
                                            st.session_state.export_ads.append({
                                                "storage_path": ad['storage_path'],
                                                "brand_code": brand_data.get('brand_code', 'XX'),
                                                "product_code": product_data.get('product_code', 'XX'),
                                                "run_id": str(run_id_full),
                                                "ad_id": str(ad_id),
                                                "format_code": get_format_code_from_spec(ad.get('prompt_spec', {})),
                                                "ext": "png",
                                            })
                                            st.rerun()

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

                                            # Generate button — queues a background job
                                            btn_col1, btn_col2 = st.columns(2)
                                            with btn_col1:
                                                if st.button(
                                                    "🚀 Queue Size Variants",
                                                    key=f"generate_variants_{ad_id}",
                                                    disabled=len(selected_sizes) == 0,
                                                ):
                                                    run_brand_id = run.get('products', {}).get('brand_id')
                                                    job_id = queue_size_variant_job(
                                                        ad_id=ad_id,
                                                        target_sizes=selected_sizes,
                                                        brand_id=run_brand_id,
                                                    )
                                                    if job_id:
                                                        st.session_state.size_variant_results = {
                                                            "queued": True,
                                                            "job_id": job_id,
                                                            "sizes": selected_sizes,
                                                        }
                                                        st.rerun()

                                            with btn_col2:
                                                if st.button("Cancel", key=f"cancel_sizes_{ad_id}"):
                                                    st.session_state.size_variant_ad_id = None
                                                    st.session_state.size_variant_results = None
                                                    st.rerun()

                                            # Show queued confirmation
                                            if st.session_state.size_variant_results and st.session_state.size_variant_results.get("queued"):
                                                queued = st.session_state.size_variant_results
                                                st.success(
                                                    f"Queued {', '.join(queued['sizes'])} size variants. "
                                                    f"Job will run in ~1 minute."
                                                )
                                                st.caption(f"Job ID: {queued['job_id']}")

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
                                            DIMS_TO_RATIO = {"1080x1080": "1:1", "1080x1350": "4:5", "1080x1920": "9:16", "1920x1080": "16:9"}
                                            _current_ratio = get_ad_current_size(ad)
                                            _current_dims = {"1:1": "1080x1080", "4:5": "1080x1350", "9:16": "1080x1920", "16:9": "1920x1080"}.get(_current_ratio, "1080x1080")
                                            st.info(f"Current size: {_current_ratio} ({_current_dims})")

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

                                            # Action buttons
                                            edit_btn_col1, edit_btn_col2 = st.columns(2)
                                            with edit_btn_col1:
                                                # Use preset if selected, otherwise use text input
                                                final_prompt = selected_preset or edit_prompt
                                                can_generate = bool(final_prompt)

                                                if st.button(
                                                    "🎨 Queue Edit",
                                                    key=f"generate_edit_{ad_id}",
                                                    disabled=not can_generate,
                                                    type="primary"
                                                ):
                                                    run_brand_id = run.get('products', {}).get('brand_id')
                                                    job_id = queue_smart_edit_job(
                                                        ad_id=ad_id,
                                                        edit_prompt=final_prompt,
                                                        temperature=temperature,
                                                        preserve_text=preserve_text,
                                                        preserve_colors=preserve_colors,
                                                        reference_image_ids=selected_ref_images if selected_ref_images else None,
                                                        brand_id=run_brand_id,
                                                    )
                                                    if job_id:
                                                        st.session_state.edit_result = {"queued": True, "job_id": job_id}
                                                        st.rerun()

                                            with edit_btn_col2:
                                                if st.button("Cancel", key=f"cancel_edit_{ad_id}"):
                                                    st.session_state.edit_ad_id = None
                                                    st.session_state.edit_result = None
                                                    st.rerun()

                                            # Show queued confirmation
                                            if st.session_state.edit_result and st.session_state.edit_result.get("queued"):
                                                queued = st.session_state.edit_result
                                                st.success("Edit job queued. Will run in ~1 minute.")
                                                st.caption(f"Job ID: {queued['job_id']}")

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

                                                    # Submit button
                                                    evo_btn_col1, evo_btn_col2 = st.columns(2)
                                                    with evo_btn_col1:
                                                        can_submit = selected_label is not None
                                                        if st.button(
                                                            "🚀 Queue Evolution",
                                                            key=f"submit_evolve_{ad_id}",
                                                            disabled=not can_submit,
                                                            type="primary"
                                                        ):
                                                            selected_mode_val = mode_options[selected_label]
                                                            run_brand_id = run.get('products', {}).get('brand_id')
                                                            job_id = queue_evolution_job(
                                                                ad_id=ad_id,
                                                                mode=selected_mode_val["mode"],
                                                                brand_id=run_brand_id,
                                                            )
                                                            if job_id:
                                                                st.session_state.evolve_result = {
                                                                    "queued": True, "job_id": job_id,
                                                                    "mode": selected_mode_val["mode"],
                                                                }
                                                                st.rerun()

                                                    with evo_btn_col2:
                                                        if st.button("Cancel", key=f"cancel_evolve_{ad_id}"):
                                                            st.session_state.evolve_ad_id = None
                                                            st.session_state.evolve_options = None
                                                            st.session_state.evolve_result = None
                                                            st.rerun()

                                                    # Show queued confirmation
                                                    if st.session_state.evolve_result and st.session_state.evolve_result.get("queued"):
                                                        queued = st.session_state.evolve_result
                                                        mode_label = queued['mode'].replace('_', ' ').title()
                                                        st.success(f"{mode_label} job queued. Will run in ~1 minute.")
                                                        st.caption(f"Job ID: {queued['job_id']}")

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
                                            variant_count = 0
                                            edit_count = 0
                                            if is_variant:
                                                st.caption("This will delete this size variant.")
                                            else:
                                                variant_count = len([a for a in ads if a.get('parent_ad_id') == ad_id])
                                                edit_count = len([a for a in ads if a.get('edit_parent_id') == ad_id])
                                                if variant_count > 0:
                                                    st.caption(f"This will also delete {variant_count} size variant(s).")
                                                if edit_count > 0:
                                                    st.caption(f"This ad has {edit_count} smart edit(s).")

                                            if edit_count > 0:
                                                # Show three options: delete all, unlink & delete, cancel
                                                del_col1, del_col2, del_col3 = st.columns(3)
                                                with del_col1:
                                                    if st.button("🗑️ Delete All", key=f"confirm_delete_all_{ad_id}", type="primary"):
                                                        with st.spinner("Deleting..."):
                                                            try:
                                                                result = asyncio.run(delete_ad_async(ad_id, unlink_edits=False))
                                                                st.session_state.delete_confirm_ad_id = None
                                                                deleted = result['deleted_variants']
                                                                st.success(f"Deleted ad and {deleted} child(ren)")
                                                                st.rerun()
                                                            except Exception as e:
                                                                st.error(f"Failed to delete: {e}")
                                                with del_col2:
                                                    if st.button("🔗 Unlink & Delete", key=f"confirm_unlink_{ad_id}"):
                                                        with st.spinner("Unlinking edits and deleting..."):
                                                            try:
                                                                result = asyncio.run(delete_ad_async(ad_id, unlink_edits=True))
                                                                st.session_state.delete_confirm_ad_id = None
                                                                parts = []
                                                                if result['deleted_variants'] > 0:
                                                                    parts.append(f"{result['deleted_variants']} variant(s) deleted")
                                                                if result['unlinked_edits'] > 0:
                                                                    parts.append(f"{result['unlinked_edits']} edit(s) unlinked")
                                                                msg = "Deleted ad"
                                                                if parts:
                                                                    msg += f" ({', '.join(parts)})"
                                                                st.success(msg)
                                                                st.rerun()
                                                            except Exception as e:
                                                                st.error(f"Failed to delete: {e}")
                                                with del_col3:
                                                    if st.button("Cancel", key=f"cancel_delete_{ad_id}"):
                                                        st.session_state.delete_confirm_ad_id = None
                                                        st.rerun()
                                            else:
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
