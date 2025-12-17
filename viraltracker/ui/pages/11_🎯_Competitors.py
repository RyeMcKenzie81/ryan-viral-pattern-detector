"""
Competitors - Manage competitors and their products for competitive analysis.

This page allows users to:
- Add and manage competitors for each brand
- Add products to competitors (mirror of brand products structure)
- Manage product variants (flavors, sizes, colors)
- View competitor stats (ads, landing pages, Amazon reviews)
- Launch competitor research pipeline
"""

import streamlit as st
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
if 'expanded_competitor_id' not in st.session_state:
    st.session_state.expanded_competitor_id = None
if 'expanded_product_id' not in st.session_state:
    st.session_state.expanded_product_id = None
if 'editing_competitor_id' not in st.session_state:
    st.session_state.editing_competitor_id = None
if 'adding_product_competitor_id' not in st.session_state:
    st.session_state.adding_product_competitor_id = None


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
    """Fetch all competitors for a brand with products."""
    try:
        service = get_competitor_service()
        competitors = service.get_competitors_for_brand(UUID(brand_id))

        # Get products for each competitor
        for competitor in competitors:
            competitor['products'] = service.get_competitor_products(
                UUID(competitor['id']),
                include_variants=True
            )
            competitor['stats'] = service.get_competitor_stats(UUID(competitor['id']))

        return competitors
    except Exception as e:
        st.error(f"Failed to fetch competitors: {e}")
        return []


# ============================================================================
# HEADER
# ============================================================================

st.title("🎯 Competitors")
st.caption("Track and analyze competitor products and messaging")

# Brand Selector
brands = get_brands()
if not brands:
    st.warning("No brands found. Please create a brand first.")
    st.stop()

brand_options = {b['name']: b['id'] for b in brands}
brand_names = list(brand_options.keys())

# Get current selection
current_brand_name = None
if st.session_state.selected_brand_id:
    for name, bid in brand_options.items():
        if bid == st.session_state.selected_brand_id:
            current_brand_name = name
            break

selected_brand_name = st.selectbox(
    "Select Brand",
    options=brand_names,
    index=brand_names.index(current_brand_name) if current_brand_name in brand_names else 0,
    key="brand_selector"
)

selected_brand_id = brand_options[selected_brand_name]
st.session_state.selected_brand_id = selected_brand_id

st.divider()

# ============================================================================
# ADD COMPETITOR SECTION
# ============================================================================

with st.expander("➕ Add New Competitor", expanded=False):
    with st.form("add_competitor_form"):
        col1, col2 = st.columns(2)

        with col1:
            new_name = st.text_input("Competitor Name *", placeholder="e.g., Acme Supplements")
            new_website = st.text_input("Website URL", placeholder="https://acme.com")
            new_industry = st.text_input("Industry", placeholder="e.g., Pet Supplements")

        with col2:
            new_fb_page_id = st.text_input(
                "Facebook Page ID",
                placeholder="e.g., 123456789",
                help="Found in the URL of their Facebook Ad Library page"
            )
            new_ad_library_url = st.text_input(
                "Ad Library URL",
                placeholder="https://www.facebook.com/ads/library/?active_status=active&ad_type=all&...",
                help="Direct link to their Facebook Ad Library"
            )

        new_notes = st.text_area("Notes", placeholder="Additional notes about this competitor")

        submitted = st.form_submit_button("Add Competitor", type="primary")

        if submitted:
            if not new_name:
                st.error("Competitor name is required")
            else:
                try:
                    service = get_competitor_service()
                    service.create_competitor(
                        brand_id=UUID(selected_brand_id),
                        name=new_name,
                        website_url=new_website or None,
                        facebook_page_id=new_fb_page_id or None,
                        ad_library_url=new_ad_library_url or None,
                        industry=new_industry or None,
                        notes=new_notes or None
                    )
                    st.success(f"Added competitor: {new_name}")
                    st.rerun()
                except Exception as e:
                    st.error(f"Failed to add competitor: {e}")

# ============================================================================
# COMPETITORS LIST
# ============================================================================

st.subheader("Competitors")

competitors = get_competitors_for_brand(selected_brand_id)

if not competitors:
    st.info("No competitors found for this brand. Add one above!")
