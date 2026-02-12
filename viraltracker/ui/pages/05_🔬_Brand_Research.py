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
from dataclasses import dataclass, field

# Fix for nested event loops in Streamlit

# Page config
st.set_page_config(
    page_title="Brand Research",
    page_icon="🔬",
    layout="wide"
)

# Authentication
from viraltracker.ui.auth import require_auth
require_auth()
from viraltracker.ui.utils import require_feature
require_feature("brand_research", "Brand Research")

# Initialize session state
if 'analysis_running' not in st.session_state:
    st.session_state.analysis_running = False
if 'suggested_personas' not in st.session_state:
    st.session_state.suggested_personas = []
if 'review_mode' not in st.session_state:
    st.session_state.review_mode = False
if 'download_legacy_mode' not in st.session_state:
    st.session_state.download_legacy_mode = False

def get_supabase_client():
    """Get Supabase client."""
    from viraltracker.core.database import get_supabase_client
    return get_supabase_client()

def get_brand_research_service():
    """Get BrandResearchService instance."""
    from viraltracker.services.brand_research_service import BrandResearchService
    return BrandResearchService()

def get_persona_service():
    """Get PersonaService instance with tracking enabled."""
    from viraltracker.services.persona_service import PersonaService
    from viraltracker.ui.utils import setup_tracking_context
    service = PersonaService()
    setup_tracking_context(service)
    return service

def get_angle_candidate_service():
    """Get AngleCandidateService instance."""
    from viraltracker.services.angle_candidate_service import AngleCandidateService
    return AngleCandidateService()

def get_ad_scraping_service():
    """Get AdScrapingService instance."""
    from viraltracker.services.ad_scraping_service import AdScrapingService
    return AdScrapingService()

def check_asset_health(brand_id: str, asset_type: str = "image") -> Dict:
    """Check health of assets for a brand.

    Args:
        brand_id: Brand UUID
        asset_type: 'image' or 'video'

    Returns:
        Health check results with counts and IDs
    """
    service = get_brand_research_service()
    return service.check_asset_health(brand_id, asset_type)

def refresh_expired_assets_sync(brand_id: str) -> Dict:
    """Re-scrape expired/failed assets (sync wrapper).

    Args:
        brand_id: Brand UUID

    Returns:
        Refresh results
    """
    from uuid import UUID

    async def _refresh():
        service = get_ad_scraping_service()
        return await service.refresh_expired_assets(UUID(brand_id))

    return run_async(_refresh())

def extract_brand_research_candidates(
    brand_id: str,
    product_id: str,
    sources: List[str]
) -> Dict[str, Any]:
    """Extract angle candidates from brand research data.

    Args:
        brand_id: Brand UUID
        product_id: Product UUID to link candidates to
        sources: List of sources to extract from ['amazon', 'landing_pages']

    Returns:
        Dict with {total_created: int, total_updated: int, by_source: dict}
    """
    service = get_angle_candidate_service()
    stats = {"total_created": 0, "total_updated": 0, "by_source": {}}

    if 'amazon' in sources:
        result = service.extract_from_brand_amazon_reviews(
            product_id=UUID(product_id),
            brand_id=UUID(brand_id)
        )
        stats["total_created"] += result.get("created", 0)
        stats["total_updated"] += result.get("updated", 0)
        stats["by_source"]["amazon"] = result

    if 'landing_pages' in sources:
        result = service.extract_from_brand_landing_pages(
            brand_id=UUID(brand_id),
            product_id=UUID(product_id)
        )
        stats["total_created"] += result.get("created", 0)
        stats["total_updated"] += result.get("updated", 0)
        stats["by_source"]["landing_pages"] = result

    return stats

def get_brands():
    """Fetch brands filtered by current organization."""
    from viraltracker.ui.utils import get_brands as get_org_brands
    return get_org_brands()

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

@dataclass
class AdIdSet:
    """Typed container for ad IDs from different sources. Never mix."""
    facebook_ad_ids: List[str] = field(default_factory=list)
    meta_ad_ids: List[str] = field(default_factory=list)


def get_ad_ids_for_product(brand_id: str, product_id: str) -> AdIdSet:
    """Get ad IDs for a product from BOTH sources, kept separate.

    Facebook path: brand_facebook_ads -> facebook_ads snapshot link_url matching
    Meta path: meta_ad_destinations URL matching via product URL patterns
    """
    try:
        db = get_supabase_client()

        # Get URL patterns for this product
        patterns_result = db.table("product_urls").select(
            "url_pattern"
        ).eq("product_id", product_id).execute()

        patterns = [p['url_pattern'] for p in (patterns_result.data or [])]

        # --- Facebook path (existing) ---
        fb_ids = []
        ads_result = db.table("brand_facebook_ads").select(
            "ad_id"
        ).eq("brand_id", brand_id).execute()

        if ads_result.data and patterns:
            ad_ids = [r['ad_id'] for r in ads_result.data]

            facebook_ads = db.table("facebook_ads").select(
                "id, snapshot"
            ).in_("id", ad_ids).execute()

            for ad in facebook_ads.data or []:
                snapshot = ad.get('snapshot', {})
                if isinstance(snapshot, str):
                    try:
                        snapshot = json.loads(snapshot)
                    except Exception:
                        continue

                link_url = snapshot.get('link_url', '') if isinstance(snapshot, dict) else ''
                if link_url:
                    for pattern in patterns:
                        if pattern in link_url:
                            fb_ids.append(ad['id'])
                            break

        # --- Meta path ---
        meta_ids = []
        if patterns:
            dest_result = db.table("meta_ad_destinations").select(
                "meta_ad_id, canonical_url, destination_url"
            ).eq("brand_id", brand_id).execute()

            for dest in (dest_result.data or []):
                url = dest.get("canonical_url") or dest.get("destination_url")
                if not url:
                    continue
                for pattern in patterns:
                    if pattern in url:
                        meta_ids.append(dest["meta_ad_id"])
                        break
            meta_ids = list(set(meta_ids))

        return AdIdSet(facebook_ad_ids=fb_ids, meta_ad_ids=meta_ids)
    except Exception as e:
        import streamlit as st
        st.error(f"Failed to get ads for product: {e}")
        return AdIdSet()

def get_ad_count_for_brand(brand_id: str, product_id: Optional[str] = None) -> int:
    """Get count of ads linked to a brand from both sources, optionally filtered by product."""
    try:
        db = get_supabase_client()

        if product_id:
            ad_id_set = get_ad_ids_for_product(brand_id, product_id)
            return len(ad_id_set.facebook_ad_ids) + len(ad_id_set.meta_ad_ids)

        # Scraped ads count
        scraped_result = db.table("brand_facebook_ads").select(
            "ad_id", count="exact"
        ).eq("brand_id", brand_id).execute()
        scraped_count = scraped_result.count or 0

        # Meta ads count (DISTINCT meta_ad_id since meta_ads_performance has daily rows)
        meta_result = db.table("meta_ads_performance").select(
            "meta_ad_id"
        ).eq("brand_id", brand_id).execute()
        meta_count = len(set(r["meta_ad_id"] for r in (meta_result.data or [])))

        return scraped_count + meta_count
    except Exception:
        return 0

