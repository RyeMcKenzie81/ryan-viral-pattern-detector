"""
URL Mapping - Product identification for Facebook ads.

This page allows users to:
- Configure landing page URLs for each product (brand or competitor)
- Run bulk URL matching on scraped ads
- Review and assign unmatched URLs to products
- View matching statistics
"""

import streamlit as st
from datetime import datetime
from typing import Optional
from uuid import UUID

# Page config
st.set_page_config(
    page_title="URL Mapping",
    page_icon="🔗",
    layout="wide"
)

# Authentication
from viraltracker.ui.auth import require_auth
require_auth()

# Initialize session state
if 'matching_in_progress' not in st.session_state:
    st.session_state.matching_in_progress = False
if 'url_mapping_mode' not in st.session_state:
    st.session_state.url_mapping_mode = "Brand Products"


def get_supabase_client():
    """Get Supabase client."""
    from viraltracker.core.database import get_supabase_client
    return get_supabase_client()


def get_product_url_service():
    """Get ProductURLService instance."""
    from viraltracker.services.product_url_service import ProductURLService
    return ProductURLService()


def get_competitor_service():
    """Get CompetitorService instance with tracking enabled."""
    from viraltracker.services.competitor_service import CompetitorService
    from viraltracker.ui.utils import setup_tracking_context
    service = CompetitorService()
    setup_tracking_context(service)
    return service


def get_brands():
    """Fetch all brands."""
    try:
        db = get_supabase_client()
        result = db.table("brands").select("id, name").order("name").execute()
        return result.data or []
    except Exception as e:
        st.error(f"Failed to fetch brands: {e}")
        return []


def get_products_for_brand(brand_id: str):
    """Fetch products for a brand."""
    try:
        db = get_supabase_client()
        result = db.table("products").select("id, name").eq("brand_id", brand_id).order("name").execute()
        return result.data or []
    except Exception as e:
        st.error(f"Failed to fetch products: {e}")
        return []


def get_sample_ads(ad_ids: list, limit: int = 3):
    """Get sample ad details for preview."""
    if not ad_ids:
        return []
    try:
        db = get_supabase_client()
        result = db.table("facebook_ads")\
            .select("id, ad_creative_body, snapshot")\
            .in_("id", ad_ids[:limit])\
            .execute()
        return result.data or []
    except:
        return []


# ============================================================
# Main Page
# ============================================================

st.title("🔗 URL Mapping")
st.caption("Map landing page URLs to products for ad identification")

# Brand selector (uses shared utility for cross-page persistence)
from viraltracker.ui.utils import render_brand_selector
brand_id = render_brand_selector(key="url_mapping_brand_selector")

if not brand_id:
    st.stop()

# Mode toggle: Brand Products vs Competitor Products
st.markdown("---")
mode_col1, mode_col2 = st.columns([1, 3])
with mode_col1:
    mode = st.radio(
        "Mode",
        options=["Brand Products", "Competitor Products"],
        index=0 if st.session_state.url_mapping_mode == "Brand Products" else 1,
        horizontal=True,
        label_visibility="collapsed"
    )
    st.session_state.url_mapping_mode = mode

