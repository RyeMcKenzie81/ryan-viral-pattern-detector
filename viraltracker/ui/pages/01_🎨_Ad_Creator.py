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
if 'selected_belief_plan_id' not in st.session_state:
    st.session_state.selected_belief_plan_id = None
if 'belief_plan_data' not in st.session_state:
    st.session_state.belief_plan_data = None
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
if 'additional_instructions' not in st.session_state:
    st.session_state.additional_instructions = ""


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


def get_products():
    """Fetch all products from database with brand info."""
    try:
        db = get_supabase_client()
        result = db.table("products").select(
            "id, name, brand_id, target_audience, brands(id, name, brand_colors, brand_fonts)"
        ).order("name").execute()
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


def get_scraped_templates(category: str = None, limit: int = 50):
    """Get approved scraped templates from database.

    Args:
        category: Optional category filter (testimonial, quote_card, etc.)
        limit: Maximum templates to return

    Returns:
        List of template records with storage paths
    """
    try:
        from viraltracker.services.template_queue_service import TemplateQueueService
        service = TemplateQueueService()
        return service.get_templates(
            category=category if category != "all" else None,
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


def get_scraped_template_url(storage_path: str) -> str:
    """Get public URL for scraped template asset."""
    try:
        from viraltracker.services.template_queue_service import TemplateQueueService
        service = TemplateQueueService()
        return service.get_asset_preview_url(storage_path)
    except Exception:
        return ""


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


def get_belief_plans_for_product(product_id: str):
    """Get belief plans for a product."""
    try:
        db = get_supabase_client()
        result = db.table("belief_plans").select(
            "id, name, status, phase_id, created_at"
        ).eq("product_id", product_id).order("updated_at", desc=True).execute()

        plans = []
        for row in result.data or []:
            # Get angle count
            angle_result = db.table("belief_plan_angles").select(
                "id", count="exact"
            ).eq("plan_id", row["id"]).execute()

            plans.append({
                **row,
                "angle_count": angle_result.count if angle_result.count else 0
            })

        return plans
    except Exception as e:
        logger.error(f"Failed to get belief plans: {e}")
        return []


def get_all_belief_plans_with_products():
    """Get all belief plans with product info for the belief plan selector."""
    try:
        db = get_supabase_client()
        result = db.table("belief_plans").select(
            "id, name, status, phase_id, product_id, persona_id, brand_id, "
            "products(id, name), brands(id, name)"
        ).order("created_at", desc=True).execute()

        plans = []
        for row in result.data or []:
            # Get angle count
            angle_result = db.table("belief_plan_angles").select(
                "id", count="exact"
            ).eq("plan_id", row["id"]).execute()

            # Check if angles have copy
            has_copy = False
            if angle_result.count and angle_result.count > 0:
                angles_result = db.table("belief_plan_angles").select("angle_id").eq("plan_id", row["id"]).limit(1).execute()
                if angles_result.data:
                    copy_result = db.table("angle_copy_sets").select("id").eq("angle_id", angles_result.data[0]["angle_id"]).execute()
                    has_copy = bool(copy_result.data)

            plans.append({
                **row,
                "angle_count": angle_result.count if angle_result.count else 0,
                "has_copy": has_copy,
                "product_name": row.get("products", {}).get("name", "Unknown") if row.get("products") else "Unknown",
                "brand_name": row.get("brands", {}).get("name", "Unknown") if row.get("brands") else "Unknown"
            })

        # Filter to only plans with angles and copy
        return [p for p in plans if p["angle_count"] > 0 and p["has_copy"]]
    except Exception as e:
        logger.error(f"Failed to get all belief plans: {e}")
        return []


def get_belief_plan_details(plan_id: str):
    """Get belief plan with angles, copy sets, templates, and product info."""
    try:
        db = get_supabase_client()

        # Get plan with product info
        plan_result = db.table("belief_plans").select(
            "*, products(id, name, brand_id, target_audience, brands(id, name, brand_colors, brand_fonts))"
        ).eq("id", plan_id).execute()
        if not plan_result.data:
            return None

        plan = plan_result.data[0]

        # Get templates for this plan (from belief_plan_templates)
        templates_result = db.table("belief_plan_templates").select(
            "template_id, template_source, is_primary"
        ).eq("plan_id", plan_id).order("is_primary", desc=True).execute()

        templates = []
        primary_template = None
        for tmpl in templates_result.data or []:
            template_source = tmpl.get("template_source", "ad_brief_templates")
            template_id = tmpl["template_id"]

            # Get template details based on source
            if template_source == "scraped_templates":
                tmpl_result = db.table("scraped_templates").select(
                    "id, name, storage_path, anchor_text"
                ).eq("id", template_id).execute()
            else:
                tmpl_result = db.table("ad_brief_templates").select(
                    "id, name, storage_path, anchor_text"
                ).eq("id", template_id).execute()

            if tmpl_result.data:
                template_data = {
                    **tmpl_result.data[0],
                    "source": template_source,
                    "is_primary": tmpl.get("is_primary", False)
                }
                templates.append(template_data)
                if tmpl.get("is_primary", False):
                    primary_template = template_data

        # Get angles
        angles_result = db.table("belief_plan_angles").select(
            "angle_id, sort_order"
        ).eq("plan_id", plan_id).order("sort_order").execute()

        angles = []
        for plan_angle in angles_result.data or []:
            angle_result = db.table("belief_angles").select(
                "id, name, belief_statement"
            ).eq("id", plan_angle["angle_id"]).execute()

            if angle_result.data:
                angle_data = angle_result.data[0]

                # Get copy set
                copy_result = db.table("angle_copy_sets").select(
                    "headline_variants, primary_text_variants"
                ).eq("angle_id", angle_data["id"]).eq("phase_id", plan.get("phase_id", 1)).execute()

                copy_set = copy_result.data[0] if copy_result.data else None

                angles.append({
                    **angle_data,
                    "has_copy": copy_set is not None,
                    "headline_count": len(copy_set.get("headline_variants", [])) if copy_set else 0,
                    "primary_text_count": len(copy_set.get("primary_text_variants", [])) if copy_set else 0
                })

        return {
            "plan": plan,
            "angles": angles,
            "templates": templates,
            "primary_template": primary_template,
            "product": plan.get("products")
        }
    except Exception as e:
        logger.error(f"Failed to get belief plan details: {e}")
        return None


def _render_belief_plan_selector():
    """Render belief plan selector UI within the form."""
    product_id = st.session_state.selected_product.get("id") if st.session_state.selected_product else None

    if not product_id:
        return

    plans = get_belief_plans_for_product(product_id)

    if not plans:
        st.warning("No belief plans found for this product. Create one in Ad Planning first.")
        return

    # Filter to show only plans with angles
    plans_with_angles = [p for p in plans if p.get("angle_count", 0) > 0]

    if not plans_with_angles:
        st.warning("No belief plans with angles found. Complete your plan in Ad Planning first.")
        return

    # Plan selector
    plan_options = {p["id"]: f"{p['name']} (Phase {p['phase_id']}, {p['angle_count']} angles)" for p in plans_with_angles}

    selected_plan_id = st.selectbox(
        "Select Belief Plan",
        options=list(plan_options.keys()),
        format_func=lambda x: plan_options.get(x, x),
        key="belief_plan_selector",
        help="Choose a belief plan to use for ad generation"
    )

    if selected_plan_id:
        st.session_state.selected_belief_plan_id = selected_plan_id

        # Load plan details for preview
        plan_details = get_belief_plan_details(selected_plan_id)

        if plan_details:
            st.session_state.belief_plan_data = plan_details

            # Show preview
            st.markdown("**Plan Preview:**")
            plan = plan_details["plan"]
            angles = plan_details["angles"]

            col1, col2, col3 = st.columns(3)
            col1.metric("Phase", plan.get("phase_id", 1))
            col2.metric("Angles", len(angles))
            col3.metric("Status", plan.get("status", "draft").title())

            # Show angles summary
            if angles:
                st.markdown("**Angles:**")
                for i, angle in enumerate(angles, 1):
                    has_copy = "✓" if angle.get("has_copy") else "✗"
                    st.caption(f"{i}. {angle['name']} - Copy: {has_copy} ({angle.get('headline_count', 0)} headlines)")

                # Check if all angles have copy
                missing_copy = [a for a in angles if not a.get("has_copy")]
                if missing_copy:
                    st.warning(f"⚠️ {len(missing_copy)} angle(s) missing copy. Generate copy in Ad Planning first.")


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
    belief_plan_id: str = None
):
    """Run the ad creation workflow with optional export.

    Args:
        product_id: UUID of the product
        reference_ad_base64: Base64-encoded reference ad image
        filename: Original filename of the reference ad
        num_variations: Number of ad variations to generate (1-15)
        content_source: "hooks", "recreate_template", or "belief_plan"
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
        belief_plan_id: Optional belief plan UUID for belief_plan content source
    """
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
        belief_plan_id=belief_plan_id
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

