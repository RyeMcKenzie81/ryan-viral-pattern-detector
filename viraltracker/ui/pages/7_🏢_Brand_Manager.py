"""
Brand Manager - Central hub for managing brands, products, and images.

This page allows users to:
- View and edit brand settings (colors, fonts, guidelines)
- Manage products under each brand
- View product images with analysis status
- Trigger image analysis for smart auto-selection
- Quick access to hooks and ad history
"""

import streamlit as st
import asyncio
from datetime import datetime

# Page config
st.set_page_config(
    page_title="Brand Manager",
    page_icon="🏢",
    layout="wide"
)

# Initialize session state
if 'selected_brand_id' not in st.session_state:
    st.session_state.selected_brand_id = None
if 'expanded_product_id' not in st.session_state:
    st.session_state.expanded_product_id = None
if 'analyzing_image' not in st.session_state:
    st.session_state.analyzing_image = None


def get_supabase_client():
    """Get Supabase client."""
    from viraltracker.core.database import get_supabase_client
    return get_supabase_client()


def get_brands():
    """Fetch all brands."""
    try:
        db = get_supabase_client()
        result = db.table("brands").select("*").order("name").execute()
        return result.data
    except Exception as e:
        st.error(f"Failed to fetch brands: {e}")
        return []


def get_products_for_brand(brand_id: str):
    """Fetch all products for a brand with images.

    Images can come from two sources:
    1. products.main_image_storage_path and products.reference_image_storage_paths (legacy)
    2. product_images table (new, with analysis support)

    This function merges both sources.
    """
    try:
        db = get_supabase_client()
        result = db.table("products").select(
            "*, main_image_storage_path, reference_image_storage_paths, product_images(id, storage_path, image_analysis, analyzed_at)"
        ).eq("brand_id", brand_id).order("name").execute()

        # Merge legacy image columns with product_images table
        for product in result.data:
            images = list(product.get('product_images') or [])
            existing_paths = {img['storage_path'] for img in images}

            # Add main image if not already in product_images
            main_path = product.get('main_image_storage_path')
            if main_path and main_path not in existing_paths:
                images.insert(0, {
                    'id': f"legacy_main_{product['id']}",
                    'storage_path': main_path,
                    'image_analysis': None,
                    'analyzed_at': None
                })
                existing_paths.add(main_path)

            # Add reference images if not already in product_images
            ref_paths = product.get('reference_image_storage_paths') or []
            for ref_path in ref_paths:
                if ref_path and ref_path not in existing_paths:
                    images.append({
                        'id': f"legacy_ref_{hash(ref_path)}",
                        'storage_path': ref_path,
                        'image_analysis': None,
                        'analyzed_at': None
                    })
                    existing_paths.add(ref_path)

            product['product_images'] = images

        return result.data
    except Exception as e:
        st.error(f"Failed to fetch products: {e}")
        return []


def get_hooks_count(product_id: str) -> int:
    """Get count of hooks for a product."""
    try:
        db = get_supabase_client()
        result = db.table("hooks").select("id", count="exact").eq("product_id", product_id).execute()
        return result.count or 0
    except:
        return 0


def get_ad_runs_stats(product_id: str) -> dict:
    """Get ad run statistics for a product."""
    try:
        db = get_supabase_client()
        runs = db.table("ad_runs").select("id").eq("product_id", product_id).execute()
        run_count = len(runs.data)

        if run_count == 0:
            return {"runs": 0, "ads": 0, "approved": 0}

        run_ids = [r['id'] for r in runs.data]
        ads = db.table("generated_ads").select("id, final_status").in_("ad_run_id", run_ids).execute()

        total_ads = len(ads.data)
        approved = len([a for a in ads.data if a.get('final_status') == 'approved'])

        return {"runs": run_count, "ads": total_ads, "approved": approved}
    except:
        return {"runs": 0, "ads": 0, "approved": 0}


def get_signed_url(storage_path: str, expiry: int = 3600) -> str:
    """Get signed URL for storage path."""
    if not storage_path:
        return ""
    try:
        db = get_supabase_client()
        parts = storage_path.split('/', 1)
        if len(parts) == 2:
            bucket, path = parts
        else:
            return ""
        result = db.storage.from_(bucket).create_signed_url(path, expiry)
        return result.get('signedURL', '')
    except:
        return ""


async def analyze_image(image_path: str) -> dict:
    """Run image analysis using the agent tool."""
    from pydantic_ai import RunContext
    from pydantic_ai.usage import RunUsage
    from viraltracker.agent.agents.ad_creation_agent import analyze_product_image
    from viraltracker.agent.dependencies import AgentDependencies

    deps = AgentDependencies.create(project_name="default")
    ctx = RunContext(deps=deps, model=None, usage=RunUsage())

    return await analyze_product_image(ctx=ctx, image_storage_path=image_path)


