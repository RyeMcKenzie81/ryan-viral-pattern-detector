"""
Brand Research - Analyze brand ads to build 4D customer personas.

This page allows users to:
- Select a brand for research
- Download video/image assets from existing ads
- Analyze videos, images, and ad copy
- View analysis progress and stats
- Synthesize insights into 4D personas
- Review and approve generated personas
"""

import streamlit as st
import asyncio
import json
from datetime import datetime
from uuid import UUID
from typing import Optional, Dict, Any, List

# Page config
st.set_page_config(
    page_title="Brand Research",
    page_icon="🔬",
    layout="wide"
)

# Authentication
from viraltracker.ui.auth import require_auth
require_auth()

# Initialize session state
if 'research_brand_id' not in st.session_state:
    st.session_state.research_brand_id = None
if 'analysis_running' not in st.session_state:
    st.session_state.analysis_running = False
if 'suggested_personas' not in st.session_state:
    st.session_state.suggested_personas = []
if 'review_mode' not in st.session_state:
    st.session_state.review_mode = False


def get_supabase_client():
    """Get Supabase client."""
    from viraltracker.core.database import get_supabase_client
    return get_supabase_client()


def get_brand_research_service():
    """Get BrandResearchService instance."""
    from viraltracker.services.brand_research_service import BrandResearchService
    return BrandResearchService()


def get_persona_service():
    """Get PersonaService instance."""
    from viraltracker.services.persona_service import PersonaService
    return PersonaService()


def get_brands():
    """Fetch all brands."""
    try:
        db = get_supabase_client()
        result = db.table("brands").select("id, name").order("name").execute()
        return result.data
    except Exception as e:
        st.error(f"Failed to fetch brands: {e}")
        return []


def get_products_for_brand(brand_id: str):
    """Fetch products for a brand."""
    try:
        db = get_supabase_client()
        result = db.table("products").select("id, name").eq(
            "brand_id", brand_id
        ).order("name").execute()
        return result.data
    except Exception as e:
        st.error(f"Failed to fetch products: {e}")
        return []


def get_ad_count_for_brand(brand_id: str) -> int:
    """Get count of ads linked to a brand."""
    try:
        db = get_supabase_client()
        result = db.table("brand_facebook_ads").select(
            "ad_id", count="exact"
        ).eq("brand_id", brand_id).execute()
        return result.count or 0
    except Exception:
        return 0


def get_asset_stats_for_brand(brand_id: str) -> Dict[str, int]:
    """Get counts of video/image assets for a brand."""
    try:
        db = get_supabase_client()

        # Get ad IDs for brand
        link_result = db.table("brand_facebook_ads").select("ad_id").eq(
            "brand_id", brand_id
        ).execute()

        if not link_result.data:
            return {"total": 0, "videos": 0, "images": 0}

        ad_ids = [r['ad_id'] for r in link_result.data]

        # Get asset counts
        assets_result = db.table("scraped_ad_assets").select(
            "id, mime_type"
        ).in_("facebook_ad_id", ad_ids).execute()

        videos = sum(1 for a in assets_result.data if a.get('mime_type', '').startswith('video/'))
        images = sum(1 for a in assets_result.data if a.get('mime_type', '').startswith('image/'))

        return {
            "total": len(assets_result.data),
            "videos": videos,
            "images": images
        }
    except Exception as e:
        st.error(f"Failed to get asset stats: {e}")
        return {"total": 0, "videos": 0, "images": 0}


def get_analysis_stats_for_brand(brand_id: str) -> Dict[str, int]:
    """Get counts of completed analyses for a brand."""
    try:
        db = get_supabase_client()

        result = db.table("brand_ad_analysis").select(
            "analysis_type"
        ).eq("brand_id", brand_id).execute()

        stats = {
            "video_vision": 0,
            "image_vision": 0,
            "copy_analysis": 0,
            "total": len(result.data)
        }

        for row in result.data:
            analysis_type = row.get("analysis_type", "")
            if analysis_type in stats:
                stats[analysis_type] += 1

        return stats
    except Exception as e:
        st.error(f"Failed to get analysis stats: {e}")
        return {"video_vision": 0, "image_vision": 0, "copy_analysis": 0, "total": 0}


