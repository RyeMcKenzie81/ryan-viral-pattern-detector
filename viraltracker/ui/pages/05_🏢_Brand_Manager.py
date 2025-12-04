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
import json
from datetime import datetime

# Page config
st.set_page_config(
    page_title="Brand Manager",
    page_icon="🏢",
    layout="wide"
)

# Authentication
from viraltracker.ui.auth import require_auth
require_auth()

# Initialize session state
if 'selected_brand_id' not in st.session_state:
    st.session_state.selected_brand_id = None
if 'expanded_product_id' not in st.session_state:
    st.session_state.expanded_product_id = None
if 'analyzing_image' not in st.session_state:
    st.session_state.analyzing_image = None
if 'scraping_ads' not in st.session_state:
    st.session_state.scraping_ads = False


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
    """Fetch all products for a brand with images from product_images table."""
    try:
        db = get_supabase_client()
        result = db.table("products").select(
            "*, product_images(id, storage_path, image_analysis, analyzed_at, notes, is_main)"
        ).eq("brand_id", brand_id).order("name").execute()

        # Supported image formats for Vision AI analysis
        image_extensions = ('.jpg', '.jpeg', '.png', '.webp', '.gif')

        # Add file type info to images
        for product in result.data:
            images = list(product.get('product_images') or [])

            # Sort: main image first, then by storage_path
            images.sort(key=lambda x: (not x.get('is_main', False), x.get('storage_path', '')))

            for img in images:
                path = img.get('storage_path', '').lower()
                img['is_image'] = path.endswith(image_extensions)
                img['is_pdf'] = path.endswith('.pdf')
                img['file_type'] = 'pdf' if img['is_pdf'] else 'image' if img['is_image'] else 'other'

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


def save_product_social_proof(product_id: str, review_platforms: dict, media_features: list, awards_certifications: list):
    """Save social proof data for a product."""
    try:
        db = get_supabase_client()
        db.table("products").update({
            "review_platforms": review_platforms,
            "media_features": media_features,
            "awards_certifications": awards_certifications
        }).eq("id", product_id).execute()
        return True
    except Exception as e:
        st.error(f"Failed to save social proof: {e}")
        return False


def save_image_analysis(image_id: str, analysis: dict):
    """Save analysis to product_images table."""
    try:
        db = get_supabase_client()
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


def save_image_notes(image_id: str, notes: str):
    """Save notes for an image."""
    try:
        db = get_supabase_client()
        db.table("product_images").update({
            "notes": notes
        }).eq("id", image_id).execute()
        return True
    except Exception as e:
        st.error(f"Failed to save notes: {e}")
        return False


def save_brand_code(brand_id: str, brand_code: str) -> bool:
    """Save brand_code for a brand (used in ad filenames)."""
    try:
        db = get_supabase_client()
        # Validate: max 4 chars, uppercase
        code = brand_code.strip().upper()[:4] if brand_code else None
        db.table("brands").update({"brand_code": code}).eq("id", brand_id).execute()
        return True
    except Exception as e:
        st.error(f"Failed to save brand code: {e}")
        return False


def save_product_code(product_id: str, product_code: str) -> bool:
    """Save product_code for a product (used in ad filenames)."""
    try:
        db = get_supabase_client()
        # Validate: max 4 chars, uppercase
        code = product_code.strip().upper()[:4] if product_code else None
        db.table("products").update({"product_code": code}).eq("id", product_id).execute()
        return True
    except Exception as e:
        st.error(f"Failed to save product code: {e}")
        return False


def format_color_swatch(hex_color: str, name: str = None) -> str:
    """Create HTML for a color swatch."""
    label = f" {name}" if name else ""
    return f'<span style="display:inline-block;width:20px;height:20px;background:{hex_color};border:1px solid #ccc;border-radius:3px;vertical-align:middle;margin-right:5px;"></span><code>{hex_color}</code>{label}'