def get_asset_stats_for_brand(brand_id: str, product_id: Optional[str] = None) -> Dict[str, int]:
    """Get counts of video/image assets for a brand from both sources, optionally filtered by product."""
    try:
        db = get_supabase_client()

        # Get ad IDs - filtered by product if specified
        if product_id:
            ad_id_set = get_ad_ids_for_product(brand_id, product_id)
            fb_ad_ids = ad_id_set.facebook_ad_ids
            meta_ad_ids = ad_id_set.meta_ad_ids
        else:
            link_result = db.table("brand_facebook_ads").select("ad_id").eq(
                "brand_id", brand_id
            ).execute()
            fb_ad_ids = [r['ad_id'] for r in link_result.data] if link_result.data else []
            meta_ad_ids = None  # signal to query all Meta assets for brand

        total_ads = len(fb_ad_ids) + (len(meta_ad_ids) if meta_ad_ids is not None else 0)
        videos = 0
        images = 0
        ads_with_assets = 0

        # Scraped assets
        if fb_ad_ids:
            assets_result = db.table("scraped_ad_assets").select(
                "id, mime_type, facebook_ad_id"
            ).in_("facebook_ad_id", fb_ad_ids).execute()

            videos += sum(1 for a in assets_result.data if a.get('mime_type', '').startswith('video/'))
            images += sum(1 for a in assets_result.data if a.get('mime_type', '').startswith('image/'))
            ads_with_assets += len(set(a['facebook_ad_id'] for a in assets_result.data))

        # Meta assets
        meta_query = db.table("meta_ad_assets").select(
            "id, meta_ad_id, asset_type"
        ).eq("brand_id", brand_id).eq("status", "downloaded")
        if meta_ad_ids is not None:
            if meta_ad_ids:
                meta_query = meta_query.in_("meta_ad_id", meta_ad_ids)
            else:
                meta_query = None  # empty list = skip
        meta_assets = (meta_query.execute().data or []) if meta_query else []

        videos += sum(1 for a in meta_assets if a.get('asset_type') == 'video')
        images += sum(1 for a in meta_assets if a.get('asset_type') == 'image')
        meta_ads_with_assets = len(set(a['meta_ad_id'] for a in meta_assets))
        ads_with_assets += meta_ads_with_assets

        # Total ads including Meta distinct count
        if meta_ad_ids is None:
            meta_total_result = db.table("meta_ads_performance").select(
                "meta_ad_id"
            ).eq("brand_id", brand_id).execute()
            meta_total = len(set(r["meta_ad_id"] for r in (meta_total_result.data or [])))
            total_ads = len(fb_ad_ids) + meta_total

        ads_without_assets = max(0, total_ads - ads_with_assets)

        return {
            "total": videos + images,
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
            ad_id_set = get_ad_ids_for_product(brand_id, product_id)
            if not ad_id_set.facebook_ad_ids and not ad_id_set.meta_ad_ids:
                return {"video_vision": 0, "image_vision": 0, "copy_analysis": 0, "amazon_reviews": 0, "total": 0}

            # Query both ID types separately and merge
            all_rows = []
            if ad_id_set.facebook_ad_ids:
                fb_result = db.table("brand_ad_analysis").select(
                    "analysis_type"
                ).eq("brand_id", brand_id).in_("facebook_ad_id", ad_id_set.facebook_ad_ids).execute()
                all_rows.extend(fb_result.data or [])
            if ad_id_set.meta_ad_ids:
                meta_result = db.table("brand_ad_analysis").select(
                    "analysis_type"
                ).eq("brand_id", brand_id).in_("meta_ad_id", ad_id_set.meta_ad_ids).execute()
                all_rows.extend(meta_result.data or [])
            result = type('Result', (), {'data': all_rows})()
        else:
            result = db.table("brand_ad_analysis").select(
                "analysis_type"
            ).eq("brand_id", brand_id).execute()

        stats = {
            "video_vision": 0,
            "image_vision": 0,
            "copy_analysis": 0,
            "amazon_reviews": 0,
            "total": len(result.data)
        }

        for row in result.data:
            analysis_type = row.get("analysis_type", "")
            if analysis_type in stats:
                stats[analysis_type] += 1

        # Check for Amazon review analyses
        try:
            if product_id:
                amazon_result = db.table("amazon_review_analysis").select(
                    "total_reviews_analyzed"
                ).eq("product_id", product_id).execute()
            else:
                amazon_result = db.table("amazon_review_analysis").select(
                    "total_reviews_analyzed"
                ).eq("brand_id", brand_id).execute()

            if amazon_result.data:
                for row in amazon_result.data:
                    stats["amazon_reviews"] += row.get("total_reviews_analyzed", 0)
                stats["total"] += len(amazon_result.data)  # Count each product analysis
        except Exception:
            pass  # Table may not exist yet

        return stats
    except Exception as e:
        st.error(f"Failed to get analysis stats: {e}")
        return {"video_vision": 0, "image_vision": 0, "copy_analysis": 0, "amazon_reviews": 0, "total": 0}

def run_async(coro):
    """Run async function in Streamlit context."""
    return asyncio.run(coro)

def download_assets_sync(brand_id: str, limit: int = 50, product_id: Optional[str] = None) -> Dict[str, int]:
    """Download assets for brand (sync wrapper)."""
    from viraltracker.services.brand_research_service import BrandResearchService

    # If filtering by product, get the specific ad IDs (only FB path — Meta assets
    # are downloaded by meta_sync job via download_new_ad_assets)
    ad_ids = None
    if product_id:
        ad_id_set = get_ad_ids_for_product(brand_id, product_id)
        ad_ids = ad_id_set.facebook_ad_ids or None
        if not ad_ids:
            return {"ads_processed": 0, "videos_downloaded": 0, "images_downloaded": 0, "errors": 0}

    async def _download():
        service = BrandResearchService()
        return await service.download_assets_for_brand(UUID(brand_id), limit=limit, ad_ids=ad_ids)

    return run_async(_download())

def analyze_videos_sync(brand_id: str, limit: int = 10, product_id: Optional[str] = None) -> List[Dict]:
    """Analyze videos for brand (sync wrapper).

    Uses analyze_videos_for_brand() for scraped ads and
    analyze_videos_for_brand_meta() for Meta API ads.
    """
    from viraltracker.services.brand_research_service import BrandResearchService

    ad_id_set = None
    if product_id:
        ad_id_set = get_ad_ids_for_product(brand_id, product_id)
        if not ad_id_set.facebook_ad_ids and not ad_id_set.meta_ad_ids:
            return []

    async def _analyze():
        service = BrandResearchService()
        results = []
        # Scraped path
        fb_ids = ad_id_set.facebook_ad_ids if ad_id_set else None
        if fb_ids is None or fb_ids:
            r = await service.analyze_videos_for_brand(UUID(brand_id), limit=limit, ad_ids=fb_ids)
            results.extend(r)
        # Meta path
        meta_ids = ad_id_set.meta_ad_ids if ad_id_set else None
        if meta_ids is None or meta_ids:
            remaining = max(0, limit - len(results))
            if remaining > 0:
                r = await service.analyze_videos_for_brand_meta(UUID(brand_id), limit=remaining, meta_ad_ids=meta_ids)
                results.extend(r)
        return results

    return run_async(_analyze())

def analyze_images_sync(brand_id: str, limit: int = 20, product_id: Optional[str] = None) -> List[Dict]:
    """Analyze images for brand (sync wrapper).

    Uses analyze_images_for_brand() for scraped ads and
    analyze_images_for_brand_meta() for Meta API ads.
    """
    from viraltracker.services.brand_research_service import BrandResearchService

    ad_id_set = None
    if product_id:
        ad_id_set = get_ad_ids_for_product(brand_id, product_id)
        if not ad_id_set.facebook_ad_ids and not ad_id_set.meta_ad_ids:
            return []

    async def _analyze():
        service = BrandResearchService()
        results = []
        # Scraped path
        fb_ids = ad_id_set.facebook_ad_ids if ad_id_set else None
        if fb_ids is None or fb_ids:
            r = await service.analyze_images_for_brand(UUID(brand_id), limit=limit, ad_ids=fb_ids)
            results.extend(r)
        # Meta path
        meta_ids = ad_id_set.meta_ad_ids if ad_id_set else None
        if meta_ids is None or meta_ids:
            remaining = max(0, limit - len(results))
            if remaining > 0:
                r = await service.analyze_images_for_brand_meta(UUID(brand_id), limit=remaining, meta_ad_ids=meta_ids)
                results.extend(r)
        return results

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
    """Analyze ad copy for brand (sync wrapper). Handles both sources."""
    from viraltracker.services.brand_research_service import BrandResearchService

    ad_id_set = None
    if product_id:
        ad_id_set = get_ad_ids_for_product(brand_id, product_id)
        if not ad_id_set.facebook_ad_ids and not ad_id_set.meta_ad_ids:
            return []

    async def _analyze():
        service = BrandResearchService()
        results = []
        # Scraped path
        fb_ids = ad_id_set.facebook_ad_ids if ad_id_set else None
        if fb_ids is None or fb_ids:
            r = await service.analyze_copy_batch(UUID(brand_id), limit=limit, ad_ids=fb_ids)
            results.extend(r)
        # Meta path
        meta_ids = ad_id_set.meta_ad_ids if ad_id_set else None
        if meta_ids is None or meta_ids:
            remaining = max(0, limit - len(results))
            if remaining > 0:
                r = await service.analyze_copy_batch_meta(UUID(brand_id), limit=remaining, meta_ad_ids=meta_ids)
                results.extend(r)
        return results

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

def render_brand_product_selector():
    """Render brand and product selector using shared utility."""
    from viraltracker.ui.utils import render_brand_selector as shared_brand_selector
    return shared_brand_selector(
        include_product=True,
        product_label="Filter by Product (optional)",
        key="research_brand_selector",
        product_key="research_product_selector"
    )

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

    legacy_mode = st.checkbox(
        "Run download directly (legacy)", value=False, key="download_legacy_mode",
        help="Runs the download in-process instead of queuing to the background worker"
    )

    if legacy_mode:
        # Legacy mode: original in-process behavior with BrandResearchService
        col1, col2 = st.columns([2, 1])

        with col1:
            limit = st.slider("Max ads to process", 10, 100, 50, key="download_limit")

        with col2:
            if st.button("Download Assets", type="primary", disabled=st.session_state.analysis_running):
                st.session_state.analysis_running = True

                with st.spinner("Downloading assets from ad snapshots..."):
                    try:
                        result = download_assets_sync(brand_id, limit, product_id=product_id)

                        # Check for early exit reasons
                        reason = result.get('reason')
                        if reason == 'no_ads_linked':
                            st.error("No ads linked to this brand. Link ads first from the Facebook Ads page.")
                        elif reason == 'no_ads_for_product':
                            st.warning("No ads found for the selected product. Check URL mappings.")
                        elif reason == 'all_have_assets':
                            st.success(f"All {result.get('total_ads', 0)} ads already have assets downloaded.")
                        elif result['videos_downloaded'] > 0 or result['images_downloaded'] > 0:
                            st.success(
                                f"Downloaded {result['videos_downloaded']} videos, "
                                f"{result['images_downloaded']} images from {result['ads_processed']} ads"
                            )
                        else:
                            st.warning(
                                f"No assets downloaded. Processed {result['ads_processed']} ads."
                            )
                            skipped = result.get('ads_skipped_no_urls', 0)
                            errors = result.get('errors', 0)
                            if skipped > 0 or errors > 0:
                                details = []
                                if skipped > 0:
                                    details.append(f"{skipped} ads had no asset URLs (may need fresh scrape)")
                                if errors > 0:
                                    details.append(f"{errors} download errors (CDN URLs may have expired)")
                                st.info(" | ".join(details))

                    except Exception as e:
                        st.error(f"Download failed: {e}")

                st.session_state.analysis_running = False
                st.rerun()
    else:
        # Queued mode: queue to background worker via asset_download job
        col1, col2, col3 = st.columns([1, 1, 1])

        with col1:
            max_videos = st.slider("Max videos", 5, 100, 20, key="download_max_videos")
        with col2:
            max_images = st.slider("Max images", 10, 200, 40, key="download_max_images")
        with col3:
            st.write("")  # Spacer
            if st.button("Download Assets", type="primary", disabled=st.session_state.analysis_running):
                from viraltracker.services.pipeline_helpers import queue_one_time_job

                job_id = queue_one_time_job(
                    brand_id=brand_id,
                    job_type="asset_download",
                    parameters={
                        "max_videos": max_videos,
                        "max_images": max_images,
                    },
                )
                if job_id:
                    st.success("Asset download queued! It will start within 60 seconds.")
                else:
                    st.error("Failed to queue download job. Please try legacy mode.")

        # Recent manual download runs
        render_recent_asset_downloads(brand_id)


def render_recent_asset_downloads(brand_id: str):
    """Show recent one-time asset_download runs for this brand."""
    db = get_supabase_client()
    try:
        jobs_result = db.table("scheduled_jobs").select(
            "id, status, created_at"
        ).eq("brand_id", brand_id).eq(
            "job_type", "asset_download"
        ).eq("schedule_type", "one_time").order(
            "created_at", desc=True
        ).limit(5).execute()

        jobs = jobs_result.data or []
        if not jobs:
            return

        st.divider()
        st.caption("**Recent Asset Downloads**")

        for job in jobs:
            job_id = job["id"]
            job_status = job.get("status", "unknown")

            # Fetch latest run for this job
            run_result = db.table("scheduled_job_runs").select(
                "status, started_at, completed_at, logs"
            ).eq("scheduled_job_id", job_id).order(
                "started_at", desc=True
            ).limit(1).execute()

            run = run_result.data[0] if run_result.data else None

            if run:
                run_status = run.get("status", "unknown")
                status_emoji = {"completed": "done", "failed": "failed", "running": "running"}.get(run_status, run_status)
                started = run.get("started_at", "")
                if started:
                    try:
                        started_dt = datetime.fromisoformat(started.replace("Z", "+00:00"))
                        started_str = started_dt.strftime("%b %d, %I:%M %p")
                    except Exception:
                        started_str = started[:16]
                else:
                    started_str = "Pending"

                # Extract summary from logs
                logs = run.get("logs", "") or ""
                summary = ""
                for line in logs.split("\n"):
                    if "Videos downloaded:" in line or "Total:" in line:
                        summary = line.strip()
                        break

                display = f"{started_str} — {status_emoji}"
                if summary:
                    display += f" — {summary}"
                st.caption(display)
            else:
                # Job exists but no run yet (queued, waiting for worker)
                if job_status == "active":
                    st.caption("Queued — waiting for worker pickup...")
                elif job_status == "archived":
                    st.caption("Archived (no run data)")

    except Exception:
        pass  # Non-critical UI section — don't break the page

def render_analysis_section(brand_id: str, product_id: Optional[str] = None):
    """Render analysis controls."""
    st.subheader("2. Analyze Assets")
    st.markdown("Run AI analysis on videos, images, and ad copy to extract persona signals.")

    # Media Health Check Section
    health_key = f"asset_health_{brand_id}"
    with st.expander("Media Health Check", expanded=False):
        st.caption("Check for expired/failed media assets before analysis")

        hc_col1, hc_col2 = st.columns([1, 2])
        with hc_col1:
            if st.button("Check Health", key=f"check_health_{brand_id}"):
                with st.spinner("Checking asset health..."):
                    image_health = check_asset_health(brand_id, "image")
                    video_health = check_asset_health(brand_id, "video")

                    # Combine results
                    combined_health = {
                        "total": image_health["total"] + video_health["total"],
                        "healthy": image_health["healthy"] + video_health["healthy"],
                        "expired": image_health["expired"] + video_health["expired"],
                        "failed": image_health["failed"] + video_health["failed"],
                        "expired_asset_ids": image_health["expired_asset_ids"] + video_health["expired_asset_ids"],
                        "failed_asset_ids": image_health["failed_asset_ids"] + video_health["failed_asset_ids"],
                    }
                    st.session_state[health_key] = combined_health

        # Display health status if available
        health = st.session_state.get(health_key)
        if health:
            with hc_col2:
                m1, m2, m3, m4 = st.columns(4)
                with m1:
                    st.metric("Total", health['total'])
                with m2:
                    st.metric("Healthy", health['healthy'])
                with m3:
                    st.metric("Expired", health['expired'], delta=-health['expired'] if health['expired'] > 0 else None, delta_color="inverse")
                with m4:
                    st.metric("Failed", health['failed'], delta=-health['failed'] if health['failed'] > 0 else None, delta_color="inverse")

            # Show refresh button if there are problems
            if health['expired'] > 0 or health['failed'] > 0:
                st.warning(f"{health['expired'] + health['failed']} assets need attention (will be skipped during analysis)")
                if st.button("Refresh Expired Media", type="primary", key=f"refresh_{brand_id}"):
                    with st.spinner("Re-downloading expired assets from fresh CDN URLs..."):
                        result = refresh_expired_assets_sync(brand_id)
                        if result['refreshed'] > 0:
                            st.success(
                                f"Refreshed {result['refreshed']} assets from "
                                f"{result['ads_rescraped']} ads"
                            )
                        if result['still_failed'] > 0:
                            st.warning(
                                f"{result['still_failed']} assets still failed "
                                "(CDN URLs may be permanently expired)"
                            )
                        # Clear cached health
                        st.session_state.pop(health_key, None)
                        st.rerun()
            else:
                st.success("All assets are healthy!")

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

def add_manual_landing_page(brand_id: str, url: str, product_id: Optional[str] = None) -> bool:
    """Add a manual landing page URL for a brand.

    Args:
        brand_id: Brand UUID
        url: Landing page URL to add
        product_id: Optional product UUID to link

    Returns:
        True if successful, False otherwise
    """
    try:
        db = get_supabase_client()
        record = {
            "brand_id": brand_id,
            "url": url,
            "product_id": product_id,
            "scrape_status": "pending"
        }
        db.table("brand_landing_pages").upsert(
            record,
            on_conflict="brand_id,url"
        ).execute()
        return True
    except Exception as e:
        st.error(f"Failed to add landing page: {e}")
        return False

def scrape_single_landing_page(brand_id: str, url: str, product_id: Optional[str] = None) -> bool:
    """Scrape a single landing page URL.

    Args:
        brand_id: Brand UUID
        url: Landing page URL to scrape
        product_id: Optional product UUID

    Returns:
        True if successful, False otherwise
    """
    from viraltracker.services.web_scraping_service import WebScrapingService, LANDING_PAGE_SCHEMA
    from datetime import datetime

    async def _scrape():
        scraper = WebScrapingService()

        try:
            # Scrape the page
            scrape_result = await scraper.scrape_url_async(url)
            if not scrape_result or not scrape_result.success:
                return False

            # Try structured extraction
            extract_result = None
            try:
                extract_result = await scraper.extract_structured_async(url=url, schema=LANDING_PAGE_SCHEMA)
            except Exception:
                pass

            # Build extracted_data from extract_result
            extracted_data = {}
            if extract_result and extract_result.success and extract_result.data:
                extracted_data = extract_result.data if isinstance(extract_result.data, dict) else {}

            # Extract metadata
            raw_metadata = scrape_result.metadata
            if raw_metadata is None:
                metadata = {}
            elif isinstance(raw_metadata, dict):
                metadata = raw_metadata
            else:
                metadata = {
                    "title": getattr(raw_metadata, 'title', None),
                    "description": getattr(raw_metadata, 'description', None),
                }

            # Build update record
            update_record = {
                "page_title": metadata.get("title") or extracted_data.get("page_title"),
                "meta_description": metadata.get("description") or extracted_data.get("meta_description"),
                "raw_markdown": scrape_result.markdown,
                "extracted_data": extracted_data,
                "product_name": extracted_data.get("product_name"),
                "pricing": extracted_data.get("pricing", {}),
                "benefits": extracted_data.get("benefits", []),
                "features": extracted_data.get("features", []),
                "testimonials": extracted_data.get("testimonials", []),
                "social_proof": extracted_data.get("social_proof", []),
                "call_to_action": extracted_data.get("call_to_action"),
                "objection_handling": extracted_data.get("objection_handling", []),
                "guarantee": extracted_data.get("guarantee"),
                "urgency_elements": extracted_data.get("urgency_elements", []),
                "scrape_status": "scraped",
                "scraped_at": datetime.utcnow().isoformat()
            }

            # Update existing record (upsert pattern)
            db = get_supabase_client()
            db.table("brand_landing_pages").update(update_record).eq(
                "brand_id", brand_id
            ).eq("url", url).execute()

            return True
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"Failed to scrape {url}: {e}")
            return False

    return run_async(_scrape())

