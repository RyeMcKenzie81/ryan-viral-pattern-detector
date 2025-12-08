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
if 'research_product_id' not in st.session_state:
    st.session_state.research_product_id = None
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


def get_ad_ids_for_product(brand_id: str, product_id: str) -> List[str]:
    """Get ad IDs that link to a specific product's URLs.

    Matches ads whose link_url contains any of the product's URL patterns.
    """
    try:
        db = get_supabase_client()

        # Get URL patterns for this product
        patterns_result = db.table("product_urls").select(
            "url_pattern"
        ).eq("product_id", product_id).execute()

        if not patterns_result.data:
            return []

        patterns = [p['url_pattern'] for p in patterns_result.data]

        # Get all ads for this brand
        ads_result = db.table("brand_facebook_ads").select(
            "ad_id"
        ).eq("brand_id", brand_id).execute()

        if not ads_result.data:
            return []

        ad_ids = [r['ad_id'] for r in ads_result.data]

        # Get ads with their link_urls
        facebook_ads = db.table("facebook_ads").select(
            "id, snapshot"
        ).in_("id", ad_ids).execute()

        # Filter to ads whose link_url matches a product pattern
        matching_ad_ids = []
        for ad in facebook_ads.data or []:
            snapshot = ad.get('snapshot', {})
            if isinstance(snapshot, str):
                import json
                try:
                    snapshot = json.loads(snapshot)
                except:
                    continue

            link_url = snapshot.get('link_url', '') if isinstance(snapshot, dict) else ''
            if link_url:
                for pattern in patterns:
                    if pattern in link_url:
                        matching_ad_ids.append(ad['id'])
                        break

        return matching_ad_ids
    except Exception as e:
        import streamlit as st
        st.error(f"Failed to get ads for product: {e}")
        return []


def get_ad_count_for_brand(brand_id: str, product_id: Optional[str] = None) -> int:
    """Get count of ads linked to a brand, optionally filtered by product."""
    try:
        db = get_supabase_client()

        if product_id:
            ad_ids = get_ad_ids_for_product(brand_id, product_id)
            return len(ad_ids)

        result = db.table("brand_facebook_ads").select(
            "ad_id", count="exact"
        ).eq("brand_id", brand_id).execute()
        return result.count or 0
    except Exception:
        return 0


def get_asset_stats_for_brand(brand_id: str, product_id: Optional[str] = None) -> Dict[str, int]:
    """Get counts of video/image assets for a brand, optionally filtered by product."""
    try:
        db = get_supabase_client()

        # Get ad IDs - filtered by product if specified
        if product_id:
            ad_ids = get_ad_ids_for_product(brand_id, product_id)
        else:
            link_result = db.table("brand_facebook_ads").select("ad_id").eq(
                "brand_id", brand_id
            ).execute()
            ad_ids = [r['ad_id'] for r in link_result.data] if link_result.data else []

        if not ad_ids:
            return {"total": 0, "videos": 0, "images": 0, "ads_with_assets": 0, "ads_without_assets": 0}

        total_ads = len(ad_ids)

        # Get asset counts
        assets_result = db.table("scraped_ad_assets").select(
            "id, mime_type, facebook_ad_id"
        ).in_("facebook_ad_id", ad_ids).execute()

        videos = sum(1 for a in assets_result.data if a.get('mime_type', '').startswith('video/'))
        images = sum(1 for a in assets_result.data if a.get('mime_type', '').startswith('image/'))

        # Count ads that have assets downloaded
        ads_with_assets = len(set(a['facebook_ad_id'] for a in assets_result.data))
        ads_without_assets = total_ads - ads_with_assets

        return {
            "total": len(assets_result.data),
            "videos": videos,
            "images": images,
            "ads_with_assets": ads_with_assets,
            "ads_without_assets": ads_without_assets
        }
    except Exception as e:
        st.error(f"Failed to get asset stats: {e}")
        return {"total": 0, "videos": 0, "images": 0, "ads_with_assets": 0, "ads_without_assets": 0}


def get_analysis_stats_for_brand(brand_id: str, product_id: Optional[str] = None) -> Dict[str, int]:
    """Get counts of completed analyses for a brand, optionally filtered by product."""
    try:
        db = get_supabase_client()

        # If filtering by product, get the relevant ad IDs first
        if product_id:
            ad_ids = get_ad_ids_for_product(brand_id, product_id)
            if not ad_ids:
                return {"video_vision": 0, "image_vision": 0, "copy_analysis": 0, "total": 0}

            result = db.table("brand_ad_analysis").select(
                "analysis_type"
            ).eq("brand_id", brand_id).in_("facebook_ad_id", ad_ids).execute()
        else:
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


