"""
Template Queue UI

Review and approve scraped ad templates:
- View pending templates with previews
- Approve with category and name
- Reject with reason
- View queue statistics
- Browse approved template library
"""

import streamlit as st
from typing import Optional, List, Dict, Any
from datetime import datetime

# Page config (must be first)
st.set_page_config(
    page_title="Template Queue",
    page_icon="📋",
    layout="wide"
)

# Authentication
from viraltracker.ui.auth import require_auth
require_auth()

# Initialize session state
if 'queue_tab' not in st.session_state:
    st.session_state.queue_tab = "Pending Review"
if 'queue_page' not in st.session_state:
    st.session_state.queue_page = 0
if 'ingestion_running' not in st.session_state:
    st.session_state.ingestion_running = False
if 'ingestion_url' not in st.session_state:
    st.session_state.ingestion_url = ""
if 'ingestion_max_ads' not in st.session_state:
    st.session_state.ingestion_max_ads = 20
if 'ingestion_images_only' not in st.session_state:
    st.session_state.ingestion_images_only = True
if 'ingestion_result' not in st.session_state:
    st.session_state.ingestion_result = None  # Store last result for display
if 'reviewing_item_id' not in st.session_state:
    st.session_state.reviewing_item_id = None  # Item ID being reviewed (pending_details)
if 'ai_suggestions' not in st.session_state:
    st.session_state.ai_suggestions = None  # AI suggestions for current review


def get_template_queue_service():
    """Get TemplateQueueService instance."""
    from viraltracker.services.template_queue_service import TemplateQueueService
    return TemplateQueueService()


def get_supabase_client():
    """Get Supabase client."""
    from viraltracker.core.database import get_supabase_client
    return get_supabase_client()


# ============================================================================
# Data Loading
# ============================================================================

@st.cache_data(ttl=30)
def get_queue_stats() -> Dict[str, int]:
    """Get queue statistics."""
    service = get_template_queue_service()
    return service.get_queue_stats()


def get_pending_items(limit: int = 20, offset: int = 0) -> List[Dict]:
    """Get pending queue items."""
    service = get_template_queue_service()
    return service.get_pending_queue(limit=limit, offset=offset)


def get_approved_templates(limit: int = 50) -> List[Dict]:
    """Get approved templates."""
    service = get_template_queue_service()
    return service.get_templates(active_only=True, limit=limit)


def get_asset_url(storage_path: str) -> str:
    """Get public URL for asset."""
    if not storage_path:
        return ""
    service = get_template_queue_service()
    return service.get_asset_preview_url(storage_path)


# ============================================================================
# Actions
# ============================================================================

def approve_item(queue_id: str, category: str, name: str, description: str = ""):
    """Approve a queue item."""
    from uuid import UUID
    service = get_template_queue_service()
    try:
        result = service.approve_template(
            queue_id=UUID(queue_id),
            category=category,
            name=name,
            description=description if description else None,
            reviewed_by="streamlit_user"
        )
        st.success(f"Approved: {name}")
        st.cache_data.clear()
        return True
    except Exception as e:
        st.error(f"Failed to approve: {e}")
        return False


def reject_item(queue_id: str, reason: str):
    """Reject a queue item."""
    from uuid import UUID
    service = get_template_queue_service()
    try:
        service.reject_template(
            queue_id=UUID(queue_id),
            reason=reason,
            reviewed_by="streamlit_user"
        )
        st.success("Item rejected")
        st.cache_data.clear()
        return True
    except Exception as e:
        st.error(f"Failed to reject: {e}")
        return False


def archive_item(queue_id: str):
    """Archive a queue item."""
    from uuid import UUID
    service = get_template_queue_service()
    try:
        service.archive_template(
            queue_id=UUID(queue_id),
            reviewed_by="streamlit_user"
        )
        st.success("Item archived")
        st.cache_data.clear()
        return True
    except Exception as e:
        st.error(f"Failed to archive: {e}")
        return False


# ============================================================================
# Two-Step Approval Actions
# ============================================================================

def start_ai_approval(queue_id: str):
    """Start AI-assisted approval (step 1)."""
    import asyncio
    from uuid import UUID
    service = get_template_queue_service()
    try:
        with st.spinner("Analyzing template with AI..."):
            suggestions = asyncio.run(service.start_approval(UUID(queue_id)))
        st.session_state.reviewing_item_id = queue_id
        st.session_state.ai_suggestions = suggestions
        st.cache_data.clear()
        return True
    except Exception as e:
        st.error(f"AI analysis failed: {e}")
        return False