def run_async(coro):
    """Run async function in Streamlit context."""
    return asyncio.run(coro)


def download_assets_sync(brand_id: str, limit: int = 50) -> Dict[str, int]:
    """Download assets for brand (sync wrapper)."""
    service = get_brand_research_service()
    return run_async(service.download_assets_for_brand(UUID(brand_id), limit=limit))


def analyze_videos_sync(brand_id: str, limit: int = 10) -> List[Dict]:
    """Analyze videos for brand (sync wrapper)."""
    service = get_brand_research_service()

    # Get unanalyzed video assets
    video_assets = service.get_video_assets_for_brand(UUID(brand_id), only_unanalyzed=True, limit=limit)

    if not video_assets:
        return []

    asset_ids = [UUID(v['id']) for v in video_assets]
    return run_async(service.analyze_videos_batch(asset_ids, UUID(brand_id)))


def analyze_images_sync(brand_id: str, limit: int = 20) -> List[Dict]:
    """Analyze images for brand (sync wrapper)."""
    service = get_brand_research_service()

    # Get unanalyzed image assets
    image_assets = get_image_assets_for_brand(brand_id, only_unanalyzed=True, limit=limit)

    if not image_assets:
        return []

    asset_ids = [UUID(a['id']) for a in image_assets]
    return run_async(service.analyze_images_batch(asset_ids, UUID(brand_id)))


def get_image_assets_for_brand(brand_id: str, only_unanalyzed: bool = True, limit: int = 50) -> List[Dict]:
    """Get image assets for a brand."""
    try:
        db = get_supabase_client()

        # Get ad IDs from junction table
        link_result = db.table("brand_facebook_ads").select("ad_id").eq(
            "brand_id", brand_id
        ).execute()

        if not link_result.data:
            return []

        ad_ids = [r['ad_id'] for r in link_result.data]

        # Get image assets
        assets_result = db.table("scraped_ad_assets").select(
            "id, facebook_ad_id, storage_path, mime_type"
        ).in_("facebook_ad_id", ad_ids).like("mime_type", "image/%").limit(limit * 2).execute()

        if not assets_result.data:
            return []

        image_assets = assets_result.data

        # Filter out already analyzed if requested
        if only_unanalyzed:
            asset_ids = [a['id'] for a in image_assets]
            analyzed_result = db.table("brand_ad_analysis").select(
                "asset_id"
            ).in_("asset_id", asset_ids).eq("analysis_type", "image_vision").execute()

            analyzed_ids = {r['asset_id'] for r in (analyzed_result.data or [])}
            image_assets = [a for a in image_assets if a['id'] not in analyzed_ids]

        return image_assets[:limit]
    except Exception as e:
        st.error(f"Failed to get image assets: {e}")
        return []


def analyze_copy_sync(brand_id: str, limit: int = 50) -> List[Dict]:
    """Analyze ad copy for brand (sync wrapper)."""
    service = get_brand_research_service()
    return run_async(service.analyze_copy_batch(UUID(brand_id), limit=limit))


def synthesize_personas_sync(brand_id: str) -> List[Dict]:
    """Synthesize personas from analyses (sync wrapper)."""
    service = get_brand_research_service()
    return run_async(service.synthesize_to_personas(UUID(brand_id)))


def render_brand_selector():
    """Render brand selector."""
    brands = get_brands()

    if not brands:
        st.warning("No brands found. Please create a brand first in Brand Manager.")
        return None

    brand_options = {b["name"]: b["id"] for b in brands}

    selected_name = st.selectbox(
        "Select Brand to Research",
        options=list(brand_options.keys()),
        index=0
    )

    return brand_options[selected_name]


