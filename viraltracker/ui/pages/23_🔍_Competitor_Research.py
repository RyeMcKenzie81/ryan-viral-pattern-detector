"""
Competitor Research - Analyze competitor ads to understand their targeting.

This page allows users to:
- Select a competitor to research
- Scrape ads from Facebook Ad Library
- Download video/image assets from competitor ads
- Analyze videos, images, and ad copy
- Scrape and analyze competitor landing pages
- Synthesize insights into competitor 4D personas
"""

import streamlit as st
import asyncio
import json
from datetime import datetime
from uuid import UUID
from typing import Optional, Dict, Any, List

# Page config
st.set_page_config(
    page_title="Competitor Research",
    page_icon="🔍",
    layout="wide"
)

# Authentication
from viraltracker.ui.auth import require_auth
require_auth()

# Initialize session state
if 'research_competitor_id' not in st.session_state:
    st.session_state.research_competitor_id = None
if 'competitor_analysis_running' not in st.session_state:
    st.session_state.competitor_analysis_running = False
if 'competitor_persona' not in st.session_state:
    st.session_state.competitor_persona = None


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


def get_competitors_for_brand(brand_id: str):
    """Fetch competitors for a brand."""
    try:
        db = get_supabase_client()
        result = db.table("competitors").select("*").eq(
            "brand_id", brand_id
        ).order("name").execute()
        return result.data or []
    except Exception as e:
        st.error(f"Failed to fetch competitors: {e}")
        return []


# =============================================================================
# Async Wrappers (run async in sync Streamlit context)
# =============================================================================

def scrape_ads_sync(competitor_id: str, ad_library_url: str, limit: int) -> Dict:
    """Sync wrapper for ad scraping."""
    from viraltracker.core.database import reset_supabase_client
    reset_supabase_client()

    service = get_competitor_service()

    async def _run():
        return await service.scrape_competitor_ads(
            competitor_id=UUID(competitor_id),
            ad_library_url=ad_library_url,
            max_ads=limit
        )

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(_run())
    finally:
        loop.close()


def download_assets_sync(competitor_id: str, limit: int) -> Dict:
    """Sync wrapper for asset download."""
    from viraltracker.core.database import reset_supabase_client
    reset_supabase_client()

    service = get_competitor_service()

    async def _run():
        return await service.download_competitor_assets(
            competitor_id=UUID(competitor_id),
            limit=limit
        )

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(_run())
    finally:
        loop.close()


def analyze_videos_sync(competitor_id: str, limit: int) -> List[Dict]:
    """Sync wrapper for video analysis."""
    from viraltracker.core.database import reset_supabase_client
    reset_supabase_client()

    service = get_competitor_service()

    async def _run():
        return await service.analyze_competitor_videos(
            competitor_id=UUID(competitor_id),
            limit=limit
        )

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(_run())
    finally:
        loop.close()


def analyze_images_sync(competitor_id: str, limit: int) -> List[Dict]:
    """Sync wrapper for image analysis."""
    from viraltracker.core.database import reset_supabase_client
    reset_supabase_client()

    service = get_competitor_service()

    async def _run():
        return await service.analyze_competitor_images(
            competitor_id=UUID(competitor_id),
            limit=limit
        )

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(_run())
    finally:
        loop.close()


def analyze_copy_sync(competitor_id: str, limit: int) -> List[Dict]:
    """Sync wrapper for copy analysis."""
    from viraltracker.core.database import reset_supabase_client
    reset_supabase_client()

    service = get_competitor_service()

    async def _run():
        return await service.analyze_competitor_copy(
            competitor_id=UUID(competitor_id),
            limit=limit
        )

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(_run())
    finally:
        loop.close()


def scrape_landing_pages_sync(competitor_id: str, limit: int) -> Dict:
    """Sync wrapper for landing page scraping."""
    from viraltracker.core.database import reset_supabase_client
    reset_supabase_client()

    service = get_competitor_service()

    async def _run():
        return await service.scrape_competitor_landing_pages(
            competitor_id=UUID(competitor_id),
            limit=limit
        )

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(_run())
    finally:
        loop.close()