def finalize_ai_approval(
    queue_id: str,
    name: str,
    description: str,
    category: str,
    industry_niche: str,
    target_sex: str,
    awareness_level: int,
    sales_event: str
):
    """Finalize approval with confirmed details (step 2)."""
    from uuid import UUID
    service = get_template_queue_service()
    try:
        result = service.finalize_approval(
            queue_id=UUID(queue_id),
            name=name,
            description=description,
            category=category,
            industry_niche=industry_niche,
            target_sex=target_sex,
            awareness_level=awareness_level,
            sales_event=sales_event if sales_event != "None" else None,
            reviewed_by="streamlit_user"
        )
        st.success(f"Template approved: {name}")
        st.session_state.reviewing_item_id = None
        st.session_state.ai_suggestions = None
        st.cache_data.clear()
        return True
    except Exception as e:
        st.error(f"Failed to finalize approval: {e}")
        return False


def cancel_ai_approval(queue_id: str):
    """Cancel in-progress approval and return to pending."""
    from uuid import UUID
    service = get_template_queue_service()
    try:
        service.cancel_approval(UUID(queue_id))
        st.session_state.reviewing_item_id = None
        st.session_state.ai_suggestions = None
        st.cache_data.clear()
        return True
    except Exception as e:
        st.error(f"Failed to cancel: {e}")
        return False


# ============================================================================
# UI Components
# ============================================================================

def render_stats():
    """Render queue statistics."""
    stats = get_queue_stats()

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Pending", stats.get("pending", 0))
    col2.metric("Approved", stats.get("approved", 0))
    col3.metric("Rejected", stats.get("rejected", 0))
    col4.metric("Total", stats.get("total", 0))


def get_industry_options() -> List[str]:
    """Get list of industry/niche options."""
    return [
        "supplements", "pets", "skincare", "fitness", "fashion",
        "tech", "food_beverage", "home_garden", "finance",
        "health_wellness", "beauty", "automotive", "travel", "education", "other"
    ]


def get_sales_event_options() -> List[str]:
    """Get list of sales event options."""
    return [
        "None", "black_friday", "cyber_monday", "mothers_day", "fathers_day",
        "valentines_day", "christmas", "new_year", "summer_sale",
        "labor_day", "memorial_day", "other"
    ]


def get_awareness_level_options() -> List[tuple]:
    """Get awareness level options as (value, display_name) tuples."""
    return [
        (1, "1 - Unaware"),
        (2, "2 - Problem Aware"),
        (3, "3 - Solution Aware"),
        (4, "4 - Product Aware"),
        (5, "5 - Most Aware")
    ]