def render_landing_page_section(brand_id: str, product_id: Optional[str] = None):
    """Render landing page scraping and analysis section."""
    st.subheader("3. Landing Pages")
    st.markdown("Scrape and analyze landing pages from URL patterns for deeper persona insights.")

    # Manual URL addition form
    with st.expander("➕ Add Landing Page URL Manually"):
        with st.form("add_brand_landing_page"):
            lp_url = st.text_input("URL", placeholder="https://example.com/product-page")

            # Product assignment
            products = get_products_for_brand(brand_id)
            lp_product_options = {"Unassigned": None}
            if products:
                lp_product_options.update({p['name']: p['id'] for p in products})

            lp_product = st.selectbox(
                "Assign to Product (optional)",
                options=list(lp_product_options.keys())
            )
            lp_product_id = lp_product_options[lp_product]

            col_add, col_scrape = st.columns(2)
            with col_add:
                add_only = st.form_submit_button("Add URL")
            with col_scrape:
                add_and_scrape = st.form_submit_button("Add & Scrape Now", type="primary")

            if add_only or add_and_scrape:
                if not lp_url:
                    st.error("URL is required")
                elif not lp_url.startswith(("http://", "https://")):
                    st.error("URL must start with http:// or https://")
                else:
                    if add_manual_landing_page(brand_id, lp_url, lp_product_id):
                        if add_and_scrape:
                            with st.spinner(f"Scraping {lp_url}..."):
                                if scrape_single_landing_page(brand_id, lp_url, lp_product_id):
                                    st.success("Landing page added and scraped!")
                                else:
                                    st.warning("Landing page added but scraping failed. You can retry later.")
                        else:
                            st.success("Landing page URL added! Click 'Scrape Landing Pages' to scrape it.")
                        st.rerun()

    lp_stats = get_landing_page_stats(brand_id, product_id)
    available = lp_stats.get("available", 0)
    to_scrape = lp_stats.get("to_scrape", 0)
    successfully_scraped = lp_stats.get("successfully_scraped", 0)
    analyzed = lp_stats.get("analyzed", 0)
    to_analyze = lp_stats.get("to_analyze", 0)

    # Show overall status - only show warning if no landing pages at all
    if available == 0:
        st.info("No landing pages yet. Use the form above to add URLs manually, or add URL patterns on the URL Mapping page.")
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

    # Belief-First Analysis Section
    st.divider()
    _render_belief_first_section(brand_id, product_id, successfully_scraped)