# ============================================================
# COMPETITOR PRODUCTS MODE
# ============================================================
if mode == "Competitor Products":
    competitor_service = get_competitor_service()

    # Get competitors for this brand
    competitors = competitor_service.get_competitors_for_brand(UUID(brand_id))

    if not competitors:
        st.warning("No competitors found for this brand. Add competitors on the Competitors page first.")
        st.stop()

    # Competitor selector
    competitor_options = {c['name']: c['id'] for c in competitors}
    selected_competitor_name = st.selectbox(
        "Select Competitor",
        options=list(competitor_options.keys()),
        index=0
    )

    if not selected_competitor_name:
        st.stop()

    competitor_id = UUID(competitor_options[selected_competitor_name])

    # Get competitor products
    competitor_products = competitor_service.get_competitor_products(competitor_id, include_variants=False)

    if not competitor_products:
        st.info(f"No products found for {selected_competitor_name}. Add products on the Competitors page first.")
        st.stop()

    # Statistics Section
    st.markdown("---")
    st.subheader("📊 Matching Statistics")

    stats = competitor_service.get_competitor_matching_stats(competitor_id)

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Ads", stats['total_ads'])
    with col2:
        st.metric("Matched", stats['matched_ads'], delta=f"{stats['match_percentage']}%")
    with col3:
        st.metric("Unmatched", stats['unmatched_ads'])
    with col4:
        st.metric("URL Patterns", stats['configured_patterns'])

    # Bulk match button
    if stats['configured_patterns'] > 0 and stats['unmatched_ads'] > 0:
        if st.button("🔄 Run Bulk URL Matching", disabled=st.session_state.matching_in_progress, help="Match competitor ads to products using configured patterns"):
            st.session_state.matching_in_progress = True
            with st.spinner("Matching competitor ads to products..."):
                try:
                    result = competitor_service.bulk_match_competitor_ads(competitor_id, limit=500)
                    st.success(f"Matched {result['matched']} ads, {result['unmatched']} unmatched, {result['failed']} failed")
                    st.session_state.matching_in_progress = False
                    st.rerun()
                except Exception as e:
                    st.error(f"Matching failed: {e}")
                    st.session_state.matching_in_progress = False
    elif stats['configured_patterns'] == 0:
        st.info("Add URL patterns to products below, then run bulk matching.")

    # Product URL Patterns
    st.markdown("---")
    st.subheader("🏷️ Competitor Product URL Patterns")

    product_tabs = st.tabs([p['name'] for p in competitor_products])

    for i, (tab, product) in enumerate(zip(product_tabs, competitor_products)):
        with tab:
            product_id = UUID(product['id'])
            urls = competitor_service.get_competitor_product_urls(product_id)

            # Display existing URLs
            if urls:
                for url in urls:
                    col1, col2, col3 = st.columns([4, 1, 1])
                    with col1:
                        badge = "🏠" if url.get('is_primary') else ""
                        st.text(f"{badge} {url['url_pattern']}")
                    with col2:
                        st.caption(url['match_type'])
                    with col3:
                        if st.button("🗑️", key=f"comp_del_{url['id']}", help="Delete"):
                            competitor_service.delete_competitor_product_url(UUID(url['id']))
                            st.rerun()
            else:
                st.info("No URL patterns configured for this product.")

            # Add new URL form
            with st.expander("➕ Add URL Pattern"):
                new_url = st.text_input(
                    "URL Pattern",
                    key=f"comp_url_{product['id']}",
                    placeholder="e.g., competitor.com/products/their-product"
                )
                col1, col2, col3 = st.columns(3)
                with col1:
                    match_type = st.selectbox(
                        "Match Type",
                        options=['contains', 'prefix', 'exact', 'regex'],
                        index=0,
                        key=f"comp_type_{product['id']}",
                        help="contains: URL includes pattern, prefix: URL starts with, exact: exact match, regex: regular expression"
                    )
                with col2:
                    is_primary = st.checkbox("Primary landing page", key=f"comp_primary_{product['id']}")
                with col3:
                    if st.button("Add", key=f"comp_add_{product['id']}"):
                        if new_url:
                            competitor_service.add_competitor_product_url(
                                competitor_product_id=product_id,
                                url_pattern=new_url,
                                match_type=match_type,
                                is_primary=is_primary
                            )
                            st.success("URL pattern added!")
                            st.rerun()
                        else:
                            st.warning("Please enter a URL pattern")

    # Help section for competitor mode
    with st.expander("ℹ️ How Competitor URL Mapping Works"):
        st.markdown("""
        ### Competitor URL Matching

        1. **Add URL Patterns**: Configure URL patterns for each competitor product that identify their landing pages.

        2. **Run Bulk Matching**: Click "Run Bulk URL Matching" to automatically tag competitor ads with their products based on URL patterns.

        3. **Pattern Types**:
           - `contains`: URL includes the pattern (most flexible, recommended)
           - `prefix`: URL starts with the pattern
           - `exact`: URL matches exactly
           - `regex`: Regular expression matching

        ### Example Patterns

        | Product | Pattern | Type |
        |---------|---------|------|
        | Competitor Collagen | `competitor.com/products/collagen` | contains |
        | Competitor Vitamin | `competitor.com/vitamin` | prefix |
        """)

    st.stop()  # Don't show brand products section when in competitor mode

# ============================================================
# BRAND PRODUCTS MODE (Original functionality)
# ============================================================

# Get service and products
service = get_product_url_service()
products = get_products_for_brand(brand_id)

if not products:
    st.warning("No products found for this brand. Please create products first.")
    st.stop()

# ============================================================
# Statistics Section
# ============================================================

st.markdown("---")
st.subheader("📊 Matching Statistics")

stats = service.get_matching_stats(brand_id)

col1, col2, col3, col4 = st.columns(4)
with col1:
    st.metric("Total Ads", stats['total_ads'])
with col2:
    st.metric("Matched", stats['matched_ads'], delta=f"{stats['match_percentage']}%")
