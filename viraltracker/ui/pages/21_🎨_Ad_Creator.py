"""
Ad Creator - Generate Facebook ad variations with AI.

This page allows users to:
- Select a product from the database
- Choose the number of ad variations (1-15)
- Upload a reference ad or select from existing templates
- Run the ad creation workflow
- View generated ads with approval status
"""

import streamlit as st
import base64
import asyncio
import logging
from pathlib import Path
from datetime import datetime
from uuid import UUID

# Handle Streamlit's event loop for async operations
import nest_asyncio
nest_asyncio.apply()

logger = logging.getLogger(__name__)

# Page config
st.set_page_config(
    page_title="Ad Creator",
    page_icon="🎨",
    layout="wide"
)

# Authentication
from viraltracker.ui.auth import require_auth
require_auth()

# Initialize session state
if 'workflow_running' not in st.session_state:
    st.session_state.workflow_running = False
if 'workflow_result' not in st.session_state:
    st.session_state.workflow_result = None
if 'workflow_error' not in st.session_state:
    st.session_state.workflow_error = None
if 'selected_product' not in st.session_state:
    st.session_state.selected_product = None
if 'num_variations' not in st.session_state:
    st.session_state.num_variations = 5
if 'content_source' not in st.session_state:
    st.session_state.content_source = "hooks"
if 'color_mode' not in st.session_state:
    st.session_state.color_mode = "original"
if 'image_selection_mode' not in st.session_state:
    st.session_state.image_selection_mode = "auto"
if 'selected_image_paths' not in st.session_state:
    st.session_state.selected_image_paths = []  # List of up to 2 image paths
if 'reference_source' not in st.session_state:
    st.session_state.reference_source = "Upload New"
if 'selected_template' not in st.session_state:
    st.session_state.selected_template = None
if 'selected_template_storage' not in st.session_state:
    st.session_state.selected_template_storage = None
if 'templates_visible' not in st.session_state:
    st.session_state.templates_visible = 30
if 'export_destination' not in st.session_state:
    st.session_state.export_destination = "none"
if 'export_email' not in st.session_state:
    st.session_state.export_email = ""
if 'export_slack_webhook' not in st.session_state:
    st.session_state.export_slack_webhook = ""
if 'selected_scraped_template' not in st.session_state:
    st.session_state.selected_scraped_template = None
if 'scraped_template_category' not in st.session_state:
    st.session_state.scraped_template_category = "all"
if 'selected_persona_id' not in st.session_state:
    st.session_state.selected_persona_id = None
if 'selected_variant_id' not in st.session_state:
    st.session_state.selected_variant_id = None
# Offer Variant (landing page angle) state
if 'selected_offer_variant_id' not in st.session_state:
    st.session_state.selected_offer_variant_id = None
# Belief First mode state
if 'selected_offer_id' not in st.session_state:
    st.session_state.selected_offer_id = None
if 'selected_jtbd_id' not in st.session_state:
    st.session_state.selected_jtbd_id = None
if 'selected_angle_id' not in st.session_state:
    st.session_state.selected_angle_id = None
if 'selected_angle_data' not in st.session_state:
    st.session_state.selected_angle_data = None
if 'match_template_structure' not in st.session_state:
    st.session_state.match_template_structure = False
if 'additional_instructions' not in st.session_state:
    st.session_state.additional_instructions = ""
if 'selected_templates_for_generation' not in st.session_state:
    st.session_state.selected_templates_for_generation = []  # List of {source, id, name, storage_path, bucket}
if 'multi_template_progress' not in st.session_state:
    st.session_state.multi_template_progress = None  # {current: int, total: int, results: []}
if 'multi_template_results' not in st.session_state:
    st.session_state.multi_template_results = None  # Final batch results
# Template recommendation filter state
if 'template_rec_filter' not in st.session_state:
    st.session_state.template_rec_filter = "all"  # all, recommended, unused_recommended


def toggle_template_selection(template_info: dict):
    """Toggle a template in the selection list.

    Args:
        template_info: Dict with {source, id, name, storage_path, bucket}
    """
    current_selections = st.session_state.selected_templates_for_generation

    # Check if already selected by id
    existing_idx = next(
        (i for i, t in enumerate(current_selections) if t['id'] == template_info['id']),
        None
    )

    if existing_idx is not None:
        # Remove from selection
        current_selections.pop(existing_idx)
    else:
        # Add to selection
        current_selections.append(template_info)

    st.session_state.selected_templates_for_generation = current_selections


def is_template_selected(template_id: str) -> bool:
    """Check if a template is currently selected."""
    return any(t['id'] == template_id for t in st.session_state.selected_templates_for_generation)


def clear_template_selections():
    """Clear all template selections."""
    st.session_state.selected_templates_for_generation = []


def get_supabase_client():
    """Get Supabase client."""
    from viraltracker.core.database import get_supabase_client
    return get_supabase_client()


def get_personas_for_product(product_id: str):
    """Get personas linked to a product for the persona selector."""
    try:
        from viraltracker.services.ad_creation_service import AdCreationService
        from uuid import UUID
        service = AdCreationService()
        return service.get_personas_for_product(UUID(product_id))
    except Exception as e:
        st.warning(f"Could not load personas: {e}")
        return []


def get_variants_for_product(product_id: str):
    """Get variants for a product for the variant selector."""
    try:
        db = get_supabase_client()
        result = db.table("product_variants").select(
            "id, name, slug, variant_type, description, is_default, is_active"
        ).eq("product_id", product_id).eq("is_active", True).order("display_order").execute()
        return result.data or []
    except Exception as e:
        return []


def get_offer_variants_for_product(product_id: str):
    """Get offer variants (landing page angles) for a product."""
    try:
        from viraltracker.services.product_offer_variant_service import ProductOfferVariantService
        from uuid import UUID
        service = ProductOfferVariantService()
        return service.get_offer_variants(UUID(product_id), active_only=True)
    except Exception as e:
        return []


def get_products():
    """Fetch products from database filtered by current organization."""
    from viraltracker.ui.utils import get_current_organization_id

    try:
        db = get_supabase_client()
        org_id = get_current_organization_id()

        # Base query with brand info
        query = db.table("products").select(
            "id, name, brand_id, target_audience, brands(id, name, brand_colors, brand_fonts, organization_id)"
        )

        # Filter by organization (unless superuser "all" mode)
        if org_id and org_id != "all":
            # Get brand IDs for this organization first
            brand_result = db.table("brands").select("id").eq("organization_id", org_id).execute()
            brand_ids = [b["id"] for b in (brand_result.data or [])]

            if not brand_ids:
                return []

            # Filter products by those brands
            query = query.in_("brand_id", brand_ids)

        result = query.order("name").execute()
        return result.data
    except Exception as e:
        st.error(f"Failed to fetch products: {e}")
        return []


def get_brand_colors(brand_id: str) -> dict:
    """Get brand colors for a specific brand."""
    try:
        db = get_supabase_client()
        result = db.table("brands").select("brand_colors, brand_fonts").eq("id", brand_id).execute()
        if result.data:
            return result.data[0]
        return {}
    except Exception as e:
        return {}


def get_product_images(product_id: str) -> list:
    """Get all images for a product with analysis data from product_images table.

    Only returns actual image files (not PDFs).
    """
    try:
        db = get_supabase_client()

        # Supported image formats
        image_extensions = ('.jpg', '.jpeg', '.png', '.webp', '.gif')

        # Get product_images table data
        result = db.table("product_images").select(
            "id, storage_path, image_analysis, analyzed_at, is_main"
        ).eq("product_id", product_id).order("is_main", desc=True).execute()

        # Filter to only image files
        images = [
            img for img in (result.data or [])
            if img['storage_path'].lower().endswith(image_extensions)
        ]

        return images
    except Exception as e:
        st.error(f"Error loading images: {e}")
        return []


def get_existing_templates():
    """Get existing reference ad templates from storage, deduplicated by original filename."""
    try:
        db = get_supabase_client()
        # List files in reference-ads bucket (increase limit from default 100)
        result = db.storage.from_("reference-ads").list(path='', options={'limit': 1000})

        # Deduplicate by original filename (files are named {uuid}_{original_filename})
        seen_originals = {}
        for item in result:
            full_name = item.get('name', '')
            if not full_name.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')):
                continue

            # Extract original filename (after UUID prefix)
            # Format: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx_original.jpg
            parts = full_name.split('_', 1)
            if len(parts) == 2 and len(parts[0]) == 36:  # UUID is 36 chars
                original_name = parts[1]
            else:
                original_name = full_name  # No UUID prefix

            # Keep the first (or newest) occurrence of each original filename
            if original_name not in seen_originals:
                seen_originals[original_name] = {
                    'name': original_name,  # Display friendly name
                    'storage_name': full_name,  # Actual file in storage
                    'path': f"reference-ads/{full_name}",
                }

        # Sort by name and return as list
        templates = sorted(seen_originals.values(), key=lambda x: x['name'].lower())
        return templates
    except Exception as e:
        st.warning(f"Could not load existing templates: {e}")
        return []


def get_scraped_templates(
    category: str = None,
    awareness_level: int = None,
    industry_niche: str = None,
    target_sex: str = None,
    limit: int = 50
):
    """Get approved scraped templates from database.

    Args:
        category: Optional category filter (testimonial, quote_card, etc.)
        awareness_level: Optional awareness level (1-5)
        industry_niche: Optional industry/niche filter
        target_sex: Optional target sex filter (male/female/unisex)
        limit: Maximum templates to return

    Returns:
        List of template records with storage paths
    """
    try:
        from viraltracker.services.template_queue_service import TemplateQueueService
        service = TemplateQueueService()
        return service.get_templates(
            category=category if category != "all" else None,
            awareness_level=awareness_level,
            industry_niche=industry_niche if industry_niche != "all" else None,
            target_sex=target_sex if target_sex != "all" else None,
            active_only=True,
            limit=limit
        )
    except Exception as e:
        st.warning(f"Could not load scraped templates: {e}")
        return []


def get_template_categories():
    """Get list of template categories."""
    try:
        from viraltracker.services.template_queue_service import TemplateQueueService
        service = TemplateQueueService()
        return ["all"] + service.get_template_categories()
    except Exception:
        return ["all", "testimonial", "quote_card", "before_after", "product_showcase",
                "ugc_style", "meme", "carousel_frame", "story_format", "other"]


def get_awareness_levels():
    """Get awareness level filter options."""
    try:
        from viraltracker.services.template_queue_service import TemplateQueueService
        return TemplateQueueService().get_awareness_levels()
    except Exception:
        return []