def render_details_review():
    """Render the AI suggestions review form (step 2 of approval)."""
    queue_id = st.session_state.reviewing_item_id
    suggestions = st.session_state.ai_suggestions

    if not queue_id or not suggestions:
        st.warning("No review in progress. Please select an item to approve.")
        if st.button("Back to Queue"):
            st.session_state.reviewing_item_id = None
            st.session_state.ai_suggestions = None
            st.rerun()
        return

    # Get the queue item for preview
    service = get_template_queue_service()
    item = service.get_pending_details_item(queue_id)

    if not item:
        st.warning("Item no longer available for review.")
        st.session_state.reviewing_item_id = None
        st.session_state.ai_suggestions = None
        st.rerun()
        return

    st.subheader("Review AI Suggestions")
    st.caption("Review and edit the AI-generated metadata before finalizing approval.")

    asset = item.get("scraped_ad_assets", {})
    storage_path = asset.get("storage_path", "")
    asset_type = asset.get("asset_type", "image")

    col1, col2 = st.columns([1, 2])

    with col1:
        # Preview image
        if storage_path:
            url = get_asset_url(storage_path)
            if url and asset_type == "image":
                st.image(url, use_container_width=True)
            elif url and asset_type == "video":
                st.video(url)

        # Source info (read-only)
        st.caption("**Source Info**")
        st.text(f"Brand: {suggestions.get('source_brand', 'Unknown')}")
        landing_page = suggestions.get('source_landing_page', '')
        if landing_page:
            st.text(f"Landing: {landing_page[:50]}...")

        # Visual notes from AI
        visual_notes = suggestions.get("visual_notes", "")
        if visual_notes:
            st.caption("**AI Visual Notes**")
            st.caption(visual_notes)

    with col2:
        # Editable form with AI suggestions pre-filled
        with st.form(key="finalize_approval"):
            # Name and Description
            name = st.text_input(
                "Template Name",
                value=suggestions.get("suggested_name", ""),
                help="Short descriptive name for this template"
            )
            description = st.text_area(
                "Description",
                value=suggestions.get("suggested_description", ""),
                height=80,
                help="Brief description of template style and use case"
            )

            # Category (format type)
            categories = service.get_template_categories()
            suggested_category = suggestions.get("format_type", "other")
            category_index = categories.index(suggested_category) if suggested_category in categories else 0
            category = st.selectbox(
                "Format Category",
                options=categories,
                index=category_index
            )

            # Industry/Niche
            industries = get_industry_options()
            suggested_industry = suggestions.get("industry_niche", "other")
            industry_index = industries.index(suggested_industry) if suggested_industry in industries else len(industries) - 1
            industry_niche = st.selectbox(
                "Industry/Niche",
                options=industries,
                index=industry_index
            )

            # Target Sex
            target_sex = st.radio(
                "Target Audience",
                options=["male", "female", "unisex"],
                index=["male", "female", "unisex"].index(suggestions.get("target_sex", "unisex")),
                horizontal=True
            )

            # Awareness Level
            awareness_options = get_awareness_level_options()
            suggested_awareness = suggestions.get("awareness_level", 3)
            awareness_level = st.selectbox(
                "Awareness Level",
                options=[opt[0] for opt in awareness_options],
                format_func=lambda x: next((opt[1] for opt in awareness_options if opt[0] == x), str(x)),
                index=suggested_awareness - 1,
                help=suggestions.get("awareness_level_reasoning", "")
            )

            # Show AI reasoning for awareness level
            reasoning = suggestions.get("awareness_level_reasoning", "")
            if reasoning:
                st.caption(f"*AI Reasoning: {reasoning}*")

            # Sales Event
            events = get_sales_event_options()
            suggested_event = suggestions.get("sales_event") or "None"
            event_index = events.index(suggested_event) if suggested_event in events else 0
            sales_event = st.selectbox(
                "Sales Event (if applicable)",
                options=events,
                index=event_index
            )

            st.divider()

            col_a, col_b = st.columns(2)
            with col_a:
                confirm = st.form_submit_button("Confirm & Approve", type="primary")
            with col_b:
                cancel = st.form_submit_button("Cancel")

            if confirm:
                if not name:
                    st.error("Template name is required")
                else:
                    finalize_ai_approval(
                        queue_id=queue_id,
                        name=name,
                        description=description,
                        category=category,
                        industry_niche=industry_niche,
                        target_sex=target_sex,
                        awareness_level=awareness_level,
                        sales_event=sales_event
                    )
                    st.rerun()

            if cancel:
                cancel_ai_approval(queue_id)
                st.rerun()


def render_pending_queue():
    """Render pending items for review."""
    # Check if we're in the middle of reviewing an item
    if st.session_state.reviewing_item_id:
        render_details_review()
        return

    items = get_pending_items(limit=20, offset=st.session_state.queue_page * 20)

    if not items:
        st.info("No pending items in queue. Run the template ingestion pipeline to add items.")
        return

    service = get_template_queue_service()

    for item in items:
        asset = item.get("scraped_ad_assets", {})
        storage_path = asset.get("storage_path", "")
        asset_type = asset.get("asset_type", "image")

        with st.container():
            col1, col2 = st.columns([1, 2])

            with col1:
                # Preview
                if storage_path:
                    url = get_asset_url(storage_path)
                    if url and asset_type == "image":
                        st.image(url, use_container_width=True)
                    elif url and asset_type == "video":
                        st.video(url)
                    else:
                        st.write("Preview unavailable")
                else:
                    st.write("No preview")

            with col2:
                # AI Analysis (from previous queue analysis if available)
                ai_analysis = item.get("ai_analysis", {})
                if ai_analysis and ai_analysis.get("analyzed"):
                    st.caption(f"Pre-Analysis: {ai_analysis.get('suggested_category', 'N/A')}")

                st.markdown("**Quick Actions**")
                st.caption("Click 'Approve' to run AI analysis and review suggested metadata.")

                # Action buttons (not a form - for immediate action)
                col_a, col_b, col_c = st.columns(3)
                with col_a:
                    if st.button("Approve", key=f"approve_{item['id']}", type="primary"):
                        if start_ai_approval(item["id"]):
                            st.rerun()
                with col_b:
                    if st.button("Skip", key=f"skip_{item['id']}"):
                        archive_item(item["id"])
                        st.rerun()
                with col_c:
                    if st.button("Reject", key=f"reject_{item['id']}"):
                        reject_item(item["id"], "Rejected via UI")
                        st.rerun()

            st.divider()

    # Pagination
    col1, col2, col3 = st.columns([1, 2, 1])
    with col1:
        if st.session_state.queue_page > 0:
            if st.button("Previous"):
                st.session_state.queue_page -= 1
                st.rerun()
    with col3:
        if len(items) == 20:
            if st.button("Next"):
                st.session_state.queue_page += 1
                st.rerun()


