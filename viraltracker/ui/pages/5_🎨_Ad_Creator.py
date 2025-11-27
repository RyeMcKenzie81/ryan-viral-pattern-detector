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
import time
import threading
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
if 'current_ad_run_id' not in st.session_state:
    st.session_state.current_ad_run_id = None
if 'selected_product' not in st.session_state:
    st.session_state.selected_product = None
if 'num_variations' not in st.session_state:
    st.session_state.num_variations = 5
if 'content_source' not in st.session_state:
    st.session_state.content_source = "hooks"


def get_supabase_client():
    """Get Supabase client."""
    from viraltracker.core.database import get_supabase_client
    return get_supabase_client()


def get_products():
    """Fetch all products from database."""
    try:
        db = get_supabase_client()
        result = db.table("products").select("id, name, brand_id, target_audience").order("name").execute()
        return result.data
    except Exception as e:
        st.error(f"Failed to fetch products: {e}")
        return []


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


async def run_workflow(product_id: str, reference_ad_base64: str, filename: str, num_variations: int, content_source: str = "hooks"):
    """Run the ad creation workflow.

    Args:
        product_id: UUID of the product
        reference_ad_base64: Base64-encoded reference ad image
        filename: Original filename of the reference ad
        num_variations: Number of ad variations to generate (1-15)
        content_source: "hooks" or "recreate_template"
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
        content_source=content_source
    )

    return result


def get_latest_ad_run():
    """Get the most recent ad run (for progress tracking)."""
    try:
        db = get_supabase_client()
        result = db.table("ad_runs").select(
            "id, status, created_at"
        ).order("created_at", desc=True).limit(1).execute()
        return result.data[0] if result.data else None
    except Exception:
        return None


def get_ad_run_progress(ad_run_id: str, num_variations: int):
    """Get progress info for an ad run.

    Returns:
        tuple: (status, ads_generated, progress_pct, status_text)
    """
    try:
        db = get_supabase_client()

        # Get ad run status
        run_result = db.table("ad_runs").select("status").eq("id", ad_run_id).execute()
        if not run_result.data:
            return "unknown", 0, 0, "Loading..."

        status = run_result.data[0].get("status", "unknown")

        # Get generated ads count
        ads_result = db.table("generated_ads").select("id").eq("ad_run_id", ad_run_id).execute()
        ads_count = len(ads_result.data) if ads_result.data else 0

        # Calculate progress
        if status == "analyzing":
            progress_pct = 10
            status_text = "🔍 Analyzing reference ad..."
        elif status == "generating":
            # Each ad takes ~20% of remaining progress after analysis
            base_progress = 20
            per_ad_progress = 70 / num_variations
            progress_pct = int(base_progress + (ads_count * per_ad_progress))
            status_text = f"🎨 Generating ad {ads_count + 1} of {num_variations}..."
            if ads_count >= num_variations:
                status_text = f"✅ Generated {ads_count} ads, reviewing..."
        elif status == "complete":
            progress_pct = 100
            status_text = "✅ Complete!"
        elif status == "failed":
            progress_pct = 0
            status_text = "❌ Failed"
        else:
            progress_pct = 5
            status_text = f"⏳ Status: {status}"

        return status, ads_count, min(progress_pct, 100), status_text

    except Exception as e:
        return "error", 0, 0, f"Error: {str(e)}"


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

        # Submit button - disabled while workflow is running
        is_running = st.session_state.workflow_running
        button_text = "⏳ Generating... Please wait" if is_running else f"🚀 Generate {num_variations} Ad Variations"

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
        # Create a container for progress display
        progress_container = st.container()

        with progress_container:
            st.info(f"🎨 Generating {num_variations} ad variations using **{content_source.replace('_', ' ')}** mode...")
            progress_bar = st.progress(0, text="Starting workflow...")
            status_text = st.empty()
            ads_generated_text = st.empty()

        # Function to run workflow in thread
        def run_workflow_thread():
            try:
                result = asyncio.run(run_workflow(
                    product_id=selected_product_id,
                    reference_ad_base64=reference_ad_base64,
                    filename=reference_filename,
                    num_variations=num_variations,
                    content_source=content_source
                ))
                st.session_state.workflow_result = result
                st.session_state.workflow_error = None
            except Exception as e:
                st.session_state.workflow_error = str(e)
                st.session_state.workflow_result = None

        # Start workflow in background thread
        workflow_thread = threading.Thread(target=run_workflow_thread)
        workflow_thread.start()

        # Poll for progress while workflow runs
        poll_count = 0
        max_polls = 600  # 10 minutes max (1 second per poll)

        while workflow_thread.is_alive() and poll_count < max_polls:
            poll_count += 1
            time.sleep(1)  # Poll every second

            # Try to get the latest ad run for progress
            latest_run = get_latest_ad_run()
            if latest_run:
                ad_run_id = latest_run.get('id')
                st.session_state.current_ad_run_id = ad_run_id

                status, ads_count, progress_pct, status_msg = get_ad_run_progress(
                    ad_run_id, num_variations
                )

                # Update progress bar
                progress_bar.progress(progress_pct / 100, text=status_msg)

                # Show additional info
                if ads_count > 0:
                    ads_generated_text.caption(f"📊 {ads_count} of {num_variations} ads generated")

        # Wait for thread to complete
        workflow_thread.join(timeout=5)

        # Handle completion
        if st.session_state.workflow_error:
            st.session_state.workflow_running = False
            st.error(f"Workflow failed: {st.session_state.workflow_error}")
        elif st.session_state.workflow_result:
            progress_bar.progress(100, text="✅ Complete!")
            st.session_state.workflow_running = False
            time.sleep(0.5)  # Brief pause to show completion
            st.rerun()
        else:
            st.session_state.workflow_running = False
            st.warning("Workflow completed but no result received. Check recent runs in sidebar.")

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