def get_industry_niches():
    """Get industry niche filter options."""
    try:
        from viraltracker.services.template_queue_service import TemplateQueueService
        return TemplateQueueService().get_industry_niches()
    except Exception:
        return []


def get_scraped_template_url(storage_path: str) -> str:
    """Get public URL for scraped template asset."""
    try:
        from viraltracker.services.template_queue_service import TemplateQueueService
        service = TemplateQueueService()
        return service.get_asset_preview_url(storage_path)
    except Exception:
        return ""


def get_template_asset_match(template_id: str, product_id: str) -> dict:
    """Get asset match info for a template.

    Args:
        template_id: UUID string of the template
        product_id: UUID string of the product

    Returns:
        Dict with asset_match_score, missing_assets, warnings, detection_status
    """
    try:
        from viraltracker.services.template_element_service import TemplateElementService
        from uuid import UUID
        service = TemplateElementService()
        return service.match_assets_to_template(UUID(template_id), UUID(product_id))
    except Exception as e:
        logger.debug(f"Asset match check failed: {e}")
        return {"asset_match_score": 1.0, "detection_status": "error"}


def get_asset_badge_html(score: float, detection_status: str = "analyzed") -> str:
    """Generate HTML badge for asset match score.

    Args:
        score: Asset match score 0.0-1.0
        detection_status: Status of element detection

    Returns:
        HTML string for badge
    """
    if detection_status == "not_analyzed":
        return ""  # No badge if not analyzed

    if score >= 1.0:
        return '<span style="background:#28a745;color:white;padding:1px 4px;border-radius:3px;font-size:9px;">All assets</span>'
    elif score >= 0.5:
        pct = int(score * 100)
        return f'<span style="background:#ffc107;color:black;padding:1px 4px;border-radius:3px;font-size:9px;">{pct}% assets</span>'
    else:
        return '<span style="background:#dc3545;color:white;padding:1px 4px;border-radius:3px;font-size:9px;">Missing assets</span>'


def record_template_usage(template_id: str, ad_run_id: str = None):
    """Record that a scraped template was used."""
    try:
        from uuid import UUID
        from viraltracker.services.template_queue_service import TemplateQueueService
        service = TemplateQueueService()
        service.record_template_usage(
            template_id=UUID(template_id),
            ad_run_id=UUID(ad_run_id) if ad_run_id else None
        )
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Failed to record template usage: {e}")


def get_signed_url(storage_path: str) -> str:
    """Get a signed URL for a storage path."""
    try:
        db = get_supabase_client()
        # Parse bucket and path
        parts = storage_path.split('/', 1)
        if len(parts) == 2:
            bucket, path = parts
        else:
            bucket = "generated-ads"
            path = storage_path

        # Get signed URL (valid for 1 hour)
        result = db.storage.from_(bucket).create_signed_url(path, 3600)
        return result.get('signedURL', '')
    except Exception as e:
        return ""


def get_ad_run_details(ad_run_id: str):
    """Fetch ad run details including generated ads."""
    try:
        db = get_supabase_client()

        # Get ad run
        run_result = db.table("ad_runs").select("*").eq("id", ad_run_id).execute()
        if not run_result.data:
            return None

        ad_run = run_result.data[0]

        # Get generated ads
        ads_result = db.table("generated_ads").select("*").eq("ad_run_id", ad_run_id).order("prompt_index").execute()
        ad_run['generated_ads'] = ads_result.data

        return ad_run
    except Exception as e:
        st.error(f"Failed to fetch ad run: {e}")
        return None


async def run_workflow(
    product_id: str,
    reference_ad_base64: str,
    filename: str,
    num_variations: int,
    content_source: str = "hooks",
    color_mode: str = "original",
    brand_colors: dict = None,
    image_selection_mode: str = "auto",
    selected_image_paths: list = None,
    export_destination: str = "none",
    export_email: str = None,
    export_slack_webhook: str = None,
    product_name: str = None,
    brand_name: str = None,
    persona_id: str = None,
    variant_id: str = None,
    additional_instructions: str = None,
    angle_data: dict = None,
    match_template_structure: bool = False,
    offer_variant_id: str = None
):
    """Run the ad creation workflow with optional export.

    Args:
        product_id: UUID of the product
        reference_ad_base64: Base64-encoded reference ad image
        filename: Original filename of the reference ad
        num_variations: Number of ad variations to generate (1-15)
        content_source: "hooks", "recreate_template", or "belief_first"
        color_mode: "original", "complementary", or "brand"
        brand_colors: Brand color data when color_mode is "brand"
        image_selection_mode: "auto" or "manual"
        selected_image_paths: List of storage paths when mode is "manual" (1-2 images)
        export_destination: "none", "email", "slack", or "both"
        export_email: Email address for email export
        export_slack_webhook: Slack webhook URL (None to use default)
        product_name: Product name for export context
        brand_name: Brand name for export context
        persona_id: Optional persona UUID for targeted ad copy
        variant_id: Optional variant UUID for specific flavor/size
        additional_instructions: Optional run-specific instructions for ad generation
        angle_data: Dict with angle info for belief_first mode {id, name, belief_statement, explanation}
        match_template_structure: If True with belief_first, analyze template and adapt belief to match
        offer_variant_id: Optional offer variant UUID for landing page congruent ad copy
    """
    from pydantic_ai import RunContext
    from pydantic_ai.usage import RunUsage
    from viraltracker.agent.agents.ad_creation_agent import complete_ad_workflow
    from viraltracker.agent.dependencies import AgentDependencies
    from viraltracker.ui.auth import get_current_user_id
    from viraltracker.ui.utils import get_current_organization_id

    # Create dependencies with usage tracking context
    deps = AgentDependencies.create(
        project_name="default",
        user_id=get_current_user_id(),
        organization_id=get_current_organization_id()
    )

    # Create RunContext
    ctx = RunContext(
        deps=deps,
        model=None,
        usage=RunUsage()
    )

    # Run workflow
    result = await complete_ad_workflow(
        ctx=ctx,
        product_id=product_id,
        reference_ad_base64=reference_ad_base64,
        reference_ad_filename=filename,
        project_id="",
        num_variations=num_variations,
        content_source=content_source,
        color_mode=color_mode,
        brand_colors=brand_colors,
        image_selection_mode=image_selection_mode,
        selected_image_paths=selected_image_paths,
        persona_id=persona_id,
        variant_id=variant_id,
        additional_instructions=additional_instructions,
        angle_data=angle_data,
        match_template_structure=match_template_structure,
        offer_variant_id=offer_variant_id
    )

    # Handle exports if configured
    if export_destination != "none" and result:
        await handle_export(
            result=result,
            export_destination=export_destination,
            export_email=export_email,
            export_slack_webhook=export_slack_webhook,
            product_name=product_name or "Product",
            brand_name=brand_name or "Brand",
            deps=deps
        )

    return result


async def run_batch_workflow(
    templates: list,
    product_id: str,
    num_variations: int,
    content_source: str = "hooks",
    color_mode: str = "original",
    brand_colors: dict = None,
    image_selection_mode: str = "auto",
    selected_image_paths: list = None,
    export_destination: str = "none",
    export_email: str = None,
    export_slack_webhook: str = None,
    product_name: str = None,
    brand_name: str = None,
    persona_id: str = None,
    variant_id: str = None,
    additional_instructions: str = None,
    angle_data: dict = None,
    match_template_structure: bool = False,
    offer_variant_id: str = None,
    progress_callback=None
) -> dict:
    """Run ad creation workflow for multiple templates sequentially.

    Args:
        templates: List of template dicts with {source, id, name, storage_path, bucket}
        product_id: UUID of the product
        num_variations: Number of ad variations to generate per template
        content_source: "hooks", "recreate_template", or "belief_first"
        color_mode: "original", "complementary", or "brand"
        brand_colors: Brand color data when color_mode is "brand"
        image_selection_mode: "auto" or "manual"
        selected_image_paths: List of storage paths when mode is "manual"
        export_destination: "none", "email", "slack", or "both"
        export_email: Email address for email export
        export_slack_webhook: Slack webhook URL
        product_name: Product name for export context
        brand_name: Brand name for export context
        persona_id: Optional persona UUID
        variant_id: Optional variant UUID
        additional_instructions: Optional run-specific instructions
        angle_data: Dict with angle info for belief_first mode
        match_template_structure: If True with belief_first, analyze template
        offer_variant_id: Optional offer variant UUID
        progress_callback: Optional callback function(current, total, template_name)

    Returns:
        Dict with batch results: {successful: [], failed: [], total: int}
    """
    from viraltracker.core.database import get_supabase_client

    results = {
        'successful': [],
        'failed': [],
        'total': len(templates)
    }

    db = get_supabase_client()

    for idx, template in enumerate(templates):
        template_name = template.get('name', 'Unknown')
        template_id = template.get('id', '')

        # Call progress callback if provided
        if progress_callback:
            progress_callback(idx + 1, len(templates), template_name)

        try:
            # Download template image from storage
            bucket = template.get('bucket', 'reference-ads')
            storage_path = template.get('storage_path', '')

            template_data = db.storage.from_(bucket).download(storage_path)
            reference_ad_base64 = base64.b64encode(template_data).decode('utf-8')

            # Run workflow for this template
            result = await run_workflow(
                product_id=product_id,
                reference_ad_base64=reference_ad_base64,
                filename=template_name,
                num_variations=num_variations,
                content_source=content_source,
                color_mode=color_mode,
                brand_colors=brand_colors,
                image_selection_mode=image_selection_mode,
                selected_image_paths=selected_image_paths,
                export_destination=export_destination,
                export_email=export_email,
                export_slack_webhook=export_slack_webhook,
                product_name=product_name,
                brand_name=brand_name,
                persona_id=persona_id,
                variant_id=variant_id,
                additional_instructions=additional_instructions,
                angle_data=angle_data,
                match_template_structure=match_template_structure,
                offer_variant_id=offer_variant_id
            )

            # Record template usage if scraped template
            if template.get('source') == 'scraped' and result:
                ad_run_id = result.get('ad_run_id')
                if ad_run_id:
                    record_template_usage(template_id=template_id, ad_run_id=ad_run_id)

            results['successful'].append({
                'template_id': template_id,
                'template_name': template_name,
                'ad_run_id': result.get('ad_run_id'),
                'approved_count': result.get('approved_count', 0),
                'generated_count': len(result.get('generated_ads', []))
            })

        except Exception as e:
            logger.error(f"Batch workflow failed for template {template_name}: {e}")
            results['failed'].append({
                'template_id': template_id,
                'template_name': template_name,
                'error': str(e)
            })

    return results