def scrape_facebook_ads(ad_library_url: str, brand_id: str, max_ads: int = 100) -> dict:
    """
    Scrape ads from Facebook Ad Library and save to database.

    Args:
        ad_library_url: Facebook Ad Library URL to scrape
        brand_id: Brand UUID to link ads to
        max_ads: Maximum number of ads to scrape

    Returns:
        Dict with results: {"success": bool, "count": int, "message": str}
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
            return {"success": True, "count": 0, "message": "No ads found at this URL"}

        # Save to database linked to brand
        saved_ids = scraper.save_ads_to_db(df, brand_id=brand_id)

        return {
            "success": True,
            "count": len(saved_ids),
            "message": f"Successfully scraped and saved {len(saved_ids)} ads"
        }

    except Exception as e:
        return {"success": False, "count": 0, "message": str(e)}


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
    # Brand Code (for ad filenames)
    col_code, col_code_spacer = st.columns([1, 3])
    with col_code:
        current_brand_code = selected_brand.get('brand_code') or ''
        new_brand_code = st.text_input(
            "Brand Code",
            value=current_brand_code,
            max_chars=4,
            placeholder="e.g., WP",
            help="2-4 character code used in ad filenames (e.g., WP for WonderPaws)"
        )
        if new_brand_code.upper() != current_brand_code.upper():
            if st.button("Save Code", key="save_brand_code", type="primary"):
                if save_brand_code(selected_brand_id, new_brand_code):
                    st.success("Brand code saved!")
                    st.rerun()

    st.markdown("")  # Spacer

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

    # Facebook Ad Library Section
    st.markdown("")  # Spacer
    st.markdown("**Facebook Ad Library**")

    current_ad_library_url = selected_brand.get('ad_library_url') or ""
    current_page_id = selected_brand.get('facebook_page_id') or ""

    new_ad_library_url = st.text_input(
        "Ad Library URL",
        value=current_ad_library_url,
        placeholder="https://www.facebook.com/ads/library/?active_status=all&ad_type=all&country=US&view_all_page_id=YOUR_PAGE_ID",
        help="Full Facebook Ad Library URL for scraping your brand's ads",
        key="brand_ad_library_url"
    )

    col_save, col_count, col_scrape = st.columns([1, 1, 1])

    with col_save:
        if new_ad_library_url != current_ad_library_url:
            if st.button("Save URL", key="save_ad_library_url", type="secondary"):
                try:
                    db = get_supabase_client()
                    db.table("brands").update({
                        "ad_library_url": new_ad_library_url
                    }).eq("id", selected_brand_id).execute()
                    st.success("Saved!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Failed: {e}")

    with col_count:
        scrape_count = st.number_input("Max ads", min_value=50, max_value=3000, value=100, step=50, key="scrape_count")

    with col_scrape:
        scrape_url = new_ad_library_url or current_ad_library_url
        if scrape_url:
            if st.button("Scrape Ads", key="scrape_brand_ads", type="primary"):
                with st.spinner(f"Scraping up to {scrape_count} ads from Facebook Ad Library... This may take several minutes."):
                    result = scrape_facebook_ads(
                        ad_library_url=scrape_url,
                        brand_id=selected_brand_id,
                        max_ads=scrape_count
                    )

                if result["success"]:
                    if result["count"] > 0:
                        st.success(f"✅ {result['message']}")
                    else:
                        st.warning(result["message"])
                else:
                    st.error(f"❌ Scraping failed: {result['message']}")
        else:
            st.button("Scrape Ads", key="scrape_brand_ads_disabled", disabled=True)

    if current_ad_library_url:
        st.caption(f"[Open in Facebook Ad Library ↗]({current_ad_library_url})")

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
                    # Product Code (for ad filenames)
                    col_pc, col_pc_spacer = st.columns([1, 3])
                    with col_pc:
                        current_product_code = product.get('product_code') or ''
                        new_product_code = st.text_input(
                            "Product Code",
                            value=current_product_code,
                            max_chars=4,
                            placeholder="e.g., C3",
                            help="2-4 character code used in ad filenames (e.g., C3 for Collagen 3x)",
                            key=f"product_code_{product_id}"
                        )
                        if new_product_code.upper() != current_product_code.upper():
                            if st.button("Save Code", key=f"save_pc_{product_id}", type="primary"):
                                if save_product_code(product_id, new_product_code):
                                    st.success("Product code saved!")
                                    st.rerun()

                    st.markdown("")  # Spacer

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

                    # Social Proof section (full width)
                    st.markdown("---")
                    st.markdown("**📊 Verified Social Proof** (used in ad generation)")

                    col_sp1, col_sp2, col_sp3 = st.columns(3)

                    with col_sp1:
                        st.markdown("**Review Platforms**")
                        review_platforms = product.get('review_platforms', {})
                        if review_platforms:
                            for platform, data in review_platforms.items():
                                rating = data.get('rating', 'N/A')
                                count = data.get('count', 'N/A')
                                st.caption(f"• {platform}: {rating}★ ({count} reviews)")
                        else:
                            st.caption("None configured")

                    with col_sp2:
                        st.markdown("**Media Features**")
                        media_features = product.get('media_features', [])
                        if media_features:
                            for media in media_features[:5]:
                                st.caption(f"• {media}")
                        else:
                            st.caption("None configured")

                    with col_sp3:
                        st.markdown("**Awards & Certifications**")
                        awards = product.get('awards_certifications', [])
                        if awards:
                            for award in awards[:5]:
                                st.caption(f"• {award}")
                        else:
                            st.caption("None configured")

                    # Edit Social Proof button
                    edit_key = f"edit_sp_{product_id}"
                    if edit_key not in st.session_state:
                        st.session_state[edit_key] = False

                    if st.button("✏️ Edit Social Proof", key=f"btn_edit_sp_{product_id}"):
                        st.session_state[edit_key] = not st.session_state[edit_key]
                        st.rerun()

                    if st.session_state[edit_key]:
                        with st.form(key=f"form_sp_{product_id}"):
                            st.markdown("#### Edit Social Proof")

                            # Review Platforms
                            st.markdown("**Review Platforms** (JSON format)")
                            st.caption("Example: {\"trustpilot\": {\"rating\": 4.5, \"count\": 1200}, \"amazon\": {\"rating\": 4.7, \"count\": 3500}}")
                            current_reviews = product.get('review_platforms', {}) or {}
                            reviews_str = st.text_area(
                                "Review Platforms JSON",
                                value=json.dumps(current_reviews, indent=2) if current_reviews else "{}",
                                height=100,
                                key=f"reviews_{product_id}"
                            )

                            # Media Features
                            st.markdown("**Media Features** (one per line)")
                            st.caption("Example: Forbes, Good Morning America, Today Show")
                            current_media = product.get('media_features', []) or []
                            media_str = st.text_area(
                                "Media Features",
                                value="\n".join(current_media) if current_media else "",
                                height=80,
                                key=f"media_{product_id}"
                            )

                            # Awards & Certifications
                            st.markdown("**Awards & Certifications** (one per line)")
                            st.caption("Example: #1 Best Seller, Vet Recommended, NASC Certified")
                            current_awards = product.get('awards_certifications', []) or []
                            awards_str = st.text_area(
                                "Awards & Certifications",
                                value="\n".join(current_awards) if current_awards else "",
                                height=80,
                                key=f"awards_{product_id}"
                            )

                            col_save, col_cancel = st.columns(2)
                            with col_save:
                                submitted = st.form_submit_button("💾 Save", type="primary")
                            with col_cancel:
                                cancelled = st.form_submit_button("Cancel")

                            if submitted:
                                try:
                                    # Parse JSON for review platforms
                                    review_data = json.loads(reviews_str) if reviews_str.strip() else {}

                                    # Parse newline-separated lists
                                    media_list = [m.strip() for m in media_str.split("\n") if m.strip()]
                                    awards_list = [a.strip() for a in awards_str.split("\n") if a.strip()]

                                    if save_product_social_proof(product_id, review_data, media_list, awards_list):
                                        st.success("Social proof saved!")
                                        st.session_state[edit_key] = False
                                        st.rerun()
                                except json.JSONDecodeError as e:
                                    st.error(f"Invalid JSON in Review Platforms: {e}")

                            if cancelled:
                                st.session_state[edit_key] = False
                                st.rerun()

                with tab_images:
                    images = product.get('product_images', [])

                    if not images:
                        st.info("No images uploaded for this product.")
                    else:
                        # Analyze All button - only for images (not PDFs)
                        analyzable_images = [i for i in images if i.get('is_image', True) and not i.get('is_pdf')]
                        unanalyzed = [i for i in analyzable_images if not i.get('analyzed_at')]
                        if unanalyzed:
                            if st.button(f"🔍 Analyze All ({len(unanalyzed)} unanalyzed)", key=f"analyze_all_{product_id}"):
                                st.info("Analyzing images... This may take a minute.")
                                for img in unanalyzed:
                                    try:
                                        analysis = asyncio.run(analyze_image(img['storage_path']))
                                        save_image_analysis(img['id'], analysis)
                                    except Exception as e:
                                        st.error(f"Failed to analyze {img['storage_path']}: {e}")
                                st.success("Analysis complete!")
                                st.rerun()

                        # Image/file grid
                        cols = st.columns(4)
                        for idx, img in enumerate(images):
                            with cols[idx % 4]:
                                is_pdf = img.get('is_pdf', False)
                                is_image = img.get('is_image', True)

                                # Display thumbnail or PDF badge
                                if is_pdf:
                                    # PDF badge
                                    st.markdown(
                                        "<div style='height:100px;background:#2d2d2d;border-radius:8px;"
                                        "display:flex;align-items:center;justify-content:center;"
                                        "font-size:2em;'>📄</div>",
                                        unsafe_allow_html=True
                                    )
                                    filename = img['storage_path'].split('/')[-1]
                                    st.caption(f"**PDF:** {filename[:20]}...")
                                else:
                                    # Regular image thumbnail
                                    img_url = get_signed_url(img['storage_path'])
                                    if img_url:
                                        st.image(img_url, use_container_width=True)
                                    else:
                                        st.markdown("<div style='height:100px;background:#333;'></div>", unsafe_allow_html=True)

                                # Analysis status (only for images)
                                if is_image and not is_pdf:
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
                                                    save_image_analysis(img['id'], result)
                                                    st.success("Done!")
                                                    st.rerun()
                                                except Exception as e:
                                                    st.error(f"Failed: {e}")
                                elif is_pdf:
                                    st.caption("📋 PDF - Gemini analysis coming soon")

                                # Notes input (for all file types)
                                current_notes = img.get('notes', '') or ''
                                with st.expander("📝 Notes", expanded=bool(current_notes)):
                                    new_notes = st.text_area(
                                        "Add context",
                                        value=current_notes,
                                        key=f"notes_{img['id']}",
                                        placeholder="e.g., Product packaging front view, Card examples...",
                                        height=80
                                    )
                                    if new_notes != current_notes:
                                        if st.button("Save", key=f"save_notes_{img['id']}", type="primary"):
                                            save_image_notes(img['id'], new_notes)
                                            st.success("Saved!")
                                            st.rerun()

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