# Check if we have a completed workflow to display
if st.session_state.workflow_result:
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
                        claude = ad.get('claude_review', {})
                        gemini = ad.get('gemini_review', {})

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

    content_source = st.radio(
        "How should we create the ad variations?",
        options=["hooks", "recreate_template", "belief_plan"],
        index=["hooks", "recreate_template", "belief_plan"].index(st.session_state.content_source),
        format_func=lambda x: {
            "hooks": "🎣 Hooks - Use persuasive hooks from your database",
            "recreate_template": "🔄 Recreate - Vary template by product benefits",
            "belief_plan": "🎯 Belief Plan - Use pre-planned angles with validated copy"
        }.get(x, x),
        horizontal=True,
        help="Belief Plan mode uses all context from your plan (product, template, copy)"
    )
    st.session_state.content_source = content_source

    st.divider()

    # Initialize variables that may be set by belief plan
    selected_product = None
    selected_product_id = None
    products = get_products()

    # ============================================================================
    # BELIEF PLAN FLOW - Auto-populates product, template, persona from plan
    # ============================================================================
    if content_source == "belief_plan":
        st.subheader("2. Select Belief Plan")

        all_plans = get_all_belief_plans_with_products()

        if not all_plans:
            st.warning("⚠️ No belief plans with copy found. Create a plan in Ad Planning first and generate copy for all angles.")
            st.stop()

        # Plan selector
        plan_options = {
            p["id"]: f"{p['name']} ({p['product_name']}, Phase {p['phase_id']}, {p['angle_count']} angles)"
            for p in all_plans
        }

        # Get current selection or default
        current_plan_id = st.session_state.selected_belief_plan_id
        if current_plan_id not in plan_options:
            current_plan_id = list(plan_options.keys())[0] if plan_options else None

        selected_plan_id = st.selectbox(
            "Belief Plan",
            options=list(plan_options.keys()),
            index=list(plan_options.keys()).index(current_plan_id) if current_plan_id in plan_options else 0,
            format_func=lambda x: plan_options.get(x, x),
            help="Select a belief plan - product, template, and copy will be loaded automatically"
        )
        st.session_state.selected_belief_plan_id = selected_plan_id

        # Load plan details
        if selected_plan_id:
            plan_details = get_belief_plan_details(selected_plan_id)
            if plan_details:
                st.session_state.belief_plan_data = plan_details

                # Auto-populate product from plan
                plan_product = plan_details.get("product")
                if plan_product:
                    selected_product = plan_product
                    selected_product_id = plan_product.get("id")
                    # Update product session state to match
                    st.session_state.selected_product = selected_product
                    st.session_state.selected_product_name = plan_product.get("name", "")

                # Show plan summary
                plan = plan_details.get("plan", {})
                angles = plan_details.get("angles", [])
                primary_template = plan_details.get("primary_template")

                st.success(f"✅ Plan loaded: **{plan.get('name')}** (Phase {plan.get('phase_id')})")

                col1, col2, col3 = st.columns(3)
                with col1:
                    st.markdown(f"**Product:** {plan_product.get('name', 'N/A')}")
                with col2:
                    st.markdown(f"**Angles:** {len(angles)} with copy")
                with col3:
                    st.markdown(f"**Template:** {primary_template.get('name', 'N/A') if primary_template else 'None'}")

                # Show angles preview
                with st.expander("📋 Plan Angles", expanded=False):
                    for angle in angles:
                        st.markdown(f"• **{angle['name']}** - {angle.get('headline_count', 0)} headlines, {angle.get('primary_text_count', 0)} primary texts")

        st.divider()

    # ============================================================================
    # HOOKS/RECREATE FLOW - Manual product selection
    # ============================================================================
    else:
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

        # Show product details
        selected_product = next((p for p in products if p['id'] == selected_product_id), None)
        if selected_product:
            st.caption(f"Target Audience: {selected_product.get('target_audience', 'Not specified')}")

        st.divider()

    # ============================================================================
    # Image Selection (outside form for interactivity)
    # ============================================================================

    st.subheader("3. Product Image" if content_source == "belief_plan" else "3. Product Image")

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
    # Persona, Variant, Instructions - ONLY for hooks/recreate modes
    # (belief_plan mode uses these from the plan)
    # ============================================================================

    if content_source != "belief_plan":
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
        # Section 2.6: Product Variant (Optional)
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
        # Section 2.7: Additional Instructions (Optional)
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
        # Section 3: Reference Ad (outside form for interactivity)
        # ============================================================================

        st.subheader("4. Reference Ad")
    else:
        # For belief_plan, personas are loaded from session state
        personas = []

    # Initialize reference_ad variables
    reference_ad_base64 = None
    reference_filename = None
    selected_scraped_template_id = None

    # ============================================================================
    # Reference Ad handling - different for belief_plan vs other modes
    # ============================================================================
    if content_source == "belief_plan":
        # Load template from the belief plan
        st.subheader("4. Reference Template (from Plan)")

        plan_data = st.session_state.get("belief_plan_data")
        primary_template = plan_data.get("primary_template") if plan_data else None

        if primary_template:
            storage_path = primary_template.get("storage_path")
            if storage_path:
                # Get signed URL and show preview
                template_url = get_signed_url(storage_path)
                if template_url:
                    col1, col2 = st.columns([1, 2])
                    with col1:
                        st.image(template_url, caption=f"Template: {primary_template.get('name', 'Unknown')}", width=200)
                    with col2:
                        st.success(f"✅ Using template: **{primary_template.get('name', 'Unknown')}**")
                        if primary_template.get("anchor_text"):
                            st.caption(f"📝 Anchor text: \"{primary_template.get('anchor_text')}\"")

                    # Load image as base64 for the workflow
                    try:
                        import requests
                        response = requests.get(template_url)
                        if response.status_code == 200:
                            reference_ad_base64 = base64.b64encode(response.content).decode('utf-8')
                            reference_filename = primary_template.get('name', 'template') + ".png"
                    except Exception as e:
                        logger.error(f"Failed to load template image: {e}")
                        st.error("Failed to load template image")
                else:
                    st.error("Could not load template image URL")
            else:
                st.warning("Template has no storage path")
        else:
            st.warning("⚠️ No template found in this plan. Go to Ad Planning to select a template.")

        st.divider()

    # ============================================================================
    # Standard reference ad selection - ONLY for hooks/recreate modes
    # ============================================================================
    if content_source != "belief_plan":
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

                st.caption(f"Showing {visible_count} of {total_templates} templates")

                # Thumbnail grid - 5 columns
                cols = st.columns(5)
                for idx, template in enumerate(visible_templates):
                    with cols[idx % 5]:
                        storage_name = template['storage_name']
                        display_name = template['name']
                        is_selected = st.session_state.selected_template_storage == storage_name

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

                        # Select button
                        if st.button(
                            "✓ Selected" if is_selected else "Select",
                            key=f"tpl_{idx}",
                            type="primary" if is_selected else "secondary",
                            use_container_width=True
                        ):
                            st.session_state.selected_template = display_name
                            st.session_state.selected_template_storage = storage_name
                            st.rerun()

                # Load more button
                if visible_count < total_templates:
                    remaining = total_templates - visible_count
                    if st.button(f"Load More ({remaining} more)", use_container_width=True):
                        st.session_state.templates_visible += 30
                        st.rerun()

                # Show selected template preview
                if st.session_state.selected_template_storage:
                    st.markdown("---")
                    st.markdown(f"**Selected:** {st.session_state.selected_template}")

                    try:
                        db = get_supabase_client()
                        template_data = db.storage.from_("reference-ads").download(
                            st.session_state.selected_template_storage
                        )
                        reference_ad_base64 = base64.b64encode(template_data).decode('utf-8')
                        reference_filename = st.session_state.selected_template

                        # Larger preview
                        st.image(template_data, caption="Selected Template", width=300)
                    except Exception as e:
                        st.error(f"Failed to load template: {e}")
            else:
                st.warning("No uploaded templates found. Upload a reference ad first, or use Scraped Template Library.")

        elif reference_source == "Scraped Template Library":
            # Category filter
            categories = get_template_categories()
            col1, col2 = st.columns([1, 3])
            with col1:
                selected_category = st.selectbox(
                    "Category",
                    options=categories,
                    index=categories.index(st.session_state.scraped_template_category) if st.session_state.scraped_template_category in categories else 0,
                    format_func=lambda x: x.replace("_", " ").title() if x != "all" else "All Categories",
                    key="scraped_category_filter"
                )
                st.session_state.scraped_template_category = selected_category

            # Get scraped templates
            scraped_templates = get_scraped_templates(
                category=selected_category if selected_category != "all" else None,
                limit=50
            )

            if scraped_templates:
                st.caption(f"Showing {len(scraped_templates)} templates" +
                          (f" in '{selected_category.replace('_', ' ').title()}'" if selected_category != "all" else ""))

                # Thumbnail grid - 5 columns
                cols = st.columns(5)
                for idx, template in enumerate(scraped_templates):
                    with cols[idx % 5]:
                        template_id = template.get('id', '')
                        template_name = template.get('name', 'Unnamed')
                        storage_path = template.get('storage_path', '')
                        category = template.get('category', 'other')
                        times_used = template.get('times_used', 0) or 0

                        is_selected = st.session_state.selected_scraped_template == template_id

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

                        # Select button
                        if st.button(
                            "✓ Selected" if is_selected else "Select",
                            key=f"scraped_tpl_{idx}",
                            type="primary" if is_selected else "secondary",
                            use_container_width=True
                        ):
                            st.session_state.selected_scraped_template = template_id
                            st.rerun()

                # Show selected template preview and load its data
                if st.session_state.selected_scraped_template:
                    # Find selected template in list
                    selected_tpl = next(
                        (t for t in scraped_templates if t.get('id') == st.session_state.selected_scraped_template),
                        None
                    )
                    if selected_tpl:
                        st.markdown("---")
                        st.markdown(f"**Selected:** {selected_tpl.get('name', 'Unnamed')}")

                        storage_path = selected_tpl.get('storage_path', '')
                        if storage_path:
                            try:
                                # Download the template image
                                db = get_supabase_client()
                                parts = storage_path.split("/", 1)
                                if len(parts) == 2:
                                    bucket, path = parts
                                    template_data = db.storage.from_(bucket).download(path)
                                    reference_ad_base64 = base64.b64encode(template_data).decode('utf-8')
                                    reference_filename = selected_tpl.get('name', 'template.jpg')
                                    selected_scraped_template_id = st.session_state.selected_scraped_template

                                    # Larger preview
                                    st.image(template_data, caption="Selected Template", width=300)
                            except Exception as e:
                                st.error(f"Failed to load template: {e}")
            else:
                st.info("No scraped templates found. Use the Template Queue to approve templates from competitor ads.")
                if st.button("Go to Template Queue →"):
                    st.switch_page("pages/16_📋_Template_Queue.py")

        st.divider()

    # ============================================================================
    # Section 4: Export Destination (outside form for conditional fields)
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
            "recreate_template": "benefits/USPs",
            "belief_plan": "belief angles"
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
        button_text = "⏳ Generating... Please wait" if is_running else "🚀 Generate Ad Variations"

        submitted = st.form_submit_button(
            button_text,
            type="primary",
            use_container_width=True,
            disabled=is_running
        )

        if submitted and not is_running:
            # Validate form
            validation_error = None

            if not reference_ad_base64:
                validation_error = "Please upload or select a reference ad"
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

            if validation_error:
                st.error(validation_error)
            else:
                st.session_state.workflow_running = True
                st.rerun()  # Rerun to show disabled button immediately

    # Run workflow outside form
    if st.session_state.workflow_running and reference_ad_base64:
        # Show progress info
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

            # Get belief_plan_id if using belief_plan content source
            belief_plan_id = None
            if content_source == "belief_plan":
                belief_plan_id = st.session_state.selected_belief_plan_id

            # Run workflow synchronously (simpler and more reliable than threading)
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
                belief_plan_id=belief_plan_id
            ))

            # Record template usage if a scraped template was used
            if st.session_state.selected_scraped_template and result:
                ad_run_id = result.get('ad_run_id')
                record_template_usage(
                    template_id=st.session_state.selected_scraped_template,
                    ad_run_id=ad_run_id
                )

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