def render_stats_section(brand_id: str):
    """Render statistics about the brand's data."""
    col1, col2, col3, col4 = st.columns(4)

    ad_count = get_ad_count_for_brand(brand_id)
    asset_stats = get_asset_stats_for_brand(brand_id)
    analysis_stats = get_analysis_stats_for_brand(brand_id)

    with col1:
        st.metric("Ads Linked", ad_count)

    with col2:
        st.metric("Videos Available", asset_stats["videos"])
        if analysis_stats["video_vision"] > 0:
            st.caption(f"{analysis_stats['video_vision']} analyzed")

    with col3:
        st.metric("Images Available", asset_stats["images"])
        if analysis_stats["image_vision"] > 0:
            st.caption(f"{analysis_stats['image_vision']} analyzed")

    with col4:
        st.metric("Copy Analyzed", analysis_stats["copy_analysis"])


def render_download_section(brand_id: str):
    """Render asset download section."""
    st.subheader("1. Download Assets")
    st.markdown("Download video and image assets from linked ads to storage.")

    col1, col2 = st.columns([2, 1])

    with col1:
        limit = st.slider("Max ads to process", 10, 100, 50, key="download_limit")

    with col2:
        if st.button("Download Assets", type="primary", disabled=st.session_state.analysis_running):
            st.session_state.analysis_running = True

            with st.spinner("Downloading assets from ad snapshots..."):
                try:
                    result = download_assets_sync(brand_id, limit)
                    st.success(
                        f"Downloaded {result['videos_downloaded']} videos, "
                        f"{result['images_downloaded']} images from {result['ads_processed']} ads"
                    )
                except Exception as e:
                    st.error(f"Download failed: {e}")

            st.session_state.analysis_running = False
            st.rerun()


def render_analysis_section(brand_id: str):
    """Render analysis controls."""
    st.subheader("2. Analyze Assets")
    st.markdown("Run AI analysis on videos, images, and ad copy to extract persona signals.")

    col1, col2, col3 = st.columns(3)

    with col1:
        st.markdown("**Video Analysis**")
        st.caption("Transcripts, hooks, persona signals")
        video_limit = st.number_input("Videos to analyze", 1, 20, 10, key="video_limit")

        if st.button("Analyze Videos", disabled=st.session_state.analysis_running, key="btn_video"):
            st.session_state.analysis_running = True

            with st.spinner(f"Analyzing up to {video_limit} videos (5-15 sec each)..."):
                try:
                    results = analyze_videos_sync(brand_id, video_limit)
                    success_count = len([r for r in results if 'analysis' in r])
                    st.success(f"Analyzed {success_count} videos")
                except Exception as e:
                    st.error(f"Video analysis failed: {e}")

            st.session_state.analysis_running = False
            st.rerun()

    with col2:
        st.markdown("**Image Analysis**")
        st.caption("Visual style, text overlays, hooks")
        image_limit = st.number_input("Images to analyze", 1, 50, 20, key="image_limit")

        if st.button("Analyze Images", disabled=st.session_state.analysis_running, key="btn_image"):
            st.session_state.analysis_running = True

            with st.spinner(f"Analyzing up to {image_limit} images..."):
                try:
                    results = analyze_images_sync(brand_id, image_limit)
                    success_count = len([r for r in results if 'analysis' in r])
                    st.success(f"Analyzed {success_count} images")
                except Exception as e:
                    st.error(f"Image analysis failed: {e}")

            st.session_state.analysis_running = False
            st.rerun()

    with col3:
        st.markdown("**Copy Analysis**")
        st.caption("Headlines, hooks, messaging patterns")
        copy_limit = st.number_input("Ads to analyze", 1, 100, 50, key="copy_limit")

        if st.button("Analyze Copy", disabled=st.session_state.analysis_running, key="btn_copy"):
            st.session_state.analysis_running = True

            with st.spinner(f"Analyzing ad copy from up to {copy_limit} ads..."):
                try:
                    results = analyze_copy_sync(brand_id, copy_limit)
                    success_count = len([r for r in results if 'analysis' in r])
                    st.success(f"Analyzed {success_count} ad copy texts")
                except Exception as e:
                    st.error(f"Copy analysis failed: {e}")

            st.session_state.analysis_running = False
            st.rerun()