def analyze_landing_pages_sync(competitor_id: str, limit: int) -> List[Dict]:
    """Sync wrapper for landing page analysis."""
    from viraltracker.core.database import reset_supabase_client
    reset_supabase_client()

    service = get_competitor_service()

    async def _run():
        return await service.analyze_competitor_landing_pages(
            competitor_id=UUID(competitor_id),
            limit=limit
        )

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(_run())
    finally:
        loop.close()


def synthesize_persona_sync(competitor_id: str) -> Dict:
    """Sync wrapper for persona synthesis."""
    from viraltracker.core.database import reset_supabase_client
    reset_supabase_client()

    service = get_competitor_service()

    async def _run():
        return await service.synthesize_competitor_persona(
            competitor_id=UUID(competitor_id)
        )

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(_run())
    finally:
        loop.close()


# =============================================================================
# UI Components
# =============================================================================

def render_stats_dashboard(competitor: Dict, stats: Dict):
    """Render statistics dashboard."""
    st.subheader("📊 Research Progress")

    col1, col2, col3, col4, col5 = st.columns(5)

    with col1:
        st.metric("Ads Scraped", stats['ads'])
        if competitor.get('last_scraped_at'):
            scraped = datetime.fromisoformat(competitor['last_scraped_at'].replace('Z', '+00:00'))
            st.caption(f"Last: {scraped.strftime('%m/%d')}")

    with col2:
        st.metric("Videos", stats['videos'])
        if stats['video_analyses'] > 0:
            pending = stats['videos'] - stats['video_analyses']
            st.caption(f"{stats['video_analyses']} analyzed" + (f", {pending} pending" if pending > 0 else ""))

    with col3:
        st.metric("Images", stats['images'])
        if stats['image_analyses'] > 0:
            pending = stats['images'] - stats['image_analyses']
            st.caption(f"{stats['image_analyses']} analyzed" + (f", {pending} pending" if pending > 0 else ""))

    with col4:
        st.metric("Copy Analyzed", stats['copy_analyses'])
        if stats['ads'] > 0:
            pending = stats['ads'] - stats['copy_analyses']
            if pending > 0:
                st.caption(f"{pending} pending")

    with col5:
        st.metric("Landing Pages", f"{stats['landing_pages_analyzed']}/{stats['landing_pages']}")
        if stats['landing_pages_scraped'] > stats['landing_pages_analyzed']:
            to_analyze = stats['landing_pages_scraped'] - stats['landing_pages_analyzed']
            st.caption(f"{to_analyze} to analyze")


def render_scrape_section(competitor: Dict):
    """Render ad scraping section."""
    st.subheader("1. Scrape Competitor Ads")
    st.markdown("Pull ads from Facebook Ad Library for this competitor.")

    if not competitor.get('ad_library_url'):
        st.warning("No Ad Library URL configured. Add it on the Competitors page.")
        return

    st.caption(f"**Ad Library URL:** {competitor['ad_library_url'][:80]}...")

    col1, col2 = st.columns([2, 1])

    with col1:
        limit = st.slider("Max ads to scrape", 10, 100, 50, key="scrape_limit")

    with col2:
        if st.button("Scrape Ads", type="primary", disabled=st.session_state.competitor_analysis_running):
            st.session_state.competitor_analysis_running = True

            with st.spinner("Scraping ads from Facebook Ad Library (may take 1-3 minutes)..."):
                try:
                    result = scrape_ads_sync(
                        competitor['id'],
                        competitor['ad_library_url'],
                        limit
                    )
                    st.success(
                        f"Scraped {result['ads_scraped']} ads: "
                        f"{result['ads_new']} new, {result['ads_existing']} existing"
                    )
                except Exception as e:
                    st.error(f"Scraping failed: {e}")

            st.session_state.competitor_analysis_running = False
            st.rerun()


def render_download_section(competitor_id: str):
    """Render asset download section."""
    st.subheader("2. Download Assets")
    st.markdown("Download video and image assets from scraped ads.")

    col1, col2 = st.columns([2, 1])

    with col1:
        limit = st.slider("Max ads to process", 10, 100, 50, key="download_limit")

    with col2:
        if st.button("Download Assets", type="primary", disabled=st.session_state.competitor_analysis_running):
            st.session_state.competitor_analysis_running = True

            with st.spinner("Downloading assets from ad snapshots..."):
                try:
                    result = download_assets_sync(competitor_id, limit)

                    reason = result.get('reason')
                    if reason == 'all_have_assets':
                        st.success("All ads already have assets downloaded.")
                    elif result['videos_downloaded'] > 0 or result['images_downloaded'] > 0:
                        st.success(
                            f"Downloaded {result['videos_downloaded']} videos, "
                            f"{result['images_downloaded']} images from {result['ads_processed']} ads"
                        )
                    else:
                        st.warning(f"No assets downloaded. Processed {result['ads_processed']} ads.")

                except Exception as e:
                    st.error(f"Download failed: {e}")

            st.session_state.competitor_analysis_running = False
            st.rerun()