async def handle_export(
    result: dict,
    export_destination: str,
    export_email: str,
    export_slack_webhook: str,
    product_name: str,
    brand_name: str,
    deps
):
    """Handle exporting generated ads to email and/or Slack.

    Args:
        result: The workflow result containing generated_ads
        export_destination: "email", "slack", or "both"
        export_email: Email address for email export
        export_slack_webhook: Custom Slack webhook URL (None for default)
        product_name: Product name for context
        brand_name: Brand name for context
        deps: AgentDependencies for accessing services
    """
    # Collect image URLs for approved ads
    db = get_supabase_client()
    image_urls = []

    generated_ads = result.get('generated_ads', [])
    for ad in generated_ads:
        storage_path = ad.get('storage_path')
        if storage_path and ad.get('final_status') in ['approved', 'flagged']:
            # Get public URL for the image
            signed_url = get_signed_url(storage_path)
            if signed_url:
                image_urls.append(signed_url)

    if not image_urls:
        logger.warning("No approved/flagged ads to export")
        return

    # TODO: Generate ZIP download URL (future enhancement)
    zip_download_url = None

    # Send to Email if configured
    if export_destination in ["email", "both"] and export_email:
        try:
            from viraltracker.services.email_service import AdEmailContent

            content = AdEmailContent(
                product_name=product_name,
                brand_name=brand_name,
                image_urls=image_urls,
                zip_download_url=zip_download_url,
                ad_run_ids=[result.get('ad_run_id')]
            )

            email_result = await deps.email.send_ad_export_email(
                to_email=export_email,
                content=content
            )

            if email_result.success:
                logger.info(f"Email sent successfully to {export_email}")
            else:
                logger.error(f"Email failed: {email_result.error}")

        except Exception as e:
            logger.error(f"Email export failed: {str(e)}")

    # Send to Slack if configured
    if export_destination in ["slack", "both"]:
        try:
            from viraltracker.services.slack_service import AdSlackContent

            content = AdSlackContent(
                product_name=product_name,
                brand_name=brand_name,
                image_urls=image_urls,
                zip_download_url=zip_download_url,
                ad_run_ids=[result.get('ad_run_id')]
            )

            slack_result = await deps.slack.send_ad_export_message(
                content=content,
                webhook_url=export_slack_webhook if export_slack_webhook else None
            )

            if slack_result.success:
                logger.info("Slack message sent successfully")
            else:
                logger.error(f"Slack failed: {slack_result.error}")

        except Exception as e:
            logger.error(f"Slack export failed: {str(e)}")


# ============================================================================
# Main UI
# ============================================================================

st.title("🎨 Ad Creator")
st.markdown("**Generate Facebook ad variations with AI-powered dual review**")

st.divider()

# Check if we have batch results to display
if st.session_state.multi_template_results:
    batch_results = st.session_state.multi_template_results
    successful = batch_results.get('successful', [])
    failed = batch_results.get('failed', [])
    total = batch_results.get('total', 0)

    # Batch summary header
    if failed:
        st.warning(f"⚠️ Batch Processing Complete: {len(successful)}/{total} templates succeeded")
    else:
        st.success(f"✅ Batch Processing Complete: All {total} templates processed successfully!")

    # Metrics
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Templates Processed", total)
    with col2:
        st.metric("Successful", len(successful))
    with col3:
        total_ads = sum(r.get('generated_count', 0) for r in successful)
        st.metric("Total Ads Generated", total_ads)
    with col4:
        total_approved = sum(r.get('approved_count', 0) for r in successful)
        st.metric("Total Approved", total_approved)

    st.divider()

    # Successful runs
    if successful:
        st.subheader("✅ Successful Runs")
        for run in successful:
            run_id = run.get('ad_run_id', '')[:8] if run.get('ad_run_id') else 'N/A'
            template_name = run.get('template_name', 'Unknown')
            gen_count = run.get('generated_count', 0)
            approved = run.get('approved_count', 0)
            st.markdown(f"- **{template_name}**: {gen_count} ads generated, {approved} approved | Run ID: `{run_id}`")

    # Failed runs
    if failed:
        st.subheader("❌ Failed Runs")
        for run in failed:
            template_name = run.get('template_name', 'Unknown')
            error = run.get('error', 'Unknown error')
            st.error(f"**{template_name}**: {error}")

    st.divider()

    # Actions
    col_action1, col_action2 = st.columns(2)
    with col_action1:
        if st.button("🔄 Create More Ads", type="primary", key="batch_more_ads"):
            st.session_state.multi_template_results = None
            st.rerun()
    with col_action2:
        if st.button("📊 View in Ad History", key="batch_view_history"):
            st.switch_page("pages/22_📊_Ad_History.py")

# Check if we have a completed single workflow to display
elif st.session_state.workflow_result:
    result = st.session_state.workflow_result

    # Success header
    st.success(f"✅ Ad Creation Complete!")

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Ads", len(result.get('generated_ads', [])))
    with col2:
        st.metric("Approved", result.get('approved_count', 0))
    with col3:
        st.metric("Rejected", result.get('rejected_count', 0))
    with col4:
        st.metric("Flagged", result.get('flagged_count', 0))

    st.divider()

    # Display generated ads
    st.subheader("Generated Ads")

    generated_ads = result.get('generated_ads', [])

    # Create columns for ads (3 per row)
    for i in range(0, len(generated_ads), 3):
        cols = st.columns(3)
        for j, col in enumerate(cols):
            if i + j < len(generated_ads):
                ad = generated_ads[i + j]
                with col:
                    # Status badge
                    status = ad.get('final_status', 'unknown')
                    if status == 'approved':
                        st.success(f"✅ Ad {ad.get('prompt_index', i+j+1)} - Approved")
                    elif status == 'rejected':
                        st.error(f"❌ Ad {ad.get('prompt_index', i+j+1)} - Rejected")
                    else:
                        st.warning(f"🚩 Ad {ad.get('prompt_index', i+j+1)} - Flagged")

                    # Try to display the image
                    storage_path = ad.get('storage_path', '')
                    if storage_path:
                        signed_url = get_signed_url(storage_path)
                        if signed_url:
                            st.image(signed_url, use_container_width=True)
                        else:
                            st.info(f"📁 {storage_path}")

                    # Review details in expander
                    with st.expander("Review Details"):
                        claude = ad.get('claude_review') or {}
                        gemini = ad.get('gemini_review') or {}

                        st.markdown(f"**Claude:** {claude.get('status', 'N/A')}")
                        if claude.get('reasoning'):
                            st.caption(claude.get('reasoning', '')[:200])

                        st.markdown(f"**Gemini:** {gemini.get('status', 'N/A')}")
                        if gemini.get('reasoning'):
                            st.caption(gemini.get('reasoning', '')[:200])

    st.divider()

    # Button to create more ads
    if st.button("🔄 Create More Ads", type="primary"):
        st.session_state.workflow_result = None
        st.rerun()