def download_assets_sync(brand_id: str, limit: int = 50, product_id: Optional[str] = None) -> Dict[str, int]:
    """Download assets for brand (sync wrapper)."""
    from viraltracker.services.brand_research_service import BrandResearchService

    # If filtering by product, get the specific ad IDs
    ad_ids = None
    if product_id:
        ad_ids = get_ad_ids_for_product(brand_id, product_id)
        if not ad_ids:
            return {"ads_processed": 0, "videos_downloaded": 0, "images_downloaded": 0, "errors": 0}

    async def _download():
        service = BrandResearchService()
        return await service.download_assets_for_brand(UUID(brand_id), limit=limit, ad_ids=ad_ids)

    return run_async(_download())


def analyze_videos_sync(brand_id: str, limit: int = 10, product_id: Optional[str] = None) -> List[Dict]:
    """Analyze videos for brand (sync wrapper).

    Uses analyze_videos_for_brand() which combines fetching and analyzing
    in one async operation to avoid event loop issues on repeated runs.
    """
    from viraltracker.services.brand_research_service import BrandResearchService

    # If filtering by product, get the specific ad IDs
    ad_ids = None
    if product_id:
        ad_ids = get_ad_ids_for_product(brand_id, product_id)
        if not ad_ids:
            return []

    async def _analyze():
        service = BrandResearchService()
        return await service.analyze_videos_for_brand(UUID(brand_id), limit=limit, ad_ids=ad_ids)

    return run_async(_analyze())


def analyze_images_sync(brand_id: str, limit: int = 20, product_id: Optional[str] = None) -> List[Dict]:
    """Analyze images for brand (sync wrapper).

    Uses analyze_images_for_brand() which combines fetching and analyzing
    in one async operation to avoid event loop issues on repeated runs.
    """
    from viraltracker.services.brand_research_service import BrandResearchService

    # If filtering by product, get the specific ad IDs
    ad_ids = None
    if product_id:
        ad_ids = get_ad_ids_for_product(brand_id, product_id)
        if not ad_ids:
            return []

    async def _analyze():
        service = BrandResearchService()
        return await service.analyze_images_for_brand(UUID(brand_id), limit=limit, ad_ids=ad_ids)

    return run_async(_analyze())


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


def analyze_copy_sync(brand_id: str, limit: int = 50, product_id: Optional[str] = None) -> List[Dict]:
    """Analyze ad copy for brand (sync wrapper)."""
    from viraltracker.services.brand_research_service import BrandResearchService

    # If filtering by product, get the specific ad IDs
    ad_ids = None
    if product_id:
        ad_ids = get_ad_ids_for_product(brand_id, product_id)
        if not ad_ids:
            return []

    async def _analyze():
        service = BrandResearchService()
        return await service.analyze_copy_batch(UUID(brand_id), limit=limit, ad_ids=ad_ids)

    return run_async(_analyze())


def scrape_landing_pages_sync(brand_id: str, limit: int = 20, product_id: Optional[str] = None) -> Dict:
    """Scrape landing pages for brand (sync wrapper).

    Uses scrape_landing_pages_for_brand() which combines fetching URLs
    and scraping in one async operation.
    """
    from viraltracker.services.brand_research_service import BrandResearchService

    async def _scrape():
        service = BrandResearchService()
        return await service.scrape_landing_pages_for_brand(
            UUID(brand_id),
            limit=limit,
            product_id=UUID(product_id) if product_id else None
        )

    return run_async(_scrape())


def analyze_landing_pages_sync(brand_id: str, limit: int = 20, product_id: Optional[str] = None) -> List[Dict]:
    """Analyze landing pages for brand (sync wrapper).

    Uses analyze_landing_pages_for_brand() which combines fetching pages
    and analyzing in one async operation.
    """
    from viraltracker.services.brand_research_service import BrandResearchService

    async def _analyze():
        service = BrandResearchService()
        return await service.analyze_landing_pages_for_brand(
            UUID(brand_id),
            limit=limit,
            product_id=UUID(product_id) if product_id else None
        )

    return run_async(_analyze())


