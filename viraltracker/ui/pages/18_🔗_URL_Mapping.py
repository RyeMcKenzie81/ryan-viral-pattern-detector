"""
URL Mapping - Product identification for Facebook ads.

This page allows users to:
- Configure landing page URLs for each product
- Run bulk URL matching on scraped ads
- Review and assign unmatched URLs to products
- View matching statistics
- Add Amazon product URLs for review scraping
"""

import streamlit as st
from datetime import datetime
from typing import Optional

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
if 'selected_brand_id' not in st.session_state:
    st.session_state.selected_brand_id = None
if 'matching_in_progress' not in st.session_state:
    st.session_state.matching_in_progress = False
if 'amazon_scraping' not in st.session_state:
    st.session_state.amazon_scraping = False


def get_supabase_client():
    """Get Supabase client."""
    from viraltracker.core.database import get_supabase_client
    return get_supabase_client()


def get_product_url_service():
    """Get ProductURLService instance."""
    from viraltracker.services.product_url_service import ProductURLService
    return ProductURLService()


def get_amazon_review_service():
    """Get AmazonReviewService instance."""
    from viraltracker.services.amazon_review_service import AmazonReviewService
    return AmazonReviewService()


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

# Brand selector
brands = get_brands()
if not brands:
    st.warning("No brands found. Please create a brand first.")
    st.stop()

brand_options = {b['name']: b['id'] for b in brands}
selected_brand_name = st.selectbox(
    "Select Brand",
    options=list(brand_options.keys()),
    index=0 if brands else None
)

if selected_brand_name:
    brand_id = brand_options[selected_brand_name]
    st.session_state.selected_brand_id = brand_id
else:
    st.stop()

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
# Amazon Reviews Section
# ============================================================

st.markdown("---")
st.subheader("🛒 Amazon Product Reviews")
st.caption("Add Amazon product URLs to scrape customer reviews for persona research")

amazon_service = get_amazon_review_service()

# Get existing Amazon URLs for this brand
amazon_urls = amazon_service.get_amazon_urls_for_brand(brand_id)

# Display existing Amazon URLs with stats
if amazon_urls:
    for amz_url in amazon_urls:
        product_name = amz_url.get('products', {}).get('name', 'Unknown Product') if amz_url.get('products') else 'Unknown Product'
        with st.container():
            col1, col2, col3 = st.columns([3, 1, 1])

            with col1:
                st.markdown(f"**{product_name}**")
                st.caption(f"ASIN: {amz_url['asin']} | Domain: .{amz_url['domain_code']}")

            with col2:
                reviews_count = amz_url.get('total_reviews_scraped', 0)
                last_scraped = amz_url.get('last_scraped_at')
                if reviews_count > 0:
                    st.metric("Reviews", reviews_count)
                else:
                    st.caption("Not scraped yet")

            with col3:
                # Get analysis status
                stats = amazon_service.get_review_stats(amz_url['product_id'])

                if stats.get('has_analysis'):
                    st.success("✅ Analyzed")
                elif reviews_count > 0:
                    if st.button("📊 Analyze", key=f"analyze_amz_{amz_url['id']}", help="Analyze reviews with AI"):
                        with st.spinner("Analyzing reviews..."):
                            import asyncio
                            try:
                                loop = asyncio.new_event_loop()
                                asyncio.set_event_loop(loop)
                                result = loop.run_until_complete(
                                    amazon_service.analyze_reviews_for_product(
                                        product_id=amz_url['product_id'],
                                        limit=500
                                    )
                                )
                                loop.close()
                                if result:
                                    st.success("Analysis complete!")
                                    st.rerun()
                                else:
                                    st.error("Analysis failed")
                            except Exception as e:
                                st.error(f"Error: {e}")
                else:
                    if st.button("🔄 Scrape", key=f"scrape_amz_{amz_url['id']}",
                                disabled=st.session_state.amazon_scraping,
                                help="Scrape reviews from Amazon (~$2)"):
                        st.session_state.amazon_scraping = True
                        with st.spinner("Scraping Amazon reviews... this may take a few minutes"):
                            try:
                                result = amazon_service.scrape_reviews_for_product(
                                    product_id=amz_url['product_id'],
                                    amazon_url=amz_url['amazon_url'],
                                    timeout=900
                                )
                                st.success(f"Scraped {result.unique_reviews_count} reviews (cost: ~${result.cost_estimate:.2f})")
                                st.session_state.amazon_scraping = False
                                st.rerun()
                            except Exception as e:
                                st.error(f"Scrape failed: {e}")
                                st.session_state.amazon_scraping = False
        st.markdown("---")
else:
    st.info("No Amazon product URLs added yet. Add one below to start scraping reviews.")

# Add new Amazon URL
with st.expander("➕ Add Amazon Product URL"):
    col1, col2 = st.columns([2, 1])

    with col1:
        amazon_url_input = st.text_input(
            "Amazon Product URL",
            placeholder="https://www.amazon.com/dp/B0DJWSV1J3",
            help="Paste any Amazon product URL - ASIN will be extracted automatically"
        )

    with col2:
        # Product selector
        product_options_amz = {p['name']: p['id'] for p in products}
        selected_product_amz = st.selectbox(
            "Link to Product",
            options=list(product_options_amz.keys()),
            key="amazon_product_select"
        )

    # Preview ASIN extraction
    if amazon_url_input:
        asin, domain = amazon_service.parse_amazon_url(amazon_url_input)
        if asin:
            st.success(f"✓ Detected ASIN: **{asin}** (amazon.{domain})")
        else:
            st.warning("Could not extract ASIN from URL. Please check the URL format.")

    col1, col2 = st.columns(2)
    with col1:
        if st.button("Add Amazon URL", type="primary"):
            if amazon_url_input and selected_product_amz:
                asin, domain = amazon_service.parse_amazon_url(amazon_url_input)
                if asin:
                    try:
                        db = get_supabase_client()
                        # Check if already exists
                        existing = db.table("amazon_product_urls").select("id")\
                            .eq("product_id", product_options_amz[selected_product_amz])\
                            .eq("asin", asin).execute()

                        if existing.data:
                            st.warning("This Amazon URL is already added for this product.")
                        else:
                            db.table("amazon_product_urls").insert({
                                "product_id": product_options_amz[selected_product_amz],
                                "brand_id": brand_id,
                                "amazon_url": amazon_url_input,
                                "asin": asin,
                                "domain_code": domain
                            }).execute()
                            st.success(f"Added Amazon URL for {selected_product_amz}!")
                            st.rerun()
                    except Exception as e:
                        st.error(f"Error adding URL: {e}")
                else:
                    st.error("Invalid Amazon URL. Please check the format.")
            else:
                st.warning("Please enter an Amazon URL and select a product.")

    with col2:
        st.caption("💰 Estimated cost: ~$2 per product")

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

    ### Amazon Review Scraping

    Add Amazon product URLs to scrape customer reviews for authentic persona language.

    **Process:**
    1. Add Amazon URL → ASIN is automatically extracted
    2. Click "Scrape" → Reviews are collected via Apify (~$2/product)
    3. Click "Analyze" → AI extracts pain points, desires, and verbatim quotes

    **Why It Matters:**
    - Reviews contain **authentic customer language** - not marketing speak
    - Real pain points and desires from actual buyers
    - Verbatim quotes you can use directly in ad copy
    - Helps build more accurate 4D personas
    """)