def render_analysis_section(competitor_id: str):
    """Render analysis controls."""
    st.subheader("3. Analyze Assets")
    st.markdown("Run AI analysis on videos, images, and ad copy to extract persona signals.")

    col1, col2, col3 = st.columns(3)

    with col1:
        st.markdown("**Video Analysis**")
        st.caption("Transcripts, hooks, persona signals")
        video_limit = st.number_input("Videos to analyze", 1, 20, 10, key="video_limit")

        if st.button("Analyze Videos", disabled=st.session_state.competitor_analysis_running, key="btn_video"):
            st.session_state.competitor_analysis_running = True

            with st.spinner(f"Analyzing up to {video_limit} videos..."):
                try:
                    results = analyze_videos_sync(competitor_id, video_limit)
                    success_count = len([r for r in results if 'analysis' in r])
                    st.success(f"Analyzed {success_count} videos")
                except Exception as e:
                    st.error(f"Video analysis failed: {e}")

            st.session_state.competitor_analysis_running = False
            st.rerun()

    with col2:
        st.markdown("**Image Analysis**")
        st.caption("Visual style, text overlays, hooks")
        image_limit = st.number_input("Images to analyze", 1, 50, 20, key="image_limit")

        if st.button("Analyze Images", disabled=st.session_state.competitor_analysis_running, key="btn_image"):
            st.session_state.competitor_analysis_running = True

            with st.spinner(f"Analyzing up to {image_limit} images..."):
                try:
                    results = analyze_images_sync(competitor_id, image_limit)
                    success_count = len([r for r in results if 'analysis' in r])
                    st.success(f"Analyzed {success_count} images")
                except Exception as e:
                    st.error(f"Image analysis failed: {e}")

            st.session_state.competitor_analysis_running = False
            st.rerun()

    with col3:
        st.markdown("**Copy Analysis**")
        st.caption("Headlines, hooks, messaging patterns")
        copy_limit = st.number_input("Ads to analyze", 1, 100, 50, key="copy_limit")

        if st.button("Analyze Copy", disabled=st.session_state.competitor_analysis_running, key="btn_copy"):
            st.session_state.competitor_analysis_running = True

            with st.spinner(f"Analyzing ad copy from up to {copy_limit} ads..."):
                try:
                    results = analyze_copy_sync(competitor_id, copy_limit)
                    success_count = len([r for r in results if 'analysis' in r])
                    st.success(f"Analyzed {success_count} ad copy texts")
                except Exception as e:
                    st.error(f"Copy analysis failed: {e}")

            st.session_state.competitor_analysis_running = False
            st.rerun()