def get_landing_page_stats(brand_id: str, product_id: Optional[str] = None) -> Dict[str, int]:
    """Get landing page statistics for a brand, optionally filtered by product."""
    from viraltracker.services.brand_research_service import BrandResearchService
    service = BrandResearchService()
    return service.get_landing_page_stats(UUID(brand_id), UUID(product_id) if product_id else None)


def synthesize_personas_sync(brand_id: str) -> List[Dict]:
    """Synthesize personas from analyses (sync wrapper)."""
    from viraltracker.services.brand_research_service import BrandResearchService

    async def _synthesize():
        service = BrandResearchService()
        return await service.synthesize_to_personas(UUID(brand_id))

    return run_async(_synthesize())


def render_brand_selector():
    """Render brand selector and return (brand_id, product_id)."""
    brands = get_brands()

    if not brands:
        st.warning("No brands found. Please create a brand first in Brand Manager.")
        return None, None

    brand_options = {b["name"]: b["id"] for b in brands}

    col1, col2 = st.columns(2)

    with col1:
        selected_brand_name = st.selectbox(
            "Select Brand",
            options=list(brand_options.keys()),
            index=0
        )
        selected_brand_id = brand_options[selected_brand_name]

    with col2:
        products = get_products_for_brand(selected_brand_id)
        if products:
            product_options = {"All Products (Brand-level)": None}
            product_options.update({p["name"]: p["id"] for p in products})

            selected_product_name = st.selectbox(
                "Filter by Product (optional)",
                options=list(product_options.keys()),
                index=0,
                help="Select a product to analyze only ads linking to that product's URLs"
            )
            selected_product_id = product_options[selected_product_name]
        else:
            st.info("No products defined yet")
            selected_product_id = None

    return selected_brand_id, selected_product_id


def render_stats_section(brand_id: str, product_id: Optional[str] = None):
    """Render statistics about the brand's data, optionally filtered by product."""
    col1, col2, col3, col4, col5, col6 = st.columns(6)

    ad_count = get_ad_count_for_brand(brand_id, product_id)
    asset_stats = get_asset_stats_for_brand(brand_id, product_id)
    analysis_stats = get_analysis_stats_for_brand(brand_id, product_id)
    lp_stats = get_landing_page_stats(brand_id, product_id)

    with col1:
        st.metric("Ads Linked", ad_count)
        if asset_stats.get("ads_without_assets", 0) > 0:
            st.caption(f"{asset_stats['ads_without_assets']} need download")

    with col2:
        st.metric("Videos", asset_stats["videos"])
        if analysis_stats["video_vision"] > 0:
            unanalyzed = asset_stats["videos"] - analysis_stats["video_vision"]
            st.caption(f"{analysis_stats['video_vision']} analyzed" + (f", {unanalyzed} pending" if unanalyzed > 0 else ""))

    with col3:
        st.metric("Images", asset_stats["images"])
        if analysis_stats["image_vision"] > 0:
            unanalyzed = asset_stats["images"] - analysis_stats["image_vision"]
            st.caption(f"{analysis_stats['image_vision']} analyzed" + (f", {unanalyzed} pending" if unanalyzed > 0 else ""))

    with col4:
        st.metric("Copy Analyzed", analysis_stats["copy_analysis"])
        if ad_count > 0:
            pending = ad_count - analysis_stats["copy_analysis"]
            if pending > 0:
                st.caption(f"{pending} pending")

    with col5:
        available = lp_stats.get("available", 0)
        successfully_scraped = lp_stats.get("successfully_scraped", 0)
        st.metric("Landing Pages", f"{successfully_scraped}/{available}")
        to_scrape = lp_stats.get("to_scrape", 0)
        analyzed = lp_stats.get("analyzed", 0)
        to_analyze = lp_stats.get("to_analyze", 0)
        if to_scrape > 0 or to_analyze > 0:
            parts = []
            if to_scrape > 0:
                parts.append(f"{to_scrape} to scrape")
            if to_analyze > 0:
                parts.append(f"{to_analyze} to analyze")
            st.caption(", ".join(parts))
        elif successfully_scraped > 0:
            st.caption(f"{analyzed} analyzed")

    with col6:
        st.metric("Total Analyses", analysis_stats["total"])


def render_download_section(brand_id: str, product_id: Optional[str] = None):
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
                    result = download_assets_sync(brand_id, limit, product_id=product_id)
                    st.success(
                        f"Downloaded {result['videos_downloaded']} videos, "
                        f"{result['images_downloaded']} images from {result['ads_processed']} ads"
                    )
                except Exception as e:
                    st.error(f"Download failed: {e}")

            st.session_state.analysis_running = False
            st.rerun()


