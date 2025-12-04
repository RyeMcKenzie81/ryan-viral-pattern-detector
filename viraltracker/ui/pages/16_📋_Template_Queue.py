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


def render_pending_queue():
    """Render pending items for review."""
    items = get_pending_items(limit=20, offset=st.session_state.queue_page * 20)

    if not items:
        st.info("No pending items in queue. Run the template ingestion pipeline to add items.")
        return

    service = get_template_queue_service()
    categories = service.get_template_categories()

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
                # AI Analysis
                ai_analysis = item.get("ai_analysis", {})
                if ai_analysis and ai_analysis.get("analyzed"):
                    st.caption(f"AI Suggested: {ai_analysis.get('suggested_category', 'N/A')}")
                    st.caption(f"Quality Score: {ai_analysis.get('quality_score', 'N/A')}")

                # Approval form
                with st.form(key=f"approve_{item['id']}"):
                    name = st.text_input("Template Name", key=f"name_{item['id']}")
                    category = st.selectbox(
                        "Category",
                        options=categories,
                        key=f"cat_{item['id']}"
                    )
                    description = st.text_area(
                        "Description (optional)",
                        key=f"desc_{item['id']}",
                        height=68
                    )

                    col_a, col_b, col_c = st.columns(3)
                    with col_a:
                        approve = st.form_submit_button("Approve", type="primary")
                    with col_b:
                        skip = st.form_submit_button("Skip/Archive")
                    with col_c:
                        reject = st.form_submit_button("Reject")

                    if approve:
                        if not name:
                            st.error("Name is required")
                        else:
                            approve_item(item["id"], category, name, description)
                            st.rerun()

                    if skip:
                        archive_item(item["id"])
                        st.rerun()

                    if reject:
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
                max_value=100,
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

            if result.get("status") == "awaiting_approval":
                st.success(
                    f"✅ Queued {result.get('queued_count', 0)} templates for review! "
                    f"({result.get('ads_scraped', 0)} ads scraped)"
                )
                st.cache_data.clear()
                st.session_state.ingestion_url = ""  # Clear URL after success
                st.rerun()
            elif result.get("status") == "error":
                st.error(f"Pipeline error: {result.get('error')}")
            elif result.get("status") == "no_ads":
                st.warning("No ads found at that URL. Check the URL is valid and the page has active ads.")
            elif result.get("status") == "no_new_ads":
                st.info("These ads were already scraped. Check the Pending Review tab for existing templates.")
            elif result.get("status") == "no_assets":
                st.warning("Ads were found but no images/videos could be downloaded. The ads may only have text content.")
            else:
                st.warning(f"Status: {result.get('status')} - {result.get('message', '')}")

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
