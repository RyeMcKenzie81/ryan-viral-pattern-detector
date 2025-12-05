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
                    col_a, col_b, col_c = st.columns(3)
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
                        if st.button("🏢", key=f"brand_{url_record['id']}", help="Mark as brand-level (homepage, collection, etc.)"):
                            service.mark_as_brand_level(url_record['id'])
                            st.rerun()
                    with col_c:
                        if st.button("✗", key=f"ignore_{url_record['id']}", help="Ignore (social media, external link, etc.)"):
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
       - **🏢 Brand-level**: Mark as brand-wide URL (homepage, collections) - included in brand analysis but not product-specific
       - **✗ Ignore**: Skip URLs that aren't relevant (social media links, external sites)

    3. **Bulk Match**: Once URL patterns are configured, "Run Bulk URL Matching" will automatically tag all ads with their products.

    ### URL Categories

    | URL Type | Action | Example |
    |----------|--------|---------|
    | Product page | Assign to product | `/products/plaque-defense` |
    | Collection page | Brand-level | `/collections/dental-care` |
    | Homepage | Brand-level | `/` |
    | Social media | Ignore | `instagram.com/brand` |
    | External link | Ignore | `youtube.com/watch?v=...` |

    ### Pattern Types

    - `contains`: URL includes the pattern (most flexible, recommended)
    - `prefix`: URL starts with the pattern
    - `exact`: URL matches exactly
    - `regex`: Regular expression matching
    """)
