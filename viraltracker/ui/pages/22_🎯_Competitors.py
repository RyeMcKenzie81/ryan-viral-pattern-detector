"""
Competitor Management - Track and manage brand competitors.

This page allows users to:
- Add competitors for a brand
- View competitor details and stats
- Configure competitor Ad Library URLs, websites, Amazon URLs
- Launch competitor research from here
"""

import streamlit as st
from datetime import datetime
from typing import Optional, Dict, Any, List
from uuid import UUID

# Page config
st.set_page_config(
    page_title="Competitors",
    page_icon="🎯",
    layout="wide"
)

# Authentication
from viraltracker.ui.auth import require_auth
require_auth()

# Initialize session state
if 'selected_brand_id' not in st.session_state:
    st.session_state.selected_brand_id = None
if 'editing_competitor_id' not in st.session_state:
    st.session_state.editing_competitor_id = None


def get_supabase_client():
    """Get Supabase client."""
    from viraltracker.core.database import get_supabase_client
    return get_supabase_client()


def get_competitor_service():
    """Get CompetitorService instance."""
    from viraltracker.services.competitor_service import CompetitorService
    return CompetitorService()


def get_brands():
    """Fetch all brands."""
    try:
        db = get_supabase_client()
        result = db.table("brands").select("id, name").order("name").execute()
        return result.data or []
    except Exception as e:
        st.error(f"Failed to fetch brands: {e}")
        return []


def render_competitor_card(competitor: Dict[str, Any], service):
    """Render a competitor card with stats and actions."""
    with st.container():
        col1, col2, col3 = st.columns([3, 2, 1])

        with col1:
            st.markdown(f"### {competitor['name']}")

            if competitor.get('website_url'):
                st.caption(f"🌐 {competitor['website_url']}")

            if competitor.get('amazon_url'):
                st.caption(f"📦 Amazon: {competitor['amazon_url'][:50]}...")

            if competitor.get('industry'):
                st.caption(f"📁 {competitor['industry']}")

            if competitor.get('notes'):
                st.caption(f"📝 {competitor['notes']}")

        with col2:
            # Get stats
            stats = service.get_competitor_stats(UUID(competitor['id']))

            stat_col1, stat_col2, stat_col3 = st.columns(3)
            with stat_col1:
                st.metric("Ads", stats['ads'])
            with stat_col2:
                st.metric("Assets", stats['videos'] + stats['images'])
            with stat_col3:
                st.metric("Analyses", stats['video_analyses'] + stats['image_analyses'] + stats['copy_analyses'])

            # Last activity
            if competitor.get('last_scraped_at'):
                scraped = datetime.fromisoformat(competitor['last_scraped_at'].replace('Z', '+00:00'))
                st.caption(f"Last scraped: {scraped.strftime('%Y-%m-%d')}")

            if competitor.get('last_analyzed_at'):
                analyzed = datetime.fromisoformat(competitor['last_analyzed_at'].replace('Z', '+00:00'))
                st.caption(f"Last analyzed: {analyzed.strftime('%Y-%m-%d')}")

        with col3:
            # Actions
            if st.button("✏️ Edit", key=f"edit_{competitor['id']}", help="Edit competitor"):
                st.session_state.editing_competitor_id = competitor['id']
                st.rerun()

            if st.button("🔬 Research", key=f"research_{competitor['id']}", help="Go to Competitor Research"):
                st.session_state.research_competitor_id = competitor['id']
                st.switch_page("pages/23_🔍_Competitor_Research.py")

            if st.button("🗑️ Delete", key=f"delete_{competitor['id']}", help="Delete competitor"):
                if service.delete_competitor(UUID(competitor['id'])):
                    st.success(f"Deleted {competitor['name']}")
                    st.rerun()
                else:
                    st.error("Failed to delete competitor")

        st.divider()


def render_add_competitor_form(brand_id: str, service):
    """Render form to add a new competitor."""
    st.subheader("➕ Add Competitor")

    with st.form("add_competitor_form"):
        name = st.text_input("Competitor Name *", placeholder="e.g., AG1, Ka'Chava")

        col1, col2 = st.columns(2)
        with col1:
            website_url = st.text_input(
                "Website URL",
                placeholder="https://drinkag1.com"
            )
            facebook_page_id = st.text_input(
                "Facebook Page ID",
                placeholder="123456789",
                help="Found in the Ad Library URL"
            )

        with col2:
            ad_library_url = st.text_input(
                "Ad Library URL",
                placeholder="https://www.facebook.com/ads/library/?view_all_page_id=123456789",
                help="URL to their Facebook Ad Library page"
            )
            amazon_url = st.text_input(
                "Amazon Product URL",
                placeholder="https://www.amazon.com/dp/B0DJWSV1J3",
                help="Amazon product URL for review scraping"
            )

        industry = st.text_input(
            "Industry",
            placeholder="e.g., Health & Wellness, Pet Care"
        )

        notes = st.text_area(
            "Notes",
            placeholder="Any notes about this competitor..."
        )

        submitted = st.form_submit_button("Add Competitor", type="primary")

        if submitted:
            if not name:
                st.error("Competitor name is required")
            else:
                try:
                    competitor = service.create_competitor(
                        brand_id=UUID(brand_id),
                        name=name,
                        website_url=website_url or None,
                        facebook_page_id=facebook_page_id or None,
                        ad_library_url=ad_library_url or None,
                        amazon_url=amazon_url or None,
                        industry=industry or None,
                        notes=notes or None
                    )
                    st.success(f"Added competitor: {name}")
                    st.rerun()
                except Exception as e:
                    st.error(f"Failed to add competitor: {e}")