else:
    # ============================================================================
    # STEP 1: Content Source (determines entire flow)
    # ============================================================================

    st.subheader("1. Content Source")

    # Reset to hooks if old deprecated value was selected
    if st.session_state.content_source == "belief_plan":
        st.session_state.content_source = "hooks"

    content_options = ["hooks", "recreate_template", "belief_first"]
    current_index = content_options.index(st.session_state.content_source) if st.session_state.content_source in content_options else 0

    content_source = st.radio(
        "How should we create the ad variations?",
        options=content_options,
        index=current_index,
        format_func=lambda x: {
            "hooks": "🎣 Hooks - Use persuasive hooks from your database",
            "recreate_template": "🔄 Recreate - Vary template by product benefits",
            "belief_first": "🎯 Belief First - Use angles from Ad Planning"
        }.get(x, x),
        horizontal=True,
        help="Choose how to generate ad copy variations"
    )
    st.session_state.content_source = content_source

    # Show info banner only for hooks/recreate modes
    if content_source != "belief_first":
        st.info("💡 **For structured belief testing**, select 'Belief First' above or use the [Plan Executor](/Plan_Executor) page.")

    st.divider()

    # Initialize variables
    selected_product = None
    selected_product_id = None
    products = get_products()

    # ============================================================================
    # STEP 2: Product Selection
    # ============================================================================
    st.subheader("2. Select Product")

    if not products:
        st.error("No products found in database")
        st.stop()

    product_options = {p['name']: p['id'] for p in products}

    # Use session state to persist product selection
    if 'selected_product_name' not in st.session_state:
        st.session_state.selected_product_name = list(product_options.keys())[0]

    selected_product_name = st.selectbox(
        "Product",
        options=list(product_options.keys()),
        index=list(product_options.keys()).index(st.session_state.selected_product_name) if st.session_state.selected_product_name in product_options else 0,
        help="Select the product to create ads for",
        key="product_selector"
    )
    st.session_state.selected_product_name = selected_product_name
    selected_product_id = product_options[selected_product_name]
    st.session_state.selected_product = selected_product_id  # For asset badge matching

    # Show product details
    selected_product = next((p for p in products if p['id'] == selected_product_id), None)
    if selected_product:
        st.caption(f"Target Audience: {selected_product.get('target_audience', 'Not specified')}")

    # ============================================================================
    # BELIEF FIRST: Cascading Selectors (Offer → Persona → JTBD → Angle)
    # ============================================================================
    if content_source == "belief_first" and selected_product_id:
        st.divider()
        st.subheader("2b. Belief Framework")
        st.caption("Select the belief angle to use for ad generation")

        from viraltracker.services.planning_service import PlanningService
        from uuid import UUID
        planning_service = PlanningService()

        # A) Offer (Optional)
        offers = planning_service.get_offers_for_product(UUID(selected_product_id))
        offer_options = {"None (skip offer)": None}
        if offers:
            offer_options.update({o.name: str(o.id) for o in offers})

        selected_offer_label = st.selectbox(
            "Offer (Optional)",
            options=list(offer_options.keys()),
            help="Select a promotional offer if applicable",
            key="belief_offer_selector"
        )
        st.session_state.selected_offer_id = offer_options[selected_offer_label]

        # B) Persona (Required)
        personas = planning_service.get_personas_for_product(UUID(selected_product_id))
        if not personas:
            st.warning("No personas found for this product. Create one in Brand Research first.")
            st.session_state.selected_persona_id = None
        else:
            persona_options = {p['name']: p['id'] for p in personas}
            # Find current selection or default to first
            current_persona_label = None
            if st.session_state.selected_persona_id:
                for label, pid in persona_options.items():
                    if pid == st.session_state.selected_persona_id:
                        current_persona_label = label
                        break

            selected_persona_label = st.selectbox(
                "Persona *",
                options=list(persona_options.keys()),
                index=list(persona_options.keys()).index(current_persona_label) if current_persona_label else 0,
                help="Select the target persona",
                key="belief_persona_selector"
            )
            st.session_state.selected_persona_id = persona_options[selected_persona_label]

        # C) JTBD (Required) - filtered by persona + product
        if st.session_state.selected_persona_id:
            jtbds = planning_service.get_jtbd_for_persona_product(
                UUID(st.session_state.selected_persona_id),
                UUID(selected_product_id)
            )
            if not jtbds:
                st.warning("No JTBDs found for this persona/product. Create one in Ad Planning first.")
                st.session_state.selected_jtbd_id = None
            else:
                jtbd_options = {j.name: str(j.id) for j in jtbds}
                # Find current selection or default to first
                current_jtbd_label = None
                if st.session_state.selected_jtbd_id:
                    for label, jid in jtbd_options.items():
                        if jid == st.session_state.selected_jtbd_id:
                            current_jtbd_label = label
                            break

                selected_jtbd_label = st.selectbox(
                    "Job To Be Done *",
                    options=list(jtbd_options.keys()),
                    index=list(jtbd_options.keys()).index(current_jtbd_label) if current_jtbd_label else 0,
                    help="Select the job-to-be-done that frames the angles",
                    key="belief_jtbd_selector"
                )
                st.session_state.selected_jtbd_id = jtbd_options[selected_jtbd_label]

        # D) Angle (Required) - filtered by JTBD
        if st.session_state.selected_jtbd_id:
            angles = planning_service.get_angles_for_jtbd(UUID(st.session_state.selected_jtbd_id))
            if not angles:
                st.warning("No angles found for this JTBD. Create one in Ad Planning first.")
                st.session_state.selected_angle_id = None
                st.session_state.selected_angle_data = None
            else:
                angle_options = {}
                for a in angles:
                    belief_preview = a.belief_statement[:50] + "..." if len(a.belief_statement) > 50 else a.belief_statement
                    label = f"{a.name}: {belief_preview}"
                    angle_options[label] = str(a.id)

                # Find current selection or default to first
                current_angle_label = None
                if st.session_state.selected_angle_id:
                    for label, aid in angle_options.items():
                        if aid == st.session_state.selected_angle_id:
                            current_angle_label = label
                            break

                selected_angle_label = st.selectbox(
                    "Angle *",
                    options=list(angle_options.keys()),
                    index=list(angle_options.keys()).index(current_angle_label) if current_angle_label else 0,
                    help="Select the belief angle to test",
                    key="belief_angle_selector"
                )
                st.session_state.selected_angle_id = angle_options[selected_angle_label]

                # Store full angle data for passing to workflow
                selected_angle = next((a for a in angles if str(a.id) == st.session_state.selected_angle_id), None)
                if selected_angle:
                    st.session_state.selected_angle_data = {
                        "id": str(selected_angle.id),
                        "name": selected_angle.name,
                        "belief_statement": selected_angle.belief_statement,
                        "explanation": selected_angle.explanation or "",
                    }

                    # Show selected angle details
                    with st.expander("Angle Details", expanded=True):
                        st.markdown(f"**Belief:** {selected_angle.belief_statement}")
                        if selected_angle.explanation:
                            st.markdown(f"**Why it works:** {selected_angle.explanation}")

                    # Option to match reference template structure
                    st.session_state.match_template_structure = st.checkbox(
                        "Match reference template structure",
                        value=st.session_state.get('match_template_structure', False),
                        help="Analyze the reference ad's headline style and apply it to your belief statement",
                        key="match_template_structure_checkbox"
                    )

    st.divider()

    # ============================================================================
    # STEP 3: Product Image Selection
    # ============================================================================
    st.subheader("3. Product Image")

    # Fetch product images
    product_images = get_product_images(selected_product_id) if selected_product_id else []

    if not product_images:
        st.warning("⚠️ No product images found. Upload images in the Brand Manager.")
        image_selection_mode = "auto"
        selected_image_paths = []
    else:
        # Check how many are analyzed
        analyzed_count = len([img for img in product_images if img.get('analyzed_at')])
        total_count = len(product_images)

        image_selection_mode = st.radio(
            "How should we select the product image(s)?",
            options=["auto", "manual"],
            index=0 if st.session_state.image_selection_mode == "auto" else 1,
            format_func=lambda x: {
                "auto": f"🤖 Auto-Select - AI picks best 1-2 images ({analyzed_count}/{total_count} analyzed)",
                "manual": "🖼️ Choose Images - Select up to 2 product images"
            }.get(x, x),
            horizontal=True,
            help="Auto-select uses AI analysis to pick up to 2 matching images. Manual lets you choose specific images.",
            disabled=st.session_state.workflow_running
        )
        st.session_state.image_selection_mode = image_selection_mode

        if image_selection_mode == "auto":
            if analyzed_count < total_count:
                st.info(f"💡 Run image analysis in Brand Manager for better auto-selection.")
            if total_count >= 2:
                st.caption("Auto mode will select up to 2 diverse images (e.g., packaging + contents)")
            selected_image_paths = []
        else:
            # Manual selection - show image grid
            st.markdown("**Select up to 2 product images** (1st = primary/hero, 2nd = secondary/contents):")

            # Create columns for image selection
            cols = st.columns(4)
            for idx, img in enumerate(product_images):
                with cols[idx % 4]:
                    storage_path = img.get('storage_path', '')

                    # Get signed URL for display
                    img_url = get_signed_url(storage_path)

                    # Check selection status
                    current_selections = st.session_state.selected_image_paths
                    is_selected = storage_path in current_selections
                    selection_index = current_selections.index(storage_path) + 1 if is_selected else 0

                    # Show image with selection indicator
                    if img_url:
                        # Add border for selected images
                        if selection_index == 1:
                            st.markdown(f"<div style='border: 3px solid #00ff00; border-radius: 4px; padding: 2px;'><img src='{img_url}' style='width:100%;border-radius:2px;'/></div>", unsafe_allow_html=True)
                            st.caption("🥇 **Primary** (hero/packaging)")
                        elif selection_index == 2:
                            st.markdown(f"<div style='border: 3px solid #00aaff; border-radius: 4px; padding: 2px;'><img src='{img_url}' style='width:100%;border-radius:2px;'/></div>", unsafe_allow_html=True)
                            st.caption("🥈 **Secondary** (contents)")
                        else:
                            st.image(img_url, use_container_width=True)
                    else:
                        st.markdown("<div style='height:80px;background:#444;border-radius:4px;'></div>", unsafe_allow_html=True)

                    # Show analysis info if available
                    analysis = img.get('image_analysis')
                    if analysis and not is_selected:
                        quality = analysis.get('quality_score', 0)
                        use_cases = analysis.get('best_use_cases', [])[:2]
                        st.caption(f"⭐ {quality:.2f} | {', '.join(use_cases)}")
                    elif not analysis and not is_selected:
                        st.caption("❓ Not analyzed")

                    # Selection button
                    if is_selected:
                        if st.button("✓ Remove", key=f"img_remove_{img['id']}", use_container_width=True):
                            st.session_state.selected_image_paths.remove(storage_path)
                            st.rerun()
                    else:
                        # Only allow selection if less than 2 already selected
                        can_select = len(current_selections) < 2
                        if st.button(
                            "Select" if can_select else "Max 2",
                            key=f"img_select_{img['id']}",
                            use_container_width=True,
                            disabled=not can_select
                        ):
                            st.session_state.selected_image_paths.append(storage_path)
                            st.rerun()

            selected_image_paths = st.session_state.selected_image_paths

            # Show selection status
            if len(selected_image_paths) == 0:
                st.warning("⚠️ Please select at least 1 image, or switch to Auto-Select mode.")
            elif len(selected_image_paths) == 1:
                st.info("💡 You can optionally select a 2nd image to show product contents or an alternate view.")
            else:
                st.success(f"✅ {len(selected_image_paths)} images selected - primary + secondary")

    st.divider()

    # ============================================================================
    # Persona, Variant, Instructions
    # ============================================================================
    st.subheader("Target Persona (Optional)")

    # Fetch personas for selected product
    personas = get_personas_for_product(selected_product_id) if selected_product_id else []

    if personas:
        # Build persona options - "None" + all personas
        persona_options = {"None - Use product defaults": None}
        for p in personas:
            snapshot = p.get('snapshot', '')[:50] if p.get('snapshot') else ''
            label = f"{p['name']}"
            if snapshot:
                label += f" ({snapshot}...)"
            if p.get('is_primary'):
                label += " ⭐"
            persona_options[label] = p['id']

        # Get current selection label
        current_persona_label = "None - Use product defaults"
        if st.session_state.selected_persona_id:
            for label, pid in persona_options.items():
                if pid == st.session_state.selected_persona_id:
                    current_persona_label = label
                    break

        selected_persona_label = st.selectbox(
            "Select a 4D Persona to target",
            options=list(persona_options.keys()),
            index=list(persona_options.keys()).index(current_persona_label) if current_persona_label in persona_options else 0,
            help="Persona data will inform hook selection and copy generation with emotional triggers and customer voice",
            disabled=st.session_state.workflow_running,
            key="persona_selector"
        )
        st.session_state.selected_persona_id = persona_options[selected_persona_label]

        # Show persona preview if selected
        if st.session_state.selected_persona_id:
            selected_persona = next((p for p in personas if p['id'] == st.session_state.selected_persona_id), None)
            if selected_persona:
                with st.expander("Persona Preview", expanded=False):
                    st.markdown(f"**{selected_persona['name']}**")
                    if selected_persona.get('snapshot'):
                        st.write(selected_persona['snapshot'])

                    # Show key persona data if available (from the full persona)
                    st.caption("💡 Persona data will be used to select hooks and generate copy that resonates with this audience's pain points, desires, and language.")
    else:
        st.info("No personas available for this product. Create personas in Brand Research to enable persona-targeted ad creation.")
        st.session_state.selected_persona_id = None

    st.divider()

    # ============================================================================
    # Product Variant (Optional)
    # ============================================================================
    st.subheader("Product Variant (Optional)")

    # Fetch variants for selected product
    variants = get_variants_for_product(selected_product_id) if selected_product_id else []

    if variants:
        # Build variant options - "Default" + all variants
        variant_options = {"Use default variant": None}
        for v in variants:
            label = f"{v['name']}"
            if v.get('is_default'):
                label += " (default)"
            if v.get('description'):
                label += f" - {v['description'][:40]}..."
            variant_options[label] = v['id']

        # Get current selection label
        current_variant_label = "Use default variant"
        if st.session_state.selected_variant_id:
            for label, vid in variant_options.items():
                if vid == st.session_state.selected_variant_id:
                    current_variant_label = label
                    break

        selected_variant_label = st.selectbox(
            "Select a product variant",
            options=list(variant_options.keys()),
            index=list(variant_options.keys()).index(current_variant_label) if current_variant_label in variant_options else 0,
            help="Choose a specific flavor, size, or variant to feature in ads",
            disabled=st.session_state.workflow_running,
            key="variant_selector"
        )
        st.session_state.selected_variant_id = variant_options[selected_variant_label]

        # Show variant preview if selected
        if st.session_state.selected_variant_id:
            selected_variant = next((v for v in variants if v['id'] == st.session_state.selected_variant_id), None)
            if selected_variant and selected_variant.get('description'):
                st.caption(f"📦 {selected_variant['description']}")
    else:
        st.info("No variants available for this product. Add variants in Brand Manager if needed.")
        st.session_state.selected_variant_id = None

    st.divider()

    # ============================================================================
    # Offer Variant (Landing Page Angle) - Optional
    # ============================================================================
    st.subheader("Offer Variant / Landing Page Angle (Optional)")
    st.caption("Ensures ad copy aligns with specific landing page messaging")

    # Fetch offer variants for selected product
    offer_variants = get_offer_variants_for_product(selected_product_id) if selected_product_id else []

    if offer_variants:
        # Build offer variant options - "Default" + all offer variants
        offer_variant_options = {"Use default messaging": None}
        for ov in offer_variants:
            label = f"{ov['name']}"
            if ov.get('is_default'):
                label += " (default)"
            # Show landing page URL hint
            lp_url = ov.get('landing_page_url', '')
            if lp_url:
                # Extract domain/path for display
                import urllib.parse
                parsed = urllib.parse.urlparse(lp_url)
                path = parsed.path[:30] + '...' if len(parsed.path) > 30 else parsed.path
                label += f" → {parsed.netloc}{path}"
            offer_variant_options[label] = ov['id']

        # Get current selection label
        current_offer_variant_label = "Use default messaging"
        if st.session_state.selected_offer_variant_id:
            for label, ovid in offer_variant_options.items():
                if ovid == st.session_state.selected_offer_variant_id:
                    current_offer_variant_label = label
                    break

        selected_offer_variant_label = st.selectbox(
            "Select an offer variant",
            options=list(offer_variant_options.keys()),
            index=list(offer_variant_options.keys()).index(current_offer_variant_label) if current_offer_variant_label in offer_variant_options else 0,
            help="Select a landing page angle to ensure ad copy matches the destination page messaging",
            disabled=st.session_state.workflow_running,
            key="offer_variant_selector"
        )
        st.session_state.selected_offer_variant_id = offer_variant_options[selected_offer_variant_label]

        # Show offer variant preview if selected
        if st.session_state.selected_offer_variant_id:
            selected_offer_variant = next((ov for ov in offer_variants if ov['id'] == st.session_state.selected_offer_variant_id), None)
            if selected_offer_variant:
                with st.expander("Offer Variant Details", expanded=True):
                    col1, col2 = st.columns(2)
                    with col1:
                        st.markdown("**Pain Points:**")
                        for pp in selected_offer_variant.get('pain_points', [])[:5]:
                            st.write(f"• {pp}")
                    with col2:
                        st.markdown("**Benefits:**")
                        for b in selected_offer_variant.get('benefits', [])[:5]:
                            st.write(f"• {b}")

                    if selected_offer_variant.get('target_audience'):
                        st.markdown(f"**Target Audience:** {selected_offer_variant['target_audience']}")

                    st.caption(f"📎 Landing Page: {selected_offer_variant.get('landing_page_url', 'N/A')}")
    else:
        st.info("No offer variants configured for this product. Ad copy will use default product messaging.")
        st.session_state.selected_offer_variant_id = None

    st.divider()

    # ============================================================================
    # Additional Instructions (Optional)
    # ============================================================================
    st.subheader("Additional Instructions (Optional)")

    # Get brand's default ad creation notes
    brand_ad_notes = ""
    if selected_product and selected_product.get('brands'):
        brand_ad_notes = selected_product['brands'].get('ad_creation_notes') or ""

    # Show brand defaults if they exist
    if brand_ad_notes:
        st.caption(f"📋 **Brand defaults:** {brand_ad_notes[:100]}{'...' if len(brand_ad_notes) > 100 else ''}")

    additional_instructions = st.text_area(
        "Additional instructions for this run",
        value=st.session_state.additional_instructions,
        placeholder="Add any specific instructions for this ad generation run...\n\nExamples:\n- Feature the Brown Sugar flavor prominently\n- Use a summer/outdoor theme\n- Include '20% OFF' badge",
        height=100,
        help="These instructions will be combined with the brand's default ad creation notes",
        disabled=st.session_state.workflow_running,
        key="additional_instructions_input"
    )
    st.session_state.additional_instructions = additional_instructions

    st.divider()

    # ============================================================================
    # Reference Ad
    # ============================================================================
    st.subheader("4. Reference Ad")

    # Initialize reference_ad variables
    reference_ad_base64 = None
    reference_filename = None
    selected_scraped_template_id = None

    # ============================================================================
    # Reference Ad Selection
    # ============================================================================
    reference_options = ["Upload New", "Uploaded Templates", "Scraped Template Library"]
    current_index = 0
    if st.session_state.reference_source == "Use Existing Template":
        current_index = 1
    elif st.session_state.reference_source == "Scraped Template Library":
        current_index = 2

    reference_source = st.radio(
        "Reference ad source",
        options=reference_options,
        index=current_index,
        horizontal=True,
        key="reference_source_radio",
        help="Upload a new image, use previously uploaded templates, or browse scraped templates from competitors"
    )
    # Map back for backwards compatibility
    if reference_source == "Uploaded Templates":
        st.session_state.reference_source = "Use Existing Template"
    else:
        st.session_state.reference_source = reference_source

    if reference_source == "Upload New":
        uploaded_file = st.file_uploader(
            "Upload reference ad image",
            type=['jpg', 'jpeg', 'png', 'webp'],
            help="Upload a high-performing ad to use as a style reference"
        )

        if uploaded_file:
            # Preview
            st.image(uploaded_file, caption="Reference Ad Preview", width=300)

            # Encode to base64
            reference_ad_base64 = base64.b64encode(uploaded_file.read()).decode('utf-8')
            reference_filename = uploaded_file.name
            uploaded_file.seek(0)  # Reset for potential re-read

    elif reference_source == "Uploaded Templates":
        templates = get_existing_templates()
        if templates:
            total_templates = len(templates)
            visible_count = min(st.session_state.templates_visible, total_templates)
            visible_templates = templates[:visible_count]

            # Selection count and clear button
            selected_count = len([t for t in st.session_state.selected_templates_for_generation if t.get('source') == 'uploaded'])
            header_cols = st.columns([3, 1])
            with header_cols[0]:
                st.caption(f"Showing {visible_count} of {total_templates} templates | **{selected_count} selected**")
            with header_cols[1]:
                if selected_count > 0:
                    if st.button("Clear Selection", key="clear_uploaded_selection", use_container_width=True):
                        st.session_state.selected_templates_for_generation = [
                            t for t in st.session_state.selected_templates_for_generation if t.get('source') != 'uploaded'
                        ]
                        st.rerun()

            # Thumbnail grid - 5 columns with checkboxes
            cols = st.columns(5)
            for idx, template in enumerate(visible_templates):
                with cols[idx % 5]:
                    storage_name = template['storage_name']
                    display_name = template['name']
                    template_id = f"uploaded_{storage_name}"  # Unique ID for uploaded templates
                    is_selected = is_template_selected(template_id)

                    # Get signed URL for thumbnail
                    thumb_url = get_signed_url(f"reference-ads/{storage_name}")

                    # Show thumbnail with selection border
                    if thumb_url:
                        border_style = "3px solid #00ff00" if is_selected else "1px solid #333"
                        st.markdown(
                            f'<div style="border:{border_style};border-radius:4px;padding:2px;margin-bottom:4px;">'
                            f'<img src="{thumb_url}" style="width:100%;border-radius:2px;" title="{display_name}"/>'
                            f'</div>',
                            unsafe_allow_html=True
                        )
                    else:
                        st.markdown(
                            f'<div style="height:80px;background:#333;border-radius:4px;'
                            f'display:flex;align-items:center;justify-content:center;font-size:10px;">'
                            f'{display_name[:10]}...</div>',
                            unsafe_allow_html=True
                        )

                    # Checkbox for multi-select
                    if st.checkbox(
                        display_name[:15] + "..." if len(display_name) > 15 else display_name,
                        value=is_selected,
                        key=f"tpl_cb_{idx}",
                        help=display_name
                    ):
                        if not is_selected:
                            # Add to selection
                            toggle_template_selection({
                                'source': 'uploaded',
                                'id': template_id,
                                'name': display_name,
                                'storage_path': storage_name,
                                'bucket': 'reference-ads'
                            })
                            st.rerun()
                    else:
                        if is_selected:
                            # Remove from selection
                            toggle_template_selection({
                                'source': 'uploaded',
                                'id': template_id,
                                'name': display_name,
                                'storage_path': storage_name,
                                'bucket': 'reference-ads'
                            })
                            st.rerun()

            # Load more button
            if visible_count < total_templates:
                remaining = total_templates - visible_count
                if st.button(f"Load More ({remaining} more)", use_container_width=True, key="load_more_uploaded"):
                    st.session_state.templates_visible += 30
                    st.rerun()
        else:
            st.warning("No uploaded templates found. Upload a reference ad first, or use Scraped Template Library.")

    elif reference_source == "Scraped Template Library":
        # Recommendation filter row (product-specific)
        rec_filter_col1, rec_filter_col2, rec_filter_col3 = st.columns([2, 2, 4])
        with rec_filter_col1:
            rec_filter_options = ["All Templates", "Recommended", "Unused Recommended"]
            rec_filter = st.selectbox(
                "Filter by Recommendation",
                options=rec_filter_options,
                index=rec_filter_options.index(
                    {"all": "All Templates", "recommended": "Recommended", "unused_recommended": "Unused Recommended"}.get(
                        st.session_state.template_rec_filter, "All Templates"
                    )
                ),
                key="template_rec_filter_select",
                help="Filter to show only templates recommended for this product"
            )
            st.session_state.template_rec_filter = {
                "All Templates": "all",
                "Recommended": "recommended",
                "Unused Recommended": "unused_recommended"
            }.get(rec_filter, "all")

        with rec_filter_col2:
            # Show recommendation counts if product is selected
            if selected_product_id and st.session_state.template_rec_filter != "all":
                try:
                    from viraltracker.services.template_recommendation_service import TemplateRecommendationService
                    rec_service = TemplateRecommendationService()
                    counts = rec_service.get_recommendation_count(UUID(selected_product_id))
                    if st.session_state.template_rec_filter == "recommended":
                        st.caption(f"{counts['total']} recommended templates")
                    else:
                        st.caption(f"{counts['unused']} unused recommendations")
                except Exception:
                    pass

        # Filter row - 4 columns
        filter_cols = st.columns(4)

        # Category filter
        with filter_cols[0]:
            categories = get_template_categories()
            selected_category = st.selectbox(
                "Category",
                options=categories,
                index=categories.index(st.session_state.scraped_template_category) if st.session_state.scraped_template_category in categories else 0,
                format_func=lambda x: x.replace("_", " ").title() if x != "all" else "All",
                key="filter_category"
            )
            st.session_state.scraped_template_category = selected_category

        # Awareness Level filter
        with filter_cols[1]:
            awareness_opts = [{"value": None, "label": "All"}] + get_awareness_levels()
            selected_awareness = st.selectbox(
                "Awareness Level",
                options=[a["value"] for a in awareness_opts],
                format_func=lambda x: next((a["label"] for a in awareness_opts if a["value"] == x), "All"),
                key="filter_awareness"
            )

        # Industry/Niche filter
        with filter_cols[2]:
            niches = ["all"] + get_industry_niches()
            selected_niche = st.selectbox(
                "Industry/Niche",
                options=niches,
                format_func=lambda x: x.replace("_", " ").title() if x != "all" else "All",
                key="filter_niche"
            )

        # Target Sex filter
        with filter_cols[3]:
            sex_options = ["all", "male", "female", "unisex"]
            selected_sex = st.selectbox(
                "Target Audience",
                options=sex_options,
                format_func=lambda x: x.title() if x != "all" else "All",
                key="filter_sex"
            )

        # Get scraped templates with all filters
        scraped_templates = get_scraped_templates(
            category=selected_category if selected_category != "all" else None,
            awareness_level=selected_awareness,
            industry_niche=selected_niche if selected_niche != "all" else None,
            target_sex=selected_sex if selected_sex != "all" else None,
            limit=100  # Fetch more since we may filter
        )

        # Apply recommendation filter
        if st.session_state.template_rec_filter != "all" and selected_product_id:
            try:
                from viraltracker.services.template_recommendation_service import TemplateRecommendationService
                rec_service = TemplateRecommendationService()
                unused_only = st.session_state.template_rec_filter == "unused_recommended"
                recommended_ids = rec_service.get_recommended_template_ids(
                    UUID(selected_product_id), unused_only=unused_only
                )
                recommended_id_strs = {str(rid) for rid in recommended_ids}
                scraped_templates = [
                    t for t in scraped_templates
                    if t.get('id') in recommended_id_strs
                ]
            except Exception as e:
                logger.warning(f"Failed to filter by recommendations: {e}")

        if scraped_templates:
            # Selection count and clear button
            selected_count = len([t for t in st.session_state.selected_templates_for_generation if t.get('source') == 'scraped'])
            header_cols = st.columns([3, 1])
            with header_cols[0]:
                category_label = f" in '{selected_category.replace('_', ' ').title()}'" if selected_category != "all" else ""
                st.caption(f"Showing {len(scraped_templates)} templates{category_label} | **{selected_count} selected**")
            with header_cols[1]:
                if selected_count > 0:
                    if st.button("Clear Selection", key="clear_scraped_selection", use_container_width=True):
                        st.session_state.selected_templates_for_generation = [
                            t for t in st.session_state.selected_templates_for_generation if t.get('source') != 'scraped'
                        ]
                        st.rerun()

            # Thumbnail grid - 5 columns with checkboxes
            cols = st.columns(5)
            for idx, template in enumerate(scraped_templates):
                with cols[idx % 5]:
                    template_id = template.get('id', '')
                    template_name = template.get('name', 'Unnamed')
                    storage_path = template.get('storage_path', '')
                    category = template.get('category', 'other')
                    times_used = template.get('times_used', 0) or 0

                    is_selected = is_template_selected(template_id)

                    # Get preview URL
                    thumb_url = get_scraped_template_url(storage_path) if storage_path else ""

                    # Show thumbnail with selection border
                    if thumb_url:
                        border_style = "3px solid #00ff00" if is_selected else "1px solid #333"
                        st.markdown(
                            f'<div style="border:{border_style};border-radius:4px;padding:2px;margin-bottom:4px;">'
                            f'<img src="{thumb_url}" style="width:100%;border-radius:2px;" title="{template_name}"/>'
                            f'</div>',
                            unsafe_allow_html=True
                        )
                    else:
                        st.markdown(
                            f'<div style="height:80px;background:#333;border-radius:4px;'
                            f'display:flex;align-items:center;justify-content:center;font-size:10px;">'
                            f'{template_name[:10]}...</div>',
                            unsafe_allow_html=True
                        )

                    # Show template info
                    st.caption(f"📁 {category.replace('_', ' ').title()}")
                    if times_used > 0:
                        st.caption(f"Used {times_used}x")

                    # Show asset match badge if product is selected
                    if st.session_state.selected_product:
                        asset_match = get_template_asset_match(template_id, st.session_state.selected_product)
                        badge_html = get_asset_badge_html(
                            asset_match.get("asset_match_score", 1.0),
                            asset_match.get("detection_status", "unknown")
                        )
                        if badge_html:
                            st.markdown(badge_html, unsafe_allow_html=True)
                            # Show warnings on hover/tooltip via expander if missing
                            warnings = asset_match.get("warnings", [])
                            if warnings:
                                with st.expander("View missing assets", expanded=False):
                                    for w in warnings:
                                        st.caption(f"- {w}")

                    # Parse bucket and path for storage
                    parts = storage_path.split("/", 1) if storage_path else ["", ""]
                    bucket = parts[0] if len(parts) == 2 else "scraped-assets"
                    path = parts[1] if len(parts) == 2 else storage_path

                    # Checkbox for multi-select
                    if st.checkbox(
                        template_name[:15] + "..." if len(template_name) > 15 else template_name,
                        value=is_selected,
                        key=f"scraped_tpl_cb_{idx}",
                        help=template_name
                    ):
                        if not is_selected:
                            # Add to selection
                            toggle_template_selection({
                                'source': 'scraped',
                                'id': template_id,
                                'name': template_name,
                                'storage_path': path,
                                'bucket': bucket
                            })
                            st.rerun()
                    else:
                        if is_selected:
                            # Remove from selection
                            toggle_template_selection({
                                'source': 'scraped',
                                'id': template_id,
                                'name': template_name,
                                'storage_path': path,
                                'bucket': bucket
                            })
                            st.rerun()
        else:
            st.info("No scraped templates found. Use the Template Queue to approve templates from competitor ads.")
            if st.button("Go to Template Queue →"):
                st.switch_page("pages/16_📋_Template_Queue.py")

    # ============================================================================
    # Selected Templates Preview (Multi-select mode)
    # ============================================================================
    selected_templates = st.session_state.selected_templates_for_generation
    if selected_templates:
        st.divider()
        st.subheader(f"📋 Selected Templates ({len(selected_templates)})")
        st.caption("These templates will be processed sequentially with the same settings.")

        # Show selected templates in a compact row with remove buttons
        preview_cols = st.columns(min(len(selected_templates), 6))
        for idx, tpl in enumerate(selected_templates[:6]):  # Show max 6 in row
            with preview_cols[idx]:
                # Get thumbnail URL
                if tpl.get('source') == 'uploaded':
                    thumb_url = get_signed_url(f"reference-ads/{tpl['storage_path']}")
                else:
                    thumb_url = get_scraped_template_url(f"{tpl['bucket']}/{tpl['storage_path']}")

                if thumb_url:
                    st.image(thumb_url, use_container_width=True)
                st.caption(tpl['name'][:20] + "..." if len(tpl['name']) > 20 else tpl['name'])

                if st.button("✕ Remove", key=f"remove_tpl_{idx}", use_container_width=True):
                    st.session_state.selected_templates_for_generation = [
                        t for t in st.session_state.selected_templates_for_generation if t['id'] != tpl['id']
                    ]
                    st.rerun()

        # Show overflow count if more than 6
        if len(selected_templates) > 6:
            st.caption(f"...and {len(selected_templates) - 6} more templates")

        # Clear all button
        if st.button("🗑️ Clear All Selections", use_container_width=False):
            clear_template_selections()
            st.rerun()

    st.divider()

    # ============================================================================
    # Export Destination (Optional)
    # ============================================================================

    st.subheader("4. Export Destination (Optional)")

    export_destination = st.radio(
        "Where should we send the generated ads?",
        options=["none", "email", "slack", "both"],
        index=["none", "email", "slack", "both"].index(st.session_state.export_destination),
        format_func=lambda x: {
            "none": "📁 None - View in browser only",
            "email": "📧 Email - Send image links via email",
            "slack": "💬 Slack - Post to Slack channel",
            "both": "📧💬 Both - Email and Slack"
        }.get(x, x),
        horizontal=False,
        help="Optionally export generated ads to email or Slack",
        disabled=st.session_state.workflow_running,
        key="export_destination_radio"
    )
    st.session_state.export_destination = export_destination

    # Show email input if email or both selected
    if export_destination in ["email", "both"]:
        export_email = st.text_input(
            "Email address",
            value=st.session_state.export_email,
            placeholder="marketing@company.com",
            help="Enter the email address to send the ads to",
            disabled=st.session_state.workflow_running,
            key="export_email_input"
        )
        st.session_state.export_email = export_email

    # Show Slack webhook input if slack or both selected
    if export_destination in ["slack", "both"]:
        # Check if default webhook is configured
        from viraltracker.core.config import Config
        default_webhook = Config.SLACK_WEBHOOK_URL

        if default_webhook:
            use_default = st.checkbox(
                "Use default Slack channel",
                value=True,
                help="Use the Slack channel configured in environment",
                disabled=st.session_state.workflow_running,
                key="use_default_slack"
            )
            if not use_default:
                export_slack_webhook = st.text_input(
                    "Custom Slack Webhook URL",
                    value=st.session_state.export_slack_webhook,
                    placeholder="https://hooks.slack.com/services/...",
                    help="Enter a custom Slack webhook URL for a different channel",
                    disabled=st.session_state.workflow_running,
                    key="slack_webhook_input"
                )
                st.session_state.export_slack_webhook = export_slack_webhook
            else:
                st.session_state.export_slack_webhook = ""  # Will use default
        else:
            export_slack_webhook = st.text_input(
                "Slack Webhook URL",
                value=st.session_state.export_slack_webhook,
                placeholder="https://hooks.slack.com/services/...",
                help="Enter a Slack incoming webhook URL",
                disabled=st.session_state.workflow_running,
                key="slack_webhook_input"
            )
            st.session_state.export_slack_webhook = export_slack_webhook
            st.caption("💡 Set SLACK_WEBHOOK_URL in .env for a default channel")

    st.divider()

    # ============================================================================
    # Configuration Form (for remaining options)
    # ============================================================================

    with st.form("ad_creation_form"):
        st.subheader("5. Number of Variations")

        num_variations = st.slider(
            "How many ad variations to generate?",
            min_value=1,
            max_value=15,
            value=st.session_state.num_variations,
            help="Number of unique ad variations to create",
            disabled=st.session_state.workflow_running
        )
        st.session_state.num_variations = num_variations

        variation_source = {
            "hooks": "hooks",
            "recreate_template": "benefits/USPs"
        }.get(content_source, "hooks")
        st.caption(f"Will generate {num_variations} ads using different {variation_source}")

        st.divider()

        st.subheader("6. Color Scheme")

        # Check if selected product has brand colors
        brand_colors_available = False
        brand_color_preview = ""
        if selected_product and selected_product.get('brands'):
            brand_data = selected_product.get('brands', {})
            if brand_data and brand_data.get('brand_colors'):
                brand_colors_available = True
                colors = brand_data.get('brand_colors', {})
                color_list = colors.get('all', [])
                if color_list:
                    brand_color_preview = f" ({', '.join(color_list[:3])})"

        # Build color mode options
        color_options = ["original", "complementary"]
        color_labels = {
            "original": "🎨 Original - Use colors from the reference ad template",
            "complementary": "🌈 Complementary - Generate fresh, eye-catching color scheme"
        }

        if brand_colors_available:
            color_options.append("brand")
            brand_name = selected_product.get('brands', {}).get('name', 'Brand')
            color_labels["brand"] = f"🏷️ Brand Colors - Use {brand_name} official colors{brand_color_preview}"

        # Determine default index
        current_mode = st.session_state.color_mode
        if current_mode in color_options:
            default_index = color_options.index(current_mode)
        else:
            default_index = 0

        color_mode = st.radio(
            "What colors should we use?",
            options=color_options,
            index=default_index,
            format_func=lambda x: color_labels.get(x, x),
            horizontal=False,
            help="Choose the color scheme for the generated ads",
            disabled=st.session_state.workflow_running
        )
        st.session_state.color_mode = color_mode

        if color_mode == "original":
            st.info("💡 Colors will be extracted from your reference ad and applied to the new variations.")
        elif color_mode == "complementary":
            st.info("💡 AI will generate a fresh complementary color scheme optimized for Facebook ads.")
        elif color_mode == "brand":
            colors = selected_product.get('brands', {}).get('brand_colors', {})
            primary = colors.get('primary_name', colors.get('primary', ''))
            secondary = colors.get('secondary_name', colors.get('secondary', ''))
            st.info(f"💡 Using official brand colors: **{primary}** and **{secondary}**")

        st.divider()

        # Submit button - disabled while workflow is running
        is_running = st.session_state.workflow_running
        batch_count = len(st.session_state.selected_templates_for_generation)

        if is_running:
            button_text = "⏳ Generating... Please wait"
        elif batch_count > 0:
            button_text = f"🚀 Generate Ads for {batch_count} Templates"
        else:
            button_text = "🚀 Generate Ad Variations"

        submitted = st.form_submit_button(
            button_text,
            type="primary",
            use_container_width=True,
            disabled=is_running
        )

        if submitted and not is_running:
            # Validate form
            validation_error = None

            # Check for either single upload OR multi-select templates
            has_single_template = bool(reference_ad_base64)
            has_batch_templates = len(st.session_state.selected_templates_for_generation) > 0

            if not has_single_template and not has_batch_templates:
                validation_error = "Please upload a reference ad or select templates from the library"
            elif image_selection_mode == "manual" and not selected_image_paths:
                validation_error = "Please select at least one product image or switch to Auto-Select mode"
            elif export_destination in ["email", "both"] and not export_email:
                validation_error = "Please enter an email address for email export"
            elif export_destination in ["email", "both"] and "@" not in export_email:
                validation_error = "Please enter a valid email address"
            elif export_destination in ["slack", "both"]:
                # Check if we have a webhook (either default or custom)
                from viraltracker.core.config import Config
                has_webhook = bool(Config.SLACK_WEBHOOK_URL) or bool(export_slack_webhook)
                if not has_webhook:
                    validation_error = "Please enter a Slack webhook URL or configure SLACK_WEBHOOK_URL"
            elif content_source == "belief_first" and not st.session_state.selected_angle_data:
                validation_error = "Please select an angle for Belief First mode (Persona → JTBD → Angle)"

            if validation_error:
                st.error(validation_error)
            else:
                st.session_state.workflow_running = True
                st.rerun()  # Rerun to show disabled button immediately

    # Run workflow outside form
    batch_templates = st.session_state.selected_templates_for_generation
    is_batch_mode = len(batch_templates) > 0 and st.session_state.workflow_running
    is_single_mode = reference_ad_base64 and st.session_state.workflow_running and not is_batch_mode

    if is_batch_mode:
        # BATCH MODE: Process multiple templates
        persona_msg = ""
        if st.session_state.selected_persona_id and personas:
            selected_persona = next((p for p in personas if p['id'] == st.session_state.selected_persona_id), None)
            if selected_persona:
                persona_msg = f" targeting **{selected_persona['name']}**"

        st.info(f"🎨 **Batch Mode**: Processing {len(batch_templates)} templates × {num_variations} variations each{persona_msg}")
        st.warning("⏳ **Please wait** - This may take several minutes. Do not refresh the page.")

        # Progress container
        progress_placeholder = st.empty()
        status_placeholder = st.empty()

        try:
            # Get common params
            brand_colors_data = None
            if color_mode == "brand" and selected_product:
                brand_colors_data = selected_product.get('brands', {}).get('brand_colors')

            img_mode = st.session_state.image_selection_mode
            img_paths = st.session_state.selected_image_paths if img_mode == "manual" else None
            exp_dest = st.session_state.export_destination
            exp_email = st.session_state.export_email if exp_dest in ["email", "both"] else None
            exp_slack = st.session_state.export_slack_webhook if exp_dest in ["slack", "both"] else None
            prod_name = selected_product.get('name', 'Product') if selected_product else 'Product'
            brand_info = selected_product.get('brands', {}) if selected_product else {}
            brd_name = brand_info.get('name', 'Brand') if brand_info else 'Brand'
            persona_id = st.session_state.selected_persona_id
            variant_id = st.session_state.selected_variant_id
            add_instructions = st.session_state.additional_instructions
            angle_data = st.session_state.selected_angle_data if content_source == "belief_first" else None
            match_template = st.session_state.match_template_structure if content_source == "belief_first" else False
            offer_variant_id = st.session_state.selected_offer_variant_id

            # Progress tracking state
            progress_state = {'current': 0, 'total': len(batch_templates), 'template_name': ''}

            def update_progress(current, total, template_name):
                progress_state['current'] = current
                progress_state['total'] = total
                progress_state['template_name'] = template_name

            # Show initial progress
            progress_placeholder.progress(0, text=f"Starting batch processing...")

            # Run batch workflow
            async def run_batch_with_progress():
                results = {
                    'successful': [],
                    'failed': [],
                    'total': len(batch_templates)
                }

                db = get_supabase_client()

                for idx, template in enumerate(batch_templates):
                    template_name = template.get('name', 'Unknown')
                    template_id = template.get('id', '')

                    # Update progress UI
                    progress = (idx) / len(batch_templates)
                    progress_placeholder.progress(progress, text=f"Processing template {idx + 1}/{len(batch_templates)}: {template_name}")
                    status_placeholder.caption(f"📄 Currently processing: **{template_name}**")

                    try:
                        # Download template image
                        bucket = template.get('bucket', 'reference-ads')
                        storage_path = template.get('storage_path', '')
                        template_data = db.storage.from_(bucket).download(storage_path)
                        ref_base64 = base64.b64encode(template_data).decode('utf-8')

                        # Run workflow for this template
                        result = await run_workflow(
                            product_id=selected_product_id,
                            reference_ad_base64=ref_base64,
                            filename=template_name,
                            num_variations=num_variations,
                            content_source=content_source,
                            color_mode=color_mode,
                            brand_colors=brand_colors_data,
                            image_selection_mode=img_mode,
                            selected_image_paths=img_paths,
                            export_destination=exp_dest,
                            export_email=exp_email,
                            export_slack_webhook=exp_slack,
                            product_name=prod_name,
                            brand_name=brd_name,
                            persona_id=persona_id,
                            variant_id=variant_id,
                            additional_instructions=add_instructions,
                            angle_data=angle_data,
                            match_template_structure=match_template,
                            offer_variant_id=offer_variant_id
                        )

                        # Record template usage if scraped
                        if template.get('source') == 'scraped' and result:
                            ad_run_id = result.get('ad_run_id')
                            if ad_run_id:
                                record_template_usage(template_id=template_id, ad_run_id=ad_run_id)
                            # Mark recommendation as used (non-critical)
                            try:
                                from viraltracker.services.template_recommendation_service import TemplateRecommendationService
                                rec_service = TemplateRecommendationService()
                                rec_service.mark_as_used(UUID(selected_product_id), UUID(template_id))
                            except Exception:
                                pass  # Non-critical

                        results['successful'].append({
                            'template_id': template_id,
                            'template_name': template_name,
                            'ad_run_id': result.get('ad_run_id'),
                            'approved_count': result.get('approved_count', 0),
                            'generated_count': len(result.get('generated_ads', []))
                        })

                    except Exception as e:
                        logger.error(f"Batch workflow failed for template {template_name}: {e}")
                        results['failed'].append({
                            'template_id': template_id,
                            'template_name': template_name,
                            'error': str(e)
                        })

                return results

            batch_results = asyncio.run(run_batch_with_progress())

            # Complete progress
            progress_placeholder.progress(1.0, text="Batch processing complete!")
            status_placeholder.empty()

            # Store batch results and clear selections
            st.session_state.multi_template_results = batch_results
            st.session_state.workflow_result = None  # Clear single result
            st.session_state.selected_templates_for_generation = []  # Clear selections
            st.session_state.workflow_error = None
            st.session_state.workflow_running = False
            st.rerun()

        except Exception as e:
            st.session_state.workflow_running = False
            st.session_state.workflow_error = str(e)
            st.error(f"Batch workflow failed: {str(e)}")
            st.info("💡 Check the sidebar for recent runs - some ads may have been generated before the error.")

    elif is_single_mode:
        # SINGLE MODE: Process one uploaded template (original behavior)
        persona_msg = ""
        if st.session_state.selected_persona_id and personas:
            selected_persona = next((p for p in personas if p['id'] == st.session_state.selected_persona_id), None)
            if selected_persona:
                persona_msg = f" targeting **{selected_persona['name']}**"

        st.info(f"🎨 Generating {num_variations} ad variations using **{content_source.replace('_', ' ')}** mode{persona_msg}...")
        st.warning("⏳ **Please wait** - This may take 2-5 minutes. Do not refresh the page.")

        try:
            # Get brand colors if using brand color mode
            brand_colors_data = None
            if color_mode == "brand" and selected_product:
                brand_colors_data = selected_product.get('brands', {}).get('brand_colors')

            # Get image selection params from session state
            img_mode = st.session_state.image_selection_mode
            img_paths = st.session_state.selected_image_paths if img_mode == "manual" else None

            # Get export params from session state
            exp_dest = st.session_state.export_destination
            exp_email = st.session_state.export_email if exp_dest in ["email", "both"] else None
            exp_slack = st.session_state.export_slack_webhook if exp_dest in ["slack", "both"] else None

            # Get product and brand names for export
            prod_name = selected_product.get('name', 'Product') if selected_product else 'Product'
            brand_info = selected_product.get('brands', {}) if selected_product else {}
            brd_name = brand_info.get('name', 'Brand') if brand_info else 'Brand'

            # Get persona_id, variant_id, and additional_instructions from session state
            persona_id = st.session_state.selected_persona_id
            variant_id = st.session_state.selected_variant_id
            add_instructions = st.session_state.additional_instructions

            # Get angle_data for belief_first mode
            angle_data = st.session_state.selected_angle_data if content_source == "belief_first" else None
            # Get match_template_structure flag for belief_first mode
            match_template = st.session_state.match_template_structure if content_source == "belief_first" else False
            # Get offer_variant_id from session state
            offer_variant_id = st.session_state.selected_offer_variant_id

            # Run the workflow
            result = asyncio.run(run_workflow(
                product_id=selected_product_id,
                reference_ad_base64=reference_ad_base64,
                filename=reference_filename,
                num_variations=num_variations,
                content_source=content_source,
                color_mode=color_mode,
                brand_colors=brand_colors_data,
                image_selection_mode=img_mode,
                selected_image_paths=img_paths,
                export_destination=exp_dest,
                export_email=exp_email,
                export_slack_webhook=exp_slack,
                product_name=prod_name,
                brand_name=brd_name,
                persona_id=persona_id,
                variant_id=variant_id,
                additional_instructions=add_instructions,
                angle_data=angle_data,
                match_template_structure=match_template,
                offer_variant_id=offer_variant_id
            ))

            # Record template usage if a scraped template was used
            if st.session_state.selected_scraped_template and result:
                ad_run_id = result.get('ad_run_id')
                record_template_usage(
                    template_id=st.session_state.selected_scraped_template,
                    ad_run_id=ad_run_id
                )
                # Mark recommendation as used (non-critical)
                try:
                    from viraltracker.services.template_recommendation_service import TemplateRecommendationService
                    rec_service = TemplateRecommendationService()
                    rec_service.mark_as_used(
                        UUID(selected_product_id),
                        UUID(st.session_state.selected_scraped_template)
                    )
                except Exception:
                    pass  # Non-critical, don't fail the workflow

            # Success - store result and show
            st.session_state.workflow_result = result
            st.session_state.workflow_error = None
            st.session_state.workflow_running = False
            st.rerun()

        except Exception as e:
            st.session_state.workflow_running = False
            st.session_state.workflow_error = str(e)
            st.error(f"Workflow failed: {str(e)}")

            # Show link to check database directly
            st.info("💡 Check the sidebar for recent runs - some ads may have been generated before the error.")

