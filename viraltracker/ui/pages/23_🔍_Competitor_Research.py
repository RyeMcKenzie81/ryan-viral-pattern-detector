"""
Competitor Research - Analyze competitor ads and products.

This page allows users to:
- Select a competitor and optionally filter by product
- Scrape competitor ads from Facebook Ad Library
- Match ads to products via URL patterns
- Analyze landing pages
- Scrape and analyze Amazon reviews
- Generate competitor personas (at competitor or product level)
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
if 'research_competitor_product_id' not in st.session_state:
    st.session_state.research_competitor_product_id = None
if 'research_brand_id' not in st.session_state:
    st.session_state.research_brand_id = None


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


def get_competitors_for_brand(brand_id: str) -> List[Dict]:
    """Fetch competitors for a brand."""
    try:
        service = get_competitor_service()
        return service.get_competitors_for_brand(UUID(brand_id))
    except Exception as e:
        st.error(f"Failed to fetch competitors: {e}")
        return []


def get_competitor_products(competitor_id: str) -> List[Dict]:
    """Fetch products for a competitor."""
    try:
        service = get_competitor_service()
        return service.get_competitor_products(UUID(competitor_id), include_variants=False)
    except Exception as e:
        st.error(f"Failed to fetch products: {e}")
        return []


def scrape_competitor_facebook_ads(
    ad_library_url: str,
    competitor_id: str,
    brand_id: str,
    max_ads: int = 500
) -> Dict[str, Any]:
    """
    Scrape ads from Facebook Ad Library and save to competitor_ads table.

    Args:
        ad_library_url: Facebook Ad Library URL to scrape
        competitor_id: Competitor UUID to link ads to
        brand_id: Brand UUID (owner of this research)
        max_ads: Maximum number of ads to scrape

    Returns:
        Dict with results: {"success": bool, "saved": int, "failed": int, "message": str}
    """
    try:
        from viraltracker.scrapers.facebook_ads import FacebookAdsScraper

        scraper = FacebookAdsScraper()

        # Scrape ads from Ad Library
        df = scraper.search_ad_library(
            search_url=ad_library_url,
            count=max_ads,
            scrape_details=False,
            timeout=900  # 15 min timeout for large scrapes
        )

        if len(df) == 0:
            return {"success": True, "saved": 0, "failed": 0, "message": "No ads found at this URL"}

        # Convert DataFrame to list of dicts for the competitor service
        ads_data = df.to_dict('records')

        # Save via competitor service
        service = get_competitor_service()
        stats = service.save_competitor_ads_batch(
            competitor_id=UUID(competitor_id),
            brand_id=UUID(brand_id),
            ads=ads_data,
            scrape_source="ad_library_search"
        )

        return {
            "success": True,
            "saved": stats.get("saved", 0),
            "failed": stats.get("failed", 0),
            "message": f"Scraped {len(df)} ads, saved {stats.get('saved', 0)} to database"
        }

    except Exception as e:
        return {"success": False, "saved": 0, "failed": 0, "message": str(e)}


def get_research_stats(
    competitor_id: str,
    product_id: Optional[str] = None
) -> Dict[str, Any]:
    """Get research statistics for competitor (optionally filtered by product)."""
    try:
        db = get_supabase_client()
        service = get_competitor_service()

        # Base competitor stats
        stats = service.get_competitor_stats(UUID(competitor_id))

        # If product filter, get product-specific stats
        if product_id:
            product_stats = service.get_competitor_product_stats(UUID(product_id))
            stats['filtered_ads'] = product_stats.get('ads', 0)
            stats['filtered_landing_pages'] = product_stats.get('landing_pages', 0)
            stats['filtered_amazon_urls'] = product_stats.get('amazon_urls', 0)

        # Get landing pages analyzed count
        lp_query = db.table("competitor_landing_pages").select(
            "id", count="exact"
        ).eq("competitor_id", competitor_id).not_.is_("analyzed_at", "null")

        if product_id:
            lp_query = lp_query.eq("competitor_product_id", product_id)

        lp_result = lp_query.execute()
        stats['landing_pages_analyzed'] = lp_result.count or 0

        # Get Amazon reviews count
        reviews_result = db.table("competitor_amazon_reviews").select(
            "id", count="exact"
        ).eq("competitor_id", competitor_id).execute()
        stats['amazon_reviews'] = reviews_result.count or 0

        # Check if Amazon analysis exists
        analysis_result = db.table("competitor_amazon_review_analysis").select(
            "id"
        ).eq("competitor_id", competitor_id).execute()
        stats['has_amazon_analysis'] = bool(analysis_result.data)

        return stats

    except Exception as e:
        st.error(f"Failed to get stats: {e}")
        return {}


# ============================================================================
# HEADER
# ============================================================================

st.title("🔍 Competitor Research")
st.caption("Analyze competitor messaging, ads, and customer signals")

# Brand Selector
brands = get_brands()
if not brands:
    st.warning("No brands found. Please create a brand first.")
    st.stop()

brand_options = {b['name']: b['id'] for b in brands}
brand_names = list(brand_options.keys())

# Restore previous selection
current_brand_name = None
if st.session_state.research_brand_id:
    for name, bid in brand_options.items():
        if bid == st.session_state.research_brand_id:
            current_brand_name = name
            break

col_brand, col_competitor, col_product = st.columns([1, 1, 1])

with col_brand:
    selected_brand_name = st.selectbox(
        "Brand",
        options=brand_names,
        index=brand_names.index(current_brand_name) if current_brand_name in brand_names else 0,
        key="brand_selector"
    )
    selected_brand_id = brand_options[selected_brand_name]
    st.session_state.research_brand_id = selected_brand_id

# Competitor Selector
competitors = get_competitors_for_brand(selected_brand_id)

if not competitors:
    st.warning("No competitors found. Add competitors on the Competitors page.")
    if st.button("Go to Competitors Page"):
        st.switch_page("pages/22_🎯_Competitors.py")
    st.stop()

competitor_options = {c['name']: c['id'] for c in competitors}
competitor_names = list(competitor_options.keys())

# Check for pre-selected competitor from session
current_competitor_name = None
if st.session_state.research_competitor_id:
    for name, cid in competitor_options.items():
        if cid == st.session_state.research_competitor_id:
            current_competitor_name = name
            break

with col_competitor:
    selected_competitor_name = st.selectbox(
        "Competitor",
        options=competitor_names,
        index=competitor_names.index(current_competitor_name) if current_competitor_name in competitor_names else 0,
        key="competitor_selector"
    )
    selected_competitor_id = competitor_options[selected_competitor_name]
    st.session_state.research_competitor_id = selected_competitor_id

# Product Selector (optional filter)
products = get_competitor_products(selected_competitor_id)
product_options = {"All Products": None}
product_options.update({p['name']: p['id'] for p in products})
product_names = list(product_options.keys())

with col_product:
    selected_product_name = st.selectbox(
        "Filter by Product (optional)",
        options=product_names,
        index=0,
        key="product_selector"
    )
    selected_product_id = product_options[selected_product_name]
    st.session_state.research_competitor_product_id = selected_product_id

# Get competitor details
competitor = next((c for c in competitors if c['id'] == selected_competitor_id), None)
if not competitor:
    st.error("Competitor not found")
    st.stop()

st.divider()

# ============================================================================
# STATS DASHBOARD
# ============================================================================

stats = get_research_stats(selected_competitor_id, selected_product_id)

st.subheader("📊 Research Progress")

col1, col2, col3, col4, col5 = st.columns(5)

with col1:
    st.metric("Ads", stats.get('ads', 0))
    if selected_product_id:
        st.caption(f"({stats.get('filtered_ads', 0)} for product)")

with col2:
    products_count = len(products)
    st.metric("Products", products_count)

with col3:
    lp_total = stats.get('landing_pages', 0)
    lp_analyzed = stats.get('landing_pages_analyzed', 0)
    st.metric("Landing Pages", f"{lp_analyzed}/{lp_total}")
    st.caption("analyzed/total")

with col4:
    st.metric("Amazon Reviews", stats.get('amazon_reviews', 0))
    if stats.get('has_amazon_analysis'):
        st.caption("✅ Analyzed")
    else:
        st.caption("⏳ Not analyzed")

with col5:
    # Check for persona
    persona_status = "❌ Not created"
    st.metric("Persona", "—")
    st.caption(persona_status)

st.divider()

# ============================================================================
# RESEARCH SECTIONS
# ============================================================================

tab_ads, tab_landing, tab_amazon, tab_persona = st.tabs([
    "📢 Ads",
    "📄 Landing Pages",
    "⭐ Amazon Reviews",
    "👤 Persona"
])

# ----------------------------------------------------------------------------
# ADS TAB
# ----------------------------------------------------------------------------
with tab_ads:
    st.markdown("### Ad Scraping")

    ad_library_url = competitor.get('ad_library_url')

    if ad_library_url:
        st.caption(f"[Ad Library URL]({ad_library_url})")

        col_input, col_btn = st.columns([2, 1])
        with col_input:
            max_ads_to_scrape = st.number_input(
                "Max ads to scrape",
                min_value=10,
                max_value=2000,
                value=500,
                step=100,
                key="max_ads_scrape",
                help="Maximum number of ads to scrape from the Ad Library"
            )
        with col_btn:
            st.markdown("")  # Spacer
            if st.button("🔍 Scrape Ads from Ad Library", key="scrape_ads"):
                with st.spinner(f"Scraping up to {max_ads_to_scrape} ads from Facebook Ad Library... This may take several minutes."):
                    result = scrape_competitor_facebook_ads(
                        ad_library_url=ad_library_url,
                        competitor_id=selected_competitor_id,
                        brand_id=selected_brand_id,
                        max_ads=max_ads_to_scrape
                    )

                if result["success"]:
                    if result["saved"] > 0:
                        st.success(f"✅ {result['message']}")
                        st.rerun()
                    else:
                        st.warning(result["message"])
                else:
                    st.error(f"❌ Scraping failed: {result['message']}")
    else:
        st.warning("No Ad Library URL configured for this competitor.")
        st.caption("Add one on the Competitors page.")

    # -------------------------------------------------------------------------
    # ASSET DOWNLOAD & ANALYSIS
    # -------------------------------------------------------------------------
    st.markdown("---")
    st.markdown("### 📥 Download & Analyze Assets")

    # Get stats from BrandResearchService (reused for competitors)
    from viraltracker.services.brand_research_service import BrandResearchService
    research_service = BrandResearchService()

    asset_stats = research_service.get_competitor_asset_stats(UUID(selected_competitor_id))
    analysis_stats = research_service.get_competitor_analysis_stats(UUID(selected_competitor_id))

    # Stats display
    col_s1, col_s2, col_s3, col_s4, col_s5 = st.columns(5)
    with col_s1:
        st.metric("Ads Scraped", asset_stats.get('total_ads', 0))
    with col_s2:
        videos = asset_stats.get('videos', 0)
        analyzed_v = analysis_stats.get('video_vision', 0)
        st.metric("Videos", f"{analyzed_v}/{videos}" if videos > 0 else "0")
        if videos > 0 and analyzed_v < videos:
            st.caption(f"{videos - analyzed_v} to analyze")
    with col_s3:
        images = asset_stats.get('images', 0)
        analyzed_i = analysis_stats.get('image_vision', 0)
        st.metric("Images", f"{analyzed_i}/{images}" if images > 0 else "0")
        if images > 0 and analyzed_i < images:
            st.caption(f"{images - analyzed_i} to analyze")
    with col_s4:
        total_ads = asset_stats.get('total_ads', 0)
        analyzed_c = analysis_stats.get('copy_analysis', 0)
        st.metric("Copy Analyzed", f"{analyzed_c}/{total_ads}" if total_ads > 0 else "0")
    with col_s5:
        st.metric("Total Analyses", analysis_stats.get('total', 0))

    # Download section
    st.markdown("#### 1. Download Assets")
    st.caption("Download videos and images from scraped ad snapshots")

    ads_without = asset_stats.get('ads_without_assets', 0)
    if ads_without > 0:
        st.info(f"{ads_without} ads need asset download")

    col_dl1, col_dl2, col_dl3 = st.columns([2, 1, 1])
    with col_dl1:
        download_limit = st.slider("Max ads to process", 10, 100, 50, key="dl_limit")
    with col_dl2:
        force_redownload = st.checkbox("Force re-download", key="force_dl",
                                       help="Delete existing assets and re-download (use if previous downloads failed)")
    with col_dl3:
        if st.button("📥 Download Assets", key="download_assets"):
            with st.spinner(f"Downloading assets from up to {download_limit} ads..."):
                try:
                    def run_download():
                        import asyncio
                        # Create service INSIDE async to avoid stale connection issues
                        async def _download():
                            from viraltracker.services.brand_research_service import BrandResearchService
                            service = BrandResearchService()
                            return await service.download_assets_for_competitor(
                                UUID(selected_competitor_id),
                                limit=download_limit,
                                force_redownload=force_redownload
                            )
                        return asyncio.run(_download())
                    result = run_download()

                    reason = result.get('reason')
                    if reason == 'no_ads':
                        st.warning("No ads to process. Scrape ads first.")
                    elif reason == 'all_have_assets':
                        st.success(f"All {result.get('total_ads', 0)} ads already have assets.")
                    elif result['videos_downloaded'] > 0 or result['images_downloaded'] > 0:
                        st.success(
                            f"Downloaded {result['videos_downloaded']} videos, "
                            f"{result['images_downloaded']} images from {result['ads_processed']} ads"
                        )
                        st.rerun()
                    else:
                        st.warning(f"No assets downloaded. {result.get('ads_skipped_no_urls', 0)} ads had no asset URLs.")
                except Exception as e:
                    st.error(f"Download failed: {e}")

    # Analysis section
    st.markdown("#### 2. Analyze Assets")
    st.caption("Run AI analysis to extract hooks, messaging, and persona signals")

    col_a1, col_a2, col_a3 = st.columns(3)

    with col_a1:
        st.markdown("**Video Analysis**")
        st.caption("Transcripts, hooks, persona signals")
        video_limit = st.number_input("Videos to analyze", 1, 20, 5, key="video_lim")
        if st.button("Analyze Videos", key="analyze_videos", disabled=asset_stats.get('videos', 0) == 0):
            with st.spinner(f"Analyzing up to {video_limit} videos (5-15 sec each)..."):
                try:
                    def run_video_analysis():
                        import asyncio
                        async def _analyze():
                            from viraltracker.services.brand_research_service import BrandResearchService
                            service = BrandResearchService()
                            return await service.analyze_videos_for_competitor(
                                UUID(selected_competitor_id),
                                limit=video_limit
                            )
                        return asyncio.run(_analyze())
                    results = run_video_analysis()
                    success = len([r for r in results if 'analysis' in r])
                    st.success(f"Analyzed {success} videos")
                    st.rerun()
                except Exception as e:
                    st.error(f"Video analysis failed: {e}")

    with col_a2:
        st.markdown("**Image Analysis**")
        st.caption("Visual style, hooks, copy")
        image_limit = st.number_input("Images to analyze", 1, 50, 20, key="image_lim")
        if st.button("Analyze Images", key="analyze_images", disabled=asset_stats.get('images', 0) == 0):
            with st.spinner(f"Analyzing up to {image_limit} images..."):
                try:
                    def run_image_analysis():
                        import asyncio
                        async def _analyze():
                            from viraltracker.services.brand_research_service import BrandResearchService
                            service = BrandResearchService()
                            return await service.analyze_images_for_competitor(
                                UUID(selected_competitor_id),
                                limit=image_limit
                            )
                        return asyncio.run(_analyze())
                    results = run_image_analysis()
                    success = len([r for r in results if 'analysis' in r])
                    st.success(f"Analyzed {success} images")
                    st.rerun()
                except Exception as e:
                    st.error(f"Image analysis failed: {e}")

    with col_a3:
        st.markdown("**Copy Analysis**")
        st.caption("Headlines, hooks, messaging")
        copy_limit = st.number_input("Ads to analyze", 1, 100, 50, key="copy_lim")
        if st.button("Analyze Copy", key="analyze_copy", disabled=asset_stats.get('total_ads', 0) == 0):
            with st.spinner(f"Analyzing copy from up to {copy_limit} ads..."):
                try:
                    def run_copy_analysis():
                        import asyncio
                        async def _analyze():
                            from viraltracker.services.brand_research_service import BrandResearchService
                            service = BrandResearchService()
                            return await service.analyze_copy_for_competitor(
                                UUID(selected_competitor_id),
                                limit=copy_limit
                            )
                        return asyncio.run(_analyze())
                    results = run_copy_analysis()
                    success = len([r for r in results if 'analysis' in r])
                    st.success(f"Analyzed {success} ad copies")
                    st.rerun()
                except Exception as e:
                    st.error(f"Copy analysis failed: {e}")

    # URL Review Queue
    st.markdown("---")
    st.markdown("### 📋 URL Review Queue")
    st.caption("Assign URLs from scraped ads to products. Create new products as needed.")

    service = get_competitor_service()
    unmatched_urls = service.get_unmatched_competitor_ad_urls(UUID(selected_competitor_id), limit=30)

    if not unmatched_urls:
        if stats.get('ads', 0) > 0:
            st.success("All ad URLs have been assigned to products!")
        else:
            st.info("Scrape ads first to discover URLs.")
    else:
        st.caption(f"Found {len(unmatched_urls)} unique unmatched URLs")

        for idx, url_data in enumerate(unmatched_urls):
            with st.container():
                col_url, col_assign = st.columns([3, 2])

                with col_url:
                    full_url = url_data['url']
                    st.markdown(f"[{full_url}]({full_url})")
                    st.caption(f"Found in {url_data['ad_count']} ads")

                with col_assign:
                    # Product assignment dropdown with "New Product" option
                    product_options = {"Select...": None, "➕ New Product": "__new__"}
                    product_options.update({p['name']: p['id'] for p in products})

                    # Use index for unique key
                    url_key = f"url_{idx}"
                    selected_option = st.selectbox(
                        "Assign to",
                        options=list(product_options.keys()),
                        key=f"assign_{url_key}",
                        label_visibility="collapsed"
                    )

                    if selected_option == "➕ New Product":
                        new_product_name = st.text_input(
                            "Product name",
                            key=f"new_prod_{url_key}",
                            placeholder="e.g., Competitor Product"
                        )
                        if st.button("Create & Assign", key=f"create_{url_key}", type="primary"):
                            if new_product_name:
                                try:
                                    # Create product
                                    new_product = service.create_competitor_product(
                                        competitor_id=UUID(selected_competitor_id),
                                        brand_id=UUID(selected_brand_id),
                                        name=new_product_name
                                    )
                                    # Assign ads to product
                                    result = service.assign_competitor_ads_to_product(
                                        competitor_id=UUID(selected_competitor_id),
                                        url_pattern=url_data['url'],
                                        competitor_product_id=UUID(new_product['id']),
                                        match_type="exact"
                                    )
                                    st.success(f"Created '{new_product_name}' and matched {result['matched']} ads!")
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Error: {e}")
                            else:
                                st.warning("Enter a product name")
                    elif selected_option and product_options[selected_option]:
                        if st.button("✓ Assign", key=f"confirm_{url_key}"):
                            try:
                                result = service.assign_competitor_ads_to_product(
                                    competitor_id=UUID(selected_competitor_id),
                                    url_pattern=url_data['url'],
                                    competitor_product_id=UUID(product_options[selected_option]),
                                    match_type="exact"
                                )
                                st.success(f"Matched {result['matched']} ads!")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Error: {e}")

                st.markdown("---")

    # Bulk matching section (if products and patterns exist)
    if products:
        matching_stats = service.get_competitor_matching_stats(UUID(selected_competitor_id))
        if matching_stats['configured_patterns'] > 0 and matching_stats['unmatched_ads'] > 0:
            st.markdown("### 🔄 Bulk URL Matching")
            st.caption(f"{matching_stats['configured_patterns']} URL patterns configured")
            if st.button("Run Bulk Matching", key="bulk_match"):
                with st.spinner("Matching ads to products using configured patterns..."):
                    try:
                        result = service.bulk_match_competitor_ads(UUID(selected_competitor_id))
                        st.success(
                            f"Matched: {result['matched']} | "
                            f"Unmatched: {result['unmatched']} | "
                            f"Total: {result['total']}"
                        )
                        st.rerun()
                    except Exception as e:
                        st.error(f"Matching failed: {e}")

# ----------------------------------------------------------------------------
# LANDING PAGES TAB
# ----------------------------------------------------------------------------
with tab_landing:
    st.markdown("### Landing Page Management")

    # Add manual landing page
    with st.expander("➕ Add Landing Page URL"):
        with st.form("add_landing_page"):
            lp_url = st.text_input("URL", placeholder="https://competitor.com/products/xyz")

            # Product assignment
            lp_product_options = {"Unassigned": None}
            lp_product_options.update({p['name']: p['id'] for p in products})

            lp_product = st.selectbox(
                "Assign to Product (optional)",
                options=list(lp_product_options.keys())
            )
            lp_product_id = lp_product_options[lp_product]

            if st.form_submit_button("Add Landing Page"):
                if not lp_url:
                    st.error("URL is required")
                else:
                    try:
                        db = get_supabase_client()
                        db.table("competitor_landing_pages").upsert({
                            "competitor_id": selected_competitor_id,
                            "brand_id": selected_brand_id,
                            "url": lp_url,
                            "is_manual": True,
                            "competitor_product_id": lp_product_id
                        }, on_conflict="competitor_id,url").execute()
                        st.success("Landing page added!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Failed: {e}")

    # List landing pages
    try:
        db = get_supabase_client()
        lp_query = db.table("competitor_landing_pages").select(
            "id, url, is_manual, competitor_product_id, scraped_at, analyzed_at"
        ).eq("competitor_id", selected_competitor_id)

        if selected_product_id:
            lp_query = lp_query.eq("competitor_product_id", selected_product_id)

        lp_result = lp_query.order("created_at", desc=True).limit(50).execute()
        landing_pages = lp_result.data or []

        if landing_pages:
            st.markdown(f"**{len(landing_pages)} landing page(s)**")

            for lp in landing_pages:
                col_url, col_status, col_product, col_actions = st.columns([3, 1, 1, 2])

                with col_url:
                    st.caption(lp['url'][:60] + "..." if len(lp['url']) > 60 else lp['url'])

                with col_status:
                    if lp.get('analyzed_at'):
                        st.caption("✅ Analyzed")
                    elif lp.get('scraped_at'):
                        st.caption("📥 Scraped")
                    else:
                        st.caption("⏳ Pending")

                with col_product:
                    if lp.get('competitor_product_id'):
                        prod = next((p for p in products if p['id'] == lp['competitor_product_id']), None)
                        st.caption(prod['name'] if prod else "—")
                    else:
                        st.caption("—")

                with col_actions:
                    col_scrape, col_analyze, col_del = st.columns(3)
                    with col_scrape:
                        if not lp.get('scraped_at'):
                            if st.button("📥", key=f"scrape_lp_{lp['id']}", help="Scrape"):
                                with st.spinner("Scraping..."):
                                    try:
                                        service = get_competitor_service()
                                        asyncio.run(service.scrape_and_save_landing_page(
                                            url=lp['url'],
                                            competitor_id=UUID(selected_competitor_id),
                                            brand_id=UUID(selected_brand_id),
                                            competitor_product_id=UUID(lp['competitor_product_id']) if lp.get('competitor_product_id') else None
                                        ))
                                        st.success("Scraped!")
                                        st.rerun()
                                    except Exception as e:
                                        st.error(f"Failed: {e}")
                    with col_analyze:
                        if lp.get('scraped_at') and not lp.get('analyzed_at'):
                            if st.button("🔍", key=f"analyze_lp_{lp['id']}", help="Analyze"):
                                with st.spinner("Analyzing..."):
                                    try:
                                        service = get_competitor_service()
                                        asyncio.run(service.analyze_landing_page(UUID(lp['id'])))
                                        st.success("Analyzed!")
                                        st.rerun()
                                    except Exception as e:
                                        st.error(f"Failed: {e}")
                    with col_del:
                        if st.button("🗑️", key=f"del_lp_{lp['id']}", help="Delete"):
                            try:
                                db.table("competitor_landing_pages").delete().eq(
                                    "id", lp['id']
                                ).execute()
                                st.rerun()
                            except Exception as e:
                                st.error(f"Failed: {e}")
        else:
            st.info("No landing pages found.")

    except Exception as e:
        st.error(f"Failed to load landing pages: {e}")

# ----------------------------------------------------------------------------
# AMAZON REVIEWS TAB
# ----------------------------------------------------------------------------
with tab_amazon:
    st.markdown("### Amazon Review Analysis")

    # Add Amazon URL
    with st.expander("➕ Add Amazon Product URL"):
        with st.form("add_amazon_url"):
            amazon_url = st.text_input(
                "Amazon Product URL",
                placeholder="https://www.amazon.com/dp/B0XXXXXXXX"
            )

            # Product assignment
            amz_product_options = {"Unassigned": None}
            amz_product_options.update({p['name']: p['id'] for p in products})

            amz_product = st.selectbox(
                "Assign to Product (optional)",
                options=list(amz_product_options.keys()),
                key="amz_product_select"
            )
            amz_product_id = amz_product_options[amz_product]

            if st.form_submit_button("Add Amazon URL"):
                if not amazon_url:
                    st.error("URL is required")
                else:
                    try:
                        # Extract ASIN from URL
                        import re
                        asin_match = re.search(r'/dp/([A-Z0-9]{10})', amazon_url)
                        if not asin_match:
                            asin_match = re.search(r'/product/([A-Z0-9]{10})', amazon_url)

                        if not asin_match:
                            st.error("Could not extract ASIN from URL")
                        else:
                            asin = asin_match.group(1)
                            db = get_supabase_client()
                            db.table("competitor_amazon_urls").upsert({
                                "competitor_id": selected_competitor_id,
                                "brand_id": selected_brand_id,
                                "amazon_url": amazon_url,
                                "asin": asin,
                                "competitor_product_id": amz_product_id
                            }, on_conflict="competitor_id,asin").execute()
                            st.success(f"Added Amazon URL (ASIN: {asin})")
                            st.rerun()
                    except Exception as e:
                        st.error(f"Failed: {e}")

    # List Amazon URLs
    try:
        db = get_supabase_client()
        amz_query = db.table("competitor_amazon_urls").select(
            "id, amazon_url, asin, competitor_product_id, last_scraped_at, total_reviews_scraped"
        ).eq("competitor_id", selected_competitor_id)

        if selected_product_id:
            amz_query = amz_query.eq("competitor_product_id", selected_product_id)

        amz_result = amz_query.execute()
        amazon_urls = amz_result.data or []

        if amazon_urls:
            st.markdown(f"**{len(amazon_urls)} Amazon product(s)**")

            for amz in amazon_urls:
                col_asin, col_reviews, col_product, col_actions = st.columns([2, 1, 1, 2])

                with col_asin:
                    st.markdown(f"**{amz['asin']}**")
                    st.caption(f"[View on Amazon](https://amazon.com/dp/{amz['asin']})")

                with col_reviews:
                    scraped = amz.get('total_reviews_scraped', 0) or 0
                    st.caption(f"{scraped} reviews")

                with col_product:
                    if amz.get('competitor_product_id'):
                        prod = next((p for p in products if p['id'] == amz['competitor_product_id']), None)
                        st.caption(prod['name'] if prod else "—")
                    else:
                        st.caption("—")

                with col_actions:
                    col_scrape, col_del = st.columns(2)
                    with col_scrape:
                        if st.button("📥 Scrape", key=f"scrape_amz_{amz['id']}", help="Scrape reviews"):
                            st.info("Review scraping will be integrated with AmazonReviewService")
                            # TODO: Integrate with Amazon review scraping
                    with col_del:
                        if st.button("🗑️", key=f"del_amz_{amz['id']}", help="Delete"):
                            try:
                                db.table("competitor_amazon_urls").delete().eq(
                                    "id", amz['id']
                                ).execute()
                                st.rerun()
                            except Exception as e:
                                st.error(f"Failed: {e}")
        else:
            st.info("No Amazon products added.")

    except Exception as e:
        st.error(f"Failed to load Amazon URLs: {e}")

    # Amazon Review Analysis Results
    if stats.get('has_amazon_analysis'):
        st.markdown("---")
        st.markdown("### Analysis Results")

        try:
            db = get_supabase_client()
            analysis_result = db.table("competitor_amazon_review_analysis").select(
                "*"
            ).eq("competitor_id", selected_competitor_id).single().execute()

            if analysis_result.data:
                analysis = analysis_result.data

                tab_pain, tab_desires, tab_language, tab_quotes = st.tabs([
                    "Pain Points", "Desires", "Language", "Quotes"
                ])

                with tab_pain:
                    pain_points = analysis.get('pain_points', {})
                    if isinstance(pain_points, dict) and pain_points.get('insights'):
                        for insight in pain_points['insights'][:10]:
                            st.markdown(f"• {insight}")
                    else:
                        st.info("No pain points extracted")

                with tab_desires:
                    desires = analysis.get('desires', {})
                    if isinstance(desires, dict) and desires.get('insights'):
                        for insight in desires['insights'][:10]:
                            st.markdown(f"• {insight}")
                    else:
                        st.info("No desires extracted")

                with tab_language:
                    language = analysis.get('language_patterns', {})
                    if isinstance(language, dict):
                        if language.get('positive_phrases'):
                            st.markdown("**Positive Phrases:**")
                            for phrase in language['positive_phrases'][:5]:
                                st.caption(f"• \"{phrase}\"")
                        if language.get('negative_phrases'):
                            st.markdown("**Negative Phrases:**")
                            for phrase in language['negative_phrases'][:5]:
                                st.caption(f"• \"{phrase}\"")
                    else:
                        st.info("No language patterns extracted")

                with tab_quotes:
                    st.markdown("**Top Positive Quotes:**")
                    for quote in (analysis.get('top_positive_quotes') or [])[:3]:
                        st.caption(f"💬 \"{quote}\"")

                    st.markdown("**Top Negative Quotes:**")
                    for quote in (analysis.get('top_negative_quotes') or [])[:3]:
                        st.caption(f"💬 \"{quote}\"")

        except Exception as e:
            st.error(f"Failed to load analysis: {e}")

# ----------------------------------------------------------------------------
# PERSONA TAB
# ----------------------------------------------------------------------------
with tab_persona:
    st.markdown("### Competitor Persona Synthesis")

    st.info("""
    Persona synthesis aggregates insights from:
    - Competitor ads (if analyzed)
    - Landing pages (if analyzed)
    - Amazon reviews (if analyzed)

    This creates a 4D customer persona for the competitor's target audience.
    """)

    # Level selection
    if products:
        persona_level = st.radio(
            "Persona Level",
            options=["Competitor-level", "Product-level"],
            help="Competitor-level creates one persona for all products. Product-level creates a persona for the selected product."
        )
    else:
        persona_level = "Competitor-level"

    # Show selected scope
    if persona_level == "Product-level" and selected_product_id:
        st.caption(f"Will synthesize persona for: {selected_product_name}")
    else:
        st.caption(f"Will synthesize persona for: {competitor['name']} (all products)")

    # Initialize session state for preview persona
    if 'competitor_persona_preview' not in st.session_state:
        st.session_state.competitor_persona_preview = None

    if st.button("🧠 Synthesize Persona", type="primary"):
        with st.spinner("Synthesizing persona from collected data..."):
            try:
                from viraltracker.services.persona_service import PersonaService
                persona_service = PersonaService()

                # Determine product_id based on level
                comp_product_id = None
                if persona_level == "Product-level" and selected_product_id:
                    comp_product_id = UUID(selected_product_id)

                # Run synthesis - store in session state for preview (don't save yet)
                persona = asyncio.run(persona_service.synthesize_competitor_persona(
                    competitor_id=UUID(selected_competitor_id),
                    brand_id=UUID(selected_brand_id),
                    competitor_product_id=comp_product_id
                ))

                # Store for preview
                st.session_state.competitor_persona_preview = persona
                st.success(f"Persona synthesized: {persona.name} - Review below and save if satisfied")
                st.rerun()

            except ValueError as e:
                st.warning(str(e))
            except Exception as e:
                st.error(f"Synthesis failed: {e}")

    # Show preview persona if just synthesized
    if st.session_state.competitor_persona_preview:
        preview = st.session_state.competitor_persona_preview

        st.markdown("---")
        st.markdown("### 🆕 New Persona (Preview)")
        st.warning("This persona has not been saved yet. Review and click Save to keep it.")

        # Header with confidence
        col_header, col_conf, col_actions = st.columns([2, 1, 1])
        with col_header:
            st.markdown(f"## {preview.name}")
        with col_conf:
            confidence = preview.confidence_score or 0
            if confidence:
                st.metric("Confidence", f"{confidence:.0%}")
            else:
                st.metric("Confidence", "N/A")
        with col_actions:
            col_save, col_discard = st.columns(2)
            with col_save:
                if st.button("✅ Save", type="primary", key="save_preview"):
                    from viraltracker.services.persona_service import PersonaService
                    persona_service = PersonaService()
                    persona_id = persona_service.create_persona(preview)
                    st.session_state.competitor_persona_preview = None
                    st.success(f"Persona saved!")
                    st.rerun()
            with col_discard:
                if st.button("❌ Discard", key="discard_preview"):
                    st.session_state.competitor_persona_preview = None
                    st.rerun()

        if preview.snapshot:
            st.info(preview.snapshot)

        # Demographics summary
        if preview.demographics:
            demo = preview.demographics
            demo_parts = []
            if hasattr(demo, 'age_range') and demo.age_range:
                demo_parts.append(demo.age_range)
            if hasattr(demo, 'gender') and demo.gender and demo.gender != 'any':
                demo_parts.append(demo.gender)
            if hasattr(demo, 'location') and demo.location:
                demo_parts.append(demo.location)
            if hasattr(demo, 'income_level') and demo.income_level:
                demo_parts.append(demo.income_level)
            if demo_parts:
                st.markdown(f"**Demographics:** {', '.join(demo_parts)}")

        # Tabbed preview
        tabs = st.tabs(["Pain & Desires", "Identity", "Social", "Worldview"])

        with tabs[0]:
            col_pain, col_desire = st.columns(2)
            with col_pain:
                st.markdown("#### Pain Points")
                if preview.pain_points:
                    for category in ['emotional', 'social', 'functional']:
                        items = getattr(preview.pain_points, category, [])
                        if items:
                            st.markdown(f"**{category.title()}:**")
                            for pp in items[:3]:
                                st.markdown(f"- {pp}")
            with col_desire:
                st.markdown("#### Desires")
                if preview.desires:
                    for category, instances in preview.desires.items():
                        if instances:
                            st.markdown(f"**{category.replace('_', ' ').title()}:**")
                            for inst in instances[:2]:
                                text = inst.text if hasattr(inst, 'text') else str(inst)
                                st.markdown(f"- {text}")

            if preview.transformation_map:
                st.markdown("#### Transformation")
                col_b, col_a = st.columns(2)
                with col_b:
                    st.markdown("**Before:**")
                    for b in (preview.transformation_map.before or [])[:3]:
                        st.markdown(f"- {b}")
                with col_a:
                    st.markdown("**After:**")
                    for a in (preview.transformation_map.after or [])[:3]:
                        st.markdown(f"- {a}")

        with tabs[1]:
            if preview.self_narratives:
                st.markdown("#### Self-Narratives")
                for n in preview.self_narratives[:4]:
                    st.markdown(f'- "{n}"')
            col_c, col_d = st.columns(2)
            with col_c:
                st.markdown("**Current Self-Image:**")
                st.write(preview.current_self_image or "N/A")
            with col_d:
                st.markdown("**Desired Self-Image:**")
                st.write(preview.desired_self_image or "N/A")

        with tabs[2]:
            if preview.social_relations:
                col_pos, col_neg = st.columns(2)
                with col_pos:
                    for label, attr in [("Want to Impress", "want_to_impress"), ("Protect", "love_loyalty")]:
                        items = getattr(preview.social_relations, attr, [])
                        if items:
                            st.markdown(f"**{label}:**")
                            for item in items[:3]:
                                st.markdown(f"- {item}")
                with col_neg:
                    for label, attr in [("Fear Judgment From", "fear_judged_by"), ("Distance From", "distance_from")]:
                        items = getattr(preview.social_relations, attr, [])
                        if items:
                            st.markdown(f"**{label}:**")
                            for item in items[:3]:
                                st.markdown(f"- {item}")

        with tabs[3]:
            if preview.worldview:
                st.markdown("#### Worldview")
                st.write(preview.worldview)
            if preview.core_values:
                st.markdown("**Core Values:**")
                st.write(", ".join(preview.core_values[:5]))

    # Show existing persona if any
    try:
        db = get_supabase_client()
        persona_query = db.table("personas_4d").select("*").eq(
            "competitor_id", selected_competitor_id
        )

        if persona_level == "Product-level" and selected_product_id:
            persona_query = persona_query.eq("competitor_product_id", selected_product_id)
        else:
            persona_query = persona_query.is_("competitor_product_id", "null")

        persona_result = persona_query.execute()

        if persona_result.data:
            st.markdown("---")
            st.markdown("### 💾 Saved Persona")
            persona = persona_result.data[0]

            # Header with name and confidence
            col_header, col_conf = st.columns([3, 1])
            with col_header:
                st.markdown(f"## {persona.get('name', 'Unnamed')}")
                st.caption(f"Created: {persona.get('created_at', 'Unknown')}")
            with col_conf:
                confidence = persona.get('confidence_score', 0)
                if confidence:
                    st.metric("Confidence", f"{confidence:.0%}")

            if persona.get('snapshot'):
                st.info(persona['snapshot'])

            # Demographics summary
            demo = persona.get('demographics', {})
            if demo:
                demo_parts = []
                if demo.get('age_range'):
                    demo_parts.append(demo['age_range'])
                if demo.get('gender') and demo.get('gender') != 'any':
                    demo_parts.append(demo['gender'])
                if demo.get('location'):
                    demo_parts.append(demo['location'])
                if demo.get('income_level'):
                    demo_parts.append(demo['income_level'])
                if demo_parts:
                    st.markdown(f"**Demographics:** {', '.join(demo_parts)}")

            # Tabbed display like Brand Research
            tabs = st.tabs(["Pain & Desires", "Identity", "Social", "Worldview", "Barriers", "Purchase"])

            with tabs[0]:  # Pain & Desires
                col_pain, col_desire = st.columns(2)

                with col_pain:
                    st.markdown("#### Pain Points")
                    pain_points = persona.get('pain_points', {})
                    for category in ['emotional', 'social', 'functional']:
                        items = pain_points.get(category, [])
                        if items:
                            st.markdown(f"**{category.title()}:**")
                            for pp in items[:4]:
                                st.markdown(f"- {pp}")

                with col_desire:
                    st.markdown("#### Desires")
                    desires = persona.get('desires', {})
                    for category, items in desires.items():
                        if items:
                            st.markdown(f"**{category.replace('_', ' ').title()}:**")
                            for item in items[:3]:
                                text = item if isinstance(item, str) else item.get('text', str(item))
                                st.markdown(f"- {text}")

                # Transformation
                transformation = persona.get('transformation_map', {})
                if transformation:
                    st.markdown("#### Transformation")
                    col_before, col_after = st.columns(2)
                    with col_before:
                        st.markdown("**Before:**")
                        for b in transformation.get('before', [])[:4]:
                            st.markdown(f"- {b}")
                    with col_after:
                        st.markdown("**After:**")
                        for a in transformation.get('after', [])[:4]:
                            st.markdown(f"- {a}")

            with tabs[1]:  # Identity
                st.markdown("#### Self-Narratives")
                narratives = persona.get('self_narratives', [])
                for n in narratives[:5]:
                    st.markdown(f'- "{n}"')

                col_curr, col_des = st.columns(2)
                with col_curr:
                    st.markdown("**Current Self-Image:**")
                    st.write(persona.get('current_self_image', 'N/A'))
                with col_des:
                    st.markdown("**Desired Self-Image:**")
                    st.write(persona.get('desired_self_image', 'N/A'))

                artifacts = persona.get('identity_artifacts', [])
                if artifacts:
                    st.markdown("**Identity Artifacts:**")
                    st.write(", ".join(artifacts[:8]))

            with tabs[2]:  # Social
                social = persona.get('social_relations', {})
                col_pos, col_neg = st.columns(2)

                with col_pos:
                    for label, key in [("Admire", "admire"), ("Want to Impress", "want_to_impress"),
                                       ("Want to Belong", "want_to_belong"), ("Protect", "love_loyalty")]:
                        items = social.get(key, [])
                        if items:
                            st.markdown(f"**{label}:**")
                            for item in items[:3]:
                                st.markdown(f"- {item}")

                with col_neg:
                    for label, key in [("Fear Judgment From", "fear_judged_by"), ("Dislike", "dislike_animosity"),
                                       ("Compare To", "compared_to"), ("Distance From", "distance_from")]:
                        items = social.get(key, [])
                        if items:
                            st.markdown(f"**{label}:**")
                            for item in items[:3]:
                                st.markdown(f"- {item}")

            with tabs[3]:  # Worldview
                if persona.get('worldview'):
                    st.markdown("#### Worldview")
                    st.write(persona.get('worldview'))

                values = persona.get('core_values', [])
                if values:
                    st.markdown("**Core Values:**")
                    st.write(", ".join(values[:6]))

                beliefs = persona.get('beliefs_assumptions', [])
                if beliefs:
                    st.markdown("**Beliefs:**")
                    for b in beliefs[:4]:
                        st.markdown(f"- {b}")

            with tabs[4]:  # Barriers
                barriers = persona.get('purchase_barriers', {})
                for category in ['trust', 'risk', 'inertia', 'complexity']:
                    items = barriers.get(category, [])
                    if items:
                        st.markdown(f"**{category.title()} Barriers:**")
                        for item in items[:3]:
                            st.markdown(f"- {item}")

                objections = persona.get('objections', [])
                if objections:
                    st.markdown("**Common Objections:**")
                    for obj in objections[:4]:
                        st.markdown(f"- {obj}")

            with tabs[5]:  # Purchase
                triggers = persona.get('activation_events', [])
                if triggers:
                    st.markdown("**Activation Events:**")
                    for t in triggers[:4]:
                        st.markdown(f"- {t}")

                failed = persona.get('failed_solutions', [])
                if failed:
                    st.markdown("**Failed Solutions:**")
                    for f in failed[:4]:
                        st.markdown(f"- {f}")

                messaging = persona.get('messaging_themes', [])
                if messaging:
                    st.markdown("**Messaging Themes:**")
                    for m in messaging[:4]:
                        st.markdown(f"- {m}")

    except Exception as e:
        pass  # No persona yet

# ============================================================================
# HELP SECTION
# ============================================================================

with st.expander("ℹ️ Help"):
    st.markdown("""
    ### Research Workflow

    **1. Add Products** (on Competitors page)
    - Add products the competitor sells
    - Add variants (flavors, sizes) if applicable

    **2. Configure URL Patterns** (on URL Mapping page)
    - Add URL patterns for each product
    - This enables automatic ad-to-product matching

    **3. Scrape Ads**
    - Configure the Ad Library URL on the Competitors page
    - Click "Scrape Ads" to collect competitor ads

    **4. Match Ads to Products**
    - Run bulk matching to link ads to products
    - Manually assign unmatched ads if needed

    **5. Add Landing Pages**
    - Add landing page URLs manually
    - Or wait for them to be extracted from ads
    - Scrape and analyze for messaging insights

    **6. Add Amazon Products**
    - Add Amazon product URLs
    - Scrape reviews for customer voice data
    - Analyze for pain points, desires, language

    **7. Synthesize Persona**
    - Choose competitor-level or product-level
    - Generates a 4D persona from all collected data
    """)