def _render_belief_first_section(brand_id: str, product_id: Optional[str], scraped_count: int):
    """Render the belief-first landing page analysis sub-section."""
    from viraltracker.ui.utils import render_belief_first_analysis, render_belief_first_aggregation

    st.markdown("#### Belief-First Analysis (13-Layer Canvas)")
    st.caption("Deep strategic analysis using Claude Opus 4.6 to evaluate messaging coherence")

    if scraped_count == 0:
        st.info("Scrape landing pages first to run belief-first analysis.")
        return

    # Get belief-first stats
    bf_stats = get_belief_first_stats(brand_id, product_id)
    total = bf_stats.get("total", 0)
    analyzed = bf_stats.get("analyzed", 0)
    pending = bf_stats.get("pending", 0)

    # Stats row
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Scraped Pages", total)
    with col2:
        st.metric("Belief-First Analyzed", analyzed)
    with col3:
        st.metric("Pending", pending)

    # Analysis controls
    col_analyze, col_aggregate = st.columns(2)

    with col_analyze:
        if pending > 0:
            analyze_limit = st.number_input(
                "Pages to analyze",
                min_value=1,
                max_value=min(pending, 20),
                value=min(pending, 5),
                key="bf_analyze_limit"
            )

            # Cost estimate
            estimated_cost = analyze_limit * 0.15  # ~$0.15 per page with Opus 4.6
            st.caption(f"Estimated cost: ~${estimated_cost:.2f} (Opus 4.6)")

            if st.button("Run Belief-First Analysis", type="primary", key="btn_bf_analyze"):
                with st.spinner(f"Analyzing {analyze_limit} pages with Claude Opus 4.6..."):
                    try:
                        results = run_belief_first_analysis_sync(brand_id, analyze_limit, product_id)
                        st.success(f"Analyzed {len(results)} pages")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Analysis failed: {e}")
        else:
            if analyzed > 0:
                st.success(f"All {total} pages analyzed")
            else:
                st.info("No pages ready for belief-first analysis")

    with col_aggregate:
        if analyzed > 0:
            if st.button("Generate Summary", key="btn_bf_aggregate"):
                with st.spinner("Aggregating analysis across all pages..."):
                    try:
                        aggregation = aggregate_belief_first_sync(brand_id, product_id)
                        st.session_state.bf_aggregation = aggregation
                        st.success("Summary generated!")
                    except Exception as e:
                        st.error(f"Aggregation failed: {e}")

    # Display results
    if analyzed > 0:
        tab_individual, tab_summary = st.tabs(["Individual Pages", "Summary View"])

        with tab_individual:
            pages = get_landing_pages_with_belief_first(brand_id, product_id)
            if pages:
                for page in pages[:10]:  # Limit to 10 for performance
                    bf_analysis = page.get("belief_first_analysis")
                    if bf_analysis:
                        url = page.get("url", "Unknown")
                        title = page.get("page_title") or url.split("/")[-1] or "Untitled"
                        score = bf_analysis.get("summary", {}).get("overall_score", "?")

                        with st.expander(f"📄 {title} (Score: {score}/10)"):
                            st.caption(url)
                            render_belief_first_analysis(bf_analysis, nested=True)
            else:
                st.info("No pages with belief-first analysis yet.")

        with tab_summary:
            # Get or generate aggregation
            if st.session_state.get("bf_aggregation"):
                render_belief_first_aggregation(
                    st.session_state.bf_aggregation,
                    entity_name="Brand Landing Pages"
                )
            else:
                # Try to get from database or generate
                aggregation = aggregate_belief_first_sync(brand_id, product_id)
                if aggregation and aggregation.get("overall", {}).get("total_pages", 0) > 0:
                    render_belief_first_aggregation(aggregation, entity_name="Brand Landing Pages")
                else:
                    st.info("Click 'Generate Summary' to see aggregated analysis.")