with col3:
    st.metric("Unmatched", stats['unmatched_ads'])
with col4:
    st.metric("URLs to Review", stats['pending_review_urls'])

# Action buttons
col1, col2 = st.columns(2)

with col1:
    if st.button("🔍 Discover URLs from Ads", disabled=st.session_state.matching_in_progress, help="Scan ads and extract all unique URLs for review"):
        st.session_state.matching_in_progress = True
        with st.spinner("Discovering URLs from ads..."):
            try:
                result = service.discover_urls_from_ads(brand_id, limit=1000)
                st.success(f"Found {result['discovered']} unique URLs: {result['new']} new, {result['existing']} already in queue")
                st.session_state.matching_in_progress = False
                st.rerun()
            except Exception as e:
                st.error(f"Discovery failed: {e}")
                st.session_state.matching_in_progress = False

with col2:
    if stats['pending_review_urls'] == 0 and stats['configured_patterns'] > 0:
        if st.button("🔄 Run Bulk URL Matching", disabled=st.session_state.matching_in_progress, help="Match ads to products using configured patterns"):
            st.session_state.matching_in_progress = True
            with st.spinner("Matching ads to products..."):
                try:
                    result = service.bulk_match_ads(brand_id, limit=500)
                    st.success(f"Matched {result['matched']} ads, {result['unmatched']} unmatched, {result['failed']} failed")
                    st.session_state.matching_in_progress = False
                    st.rerun()
                except Exception as e:
                    st.error(f"Matching failed: {e}")
                    st.session_state.matching_in_progress = False
    elif stats['pending_review_urls'] > 0:
        st.info("👆 Assign pending URLs to products first, then run bulk matching")

# ============================================================
# Product URL Management
# ============================================================

st.markdown("---")
st.subheader("🏷️ Product URL Patterns")

# Tabs for each product
product_tabs = st.tabs([p['name'] for p in products])

for i, (tab, product) in enumerate(zip(product_tabs, products)):
    with tab:
        product_id = product['id']
        urls = service.get_product_urls(product_id)

        # Display existing URLs
        if urls:
            for url in urls:
                col1, col2, col3 = st.columns([4, 1, 1])
                with col1:
                    badge = "🏠" if url.get('is_primary') else ""
                    st.text(f"{badge} {url['url_pattern']}")
                with col2:
                    st.caption(url['match_type'])
                with col3:
                    if st.button("🗑️", key=f"del_{url['id']}", help="Delete"):
                        service.delete_product_url(url['id'])
                        st.rerun()
        else:
            st.info("No URL patterns configured for this product.")

        # Add new URL form
        with st.expander("➕ Add URL Pattern"):
            new_url = st.text_input(
                "URL Pattern",
                key=f"url_{product_id}",
                placeholder="e.g., mywonderpaws.com/products/plaque"
            )
            col1, col2, col3 = st.columns(3)
            with col1:
                match_type = st.selectbox(
                    "Match Type",
                    options=['contains', 'prefix', 'exact', 'regex'],
                    index=0,
                    key=f"type_{product_id}",
                    help="contains: URL includes pattern, prefix: URL starts with, exact: exact match, regex: regular expression"
                )
            with col2:
                is_primary = st.checkbox("Primary landing page", key=f"primary_{product_id}")
            with col3:
                if st.button("Add", key=f"add_{product_id}"):
                    if new_url:
                        service.add_product_url(
                            product_id=product_id,
                            url_pattern=new_url,
                            match_type=match_type,
                            is_primary=is_primary
                        )
                        st.success("URL pattern added!")
                        st.rerun()
                    else:
                        st.warning("Please enter a URL pattern")

# ============================================================
# URL Review Queue
# ============================================================

st.markdown("---")
st.subheader("📋 URL Review Queue")

pending_urls = service.get_review_queue(brand_id, status='pending', limit=20)

if not pending_urls:
    st.success("No URLs pending review! All ads are matched or you haven't run URL discovery yet.")
