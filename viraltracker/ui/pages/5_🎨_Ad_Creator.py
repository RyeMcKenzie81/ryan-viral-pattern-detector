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


def get_existing_templates():
    """Get existing reference ad templates from storage."""
    try:
        db = get_supabase_client()
        # List files in reference-ads bucket
        result = db.storage.from_("reference-ads").list()
        templates = []
        for item in result:
            if item.get('name', '').lower().endswith(('.jpg', '.jpeg', '.png', '.webp')):
                templates.append({
                    'name': item['name'],
                    'path': f"reference-ads/{item['name']}",
                    'size': item.get('metadata', {}).get('size', 0)
                })
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


async def run_workflow(product_id: str, reference_ad_base64: str, filename: str, num_variations: int, content_source: str = "hooks", color_mode: str = "original", brand_colors: dict = None):
    """Run the ad creation workflow.

    Args:
        product_id: UUID of the product
        reference_ad_base64: Base64-encoded reference ad image
        filename: Original filename of the reference ad
        num_variations: Number of ad variations to generate (1-15)
        content_source: "hooks" or "recreate_template"
        color_mode: "original", "complementary", or "brand"
        brand_colors: Brand color data when color_mode is "brand"
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
        brand_colors=brand_colors
    )

    return result


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
    # Configuration Form
    # ============================================================================

    with st.form("ad_creation_form"):
        st.subheader("1. Select Product")

        products = get_products()
        if not products:
            st.error("No products found in database")
            st.stop()

        product_options = {p['name']: p['id'] for p in products}
        selected_product_name = st.selectbox(
            "Product",
            options=list(product_options.keys()),
            help="Select the product to create ads for"
        )
        selected_product_id = product_options[selected_product_name]

        # Show product details
        selected_product = next((p for p in products if p['id'] == selected_product_id), None)
        if selected_product:
            st.caption(f"Target Audience: {selected_product.get('target_audience', 'Not specified')}")

        st.divider()

        st.subheader("2. Content Source")

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

        st.subheader("3. Number of Variations")

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

        st.subheader("4. Reference Ad")

        reference_source = st.radio(
            "Reference ad source",
            options=["Upload New", "Use Existing Template"],
            horizontal=True
        )

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
                template_names = [t['name'] for t in templates]
                selected_template = st.selectbox(
                    "Select existing template",
                    options=template_names
                )

                if selected_template:
                    # Get the template from storage
                    try:
                        db = get_supabase_client()
                        template_data = db.storage.from_("reference-ads").download(selected_template)
                        reference_ad_base64 = base64.b64encode(template_data).decode('utf-8')
                        reference_filename = selected_template

                        # Preview
                        st.image(template_data, caption=f"Template: {selected_template}", width=300)
                    except Exception as e:
                        st.error(f"Failed to load template: {e}")
            else:
                st.warning("No existing templates found. Please upload a new reference ad.")

        st.divider()

        st.subheader("5. Color Scheme")

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
            if not reference_ad_base64:
                st.error("Please upload or select a reference ad")
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

            # Run workflow synchronously (simpler and more reliable than threading)
            result = asyncio.run(run_workflow(
                product_id=selected_product_id,
                reference_ad_base64=reference_ad_base64,
                filename=reference_filename,
                num_variations=num_variations,
                content_source=content_source,
                color_mode=color_mode,
                brand_colors=brand_colors_data
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