def render_template_library():
    """Render approved templates library."""
    templates = get_approved_templates(limit=50)

    if not templates:
        st.info("No approved templates yet. Approve items from the pending queue.")
        return

    # Group by category
    by_category = {}
    for t in templates:
        cat = t.get("category", "other")
        if cat not in by_category:
            by_category[cat] = []
        by_category[cat].append(t)

    for category, items in sorted(by_category.items()):
        st.subheader(f"{category.replace('_', ' ').title()} ({len(items)})")

        cols = st.columns(4)
        for i, template in enumerate(items):
            with cols[i % 4]:
                storage_path = template.get("storage_path", "")
                if storage_path:
                    url = get_asset_url(storage_path)
                    if url:
                        st.image(url, use_container_width=True)

                st.caption(template.get("name", "Unnamed"))

                times_used = template.get("times_used", 0)
                if times_used > 0:
                    st.caption(f"Used {times_used}x")


def render_ingestion_trigger():
    """Render template ingestion trigger form."""
    st.subheader("Ingest New Templates")

    # Display last result if exists
    if st.session_state.ingestion_result:
        result = st.session_state.ingestion_result
        status = result.get("status")

        if status == "awaiting_approval":
            st.success(
                f"✅ Queued {result.get('queued_count', 0)} templates for review! "
                f"({result.get('ads_scraped', 0)} ads scraped, {result.get('assets_downloaded', 0)} assets)"
            )
        elif status == "error":
            st.error(f"Pipeline error: {result.get('error')}")
        elif status == "no_ads":
            msg = result.get("message", "No ads found at that URL.")
            st.warning(f"⚠️ {msg}")
        elif status == "no_new_ads":
            st.info("These ads were already scraped. Check the Pending Review tab.")
        elif status == "no_assets":
            msg = result.get("message", "No images/videos could be downloaded.")
            st.warning(f"⚠️ {msg}")
        else:
            st.warning(f"Status: {status} - {result.get('message', '')}")

        # Clear button
        if st.button("Clear message", key="clear_result"):
            st.session_state.ingestion_result = None
            st.rerun()

    is_running = st.session_state.ingestion_running

    with st.form("ingest_templates"):
        url = st.text_input(
            "Facebook Ad Library URL",
            value=st.session_state.ingestion_url,
            placeholder="https://www.facebook.com/ads/library/?...",
            disabled=is_running
        )

        col1, col2 = st.columns(2)
        with col1:
            max_ads = st.number_input(
                "Max Ads",
                min_value=10,
                max_value=1000,
                value=st.session_state.ingestion_max_ads,
                disabled=is_running
            )
        with col2:
            images_only = st.checkbox(
                "Images Only",
                value=st.session_state.ingestion_images_only,
                disabled=is_running
            )

        button_text = "⏳ Scraping... Please wait" if is_running else "🚀 Start Ingestion"
        submit = st.form_submit_button(button_text, type="primary", disabled=is_running)

        if submit and not is_running:
            if not url:
                st.error("Please enter a Facebook Ad Library URL")
            else:
                # Store form values and set running state
                st.session_state.ingestion_url = url
                st.session_state.ingestion_max_ads = max_ads
                st.session_state.ingestion_images_only = images_only
                st.session_state.ingestion_running = True
                st.rerun()

    # Run ingestion outside form when triggered
    if is_running:
        st.info("🔄 Scraping ads from Facebook Ad Library... This may take 1-3 minutes.")
        st.warning("⏳ **Please wait** - Do not refresh the page.")

        try:
            import asyncio
            from viraltracker.pipelines import run_template_ingestion

            result = asyncio.run(run_template_ingestion(
                ad_library_url=st.session_state.ingestion_url,
                max_ads=st.session_state.ingestion_max_ads,
                images_only=st.session_state.ingestion_images_only
            ))

            st.session_state.ingestion_running = False

            # Store result for persistent display
            st.session_state.ingestion_result = result
            st.cache_data.clear()

            if result.get("status") == "awaiting_approval":
                st.session_state.ingestion_url = ""  # Clear URL after success

            st.rerun()

        except Exception as e:
            st.session_state.ingestion_running = False
            st.error(f"Failed to run pipeline: {e}")


# ============================================================================
# Main Page
# ============================================================================

st.title("📋 Template Queue")
st.caption("Review and approve scraped ad templates for the creative library")

# Stats
render_stats()
st.divider()

# Tabs
tab1, tab2, tab3 = st.tabs(["Pending Review", "Template Library", "Ingest New"])

with tab1:
    render_pending_queue()

with tab2:
    render_template_library()

with tab3:
    render_ingestion_trigger()