else:
    st.caption(f"Found {len(pending_urls)} unmatched URLs. Assign them to products, mark as brand-level, or ignore.")

    for url_record in pending_urls:
        with st.container():
            col1, col2 = st.columns([3, 1])

            with col1:
                st.markdown(f"**{url_record['url']}**")
                st.caption(f"Found in {url_record['occurrence_count']} ads")

                # Show sample ads using this URL
                sample_ads = get_sample_ads(url_record.get('sample_ad_ids', []))
                if sample_ads:
                    with st.expander("Preview sample ads"):
                        for ad in sample_ads:
                            body = ad.get('ad_creative_body', '')[:200]
                            st.text(f"• {body}..." if body else "• (No text content)")

            with col2:
                # Product assignment dropdown with "New Product" option
                product_options = {"Select action...": None, "➕ New Product": "__new__"}
                product_options.update({p['name']: p['id'] for p in products})

                selected_option = st.selectbox(
                    "Assign to",
                    options=list(product_options.keys()),
                    key=f"assign_{url_record['id']}",
                    label_visibility="collapsed"
                )

                # Show new product name input if "New Product" selected
                if selected_option == "➕ New Product":
                    new_product_name = st.text_input(
                        "Product name",
                        key=f"new_product_name_{url_record['id']}",
                        placeholder="e.g., Plaque Defense"
                    )
                    if st.button("Create & Assign", key=f"create_{url_record['id']}", type="primary"):
                        if new_product_name:
                            try:
                                # Create product and assign URL
                                new_product = service.create_product(
                                    brand_id=brand_id,
                                    name=new_product_name
                                )
                                service.assign_url_to_product(
                                    queue_id=url_record['id'],
                                    product_id=new_product['id'],
                                    add_as_pattern=True
                                )
                                st.success(f"Created '{new_product_name}' and assigned URL!")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Error: {e}")
                        else:
                            st.warning("Enter a product name")
                else:
                    # Standard buttons for existing product or other actions
                    col_a, col_b, col_c, col_d, col_e = st.columns(5)
                    with col_a:
                        if st.button("✓", key=f"confirm_{url_record['id']}", help="Assign to product"):
                            if selected_option and product_options[selected_option] and product_options[selected_option] != "__new__":
                                service.assign_url_to_product(
                                    queue_id=url_record['id'],
                                    product_id=product_options[selected_option],
                                    add_as_pattern=True
                                )
                                st.success("Assigned!")
                                st.rerun()
                            else:
                                st.warning("Select a product first")
                    with col_b:
                        if st.button("🏠", key=f"brand_{url_record['id']}", help="Brand-level (homepage, about)"):
                            service.mark_as_brand_level(url_record['id'])
                            st.rerun()
                    with col_c:
                        if st.button("📁", key=f"collection_{url_record['id']}", help="Collection page"):
                            service.mark_as_collection(url_record['id'])
                            st.rerun()
                    with col_d:
                        if st.button("📱", key=f"social_{url_record['id']}", help="Social media (IG, TikTok, YT)"):
                            service.mark_as_social(url_record['id'])
                            st.rerun()
                    with col_e:
                        if st.button("✗", key=f"ignore_{url_record['id']}", help="Ignore (external, other)"):
                            service.ignore_url(url_record['id'], ignore_reason="not_relevant")
                            st.rerun()

            st.markdown("---")

# ============================================================
# Help Section
# ============================================================

with st.expander("ℹ️ How URL Mapping Works"):
    st.markdown("""
    ### URL Matching Process

    1. **Discover URLs**: Click "Discover URLs from Ads" to scan all scraped ads and find unique landing page URLs.

    2. **Review & Assign**: For each discovered URL, you can:
       - **✓ Assign to Product**: Link URL to an existing product (also adds as matching pattern)
       - **➕ New Product**: Create a new product and assign the URL to it
       - **🏠 Brand-level**: Homepage, about pages - brand-wide but not product-specific
       - **📁 Collection**: Collection/category pages featuring multiple products
       - **📱 Social**: Social media profiles (Instagram, TikTok, YouTube, Facebook)
       - **✗ Ignore**: Skip URLs that aren't relevant (external sites, other)

    3. **Bulk Match**: Once URL patterns are configured, "Run Bulk URL Matching" will automatically tag all ads with their products.

    ### URL Categories

    | URL Type | Action | Example |
    |----------|--------|---------|
    | Product page | ✓ Assign to product | `/products/plaque-defense` |
    | Product landing | ➕ New Product | `/pages/dog-itch-relief` |
    | Collection page | 📁 Collection | `/collections/dental-care` |
    | Homepage | 🏠 Brand-level | `/` |
    | About/Info page | 🏠 Brand-level | `/pages/about-us` |
    | Instagram | 📱 Social | `instagram.com/brand` |
    | TikTok | 📱 Social | `tiktok.com/@brand` |
    | YouTube | 📱 Social | `youtube.com/@brand` |
    | External link | ✗ Ignore | `bit.ly/xyz`, other |

    ### Pattern Types

    - `contains`: URL includes the pattern (most flexible, recommended)
    - `prefix`: URL starts with the pattern
    - `exact`: URL matches exactly
    - `regex`: Regular expression matching
    """)