def render_analysis_section(brand_id: str, product_id: Optional[str] = None):
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
                    results = analyze_videos_sync(brand_id, video_limit, product_id)
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
                    results = analyze_images_sync(brand_id, image_limit, product_id)
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
                    results = analyze_copy_sync(brand_id, copy_limit, product_id)
                    success_count = len([r for r in results if 'analysis' in r])
                    st.success(f"Analyzed {success_count} ad copy texts")
                except Exception as e:
                    st.error(f"Copy analysis failed: {e}")

            st.session_state.analysis_running = False
            st.rerun()


def render_landing_page_section(brand_id: str, product_id: Optional[str] = None):
    """Render landing page scraping and analysis section."""
    st.subheader("3. Landing Pages")
    st.markdown("Scrape and analyze landing pages from URL patterns for deeper persona insights.")

    lp_stats = get_landing_page_stats(brand_id, product_id)
    available = lp_stats.get("available", 0)
    to_scrape = lp_stats.get("to_scrape", 0)
    successfully_scraped = lp_stats.get("successfully_scraped", 0)
    analyzed = lp_stats.get("analyzed", 0)
    to_analyze = lp_stats.get("to_analyze", 0)

    # Show overall status
    if available == 0:
        st.warning("No URL patterns found. Add URLs on the URL Mapping page first.")
        return

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("**Scrape Landing Pages**")
        st.caption("Extract content from product URLs using FireCrawl")

        if to_scrape > 0:
            st.info(f"{to_scrape} of {available} URLs ready to scrape")
        elif successfully_scraped > 0:
            st.success(f"All {available} URLs scraped")
        else:
            st.info(f"{available} URLs available")

        scrape_limit = st.number_input("Pages to scrape", 1, 50, min(to_scrape, 20) if to_scrape > 0 else 20, key="lp_scrape_limit")

        btn_disabled = st.session_state.analysis_running or to_scrape == 0
        if st.button("Scrape Landing Pages", disabled=btn_disabled, key="btn_scrape_lp"):
            st.session_state.analysis_running = True

            with st.spinner(f"Scraping up to {scrape_limit} landing pages..."):
                try:
                    result = scrape_landing_pages_sync(brand_id, scrape_limit, product_id=product_id)
                    already = result.get('already_scraped', 0)
                    if already > 0:
                        st.warning(f"All {result['urls_found']} URLs already scraped ({already} in database)")
                    elif result['pages_scraped'] > 0:
                        st.success(
                            f"Scraped {result['pages_scraped']} of {result['urls_found']} URLs "
                            f"({result['pages_failed']} failed)"
                        )
                    else:
                        st.warning(
                            f"Found {result['urls_found']} URLs but scraped 0 "
                            f"({result['pages_failed']} failed) - check logs"
                        )
                except Exception as e:
                    st.error(f"Landing page scrape failed: {e}")

            st.session_state.analysis_running = False
            st.rerun()

    with col2:
        st.markdown("**Analyze Landing Pages**")
        st.caption("Extract persona signals, copy patterns, objection handling")

        if to_analyze > 0:
            st.info(f"{to_analyze} pages ready for analysis ({analyzed} already analyzed)")
        elif successfully_scraped > 0 and analyzed > 0:
            st.success(f"All {analyzed} scraped pages analyzed")
        elif successfully_scraped == 0:
            st.caption("Scrape pages first")
        else:
            st.info(f"{successfully_scraped} pages scraped, {analyzed} analyzed")

        analyze_limit = st.number_input("Pages to analyze", 1, 50, min(to_analyze, 20) if to_analyze > 0 else 20, key="lp_analyze_limit")

        btn_disabled = st.session_state.analysis_running or to_analyze == 0
        if st.button("Analyze Landing Pages", disabled=btn_disabled, key="btn_analyze_lp"):
            st.session_state.analysis_running = True

            with st.spinner(f"Analyzing up to {analyze_limit} landing pages..."):
                try:
                    results = analyze_landing_pages_sync(brand_id, analyze_limit, product_id=product_id)
                    success_count = len([r for r in results if 'analysis' in r])
                    st.success(f"Analyzed {success_count} landing pages")
                except Exception as e:
                    st.error(f"Landing page analysis failed: {e}")

            st.session_state.analysis_running = False
            st.rerun()

    # Show list of scraped pages
    if successfully_scraped > 0:
        with st.expander(f"View {successfully_scraped} scraped landing pages"):
            pages = get_landing_pages_for_brand(brand_id)
            for page in pages:
                status_icon = "✅" if page.get("scrape_status") == "analyzed" else "📄"
                url = page.get("url", "")
                title = page.get("page_title") or url.split("/")[-1] or "Untitled"
                st.markdown(f"{status_icon} **{title}**")
                st.caption(url)