def get_belief_first_stats(brand_id: str, product_id: Optional[str] = None) -> Dict[str, int]:
    """Get belief-first analysis stats for a brand."""
    from viraltracker.services.brand_research_service import BrandResearchService
    service = BrandResearchService()
    return service.get_belief_first_analysis_stats(
        UUID(brand_id),
        UUID(product_id) if product_id else None
    )

def run_belief_first_analysis_sync(brand_id: str, limit: int, product_id: Optional[str] = None) -> List:
    """Run belief-first analysis synchronously."""
    import asyncio
    from viraltracker.services.brand_research_service import BrandResearchService
    service = BrandResearchService()
    return asyncio.run(service.analyze_landing_pages_belief_first_for_brand(
        UUID(brand_id),
        limit=limit,
        product_id=UUID(product_id) if product_id else None
    ))

def aggregate_belief_first_sync(brand_id: str, product_id: Optional[str] = None) -> Dict:
    """Aggregate belief-first analysis synchronously."""
    from viraltracker.services.brand_research_service import BrandResearchService
    service = BrandResearchService()
    return service.aggregate_belief_first_analysis_for_brand(
        UUID(brand_id),
        UUID(product_id) if product_id else None
    )

def get_landing_pages_with_belief_first(brand_id: str, product_id: Optional[str] = None) -> List:
    """Get landing pages that have belief-first analysis."""
    from viraltracker.core.database import get_supabase_client
    db = get_supabase_client()

    query = db.table("brand_landing_pages").select(
        "id, url, page_title, belief_first_analysis"
    ).eq("brand_id", brand_id).not_.is_("belief_first_analysis", "null")

    if product_id:
        query = query.eq("product_id", product_id)

    result = query.order("belief_first_analyzed_at", desc=True).execute()
    return result.data or []

def get_landing_pages_for_brand(brand_id: str) -> list:
    """Get landing pages for a brand."""
    from viraltracker.services.brand_research_service import BrandResearchService
    service = BrandResearchService()
    return service.get_landing_pages_for_brand(UUID(brand_id))

def get_amazon_review_service():
    """Get AmazonReviewService instance with tracking enabled."""
    from viraltracker.services.amazon_review_service import AmazonReviewService
    from viraltracker.ui.utils import setup_tracking_context
    service = AmazonReviewService()
    setup_tracking_context(service)
    return service

def get_amazon_review_stats(brand_id: str, product_id: Optional[str] = None) -> Dict[str, Any]:
    """Get Amazon review statistics for a brand/product."""
    try:
        db = get_supabase_client()

        # Check if there's an Amazon URL configured
        if product_id:
            url_result = db.table("amazon_product_urls").select(
                "id, asin, total_reviews_scraped"
            ).eq("product_id", product_id).execute()
        else:
            url_result = db.table("amazon_product_urls").select(
                "id, asin, total_reviews_scraped"
            ).eq("brand_id", brand_id).execute()

        if not url_result.data:
            return {
                "has_amazon_url": False,
                "reviews_scraped": 0,
                "has_analysis": False
            }

        total_scraped = sum(u.get("total_reviews_scraped", 0) or 0 for u in url_result.data)

        # Check for existing analysis
        if product_id:
            analysis_result = db.table("amazon_review_analysis").select(
                "analyzed_at, total_reviews_analyzed, model_used"
            ).eq("product_id", product_id).execute()
        else:
            analysis_result = db.table("amazon_review_analysis").select(
                "analyzed_at, total_reviews_analyzed, model_used"
            ).eq("brand_id", brand_id).execute()

        analysis_data = analysis_result.data[0] if analysis_result.data else {}

        return {
            "has_amazon_url": True,
            "url_count": len(url_result.data),
            "reviews_scraped": total_scraped,
            "has_analysis": bool(analysis_result.data),
            "analyzed_at": analysis_data.get("analyzed_at"),
            "reviews_analyzed": analysis_data.get("total_reviews_analyzed", 0),
            "model_used": analysis_data.get("model_used")
        }
    except Exception as e:
        st.error(f"Failed to get Amazon stats: {e}")
        return {"has_amazon_url": False, "reviews_scraped": 0, "has_analysis": False}

