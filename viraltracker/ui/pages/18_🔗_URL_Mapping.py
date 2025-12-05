"""
URL Mapping - Product identification for Facebook ads.

This page allows users to:
- Configure landing page URLs for each product
- Run bulk URL matching on scraped ads
- Review and assign unmatched URLs to products
- View matching statistics
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


def get_supabase_client():
    """Get Supabase client."""
    from viraltracker.core.database import get_supabase_client
    return get_supabase_client()


def get_product_url_service():
    """Get ProductURLService instance."""
    from viraltracker.services.product_url_service import ProductURLService
    return ProductURLService()


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
        result = db.table("products").select("id, name, code").eq("brand_id", brand_id).order("name").execute()
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

# Bulk matching button
if stats['unmatched_ads'] > 0:
    if st.button("🔄 Run Bulk URL Matching", disabled=st.session_state.matching_in_progress):
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
    st.success("No URLs pending review! All ads are matched or you haven't run bulk matching yet.")
else:
    st.caption(f"Found {len(pending_urls)} unmatched URLs. Assign them to products or mark as ignored.")

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
                # Product assignment dropdown
                product_options = {"Select product...": None}
                product_options.update({p['name']: p['id'] for p in products})

                selected_product = st.selectbox(
                    "Assign to",
                    options=list(product_options.keys()),
                    key=f"assign_{url_record['id']}",
                    label_visibility="collapsed"
                )

                col_a, col_b = st.columns(2)
                with col_a:
                    if st.button("✓", key=f"confirm_{url_record['id']}", help="Assign to product"):
                        if selected_product and product_options[selected_product]:
                            service.assign_url_to_product(
                                queue_id=url_record['id'],
                                product_id=product_options[selected_product],
                                add_as_pattern=True
                            )
                            st.success("Assigned!")
                            st.rerun()
                        else:
                            st.warning("Select a product first")
                with col_b:
                    if st.button("✗", key=f"ignore_{url_record['id']}", help="Ignore (not a product URL)"):
                        service.ignore_url(url_record['id'])
                        st.rerun()

            st.markdown("---")

# ============================================================
# Help Section
# ============================================================

with st.expander("ℹ️ How URL Mapping Works"):
    st.markdown("""
    ### URL Matching Process

    1. **Configure URL Patterns**: Add landing page URLs for each product
       - `contains`: URL includes the pattern (most flexible)
       - `prefix`: URL starts with the pattern
       - `exact`: URL matches exactly
       - `regex`: Regular expression matching

    2. **Run Bulk Matching**: Click "Run Bulk URL Matching" to:
       - Extract landing page URLs from all scraped Facebook ads
       - Match them against your configured patterns
       - Tag ads with the matched product
       - Queue unmatched URLs for review

    3. **Review Queue**: For unmatched URLs:
       - Assign to an existing product (also adds as a pattern)
       - Or ignore if it's not a product page (e.g., homepage, about page)

    ### Examples

    For Wonder Paws Plaque Defense, you might add:
    - `mywonderpaws.com/products/plaque` (contains)
    - `mywonderpaws.com/products/wonder-paws-plaque-defense` (contains)

    This will match URLs like:
    - `https://www.mywonderpaws.com/products/plaque-defense?utm_source=facebook`
    - `https://mywonderpaws.com/products/wonder-paws-plaque-defense-dental-powder`
    """)