def get_landing_pages_for_brand(brand_id: str) -> list:
    """Get landing pages for a brand."""
    from viraltracker.services.brand_research_service import BrandResearchService
    service = BrandResearchService()
    return service.get_landing_pages_for_brand(UUID(brand_id))


def render_synthesis_section(brand_id: str, product_id: Optional[str] = None):
    """Render persona synthesis section."""
    st.subheader("4. Synthesize Personas")
    st.markdown("Aggregate all analyses to detect customer segments and generate 4D personas.")

    analysis_stats = get_analysis_stats_for_brand(brand_id, product_id)

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

                # Use tabs for organized display of all 4D fields
                tabs = st.tabs(["Pain & Desires", "Identity", "Social", "Worldview", "Barriers", "Activation"])

                with tabs[0]:  # Pain & Desires
                    col_pain, col_desire = st.columns(2)

                    with col_pain:
                        st.markdown("**Pain Points:**")
                        pain_points = persona.get('pain_points', {})
                        for category in ['emotional', 'social', 'functional']:
                            items = pain_points.get(category, [])
                            for pp in items[:3]:
                                st.markdown(f"- *{category}:* {pp}")

                    with col_desire:
                        st.markdown("**Desires:**")
                        desires = persona.get('desires', {})
                        for category, items in desires.items():
                            if items:
                                item = items[0] if isinstance(items[0], str) else items[0].get('text', '')
                                st.markdown(f"- *{category}:* {item}")

                    st.markdown("**Transformation:**")
                    transformation = persona.get('transformation_map', {})
                    col_before, col_after = st.columns(2)
                    with col_before:
                        st.markdown("*Before:*")
                        for b in transformation.get('before', []):
                            st.markdown(f"- {b}")
                    with col_after:
                        st.markdown("*After:*")
                        for a in transformation.get('after', []):
                            st.markdown(f"- {a}")

                    st.markdown("**Outcomes (JTBD):**")
                    outcomes = persona.get('outcomes_jtbd', {})
                    for category in ['emotional', 'social', 'functional']:
                        items = outcomes.get(category, [])
                        for item in items[:2]:
                            st.markdown(f"- *{category}:* {item}")

                with tabs[1]:  # Identity
                    st.markdown("**Self-Narratives:**")
                    narratives = persona.get('self_narratives', [])
                    for n in narratives:
                        st.markdown(f"- \"{n}\"")

                    col_curr, col_des = st.columns(2)
                    with col_curr:
                        st.markdown("**Current Self-Image:**")
                        st.write(persona.get('current_self_image', 'N/A'))
                    with col_des:
                        st.markdown("**Desired Self-Image:**")
                        st.write(persona.get('desired_self_image', 'N/A'))

                    st.markdown("**Identity Artifacts:**")
                    artifacts = persona.get('identity_artifacts', [])
                    if artifacts:
                        st.write(", ".join(artifacts))
                    else:
                        st.write("N/A")

                with tabs[2]:  # Social
                    social = persona.get('social_relations', {})

                    st.markdown("**Want to Impress:**")
                    for item in social.get('want_to_impress', []):
                        st.markdown(f"- {item}")

                    st.markdown("**Fear Judgment From:**")
                    for item in social.get('fear_judged_by', []):
                        st.markdown(f"- {item}")

                    st.markdown("**Influences Their Decisions:**")
                    for item in social.get('influence_decisions', []):
                        st.markdown(f"- {item}")

                with tabs[3]:  # Worldview
                    st.markdown("**Worldview:**")
                    st.write(persona.get('worldview', 'N/A'))

                    st.markdown("**Core Values:**")
                    values = persona.get('core_values', [])
                    if values:
                        st.write(", ".join(values))

                    col_good, col_evil = st.columns(2)
                    with col_good:
                        st.markdown("**Forces of Good:**")
                        for item in persona.get('forces_of_good', []):
                            st.markdown(f"- {item}")
                    with col_evil:
                        st.markdown("**Forces of Evil:**")
                        for item in persona.get('forces_of_evil', []):
                            st.markdown(f"- {item}")

                    st.markdown("**Allergies (Turn-offs):**")
                    allergies = persona.get('allergies', {})
                    if isinstance(allergies, dict):
                        for trigger, reaction in allergies.items():
                            st.markdown(f"- *{trigger}:* {reaction}")
                    elif allergies:
                        st.write(str(allergies))

                with tabs[4]:  # Barriers
                    st.markdown("**Failed Solutions (What They've Tried):**")
                    for item in persona.get('failed_solutions', []):
                        st.markdown(f"- {item}")

                    st.markdown("**Buying Objections:**")
                    objections = persona.get('buying_objections', {})
                    for category in ['emotional', 'social', 'functional']:
                        items = objections.get(category, [])
                        for obj in items:
                            st.markdown(f"- *{category}:* {obj}")

                    st.markdown("**Familiar Promises (Claims They've Heard):**")
                    for item in persona.get('familiar_promises', []):
                        st.markdown(f"- {item}")

                    st.markdown("**Emotional Risks:**")
                    for item in persona.get('emotional_risks', []):
                        st.markdown(f"- {item}")

                    st.markdown("**Barriers to Behavior:**")
                    for item in persona.get('barriers_to_behavior', []):
                        st.markdown(f"- {item}")

                with tabs[5]:  # Activation
                    st.markdown("**Activation Events (What Triggers Purchase):**")
                    for item in persona.get('activation_events', []):
                        st.markdown(f"- {item}")

                    st.markdown("**Decision Process:**")
                    st.write(persona.get('decision_process', 'N/A'))

                    st.markdown("**Current Workarounds:**")
                    for item in persona.get('current_workarounds', []):
                        st.markdown(f"- {item}")

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
            for i, a in enumerate(by_type["video_vision"][:10]):
                raw = a.get("raw_response") or {}
                hook = raw.get("hook") or {}
                transcript = (hook.get("transcript") or "No transcript")[:100]
                st.markdown(f"**Video {i+1}:** {transcript}...")
                with st.container():
                    col1, col2 = st.columns(2)
                    with col1:
                        st.caption("Hook Type")
                        st.write(hook.get("hook_type") or "N/A")
                    with col2:
                        st.caption("Pain Points")
                        pain = raw.get("pain_points") or {}
                        emotional = pain.get("emotional") or []
                        st.write(emotional[:2] if emotional else "N/A")
                st.divider()
        else:
            st.info("No video analyses yet")

    with tabs[1]:
        if by_type["image_vision"]:
            for i, a in enumerate(by_type["image_vision"][:10]):
                raw = a.get("raw_response") or {}
                hooks = raw.get("hooks") or []
                if hooks and isinstance(hooks[0], dict):
                    hook_text = (hooks[0].get("text") or "No hook")[:100]
                else:
                    hook_text = "No hook"
                st.markdown(f"**Image {i+1}:** {hook_text}...")
                st.divider()
        else:
            st.info("No image analyses yet")

    with tabs[2]:
        if by_type["copy_analysis"]:
            for i, a in enumerate(by_type["copy_analysis"][:10]):
                raw = a.get("raw_response") or {}
                hook = raw.get("hook") or {}
                hook_text = (hook.get("text") or "No hook")[:100]
                st.markdown(f"**Copy {i+1}:** {hook_text}...")
                st.divider()
        else:
            st.info("No copy analyses yet")


# Main page
st.title("Brand Research")
st.markdown("Analyze ad content to build data-driven 4D customer personas.")

# Check if in review mode
if st.session_state.review_mode:
    render_persona_review()
else:
    # Brand and product selector
    selected_brand_id, selected_product_id = render_brand_selector()

    if selected_brand_id:
        st.session_state.research_brand_id = selected_brand_id
        st.session_state.research_product_id = selected_product_id

        # Show product filter status
        if selected_product_id:
            st.info(f"Filtering by product - analyses will be linked to this product")

        st.divider()

        # Stats
        render_stats_section(selected_brand_id, selected_product_id)

        st.divider()

        # Download section
        render_download_section(selected_brand_id, selected_product_id)

        st.divider()

        # Analysis section
        render_analysis_section(selected_brand_id, selected_product_id)

        st.divider()

        # Landing page section
        render_landing_page_section(selected_brand_id, selected_product_id)

        st.divider()

        # Synthesis section
        render_synthesis_section(selected_brand_id, selected_product_id)

        st.divider()

        # Existing analyses
        with st.expander("View Existing Analyses"):
            render_existing_analyses(selected_brand_id)