def render_amazon_review_section(brand_id: str, product_id: Optional[str] = None):
    """Render Amazon review analysis section with 7 themed tabs."""
    st.subheader("4. Amazon Review Analysis")
    st.markdown("Analyze Amazon reviews to extract customer pain points, jobs to be done, and more.")

    stats = get_amazon_review_stats(brand_id, product_id)

    if not stats.get("has_amazon_url"):
        st.info("No Amazon product URLs configured. Add URLs in URL Mapping to enable Amazon review analysis.")
        return

    col1, col2 = st.columns([2, 1])

    with col1:
        st.caption(f"📦 {stats.get('url_count', 0)} Amazon URL(s) | 📝 {stats.get('reviews_scraped', 0)} reviews scraped")

        if stats.get("has_analysis"):
            st.success(f"Analysis complete ({stats.get('reviews_analyzed', 0)} reviews analyzed)")
            st.caption(f"Model: {stats.get('model_used', 'Unknown')} | Analyzed: {stats.get('analyzed_at', 'Unknown')[:10] if stats.get('analyzed_at') else 'Unknown'}")

    with col2:
        if product_id:
            # Re-scrape button — fetch new reviews from Amazon
            if st.button("Re-scrape Reviews", disabled=st.session_state.analysis_running, key="btn_amazon_scrape"):
                st.session_state.analysis_running = True
                with st.spinner("Scraping Amazon reviews (2-5 minutes)..."):
                    try:
                        db = get_supabase_client()
                        urls = db.table("amazon_product_urls").select(
                            "amazon_url"
                        ).eq("product_id", product_id).execute()
                        if not urls.data:
                            st.warning("No Amazon URL configured for this product.")
                        else:
                            service = get_amazon_review_service()
                            total_saved = 0
                            for url_row in urls.data:
                                result = service.scrape_reviews_for_product(
                                    product_id=UUID(product_id),
                                    amazon_url=url_row["amazon_url"],
                                )
                                total_saved += result.reviews_saved
                            st.success(f"Scrape complete! {total_saved} reviews saved.")
                    except Exception as e:
                        st.error(f"Scrape failed: {e}")
                st.session_state.analysis_running = False
                st.rerun()

            # Analyze button — run AI analysis on stored reviews
            btn_label = "Re-analyze Reviews" if stats.get("has_analysis") else "Analyze Reviews"
            if st.button(btn_label, type="primary", disabled=st.session_state.analysis_running, key="btn_amazon"):
                st.session_state.analysis_running = True
                with st.spinner("Analyzing Amazon reviews (30-60 seconds)..."):
                    try:
                        service = get_amazon_review_service()
                        result = run_async(service.analyze_reviews_for_product(UUID(product_id)))
                        if result:
                            st.success("Amazon review analysis complete!")
                        else:
                            st.warning("No reviews found to analyze. Scrape reviews first.")
                    except Exception as e:
                        st.error(f"Analysis failed: {e}")
                st.session_state.analysis_running = False
                st.rerun()
        else:
            st.info("Select a product to analyze its Amazon reviews")

    # Display existing analysis with 7 tabs
    if stats.get("has_analysis") and product_id:
        try:
            service = get_amazon_review_service()
            analysis = service.get_analysis_for_product(UUID(product_id))

            if analysis:
                st.markdown("---")

                # Show summary
                st.caption(f"📊 {analysis.get('total_reviews_analyzed', 0)} reviews analyzed | Model: {analysis.get('model_used', 'Unknown')}")

                tab_pain, tab_jtbd, tab_issues, tab_outcomes, tab_objections, tab_features, tab_failed = st.tabs([
                    "😫 Pain Points", "🎯 Jobs to Be Done", "⚠️ Product Issues",
                    "✨ Desired Outcomes", "🚫 Buying Objections",
                    "💡 Desired Features", "❌ Failed Solutions"
                ])

                def render_themed_section(themes: list, tab_name: str):
                    """Render a themed section with quotes and context."""
                    if not themes:
                        st.info(f"No {tab_name.lower()} extracted yet.")
                        return

                    for i, theme in enumerate(themes, 1):
                        theme_name = theme.get('theme', 'Unknown Theme')
                        score = theme.get('score', 0)
                        quotes = theme.get('quotes', [])

                        # Theme header with score
                        st.markdown(f"### {i}. {theme_name} — Score: {score}/10")

                        # Quotes with context
                        for q in quotes[:5]:
                            quote_text = q.get('quote', '')
                            context = q.get('context', '')
                            author = q.get('author', 'Anonymous')
                            rating = q.get('rating')

                            rating_str = f"⭐{rating}" if rating else ""

                            st.markdown(f"""
> **Quote:** "{quote_text}"
>
> **Context:** {context}
>
> *— {author} {rating_str}*
""")
                        st.markdown("---")

                # Extract data - pain_points contains themes, jobs_to_be_done, and product_issues
                # Handle both new format (dict with 'themes' key) and old format (direct list)
                pain_data = analysis.get('pain_points', {})
                if isinstance(pain_data, dict):
                    pain_themes = pain_data.get('themes', [])
                    jtbd_themes = pain_data.get('jobs_to_be_done', [])
                    issues_themes = pain_data.get('product_issues', [])
                elif isinstance(pain_data, list):
                    # Old format: pain_points is directly a list of themes
                    pain_themes = pain_data
                    jtbd_themes = []
                    issues_themes = []
                else:
                    pain_themes = []
                    jtbd_themes = []
                    issues_themes = []

                with tab_pain:
                    st.caption("Life frustrations BEFORE trying the product - what drove them to seek a solution")
                    render_themed_section(pain_themes, "Pain Points")

                with tab_jtbd:
                    st.caption("What customers are trying to accomplish - functional, emotional, and social goals")
                    render_themed_section(jtbd_themes, "Jobs to Be Done")

                with tab_issues:
                    st.caption("Problems WITH this specific product - complaints, defects, disappointments")
                    render_themed_section(issues_themes, "Product Issues")

                with tab_outcomes:
                    desires_data = analysis.get('desires', {})
                    if isinstance(desires_data, dict):
                        desires_themes = desires_data.get('themes', [])
                    elif isinstance(desires_data, list):
                        desires_themes = desires_data  # Old format: direct list
                    else:
                        desires_themes = []
                    render_themed_section(desires_themes, "Desired Outcomes")

                with tab_objections:
                    objections_data = analysis.get('objections', {})
                    if isinstance(objections_data, dict):
                        objections_themes = objections_data.get('themes', [])
                    elif isinstance(objections_data, list):
                        objections_themes = objections_data  # Old format: direct list
                    else:
                        objections_themes = []
                    render_themed_section(objections_themes, "Buying Objections")

                with tab_features:
                    features_data = analysis.get('language_patterns', {})
                    features_themes = features_data.get('themes', []) if isinstance(features_data, dict) else []
                    render_themed_section(features_themes, "Desired Features")

                with tab_failed:
                    failed_data = analysis.get('transformation', {})
                    failed_themes = failed_data.get('themes', []) if isinstance(failed_data, dict) else []
                    render_themed_section(failed_themes, "Failed Solutions")

        except Exception as e:
            st.error(f"Failed to load analysis: {e}")