# ============================================================================
# Smart Edit Section (collapsible)
# ============================================================================

with st.expander("✏️ Smart Edit - Edit Existing Ads", expanded=False):
    st.caption("Make targeted edits to approved ads with AI assistance")

    # Initialize smart edit state
    if 'smart_edit_product_filter' not in st.session_state:
        st.session_state.smart_edit_product_filter = None
    if 'smart_edit_selected_ad' not in st.session_state:
        st.session_state.smart_edit_selected_ad = None
    if 'smart_edit_result' not in st.session_state:
        st.session_state.smart_edit_result = None

    # Product filter (optional - use selected product by default)
    smart_edit_product = st.session_state.selected_product

    if smart_edit_product:
        # Get approved ads for this product
        try:
            from viraltracker.services.ad_creation_service import AdCreationService
            ad_service = AdCreationService()
            editable_ads = asyncio.get_event_loop().run_until_complete(
                ad_service.get_editable_ads(product_id=UUID(smart_edit_product), limit=20)
            )

            if editable_ads:
                st.markdown(f"**{len(editable_ads)} approved ads available for editing**")

                # Display ads in a grid
                edit_cols = st.columns(4)
                for idx, ad in enumerate(editable_ads[:8]):  # Show max 8
                    with edit_cols[idx % 4]:
                        # Get thumbnail URL
                        storage_path = ad.get('storage_path', '')
                        if storage_path:
                            thumb_url = get_signed_url(storage_path)
                            if thumb_url:
                                st.image(thumb_url, use_container_width=True)

                        hook = ad.get('hook_text', '')[:30] + "..." if ad.get('hook_text') else "No hook"
                        st.caption(hook)

                        is_edit = ad.get('is_edit', False)
                        edit_label = " (edit)" if is_edit else ""
                        if st.button(f"Edit{edit_label}", key=f"smart_edit_select_{idx}"):
                            st.session_state.smart_edit_selected_ad = ad
                            st.rerun()

                # Selected ad edit panel
                if st.session_state.smart_edit_selected_ad:
                    st.divider()
                    selected_ad = st.session_state.smart_edit_selected_ad

                    st.markdown("**Edit Selected Ad**")

                    # Show selected ad thumbnail
                    sel_cols = st.columns([1, 2])
                    with sel_cols[0]:
                        sel_url = get_signed_url(selected_ad.get('storage_path', ''))
                        if sel_url:
                            st.image(sel_url, width=150)

                    with sel_cols[1]:
                        # Edit prompt
                        edit_prompt = st.text_area(
                            "What would you like to change?",
                            placeholder="e.g., Make the headline larger, add more contrast...",
                            key="smart_edit_prompt",
                            height=80
                        )

                        # Quick presets
                        presets = ad_service.EDIT_PRESETS
                        preset_options = [""] + list(presets.keys())
                        selected_preset = st.selectbox(
                            "Or choose a preset",
                            options=preset_options,
                            format_func=lambda x: x.replace("_", " ").title() if x else "Select preset...",
                            key="smart_edit_preset"
                        )

                        final_prompt = presets.get(selected_preset, "") if selected_preset else edit_prompt

                        # Options
                        opt_cols = st.columns(2)
                        with opt_cols[0]:
                            preserve_text = st.checkbox("Keep text identical", value=True, key="se_preserve_text")
                        with opt_cols[1]:
                            preserve_colors = st.checkbox("Keep colors identical", value=True, key="se_preserve_colors")

                        temperature = st.slider("Faithfulness", 0.1, 0.8, 0.3, 0.1,
                                              help="Lower = more faithful to original",
                                              key="se_temperature")

                        # Generate button
                        btn_cols = st.columns(2)
                        with btn_cols[0]:
                            if st.button("🎨 Generate Edit", disabled=not final_prompt, type="primary",
                                        key="se_generate"):
                                with st.spinner("Creating edited ad..."):
                                    try:
                                        result = asyncio.get_event_loop().run_until_complete(
                                            ad_service.create_edited_ad(
                                                source_ad_id=UUID(selected_ad['id']),
                                                edit_prompt=final_prompt,
                                                temperature=temperature,
                                                preserve_text=preserve_text,
                                                preserve_colors=preserve_colors
                                            )
                                        )
                                        st.session_state.smart_edit_result = result
                                        st.success(f"Edit created! ID: {result['ad_id'][:8]}")
                                    except Exception as e:
                                        st.error(f"Edit failed: {e}")

                        with btn_cols[1]:
                            if st.button("Cancel", key="se_cancel"):
                                st.session_state.smart_edit_selected_ad = None
                                st.session_state.smart_edit_result = None
                                st.rerun()

                        # Show result
                        if st.session_state.smart_edit_result:
                            result = st.session_state.smart_edit_result
                            st.caption(f"Generation time: {result.get('generation_time_ms', 0)}ms")
                            result_url = get_signed_url(result.get('storage_path', ''))
                            if result_url:
                                st.image(result_url, caption="Edited Ad", width=200)
            else:
                st.info("No approved ads found for this product. Generate some ads first!")
        except Exception as e:
            st.warning(f"Could not load editable ads: {e}")
    else:
        st.info("Select a product above to browse ads for editing.")