else:
    st.markdown(f"**{len(competitors)} competitor(s)**")

    for competitor in competitors:
        competitor_id = competitor['id']
        competitor_name = competitor.get('name', 'Unnamed')
        is_expanded = st.session_state.expanded_competitor_id == competitor_id
        is_editing = st.session_state.editing_competitor_id == competitor_id
        stats = competitor.get('stats', {})
        products = competitor.get('products', [])

        # Competitor header row
        col_expand, col_name, col_stats, col_actions = st.columns([0.5, 2.5, 2, 1.5])

        with col_expand:
            btn_label = "▼" if is_expanded else "▶"
            if st.button(btn_label, key=f"expand_comp_{competitor_id}"):
                if is_expanded:
                    st.session_state.expanded_competitor_id = None
                else:
                    st.session_state.expanded_competitor_id = competitor_id
                st.rerun()

        with col_name:
            st.markdown(f"**{competitor_name}**")
            if competitor.get('website_url'):
                st.caption(f"[{competitor['website_url']}]({competitor['website_url']})")

        with col_stats:
            st.caption(
                f"📦 {len(products)} products | "
                f"📢 {stats.get('ads', 0)} ads | "
                f"📄 {stats.get('landing_pages', 0)} pages"
            )

        with col_actions:
            col_research, col_edit = st.columns(2)
            with col_research:
                if st.button("🔬", key=f"research_{competitor_id}", help="Launch Research"):
                    st.session_state['research_competitor_id'] = competitor_id
                    st.switch_page("pages/23_🔍_Competitor_Research.py")
            with col_edit:
                if st.button("✏️", key=f"edit_{competitor_id}", help="Edit"):
                    st.session_state.editing_competitor_id = competitor_id if not is_editing else None
                    st.rerun()

        # Edit competitor form
        if is_editing:
            with st.container():
                st.markdown("---")
                with st.form(f"edit_competitor_{competitor_id}"):
                    col1, col2 = st.columns(2)

                    with col1:
                        edit_name = st.text_input("Name", value=competitor.get('name', ''))
                        edit_website = st.text_input("Website URL", value=competitor.get('website_url', ''))
                        edit_industry = st.text_input("Industry", value=competitor.get('industry', ''))

                    with col2:
                        edit_fb_page_id = st.text_input("Facebook Page ID", value=competitor.get('facebook_page_id', ''))
                        edit_ad_library_url = st.text_input("Ad Library URL", value=competitor.get('ad_library_url', ''))

                    edit_notes = st.text_area("Notes", value=competitor.get('notes', ''))

                    col_save, col_delete, col_cancel = st.columns([1, 1, 2])

                    with col_save:
                        if st.form_submit_button("Save", type="primary"):
                            try:
                                service = get_competitor_service()
                                service.update_competitor(UUID(competitor_id), {
                                    'name': edit_name,
                                    'website_url': edit_website or None,
                                    'facebook_page_id': edit_fb_page_id or None,
                                    'ad_library_url': edit_ad_library_url or None,
                                    'industry': edit_industry or None,
                                    'notes': edit_notes or None
                                })
                                st.success("Saved!")
                                st.session_state.editing_competitor_id = None
                                st.rerun()
                            except Exception as e:
                                st.error(f"Failed: {e}")

                    with col_delete:
                        if st.form_submit_button("🗑️ Delete", type="secondary"):
                            try:
                                service = get_competitor_service()
                                service.delete_competitor(UUID(competitor_id))
                                st.success("Deleted!")
                                st.session_state.editing_competitor_id = None
                                st.rerun()
                            except Exception as e:
                                st.error(f"Failed: {e}")

        # Expanded competitor details (products)
        if is_expanded and not is_editing:
            with st.container():
                st.markdown("---")

                # Products section
                st.markdown("##### Products")

                # Add product button
                adding_product = st.session_state.adding_product_competitor_id == competitor_id
                if st.button(
                    "➕ Add Product" if not adding_product else "Cancel",
                    key=f"add_product_btn_{competitor_id}"
                ):
                    st.session_state.adding_product_competitor_id = competitor_id if not adding_product else None
                    st.rerun()

                # Add product form
                if adding_product:
                    with st.form(f"add_product_{competitor_id}"):
                        col1, col2 = st.columns(2)
                        with col1:
                            prod_name = st.text_input("Product Name *", placeholder="e.g., Weight Loss Pro")
                        with col2:
                            prod_code = st.text_input("Product Code", placeholder="e.g., WL1", max_chars=4)
                        prod_desc = st.text_area("Description", placeholder="Brief description of the product")

                        if st.form_submit_button("Add Product", type="primary"):
                            if not prod_name:
                                st.error("Product name is required")
                            else:
                                try:
                                    service = get_competitor_service()
                                    service.create_competitor_product(
                                        competitor_id=UUID(competitor_id),
                                        brand_id=UUID(selected_brand_id),
                                        name=prod_name,
                                        description=prod_desc or None,
                                        product_code=prod_code or None
                                    )
                                    st.success(f"Added product: {prod_name}")
                                    st.session_state.adding_product_competitor_id = None
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Failed: {e}")

                # List products
                if not products:
                    st.info("No products added yet.")
                else:
                    for product in products:
                        product_id = product['id']
                        product_name = product.get('name', 'Unnamed')
                        variants = product.get('competitor_product_variants', [])
                        is_product_expanded = st.session_state.expanded_product_id == product_id

                        # Product row
                        pcol_exp, pcol_name, pcol_variants, pcol_actions = st.columns([0.5, 2, 2, 1.5])

                        with pcol_exp:
                            pbtn_label = "▼" if is_product_expanded else "▶"
                            if st.button(pbtn_label, key=f"expand_prod_{product_id}"):
                                st.session_state.expanded_product_id = product_id if not is_product_expanded else None
                                st.rerun()

                        with pcol_name:
                            code_str = f" ({product.get('product_code')})" if product.get('product_code') else ""
                            st.markdown(f"**{product_name}**{code_str}")

                        with pcol_variants:
                            if variants:
                                variant_names = [v['name'] for v in variants[:3]]
                                more = f" +{len(variants) - 3}" if len(variants) > 3 else ""
                                st.caption(f"Variants: {', '.join(variant_names)}{more}")
                            else:
                                st.caption("No variants")

                        with pcol_actions:
                            if st.button("🗑️", key=f"del_prod_{product_id}", help="Delete product"):
                                try:
                                    service = get_competitor_service()
                                    service.delete_competitor_product(UUID(product_id))
                                    st.success("Deleted!")
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Failed: {e}")

                        # Expanded product (variants)
                        if is_product_expanded:
                            with st.container():
                                # Product description
                                if product.get('description'):
                                    st.caption(product['description'])

                                # Variants section
                                st.markdown("**Variants**")

                                # Add variant form
                                with st.expander("➕ Add Variant", expanded=False):
                                    with st.form(f"add_variant_{product_id}"):
                                        vcol1, vcol2, vcol3 = st.columns(3)
                                        with vcol1:
                                            var_name = st.text_input("Variant Name *", placeholder="e.g., Strawberry")
                                        with vcol2:
                                            var_type = st.selectbox(
                                                "Type",
                                                options=["flavor", "size", "color", "bundle", "other"]
                                            )
                                        with vcol3:
                                            var_price = st.number_input("Price ($)", min_value=0.0, step=0.01, format="%.2f")

                                        var_desc = st.text_input("Description", placeholder="Optional description")

                                        if st.form_submit_button("Add Variant", type="primary"):
                                            if not var_name:
                                                st.error("Variant name is required")
                                            else:
                                                try:
                                                    service = get_competitor_service()
                                                    service.create_competitor_product_variant(
                                                        competitor_product_id=UUID(product_id),
                                                        name=var_name,
                                                        variant_type=var_type,
                                                        description=var_desc or None,
                                                        price=var_price if var_price > 0 else None
                                                    )
                                                    st.success(f"Added variant: {var_name}")
                                                    st.rerun()
                                                except Exception as e:
                                                    st.error(f"Failed: {e}")

                                # List variants
                                if variants:
                                    for variant in variants:
                                        variant_id = variant['id']
                                        vcol_name, vcol_type, vcol_price, vcol_del = st.columns([2, 1, 1, 0.5])

                                        with vcol_name:
                                            default_badge = " ⭐" if variant.get('is_default') else ""
                                            st.text(f"{variant['name']}{default_badge}")

                                        with vcol_type:
                                            st.caption(variant.get('variant_type', '-'))

                                        with vcol_price:
                                            price = variant.get('price')
                                            st.caption(f"${price:.2f}" if price else "-")

                                        with vcol_del:
                                            if st.button("🗑️", key=f"del_var_{variant_id}", help="Delete"):
                                                try:
                                                    service = get_competitor_service()
                                                    service.delete_competitor_product_variant(UUID(variant_id))
                                                    st.rerun()
                                                except Exception as e:
                                                    st.error(f"Failed: {e}")
                                else:
                                    st.caption("No variants added yet.")

                                st.markdown("")  # Spacer

        st.markdown("")  # Spacer between competitors

# ============================================================================
# HELP SECTION
# ============================================================================

with st.expander("ℹ️ Help"):
    st.markdown("""
    ### How to use this page

    **Adding a Competitor:**
    1. Click "Add New Competitor" and fill in the details
    2. The Facebook Page ID and Ad Library URL are optional but useful for scraping

    **Finding Facebook Page ID:**
    1. Go to [Facebook Ad Library](https://www.facebook.com/ads/library/)
    2. Search for the competitor
    3. The Page ID is in the URL after `view_all_page_id=`

    **Adding Products:**
    1. Expand a competitor by clicking the arrow
    2. Click "Add Product" to add a product they sell
    3. Products help you analyze competitor messaging per-product

    **Adding Variants:**
    1. Expand a product by clicking the arrow
    2. Use "Add Variant" to add flavors, sizes, colors, etc.

    **Launching Research:**
    1. Click the 🔬 button next to a competitor
    2. This opens the Competitor Research page where you can:
       - Scrape their Facebook ads
       - Analyze their landing pages
       - Scrape and analyze Amazon reviews
       - Generate competitor personas
    """)