def render_synthesis_section(brand_id: str):
    """Render persona synthesis section."""
    st.subheader("3. Synthesize Personas")
    st.markdown("Aggregate all analyses to detect customer segments and generate 4D personas.")

    analysis_stats = get_analysis_stats_for_brand(brand_id)

    if analysis_stats["total"] < 3:
        st.warning("Run at least 3 analyses before synthesizing personas.")
        return

    st.info(f"Ready to synthesize from {analysis_stats['total']} analyses "
            f"({analysis_stats['video_vision']} videos, {analysis_stats['image_vision']} images, "
            f"{analysis_stats['copy_analysis']} copy)")

    if st.button("Synthesize Personas", type="primary", disabled=st.session_state.analysis_running):
        st.session_state.analysis_running = True

        with st.spinner("Analyzing patterns and generating personas... (30-60 seconds)"):
            try:
                personas = synthesize_personas_sync(brand_id)
                st.session_state.suggested_personas = personas
                st.session_state.review_mode = True
                st.success(f"Generated {len(personas)} suggested persona(s)")
            except Exception as e:
                st.error(f"Synthesis failed: {e}")

        st.session_state.analysis_running = False
        st.rerun()


def render_persona_review():
    """Render persona review and approval interface."""
    st.subheader("Review Suggested Personas")

    if not st.session_state.suggested_personas:
        st.info("No personas to review. Run synthesis first.")
        if st.button("Back to Research"):
            st.session_state.review_mode = False
            st.rerun()
        return

    if st.button("< Back to Research"):
        st.session_state.review_mode = False
        st.rerun()

    for i, persona in enumerate(st.session_state.suggested_personas):
        with st.expander(f"Persona {i+1}: {persona.get('name', 'Unnamed')}", expanded=True):
            col1, col2 = st.columns([3, 1])

            with col1:
                st.markdown(f"**{persona.get('name', 'Unnamed')}**")
                st.markdown(f"*{persona.get('snapshot', '')}*")

                # Show confidence
                confidence = persona.get('confidence_score', 0)
                if confidence:
                    st.progress(confidence, f"Confidence: {confidence:.0%}")

                # Demographics
                demo = persona.get('demographics', {})
                if demo:
                    st.markdown(f"**Demographics:** {demo.get('age_range', 'N/A')}, "
                               f"{demo.get('gender', 'any')}, {demo.get('location', 'N/A')}")

                # Key insights
                st.markdown("**Key Pain Points:**")
                pain_points = persona.get('pain_points', {})
                for pp in pain_points.get('emotional', [])[:3]:
                    st.markdown(f"- {pp}")

                st.markdown("**Desires:**")
                desires = persona.get('desires', {})
                for category, items in list(desires.items())[:3]:
                    if items:
                        item = items[0] if isinstance(items[0], str) else items[0].get('text', '')
                        st.markdown(f"- [{category}] {item}")

                st.markdown("**Transformation:**")
                transformation = persona.get('transformation_map', {})
                before = transformation.get('before', [])[:2]
                after = transformation.get('after', [])[:2]
                for b in before:
                    st.markdown(f"- Before: {b}")
                for a in after:
                    st.markdown(f"- After: {a}")

            with col2:
                st.markdown("**Actions**")

                # Product linking
                brand_id = st.session_state.research_brand_id
                products = get_products_for_brand(brand_id) if brand_id else []

                if products:
                    product_options = {"None": None}
                    product_options.update({p["name"]: p["id"] for p in products})

                    linked_product = st.selectbox(
                        "Link to Product",
                        options=list(product_options.keys()),
                        key=f"product_{i}"
                    )

                    is_primary = st.checkbox("Set as Primary", key=f"primary_{i}")

                if st.button("Approve & Save", key=f"approve_{i}", type="primary"):
                    try:
                        persona_service = get_persona_service()
                        from viraltracker.services.models import Persona4D, PersonaType, SourceType

                        # Build Persona4D from suggested data
                        persona_obj = persona_service._build_persona_from_ai_response(
                            persona,
                            brand_id=UUID(brand_id) if brand_id else None,
                            product_id=UUID(product_options.get(linked_product)) if linked_product != "None" else None,
                            raw_response=json.dumps(persona)
                        )
                        persona_obj.source_type = SourceType.AI_GENERATED

                        # Save persona
                        persona_id = persona_service.create_persona(persona_obj)

                        # Link to product if selected
                        if linked_product and linked_product != "None":
                            persona_service.link_persona_to_product(
                                persona_id,
                                UUID(product_options[linked_product]),
                                is_primary=is_primary
                            )

                        st.success(f"Saved persona: {persona.get('name')}")

                        # Remove from suggestions
                        st.session_state.suggested_personas.pop(i)
                        st.rerun()

                    except Exception as e:
                        st.error(f"Failed to save: {e}")

                if st.button("Discard", key=f"discard_{i}"):
                    st.session_state.suggested_personas.pop(i)
                    st.rerun()