def save_image_analysis(image_id: str, storage_path: str, product_id: str, analysis: dict):
    """Save analysis to database.

    For legacy images (from products table), creates a new row in product_images.
    For existing product_images rows, updates in place.
    """
    try:
        db = get_supabase_client()

        # Check if this is a legacy image (fake ID)
        if image_id.startswith("legacy_"):
            # Insert new row into product_images
            db.table("product_images").insert({
                "product_id": product_id,
                "storage_path": storage_path,
                "image_analysis": analysis,
                "analyzed_at": datetime.utcnow().isoformat(),
                "analysis_model": analysis.get("analysis_model"),
                "analysis_version": analysis.get("analysis_version"),
                "is_main": image_id.startswith("legacy_main_")
            }).execute()
        else:
            # Update existing row
            db.table("product_images").update({
                "image_analysis": analysis,
                "analyzed_at": datetime.utcnow().isoformat(),
                "analysis_model": analysis.get("analysis_model"),
                "analysis_version": analysis.get("analysis_version")
            }).eq("id", image_id).execute()

        return True
    except Exception as e:
        st.error(f"Failed to save analysis: {e}")
        return False


def format_color_swatch(hex_color: str, name: str = None) -> str:
    """Create HTML for a color swatch."""
    label = f" {name}" if name else ""
    return f'<span style="display:inline-block;width:20px;height:20px;background:{hex_color};border:1px solid #ccc;border-radius:3px;vertical-align:middle;margin-right:5px;"></span><code>{hex_color}</code>{label}'


# ============================================================================
# MAIN UI
# ============================================================================

st.title("🏢 Brand Manager")
st.markdown("Manage brands, products, images, and hooks in one place.")

st.divider()

# Brand selector
brands = get_brands()
if not brands:
    st.warning("No brands found. Add brands to get started.")
    st.stop()

brand_options = {b['id']: b['name'] for b in brands}
brand_ids = list(brand_options.keys())

# Set default brand if not selected
if st.session_state.selected_brand_id not in brand_ids:
    st.session_state.selected_brand_id = brand_ids[0]

col_brand, col_spacer = st.columns([2, 3])
with col_brand:
    selected_brand_id = st.selectbox(
        "Select Brand",
        options=brand_ids,
        format_func=lambda x: brand_options[x],
        key="brand_selector"
    )
    st.session_state.selected_brand_id = selected_brand_id

# Get selected brand data
selected_brand = next((b for b in brands if b['id'] == selected_brand_id), None)

if not selected_brand:
    st.error("Brand not found")
    st.stop()

# ============================================================================
# BRAND SETTINGS SECTION
# ============================================================================

st.subheader("Brand Settings")

with st.container():
    col1, col2 = st.columns(2)

    with col1:
        # Brand Colors
        st.markdown("**Colors**")
        brand_colors = selected_brand.get('brand_colors') or {}

        if brand_colors:
            colors_html = ""
            if brand_colors.get('primary'):
                colors_html += format_color_swatch(
                    brand_colors['primary'],
                    brand_colors.get('primary_name', 'Primary')
                ) + "<br>"
            if brand_colors.get('secondary'):
                colors_html += format_color_swatch(
                    brand_colors['secondary'],
                    brand_colors.get('secondary_name', 'Secondary')
                ) + "<br>"
            if brand_colors.get('background'):
                colors_html += format_color_swatch(
                    brand_colors['background'],
                    brand_colors.get('background_name', 'Background')
                )

            st.markdown(colors_html, unsafe_allow_html=True)
        else:
            st.caption("No brand colors configured")

    with col2:
        # Brand Fonts
        st.markdown("**Fonts**")
        brand_fonts = selected_brand.get('brand_fonts') or {}

        if brand_fonts:
            if brand_fonts.get('primary'):
                weights = brand_fonts.get('primary_weights', [])
                weight_str = f" ({', '.join(weights)})" if weights else ""
                st.markdown(f"Primary: **{brand_fonts['primary']}**{weight_str}")
            if brand_fonts.get('secondary'):
                st.markdown(f"Secondary: **{brand_fonts['secondary']}**")
        else:
            st.caption("No brand fonts configured")

    # Brand Guidelines
    if selected_brand.get('brand_guidelines'):
        with st.expander("Brand Guidelines"):
            st.markdown(selected_brand['brand_guidelines'])

st.divider()

# ============================================================================
# PRODUCTS SECTION
# ============================================================================

st.subheader("Products")

products = get_products_for_brand(selected_brand_id)

if not products:
    st.info("No products found for this brand.")
