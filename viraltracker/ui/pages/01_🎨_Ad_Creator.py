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
from pathlib import Path
from datetime import datetime

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


def get_supabase_client():
    """Get Supabase client."""
    from viraltracker.core.database import get_supabase_client
    return get_supabase_client()


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
        # List files in reference-ads bucket
        result = db.storage.from_("reference-ads").list()

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
    brand_name: str = None
):
    """Run the ad creation workflow with optional export.

    Args:
        product_id: UUID of the product
        reference_ad_base64: Base64-encoded reference ad image
        filename: Original filename of the reference ad
        num_variations: Number of ad variations to generate (1-15)
        content_source: "hooks" or "recreate_template"
        color_mode: "original", "complementary", or "brand"
        brand_colors: Brand color data when color_mode is "brand"
        image_selection_mode: "auto" or "manual"
        selected_image_paths: List of storage paths when mode is "manual" (1-2 images)
        export_destination: "none", "email", "slack", or "both"
        export_email: Email address for email export
        export_slack_webhook: Slack webhook URL (None to use default)
        product_name: Product name for export context
        brand_name: Brand name for export context
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
        selected_image_paths=selected_image_paths
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
    import logging
    logger = logging.getLogger(__name__)

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
    # Configuration - Product & Image Selection (outside form for interactivity)
    # ============================================================================

    st.subheader("1. Select Product")

    products = get_products()
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

    st.subheader("2. Product Image")

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
    # Section 3: Reference Ad (outside form for interactivity)
    # ============================================================================

    st.subheader("3. Reference Ad")

    reference_source = st.radio(
        "Reference ad source",
        options=["Upload New", "Use Existing Template"],
        index=0 if st.session_state.reference_source == "Upload New" else 1,
        horizontal=True,
        key="reference_source_radio"
    )
    st.session_state.reference_source = reference_source

    reference_ad_base64 = None
    reference_filename = None

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

    else:
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
            st.warning("No existing templates found. Please upload a new reference ad.")

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
        st.subheader("5. Content Source")

        content_source = st.radio(
            "How should we create the ad variations?",
            options=["hooks", "recreate_template"],
            index=0 if st.session_state.content_source == "hooks" else 1,
            format_func=lambda x: {
                "hooks": "🎣 Hooks List - Use persuasive hooks from your database",
                "recreate_template": "🔄 Recreate Template - Keep template's angle, vary by product benefits"
            }.get(x, x),
            horizontal=False,
            help="Choose how to generate the messaging for each ad variation",
            disabled=st.session_state.workflow_running
        )
        st.session_state.content_source = content_source

        # Show explanation based on selection
        if content_source == "hooks":
            st.info("💡 Each variation will use a different persuasive hook from your hooks database, combined with the template's visual style.")
        else:
            st.info("💡 The template's existing angle/message will be analyzed and recreated using your product's different benefits and USPs.")

        st.divider()

        st.subheader("6. Number of Variations")

        num_variations = st.slider(
            "How many ad variations to generate?",
            min_value=1,
            max_value=15,
            value=st.session_state.num_variations,
            help="Number of unique ad variations to create",
            disabled=st.session_state.workflow_running
        )
        st.session_state.num_variations = num_variations

        variation_source = "hooks" if content_source == "hooks" else "benefits/USPs"
        st.caption(f"Will generate {num_variations} ads using different {variation_source}")

        st.divider()

        st.subheader("7. Color Scheme")

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
        st.info(f"🎨 Generating {num_variations} ad variations using **{content_source.replace('_', ' ')}** mode...")
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
                brand_name=brd_name
            ))

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