def render_existing_analyses(brand_id: str):
    """Render summary of existing analyses."""
    st.subheader("Analysis Results")

    service = get_brand_research_service()

    # Get recent analyses
    analyses = service.get_analyses_for_brand(UUID(brand_id))

    if not analyses:
        st.info("No analyses yet. Download assets and run analysis.")
        return

    # Group by type
    by_type = {"video_vision": [], "image_vision": [], "copy_analysis": []}
    for a in analyses[:50]:  # Limit display
        atype = a.get("analysis_type", "")
        if atype in by_type:
            by_type[atype].append(a)

    tabs = st.tabs(["Videos", "Images", "Copy"])

    with tabs[0]:
        if by_type["video_vision"]:
            for a in by_type["video_vision"][:10]:
                raw = a.get("raw_response", {})
                hook = raw.get("hook", {})
                with st.expander(f"Video: {hook.get('transcript', 'No transcript')[:50]}..."):
                    st.json(raw)
        else:
            st.info("No video analyses yet")

    with tabs[1]:
        if by_type["image_vision"]:
            for a in by_type["image_vision"][:10]:
                raw = a.get("raw_response", {})
                hooks = raw.get("hooks", [])
                hook_text = hooks[0].get("text", "") if hooks else "No hook"
                with st.expander(f"Image: {hook_text[:50]}..."):
                    st.json(raw)
        else:
            st.info("No image analyses yet")

    with tabs[2]:
        if by_type["copy_analysis"]:
            for a in by_type["copy_analysis"][:10]:
                raw = a.get("raw_response", {})
                hook = raw.get("hook", {})
                with st.expander(f"Copy: {hook.get('text', 'No hook')[:50]}..."):
                    st.json(raw)
        else:
            st.info("No copy analyses yet")


# Main page
st.title("Brand Research")
st.markdown("Analyze ad content to build data-driven 4D customer personas.")

# Check if in review mode
if st.session_state.review_mode:
    render_persona_review()
else:
    # Brand selector
    selected_brand_id = render_brand_selector()

    if selected_brand_id:
        st.session_state.research_brand_id = selected_brand_id

        st.divider()

        # Stats
        render_stats_section(selected_brand_id)

        st.divider()

        # Download section
        render_download_section(selected_brand_id)

        st.divider()

        # Analysis section
        render_analysis_section(selected_brand_id)

        st.divider()

        # Synthesis section
        render_synthesis_section(selected_brand_id)

        st.divider()

        # Existing analyses
        with st.expander("View Existing Analyses"):
            render_existing_analyses(selected_brand_id)