else:
    st.markdown(f"**{len(products)} product(s)**")

    for product in products:
        product_id = product['id']
        product_name = product.get('name', 'Unnamed Product')
        is_expanded = st.session_state.expanded_product_id == product_id

        # Product header row
        col_expand, col_name, col_actions = st.columns([0.5, 3, 1.5])

        with col_expand:
            btn_label = "▼" if is_expanded else "▶"
            if st.button(btn_label, key=f"expand_prod_{product_id}"):
                if is_expanded:
                    st.session_state.expanded_product_id = None
                else:
                    st.session_state.expanded_product_id = product_id
                st.rerun()

        with col_name:
            images = product.get('product_images', [])
            analyzed_count = len([i for i in images if i.get('analyzed_at')])
            st.markdown(f"**{product_name}** | {len(images)} images ({analyzed_count} analyzed)")

        with col_actions:
            if st.button("Create Ads", key=f"create_ads_{product_id}", type="primary"):
                # Navigate to Ad Creator with product pre-selected
                st.switch_page("pages/5_🎨_Ad_Creator.py")

        # Expanded product details
        if is_expanded:
            with st.container():
                st.markdown("---")

                # Details tab
                tab_details, tab_images, tab_stats = st.tabs(["Details", "Images", "Stats"])

                with tab_details:
                    col_d1, col_d2 = st.columns(2)

                    with col_d1:
                        st.markdown("**Target Audience**")
                        st.caption(product.get('target_audience', 'Not specified'))

                        st.markdown("**Benefits**")
                        benefits = product.get('benefits', [])
                        if benefits:
                            for b in benefits[:5]:
                                st.caption(f"• {b}")
                        else:
                            st.caption("None configured")

                    with col_d2:
                        st.markdown("**USPs**")
                        usps = product.get('unique_selling_points', [])
                        if usps:
                            for u in usps[:5]:
                                st.caption(f"• {u}")
                        else:
                            st.caption("None configured")

                        st.markdown("**Current Offer**")
                        st.caption(product.get('current_offer', 'None'))

                        st.markdown("**Founders**")
                        st.caption(product.get('founders', 'Not specified'))

                with tab_images:
                    images = product.get('product_images', [])

                    if not images:
                        st.info("No images uploaded for this product.")
                    else:
                        # Analyze All button
                        unanalyzed = [i for i in images if not i.get('analyzed_at')]
                        if unanalyzed:
                            if st.button(f"🔍 Analyze All ({len(unanalyzed)} unanalyzed)", key=f"analyze_all_{product_id}"):
                                st.info("Analyzing images... This may take a minute.")
                                for img in unanalyzed:
                                    try:
                                        analysis = asyncio.run(analyze_image(img['storage_path']))
                                        save_image_analysis(img['id'], img['storage_path'], product_id, analysis)
                                    except Exception as e:
                                        st.error(f"Failed to analyze {img['storage_path']}: {e}")
                                st.success("Analysis complete!")
                                st.rerun()

                        # Image grid
                        cols = st.columns(4)
                        for idx, img in enumerate(images):
                            with cols[idx % 4]:
                                # Thumbnail
                                img_url = get_signed_url(img['storage_path'])
                                if img_url:
                                    st.image(img_url, use_container_width=True)
                                else:
                                    st.markdown("<div style='height:100px;background:#333;'></div>", unsafe_allow_html=True)

                                # Analysis status
                                analysis = img.get('image_analysis')
                                if analysis:
                                    quality = analysis.get('quality_score', 0)
                                    stars = "⭐" * int(quality * 5)
                                    use_cases = analysis.get('best_use_cases', [])[:2]
                                    st.caption(f"{stars} {quality:.2f}")
                                    st.caption(f"{', '.join(use_cases)}")
                                else:
                                    st.caption("❓ Not analyzed")
                                    if st.button("Analyze", key=f"analyze_{img['id']}", type="secondary"):
                                        with st.spinner("Analyzing..."):
                                            try:
                                                result = asyncio.run(analyze_image(img['storage_path']))
                                                save_image_analysis(img['id'], img['storage_path'], product_id, result)
                                                st.success("Done!")
                                                st.rerun()
                                            except Exception as e:
                                                st.error(f"Failed: {e}")

                with tab_stats:
                    # Hooks count
                    hooks_count = get_hooks_count(product_id)
                    st.metric("Hooks", hooks_count)

                    # Ad runs stats
                    stats = get_ad_runs_stats(product_id)
                    col_s1, col_s2, col_s3 = st.columns(3)
                    with col_s1:
                        st.metric("Ad Runs", stats['runs'])
                    with col_s2:
                        st.metric("Ads Generated", stats['ads'])
                    with col_s3:
                        approval_rate = int(stats['approved'] / stats['ads'] * 100) if stats['ads'] > 0 else 0
                        st.metric("Approval Rate", f"{approval_rate}%")

                st.markdown("---")

# Footer
st.divider()
st.caption("Use Ad Creator to generate new ads, or Ad History to review past runs.")