def render_landing_page_section(competitor_id: str, stats: Dict):
    """Render landing page scraping and analysis section."""
    st.subheader("4. Landing Pages")
    st.markdown("Scrape and analyze competitor landing pages for deeper insights.")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("**Scrape Landing Pages**")
        st.caption("Extract content from URLs found in ads")

        lp_count = stats['landing_pages']
        scraped = stats['landing_pages_scraped']
        to_scrape = lp_count - scraped if lp_count > scraped else 0

        if to_scrape > 0:
            st.info(f"{to_scrape} URLs ready to scrape")
        elif scraped > 0:
            st.success(f"All {lp_count} URLs scraped")

        scrape_limit = st.number_input("Pages to scrape", 1, 20, min(10, max(1, to_scrape)), key="lp_scrape_limit")

        if st.button("Scrape Landing Pages", disabled=st.session_state.competitor_analysis_running, key="btn_scrape_lp"):
            st.session_state.competitor_analysis_running = True

            with st.spinner(f"Scraping up to {scrape_limit} landing pages..."):
                try:
                    result = scrape_landing_pages_sync(competitor_id, scrape_limit)
                    st.success(
                        f"Scraped {result['pages_scraped']} pages "
                        f"({result['pages_failed']} failed)"
                    )
                except Exception as e:
                    st.error(f"Scraping failed: {e}")

            st.session_state.competitor_analysis_running = False
            st.rerun()

    with col2:
        st.markdown("**Analyze Landing Pages**")
        st.caption("Extract offers, USPs, objection handling")

        analyzed = stats['landing_pages_analyzed']
        to_analyze = stats['landing_pages_scraped'] - analyzed

        if to_analyze > 0:
            st.info(f"{to_analyze} pages ready to analyze")
        elif analyzed > 0:
            st.success(f"All {analyzed} pages analyzed")

        analyze_limit = st.number_input("Pages to analyze", 1, 20, min(10, max(1, to_analyze)), key="lp_analyze_limit")

        btn_disabled = st.session_state.competitor_analysis_running or to_analyze == 0
        if st.button("Analyze Landing Pages", disabled=btn_disabled, key="btn_analyze_lp"):
            st.session_state.competitor_analysis_running = True

            with st.spinner(f"Analyzing up to {analyze_limit} landing pages..."):
                try:
                    results = analyze_landing_pages_sync(competitor_id, analyze_limit)
                    success_count = len([r for r in results if 'analysis' in r])
                    st.success(f"Analyzed {success_count} landing pages")
                except Exception as e:
                    st.error(f"Analysis failed: {e}")

            st.session_state.competitor_analysis_running = False
            st.rerun()


def render_synthesis_section(competitor_id: str, competitor_name: str, stats: Dict):
    """Render persona synthesis section."""
    st.subheader("5. Synthesize Competitor Persona")
    st.markdown("Generate a 4D persona profile of who this competitor is targeting.")

    # Check if we have enough data
    total_analyses = stats['video_analyses'] + stats['image_analyses'] + stats['copy_analyses']

    if total_analyses < 5:
        st.warning(
            f"Only {total_analyses} analyses completed. "
            "Run more analyses above for better persona synthesis."
        )

    if st.button(
        "Synthesize Competitor Persona",
        type="primary",
        disabled=st.session_state.competitor_analysis_running or total_analyses == 0,
        key="btn_synthesize"
    ):
        st.session_state.competitor_analysis_running = True

        with st.spinner("Synthesizing persona from all analyses (30-60 seconds)..."):
            try:
                persona = synthesize_persona_sync(competitor_id)
                st.session_state.competitor_persona = persona
                st.success("Persona synthesized!")
            except Exception as e:
                st.error(f"Synthesis failed: {e}")

        st.session_state.competitor_analysis_running = False
        st.rerun()

    # Display synthesized persona
    if st.session_state.competitor_persona:
        persona = st.session_state.competitor_persona

        st.divider()
        st.subheader(f"📋 {competitor_name} Target Persona")

        # Name and snapshot
        st.markdown(f"### {persona.get('name', 'Target Customer')}")
        if persona.get('snapshot'):
            st.markdown(persona['snapshot'])

        # Tabs for different dimensions
        tabs = st.tabs([
            "Demographics",
            "Pain & Desires",
            "Identity",
            "Worldview",
            "Purchase Behavior"
        ])

        with tabs[0]:
            demo = persona.get('demographics', {})
            if demo:
                col1, col2 = st.columns(2)
                with col1:
                    if demo.get('age_range'):
                        st.markdown(f"**Age:** {demo['age_range']}")
                    if demo.get('gender'):
                        st.markdown(f"**Gender:** {demo['gender']}")
                    if demo.get('location'):
                        st.markdown(f"**Location:** {demo['location']}")
                with col2:
                    if demo.get('income_level'):
                        st.markdown(f"**Income:** {demo['income_level']}")
                    if demo.get('occupation'):
                        st.markdown(f"**Occupation:** {demo['occupation']}")
                    if demo.get('family_status'):
                        st.markdown(f"**Family:** {demo['family_status']}")

        with tabs[1]:
            col1, col2 = st.columns(2)
            with col1:
                st.markdown("**Pain Points**")
                pain = persona.get('pain_points', {})
                for category in ['emotional', 'social', 'functional']:
                    if pain.get(category):
                        st.markdown(f"*{category.title()}:*")
                        for p in pain[category][:5]:
                            st.markdown(f"- {p}")

            with col2:
                st.markdown("**Desires**")
                desires = persona.get('desires', {})
                if isinstance(desires, dict):
                    for category, items in list(desires.items())[:5]:
                        if items:
                            st.markdown(f"*{category.replace('_', ' ').title()}:*")
                            for d in (items[:3] if isinstance(items, list) else [items]):
                                st.markdown(f"- {d}")

        with tabs[2]:
            if persona.get('self_narratives'):
                st.markdown("**Self-Narratives:**")
                for narrative in persona['self_narratives'][:5]:
                    st.markdown(f"- \"{narrative}\"")

            if persona.get('current_self_image'):
                st.markdown(f"**Current Self-Image:** {persona['current_self_image']}")

            if persona.get('desired_self_image'):
                st.markdown(f"**Desired Self-Image:** {persona['desired_self_image']}")

        with tabs[3]:
            if persona.get('worldview'):
                st.markdown(f"**Worldview:** {persona['worldview']}")

            if persona.get('core_values'):
                st.markdown("**Core Values:**")
                st.markdown(", ".join(persona['core_values'][:5]))

            if persona.get('allergies'):
                st.markdown("**Brand Allergies (Triggers):**")
                allergies = persona['allergies']
                if isinstance(allergies, dict):
                    for trigger, reaction in list(allergies.items())[:5]:
                        st.markdown(f"- {trigger}: {reaction}")

        with tabs[4]:
            if persona.get('activation_events'):
                st.markdown("**Activation Events (What triggers purchase):**")
                for event in persona['activation_events'][:5]:
                    st.markdown(f"- {event}")

            if persona.get('buying_objections'):
                st.markdown("**Buying Objections:**")
                objections = persona['buying_objections']
                if isinstance(objections, dict):
                    for category in ['emotional', 'social', 'functional']:
                        if objections.get(category):
                            st.markdown(f"*{category.title()}:*")
                            for o in objections[category][:3]:
                                st.markdown(f"- {o}")

            if persona.get('decision_process'):
                st.markdown(f"**Decision Process:** {persona['decision_process']}")

        # Export option
        st.divider()
        if st.button("📥 Export Persona JSON"):
            st.download_button(
                label="Download JSON",
                data=json.dumps(persona, indent=2),
                file_name=f"{competitor_name.lower().replace(' ', '_')}_persona.json",
                mime="application/json"
            )