# ============================================================================
# Sidebar - Recent Runs
# ============================================================================

with st.sidebar:
    st.subheader("📜 Recent Ad Runs")

    try:
        db = get_supabase_client()
        recent_runs = db.table("ad_runs").select(
            "id, created_at, status, product_id"
        ).order("created_at", desc=True).limit(5).execute()

        for run in recent_runs.data:
            status_emoji = {
                'completed': '✅',
                'failed': '❌',
                'generating': '⏳',
                'analyzing': '🔍'
            }.get(run.get('status', ''), '❓')

            created = run.get('created_at', '')[:10]
            run_id = run.get('id', '')[:8]

            if st.button(f"{status_emoji} {run_id}... ({created})", key=f"run_{run['id']}"):
                # Load this run's results
                ad_run = get_ad_run_details(run['id'])
                if ad_run:
                    st.session_state.workflow_result = {
                        'ad_run_id': ad_run['id'],
                        'generated_ads': ad_run.get('generated_ads', []),
                        'approved_count': sum(1 for a in ad_run.get('generated_ads', []) if a.get('final_status') == 'approved'),
                        'rejected_count': sum(1 for a in ad_run.get('generated_ads', []) if a.get('final_status') == 'rejected'),
                        'flagged_count': sum(1 for a in ad_run.get('generated_ads', []) if a.get('final_status') == 'flagged'),
                    }
                    st.rerun()
    except Exception as e:
        st.caption(f"Could not load recent runs: {e}")