def render_angle_extraction_section(brand_id: str, product_id: Optional[str] = None):
    """Render angle pipeline extraction section."""
    st.subheader("5. Extract to Angle Pipeline")
    st.markdown("Create angle candidates from your research for ad testing.")

    # Get stats to determine what sources are available
    analysis_stats = get_analysis_stats_for_brand(brand_id, product_id)
    bf_stats = get_belief_first_stats(brand_id, product_id)

    has_amazon = analysis_stats.get("amazon_reviews", 0) > 0
    has_landing_pages = bf_stats.get("analyzed", 0) > 0

    if not has_amazon and not has_landing_pages:
        st.info("Analyze Amazon reviews or landing pages first to extract angle candidates.")
        return

    # Need a product to link candidates to
    if not product_id:
        products = get_products_for_brand(brand_id)
        if not products:
            st.warning("Create a product first to extract angle candidates.")
            return

        product_options = {p["name"]: p["id"] for p in products}
        selected_product = st.selectbox(
            "Link Candidates to Product",
            options=list(product_options.keys()),
            key="brand_extract_product",
            help="Candidates will be linked to this product for angle testing"
        )
        product_id = product_options[selected_product]

    col1, col2 = st.columns([2, 1])

    with col1:
        st.markdown("**Select Sources:**")
        sources_to_extract = []
        if has_amazon:
            if st.checkbox("Amazon Review Themes", value=True, key="brand_extract_amazon"):
                sources_to_extract.append("amazon")
        if has_landing_pages:
            if st.checkbox("Landing Page Insights", value=True, key="brand_extract_landing"):
                sources_to_extract.append("landing_pages")

    with col2:
        st.markdown("**Available:**")
        available = []
        if has_amazon:
            available.append(f"{analysis_stats.get('amazon_reviews', 0)} Amazon reviews")
        if has_landing_pages:
            available.append(f"{bf_stats.get('analyzed', 0)} landing pages")
        st.caption("\n".join(available))

    if sources_to_extract:
        if st.button("Extract to Angle Pipeline", type="primary", key="brand_extract_btn"):
            with st.spinner("Extracting candidates..."):
                try:
                    stats = extract_brand_research_candidates(
                        brand_id=brand_id,
                        product_id=product_id,
                        sources=sources_to_extract
                    )

                    if stats["total_created"] > 0 or stats["total_updated"] > 0:
                        st.success(
                            f"Extraction complete! Created {stats['total_created']} new candidates, "
                            f"updated {stats['total_updated']} existing."
                        )

                        # Show breakdown by source
                        for source, result in stats["by_source"].items():
                            st.caption(
                                f"  {source}: {result.get('created', 0)} created, "
                                f"{result.get('updated', 0)} updated"
                            )
                    else:
                        st.info("No new candidates created. Data may already exist as candidates.")

                except Exception as e:
                    st.error(f"Extraction failed: {e}")
    else:
        st.info("Select at least one source to extract.")

def get_offer_variants_for_product(product_id: str) -> List[Dict]:
    """Get offer variants for a product."""
    try:
        from viraltracker.services.product_offer_variant_service import ProductOfferVariantService
        service = ProductOfferVariantService()
        return service.get_offer_variants(UUID(product_id), active_only=True)
    except Exception as e:
        st.error(f"Failed to get offer variants: {e}")
        return []

def synthesize_from_offer_variant_sync(offer_variant_id: str) -> List[Dict]:
    """Synthesize personas from offer variant (sync wrapper)."""
    from viraltracker.services.brand_research_service import BrandResearchService

    async def _synthesize():
        service = BrandResearchService()
        return await service.synthesize_from_offer_variant(UUID(offer_variant_id))

    return run_async(_synthesize())

def render_synthesis_section(brand_id: str, product_id: Optional[str] = None):
    """Render persona synthesis section."""
    st.subheader("6. Synthesize Personas")
    st.markdown("Generate 4D personas from analyses or offer variants.")

    # Get offer variants if product is selected
    offer_variants = []
    if product_id:
        offer_variants = get_offer_variants_for_product(product_id)

    # Show tabs if offer variants exist
    if offer_variants:
        tab_analyses, tab_variant = st.tabs(["📊 From Analyses", "🎯 From Offer Variant"])
    else:
        tab_analyses = st.container()
        tab_variant = None

    # Tab 1: Synthesize from analyses (existing flow)
    with tab_analyses:
        analysis_stats = get_analysis_stats_for_brand(brand_id, product_id)

        if analysis_stats["total"] < 3:
            st.warning("Run at least 3 analyses before synthesizing from analyses.")
        else:
            # Build analysis summary
            parts = []
            if analysis_stats['video_vision'] > 0:
                parts.append(f"{analysis_stats['video_vision']} videos")
            if analysis_stats['image_vision'] > 0:
                parts.append(f"{analysis_stats['image_vision']} images")
            if analysis_stats['copy_analysis'] > 0:
                parts.append(f"{analysis_stats['copy_analysis']} copy")
            if analysis_stats['amazon_reviews'] > 0:
                parts.append(f"{analysis_stats['amazon_reviews']} Amazon reviews")

            st.info(f"Ready to synthesize from {analysis_stats['total']} analyses ({', '.join(parts)})")

            if st.button("Synthesize from Analyses", type="primary", disabled=st.session_state.analysis_running, key="btn_synth_analyses"):
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

    # Tab 2: Synthesize from offer variant
    if tab_variant is not None:
        with tab_variant:
            st.markdown("Generate a persona based on a specific offer variant's messaging angle.")

            # Build variant options
            variant_options = {v["name"]: v["id"] for v in offer_variants}
            selected_variant_name = st.selectbox(
                "Select Offer Variant",
                options=list(variant_options.keys()),
                key="synth_variant_select"
            )
            selected_variant_id = variant_options.get(selected_variant_name)

            # Show variant details
            if selected_variant_id:
                selected_variant = next((v for v in offer_variants if v["id"] == selected_variant_id), None)
                if selected_variant:
                    col1, col2 = st.columns(2)
                    with col1:
                        st.caption("**Pain Points:**")
                        for pp in selected_variant.get("pain_points", [])[:5]:
                            st.write(f"• {pp}")
                    with col2:
                        st.caption("**Benefits:**")
                        for b in selected_variant.get("benefits", [])[:5]:
                            st.write(f"• {b}")

                    if selected_variant.get("target_audience"):
                        st.caption(f"**Target Audience:** {selected_variant['target_audience']}")

            if st.button("Synthesize from Variant", type="primary", disabled=st.session_state.analysis_running, key="btn_synth_variant"):
                if not selected_variant_id:
                    st.error("Please select an offer variant")
                else:
                    st.session_state.analysis_running = True

                    with st.spinner("Generating persona from offer variant... (30-60 seconds)"):
                        try:
                            personas = synthesize_from_offer_variant_sync(selected_variant_id)
                            st.session_state.suggested_personas = personas
                            st.session_state.review_mode = True
                            st.success(f"Generated {len(personas)} persona(s) from offer variant")
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
                tabs = st.tabs(["Pain & Desires", "Identity", "Social", "Worldview", "Barriers", "Purchase", "Testimonials"])

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

                    col_pos, col_neg = st.columns(2)

                    with col_pos:
                        st.markdown("**People They Admire:**")
                        for item in social.get('admire', []):
                            st.markdown(f"- {item}")

                        st.markdown("**People They Envy:**")
                        for item in social.get('envy', []):
                            st.markdown(f"- {item}")

                        st.markdown("**Want to Impress:**")
                        for item in social.get('want_to_impress', []):
                            st.markdown(f"- {item}")

                        st.markdown("**Groups They Want to Join:**")
                        for item in social.get('want_to_belong', []):
                            st.markdown(f"- {item}")

                        st.markdown("**People They Protect:**")
                        for item in social.get('love_loyalty', []):
                            st.markdown(f"- {item}")

                    with col_neg:
                        st.markdown("**Fear Judgment From:**")
                        for item in social.get('fear_judged_by', []):
                            st.markdown(f"- {item}")

                        st.markdown("**People They Dislike:**")
                        for item in social.get('dislike_animosity', []):
                            st.markdown(f"- {item}")

                        st.markdown("**Compare Themselves To:**")
                        for item in social.get('compared_to', []):
                            st.markdown(f"- {item}")

                        st.markdown("**Groups They Distance From:**")
                        for item in social.get('distance_from', []):
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

                with tabs[5]:  # Purchase
                    col_left, col_right = st.columns(2)

                    with col_left:
                        st.markdown("**Pain Symptoms (Observable Signs):**")
                        for item in persona.get('pain_symptoms', []):
                            st.markdown(f"- {item}")

                        st.markdown("**Activation Events (What Triggers Purchase):**")
                        for item in persona.get('activation_events', []):
                            st.markdown(f"- {item}")

                        st.markdown("**Current Workarounds:**")
                        for item in persona.get('current_workarounds', []):
                            st.markdown(f"- {item}")

                    with col_right:
                        st.markdown("**Purchasing Habits:**")
                        st.write(persona.get('purchasing_habits', 'N/A'))

                        st.markdown("**Decision Process:**")
                        st.write(persona.get('decision_process', 'N/A'))

                with tabs[6]:  # Testimonials (Amazon customer quotes)
                    testimonials = persona.get('amazon_testimonials', {})

                    if not testimonials:
                        st.info("No Amazon testimonials available. Re-analyze Amazon reviews and re-synthesize personas to populate this section.")
                    else:
                        # Helper function to render quotes
                        def render_quotes(quotes_list):
                            if not quotes_list:
                                st.caption("No quotes in this category")
                                return
                            for q in quotes_list:
                                if isinstance(q, dict):
                                    quote_text = q.get('quote', q.get('text', ''))
                                    author = q.get('author', '')
                                    rating = q.get('rating', '')
                                    rating_stars = '⭐' * int(rating) if rating else ''
                                    # Only show author if we have a real name
                                    if author and author.lower() not in ['verified buyer', 'anonymous', '']:
                                        st.markdown(f"> \"{quote_text}\" — *{author}* {rating_stars}")
                                    else:
                                        st.markdown(f"> \"{quote_text}\" {rating_stars}")
                                else:
                                    st.markdown(f"> \"{q}\"")

                        # Use columns for better layout
                        col_left, col_right = st.columns(2)

                        with col_left:
                            # Transformation quotes
                            st.markdown("**🌟 Transformation (Results/Outcomes)**")
                            render_quotes(testimonials.get('transformation', []))
                            st.markdown("---")

                            # Pain point quotes - problems BEFORE the product
                            st.markdown("**😣 Pain Points (Problems Before Product)**")
                            render_quotes(testimonials.get('pain_points', []))
                            st.markdown("---")

                            # Desired features quotes
                            st.markdown("**✨ Desired Features (What They Wanted)**")
                            render_quotes(testimonials.get('desired_features', []))

                        with col_right:
                            # Past failures quotes
                            st.markdown("**❌ Past Failures (Other Products That Failed)**")
                            render_quotes(testimonials.get('past_failures', []))
                            st.markdown("---")

                            # Buying objections quotes
                            st.markdown("**🤔 Buying Objections (Skepticism/Hesitation)**")
                            render_quotes(testimonials.get('buying_objections', []))
                            st.markdown("---")

                            # Familiar promises quotes
                            st.markdown("**📢 Familiar Promises (Other Brand Claims)**")
                            render_quotes(testimonials.get('familiar_promises', []))

            with col2:
                st.markdown("**Actions**")

                # Product linking
                brand_id = st.session_state.get('selected_brand_id')
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