def render_edit_competitor_form(competitor_id: str, service):
    """Render form to edit an existing competitor."""
    competitor = service.get_competitor(UUID(competitor_id))

    if not competitor:
        st.error("Competitor not found")
        st.session_state.editing_competitor_id = None
        return

    st.subheader(f"✏️ Edit: {competitor['name']}")

    with st.form("edit_competitor_form"):
        name = st.text_input("Competitor Name *", value=competitor['name'])

        col1, col2 = st.columns(2)
        with col1:
            website_url = st.text_input(
                "Website URL",
                value=competitor.get('website_url') or ""
            )
            facebook_page_id = st.text_input(
                "Facebook Page ID",
                value=competitor.get('facebook_page_id') or ""
            )

        with col2:
            ad_library_url = st.text_input(
                "Ad Library URL",
                value=competitor.get('ad_library_url') or ""
            )
            amazon_url = st.text_input(
                "Amazon Product URL",
                value=competitor.get('amazon_url') or ""
            )

        industry = st.text_input(
            "Industry",
            value=competitor.get('industry') or ""
        )

        notes = st.text_area(
            "Notes",
            value=competitor.get('notes') or ""
        )

        col1, col2 = st.columns(2)
        with col1:
            submitted = st.form_submit_button("Save Changes", type="primary")
        with col2:
            cancelled = st.form_submit_button("Cancel")

        if submitted:
            if not name:
                st.error("Competitor name is required")
            else:
                try:
                    service.update_competitor(
                        competitor_id=UUID(competitor_id),
                        updates={
                            "name": name,
                            "website_url": website_url or None,
                            "facebook_page_id": facebook_page_id or None,
                            "ad_library_url": ad_library_url or None,
                            "amazon_url": amazon_url or None,
                            "industry": industry or None,
                            "notes": notes or None
                        }
                    )
                    st.success(f"Updated competitor: {name}")
                    st.session_state.editing_competitor_id = None
                    st.rerun()
                except Exception as e:
                    st.error(f"Failed to update competitor: {e}")

        if cancelled:
            st.session_state.editing_competitor_id = None
            st.rerun()


# =============================================================================
# Main Page
# =============================================================================

st.title("🎯 Competitors")
st.caption("Track and analyze your brand's competitors")

# Brand selector
brands = get_brands()

if not brands:
    st.warning("No brands found. Please create a brand first in Brand Manager.")
    st.stop()

brand_options = {b['name']: b['id'] for b in brands}
selected_brand_name = st.selectbox(
    "Select Brand",
    options=list(brand_options.keys()),
    index=0
)

if selected_brand_name:
    brand_id = brand_options[selected_brand_name]
    st.session_state.selected_brand_id = brand_id
else:
    st.stop()

st.divider()

# Get service and competitors
service = get_competitor_service()
competitors = service.get_competitors_for_brand(UUID(brand_id))

# Show edit form if editing
if st.session_state.editing_competitor_id:
    render_edit_competitor_form(st.session_state.editing_competitor_id, service)
    st.divider()

# Show existing competitors
if competitors:
    st.subheader(f"📊 {len(competitors)} Competitor(s)")

    for competitor in competitors:
        render_competitor_card(competitor, service)
else:
    st.info("No competitors added yet. Add your first competitor below.")

# Add competitor form
with st.expander("➕ Add New Competitor", expanded=not competitors):
    render_add_competitor_form(brand_id, service)

# Help section
with st.expander("ℹ️ How to Find Competitor Ad Library URLs"):
    st.markdown("""
    ### Finding a Competitor's Facebook Ad Library URL

    1. Go to [Facebook Ad Library](https://www.facebook.com/ads/library/)
    2. Search for the competitor's brand name or Facebook page
    3. Click on their page in the results
    4. Copy the full URL from your browser

    **Example URL format:**
    ```
    https://www.facebook.com/ads/library/?active_status=all&ad_type=all&country=US&view_all_page_id=123456789
    ```

    The `view_all_page_id` parameter contains the Page ID we need for scraping.

    ### What Gets Scraped

    When you run research on a competitor, we'll:
    - **Scrape Ads**: Pull their active and recent ads from the Ad Library
    - **Download Assets**: Save their video and image creatives
    - **Analyze Content**: Extract hooks, pain points, desires, and messaging patterns
    - **Scrape Landing Pages**: Pull content from their website
    - **Synthesize Persona**: Generate a 4D persona of who they're targeting

    ### Tips

    - Start with your top 3-5 direct competitors
    - Include both larger established brands and newer disruptors
    - Add the Amazon URL if they sell on Amazon (for review analysis)
    """)