# =============================================================================
# Main Page
# =============================================================================

st.title("🔍 Competitor Research")
st.caption("Analyze competitor ads to understand their targeting and messaging")

# Brand selector
brands = get_brands()

if not brands:
    st.warning("No brands found. Create a brand first in Brand Manager.")
    st.stop()

brand_options = {b['name']: b['id'] for b in brands}
selected_brand_name = st.selectbox(
    "Select Your Brand",
    options=list(brand_options.keys()),
    index=0,
    help="Select your brand to see its competitors"
)

if not selected_brand_name:
    st.stop()

brand_id = brand_options[selected_brand_name]

# Competitor selector
competitors = get_competitors_for_brand(brand_id)

if not competitors:
    st.warning(
        f"No competitors found for {selected_brand_name}. "
        "Add competitors on the Competitors page."
    )
    if st.button("Go to Competitors Page"):
        st.switch_page("pages/22_🎯_Competitors.py")
    st.stop()

competitor_options = {c['name']: c for c in competitors}
selected_competitor_name = st.selectbox(
    "Select Competitor to Research",
    options=list(competitor_options.keys()),
    index=0
)

if not selected_competitor_name:
    st.stop()

competitor = competitor_options[selected_competitor_name]
competitor_id = competitor['id']
st.session_state.research_competitor_id = competitor_id

st.divider()

# Get service and stats
service = get_competitor_service()
stats = service.get_competitor_stats(UUID(competitor_id))

# Render sections
render_stats_dashboard(competitor, stats)
st.divider()

render_scrape_section(competitor)
st.divider()

render_download_section(competitor_id)
st.divider()

render_analysis_section(competitor_id)
st.divider()

render_landing_page_section(competitor_id, stats)
st.divider()

render_synthesis_section(competitor_id, selected_competitor_name, stats)