def render_existing_personas(brand_id: str, product_id: Optional[str] = None):
    """Render existing 4D personas for the brand/product."""
    db = get_supabase_client()

    # Query personas
    query = db.table("personas_4d").select(
        "id, name, persona_type, created_at, pain_points, desires"
    )

    if product_id:
        query = query.eq("product_id", product_id)
    else:
        query = query.eq("brand_id", brand_id)

    result = query.order("created_at", desc=True).limit(10).execute()

    if not result.data:
        st.info("No personas created yet. Use the Personas page or synthesize from analyses above.")
        return

    st.success(f"Found {len(result.data)} existing persona(s)")

    for persona in result.data:
        with st.expander(f"**{persona['name']}** ({persona.get('persona_type', 'Unknown type')})", expanded=False):
            col1, col2 = st.columns(2)

            with col1:
                st.markdown("**Pain Points:**")
                pain_points = persona.get("pain_points") or {}
                if isinstance(pain_points, dict):
                    for category, items in pain_points.items():
                        if items:
                            st.caption(f"*{category}:*")
                            for item in (items[:3] if isinstance(items, list) else []):
                                st.write(f"• {item}")
                elif isinstance(pain_points, list):
                    for pp in pain_points[:5]:
                        st.write(f"• {pp}")

            with col2:
                st.markdown("**Desires:**")
                desires = persona.get("desires") or {}
                if isinstance(desires, dict):
                    for category, items in desires.items():
                        if items:
                            st.caption(f"*{category}:*")
                            for item in (items[:3] if isinstance(items, list) else []):
                                st.write(f"• {item}")
                elif isinstance(desires, list):
                    for d in desires[:5]:
                        st.write(f"• {d}")

            # Emotional triggers
            triggers = persona.get("emotional_triggers") or {}
            if triggers:
                st.markdown("**Emotional Triggers:**")
                if isinstance(triggers, dict):
                    trigger_list = triggers.get("primary", []) or triggers.get("triggers", [])
                    for t in (trigger_list[:3] if isinstance(trigger_list, list) else []):
                        st.write(f"• {t}")

            st.caption(f"Created: {persona['created_at'][:10]}")
            st.markdown(f"[View/Edit in Personas Page →](/Personas)")

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
    # Brand and product selector (uses shared utility for cross-page persistence)
    selected_brand_id, selected_product_id = render_brand_product_selector()

    if selected_brand_id:
        # Offer variant selector (when product is selected)
        selected_variant_id = None
        if selected_product_id:
            variants = get_offer_variants_for_product(selected_product_id)
            if variants:
                variant_options = {"All Variants": None}
                for v in variants:
                    variant_options[v.get("name", "Unnamed")] = v.get("id")

                col_filter, col_info = st.columns([2, 3])
                with col_filter:
                    selected_variant_name = st.selectbox(
                        "Filter by Offer Variant",
                        options=list(variant_options.keys()),
                        key="research_variant_selector"
                    )
                    selected_variant_id = variant_options[selected_variant_name]

                with col_info:
                    if selected_variant_id:
                        # Get selected variant data and show pain points/desires
                        selected_variant = next(
                            (v for v in variants if v.get("id") == selected_variant_id),
                            None
                        )
                        if selected_variant:
                            st.caption("**Variant-Specific Data:**")
                            pain_points = selected_variant.get("pain_points") or []
                            desires = selected_variant.get("desires_goals") or []
                            if pain_points:
                                st.markdown(f"**Pain Points:** {', '.join(pain_points[:3])}...")
                            if desires:
                                st.markdown(f"**Desires:** {', '.join(desires[:3])}...")
                    else:
                        st.info("Select a variant to see variant-specific research data")

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

        # Amazon review analysis section
        render_amazon_review_section(selected_brand_id, selected_product_id)

        st.divider()

        # Angle pipeline extraction section
        render_angle_extraction_section(selected_brand_id, selected_product_id)

        st.divider()

        # Synthesis section
        render_synthesis_section(selected_brand_id, selected_product_id)

        # Show existing personas
        st.markdown("#### View Existing Personas")
        render_existing_personas(selected_brand_id, selected_product_id)

        st.divider()

        # Existing analyses
        with st.expander("View Existing Analyses"):
            render_existing_analyses(selected_brand_id)
