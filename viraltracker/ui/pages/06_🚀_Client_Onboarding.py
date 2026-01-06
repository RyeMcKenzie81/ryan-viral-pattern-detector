"""
Client Onboarding - Streamlit page for collecting client information.

Features:
- Multi-section data entry form (6 tabs)
- Auto-scraping with manual triggers
- Completeness tracker in sidebar
- Interview question generator
- Onboarding summary view
- Import to production functionality

Part of the Client Onboarding Pipeline.
"""

import streamlit as st
import asyncio
from datetime import datetime
from uuid import UUID

# Page config (must be first)
st.set_page_config(
    page_title="Client Onboarding",
    page_icon="🚀",
    layout="wide",
)

# Authentication
from viraltracker.ui.auth import require_auth

require_auth()

# Session state initialization
if "onboarding_session_id" not in st.session_state:
    st.session_state.onboarding_session_id = None
if "active_tab" not in st.session_state:
    st.session_state.active_tab = 0


# ============================================
# SERVICE INITIALIZATION
# ============================================


def get_onboarding_service():
    """Get ClientOnboardingService instance."""
    from viraltracker.services.client_onboarding_service import ClientOnboardingService

    return ClientOnboardingService()


def get_web_scraping_service():
    """Get WebScrapingService instance."""
    from viraltracker.services.web_scraping_service import WebScrapingService

    return WebScrapingService()


def get_amazon_service():
    """Get AmazonReviewService instance."""
    from viraltracker.services.amazon_review_service import AmazonReviewService

    return AmazonReviewService()


# ============================================
# HELPER FUNCTIONS
# ============================================


def render_completeness_bar(score: float):
    """Render a colored progress bar showing completeness."""
    if score >= 80:
        color = "#28a745"  # Green
    elif score >= 50:
        color = "#ffc107"  # Yellow/Orange
    else:
        color = "#dc3545"  # Red

    st.markdown(
        f"""
        <div style="background:#333; border-radius:10px; height:24px; margin-bottom:10px; overflow:hidden;">
            <div style="background:{color}; width:{min(score, 100)}%; height:24px; border-radius:10px 0 0 10px;
                        text-align:center; color:white; font-size:14px; font-weight:bold; line-height:24px;">
                {score:.0f}%
            </div>
        </div>
    """,
        unsafe_allow_html=True,
    )


def field_status_icon(filled: bool) -> str:
    """Return status icon for field."""
    return "✅" if filled else "❌"


# ============================================
# SESSION SELECTOR
# ============================================


def render_session_selector():
    """Render session selection/creation UI."""
    service = get_onboarding_service()

    col1, col2 = st.columns([3, 1])

    with col1:
        sessions = service.list_sessions(limit=20)
        if sessions:
            options = {
                f"{s['session_name']} ({s['completeness_score']:.0f}%) - {s['status']}": s["id"]
                for s in sessions
            }
            options_list = ["-- Select Session --"] + list(options.keys())

            # Find current selection index
            current_idx = 0
            if st.session_state.onboarding_session_id:
                for i, (label, sid) in enumerate(options.items(), 1):
                    if sid == st.session_state.onboarding_session_id:
                        current_idx = i
                        break

            selected = st.selectbox(
                "Select existing session",
                options=options_list,
                index=current_idx,
                key="session_selector",
            )

            if selected != "-- Select Session --":
                st.session_state.onboarding_session_id = options[selected]
            elif selected == "-- Select Session --" and st.session_state.onboarding_session_id:
                # Clear selection
                st.session_state.onboarding_session_id = None
        else:
            st.info("No existing sessions. Create a new one to get started.")

    with col2:
        with st.expander("➕ Create New", expanded=not sessions):
            new_name = st.text_input("Session Name", placeholder="e.g., Acme Corp Onboarding")
            new_client = st.text_input("Client Name (optional)", placeholder="e.g., Acme Corp")

            if st.button("Create Session", type="primary", use_container_width=True):
                if new_name:
                    session_id = service.create_session(
                        session_name=new_name, client_name=new_client or None
                    )
                    st.session_state.onboarding_session_id = str(session_id)
                    st.success(f"Created: {new_name}")
                    st.rerun()
                else:
                    st.warning("Please enter a session name")


# ============================================
# SIDEBAR - PROGRESS & ACTIONS
# ============================================


def render_sidebar(session: dict):
    """Render sidebar with progress, sections, and actions."""
    service = get_onboarding_service()

    st.sidebar.markdown("---")
    st.sidebar.subheader("📊 Onboarding Progress")

    summary = service.get_onboarding_summary(UUID(session["id"]))

    # Completeness bar
    score = summary["completeness"]["score"]
    st.sidebar.markdown(f"**Completeness: {score:.0f}%**")
    with st.sidebar:
        render_completeness_bar(score)

    st.sidebar.caption(f"Required: {summary['completeness']['required']}")
    st.sidebar.caption(f"Nice-to-have: {summary['completeness']['nice_to_have']}")

    # Section status
    st.sidebar.markdown("---")
    st.sidebar.markdown("**Sections**")

    sections = summary["sections"]
    section_names = {
        "brand_basics": "Brand Basics",
        "facebook_meta": "Facebook/Meta",
        "amazon_data": "Amazon",
        "product_assets": "Product Assets",
        "competitors": "Competitors",
        "target_audience": "Target Audience",
    }

    for section_key, section_label in section_names.items():
        section_status = sections.get(section_key, {})

        if section_key == "competitors":
            filled = section_status.get("filled", False)
            count = section_status.get("count", 0)
            icon = "✅" if filled else "❌"
            st.sidebar.caption(f"{icon} {section_label} ({count})")
        else:
            filled_count = sum(1 for v in section_status.values() if v)
            total = len(section_status)
            if filled_count == total and total > 0:
                icon = "✅"
            elif filled_count > 0:
                icon = "⚠️"
            else:
                icon = "❌"
            st.sidebar.caption(f"{icon} {section_label} ({filled_count}/{total})")

    # Missing fields
    if summary["missing_required"]:
        st.sidebar.markdown("---")
        st.sidebar.warning(f"**Missing Required ({len(summary['missing_required'])})**")
        for field in summary["missing_required"][:5]:
            st.sidebar.caption(f"• {field.replace('_', ' ').replace('.', ' → ')}")
        if len(summary["missing_required"]) > 5:
            st.sidebar.caption(f"...and {len(summary['missing_required']) - 5} more")

    # Actions
    st.sidebar.markdown("---")
    st.sidebar.markdown("**Actions**")

    # Interview Questions
    if st.sidebar.button("📝 Generate Interview Questions", use_container_width=True):
        with st.spinner("Generating questions with AI..."):
            try:
                questions = asyncio.run(
                    service.generate_interview_questions(UUID(session["id"]))
                )
                st.sidebar.success(f"Generated {len(questions)} questions!")
                st.rerun()
            except Exception as e:
                st.sidebar.error(f"Failed: {e}")

    # Display questions if available
    questions = session.get("interview_questions") or []
    if questions:
        with st.sidebar.expander(f"📋 Questions ({len(questions)})", expanded=False):
            for i, q in enumerate(questions, 1):
                st.caption(f"{i}. {q}")

    # Import button
    st.sidebar.markdown("---")
    if score >= 50:
        if st.sidebar.button(
            "🚀 Import to Production", type="primary", use_container_width=True
        ):
            try:
                result = service.import_to_production(UUID(session["id"]))
                st.sidebar.success(f"Imported! Brand ID: {result.get('brand_id')}")
                st.rerun()
            except Exception as e:
                st.sidebar.error(f"Import failed: {e}")
    else:
        st.sidebar.info("Complete at least 50% to import")

    # Status update
    st.sidebar.markdown("---")
    current_status = session.get("status", "in_progress")
    new_status = st.sidebar.selectbox(
        "Session Status",
        options=["in_progress", "awaiting_info", "ready_for_import", "archived"],
        index=["in_progress", "awaiting_info", "ready_for_import", "archived"].index(
            current_status
        )
        if current_status in ["in_progress", "awaiting_info", "ready_for_import", "archived"]
        else 0,
    )
    if new_status != current_status:
        if st.sidebar.button("Update Status"):
            service.update_status(UUID(session["id"]), new_status)
            st.rerun()


# ============================================
# TAB 1: BRAND BASICS
# ============================================


def render_brand_basics_tab(session: dict):
    """Render Brand Basics section."""
    service = get_onboarding_service()

    data = session.get("brand_basics") or {}

    col1, col2 = st.columns(2)

    with col1:
        name = st.text_input(
            "Brand Name *",
            value=data.get("name", ""),
            placeholder="e.g., Wonder Paws",
            key="brand_name",
        )

        website_url = st.text_input(
            "Website URL *",
            value=data.get("website_url", ""),
            placeholder="https://example.com",
            key="website_url",
        )

        # Website scraping
        if website_url:
            scrape_col1, scrape_col2 = st.columns([1, 2])
            with scrape_col1:
                if st.button("🔍 Scrape Website", key="scrape_website"):
                    with st.spinner("Scraping website..."):
                        try:
                            web_service = get_web_scraping_service()
                            from viraltracker.services.web_scraping_service import (
                                LANDING_PAGE_SCHEMA,
                            )

                            result = web_service.extract_structured(
                                url=website_url, schema=LANDING_PAGE_SCHEMA
                            )
                            if result.success:
                                data["scraped_website_data"] = result.data
                                service.update_section(
                                    UUID(session["id"]), "brand_basics", data
                                )
                                service.update_scrape_status(
                                    UUID(session["id"]),
                                    "website",
                                    "complete",
                                    result_data=result.data,
                                )
                                st.success("Website scraped!")
                                st.rerun()
                            else:
                                st.error(f"Scrape failed: {result.error}")
                        except Exception as e:
                            st.error(f"Scrape error: {e}")

            with scrape_col2:
                if data.get("scraped_website_data"):
                    st.caption("✅ Website data collected")

    with col2:
        brand_voice = st.text_area(
            "Brand Voice / Tone",
            value=data.get("brand_voice", ""),
            placeholder="Describe the brand's communication style, personality, key phrases...",
            height=120,
            key="brand_voice",
        )

        # Logo upload placeholder
        st.markdown("**Logo Upload**")
        st.caption("Upload high-res logo with transparent background (PNG preferred)")
        uploaded_logo = st.file_uploader(
            "Logo",
            type=["png", "jpg", "jpeg", "svg"],
            key="logo_upload",
            label_visibility="collapsed",
        )

        if uploaded_logo:
            st.image(uploaded_logo, width=150)
            data["logo_filename"] = uploaded_logo.name
            # TODO: Upload to Supabase storage

    # Show scraped data if available
    if data.get("scraped_website_data"):
        with st.expander("📄 Scraped Website Data", expanded=False):
            scraped = data["scraped_website_data"]
            if scraped.get("title"):
                st.markdown(f"**Title:** {scraped['title']}")
            if scraped.get("tagline"):
                st.markdown(f"**Tagline:** {scraped['tagline']}")
            if scraped.get("benefits"):
                st.markdown("**Benefits:**")
                for b in scraped["benefits"][:5]:
                    st.caption(f"• {b}")

    # Save button
    if st.button("💾 Save Brand Basics", type="primary", key="save_brand_basics"):
        data.update(
            {
                "name": name,
                "website_url": website_url,
                "brand_voice": brand_voice,
            }
        )
        service.update_section(UUID(session["id"]), "brand_basics", data)
        st.success("Saved!")
        st.rerun()


# ============================================
# TAB 2: FACEBOOK/META
# ============================================


def render_facebook_tab(session: dict):
    """Render Facebook/Meta section."""
    service = get_onboarding_service()

    data = session.get("facebook_meta") or {}

    col1, col2 = st.columns(2)

    with col1:
        page_url = st.text_input(
            "Facebook Page URL *",
            value=data.get("page_url", ""),
            placeholder="https://facebook.com/brandname",
            key="fb_page_url",
        )

        ad_library_url = st.text_input(
            "Ad Library URL *",
            value=data.get("ad_library_url", ""),
            placeholder="https://www.facebook.com/ads/library/?...",
            key="fb_ad_library_url",
        )

    with col2:
        ad_account_id = st.text_input(
            "Ad Account ID (for publishing)",
            value=data.get("ad_account_id", ""),
            placeholder="act_123456789",
            key="fb_ad_account_id",
        )

        # Scrape ads trigger
        if ad_library_url:
            st.markdown("**Ad Library Scraping**")
            scrape_col1, scrape_col2 = st.columns([1, 2])
            with scrape_col1:
                if st.button("🔍 Scrape Ads", key="scrape_fb_ads"):
                    with st.spinner("Scraping Facebook ads... This may take a few minutes."):
                        try:
                            from viraltracker.scrapers.facebook_ads import FacebookAdsScraper

                            scraper = FacebookAdsScraper()
                            df = scraper.search_ad_library(search_url=ad_library_url, count=50)
                            data["scraped_ads_count"] = len(df)
                            data["scraped_at"] = datetime.utcnow().isoformat()
                            service.update_section(UUID(session["id"]), "facebook_meta", data)
                            service.update_scrape_status(
                                UUID(session["id"]),
                                "facebook_ads",
                                "complete",
                                result_data={"count": len(df)},
                            )
                            st.success(f"Scraped {len(df)} ads!")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Scrape failed: {e}")

            with scrape_col2:
                if data.get("scraped_ads_count"):
                    st.caption(f"✅ {data['scraped_ads_count']} ads scraped")

    # Save button
    if st.button("💾 Save Facebook/Meta", type="primary", key="save_facebook"):
        data.update(
            {
                "page_url": page_url,
                "ad_library_url": ad_library_url,
                "ad_account_id": ad_account_id,
            }
        )
        service.update_section(UUID(session["id"]), "facebook_meta", data)
        st.success("Saved!")
        st.rerun()


# ============================================
# TAB 3: AMAZON
# ============================================


def render_amazon_tab(session: dict):
    """Render Amazon section."""
    service = get_onboarding_service()

    data = session.get("amazon_data") or {}
    products = data.get("products") or []

    st.markdown("Add Amazon product URLs to extract ASINs and scrape reviews.")

    # Add new product
    col1, col2 = st.columns([3, 1])
    with col1:
        new_url = st.text_input(
            "Amazon Product URL",
            placeholder="https://amazon.com/dp/B0XXXXX...",
            key="new_amazon_url",
        )

    with col2:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("➕ Add Product", key="add_amazon_product"):
            if new_url:
                try:
                    amazon_service = get_amazon_service()
                    asin, domain = amazon_service.parse_amazon_url(new_url)
                    if asin:
                        # Check for duplicate
                        existing_asins = [p.get("asin") for p in products]
                        if asin in existing_asins:
                            st.warning(f"ASIN {asin} already added")
                        else:
                            products.append(
                                {
                                    "url": new_url,
                                    "asin": asin,
                                    "domain": domain or "com",
                                    "scraped_reviews_count": 0,
                                }
                            )
                            data["products"] = products
                            service.update_section(UUID(session["id"]), "amazon_data", data)
                            st.success(f"Added ASIN: {asin}")
                            st.rerun()
                    else:
                        st.error("Could not extract ASIN from URL")
                except Exception as e:
                    st.error(f"Error: {e}")

    # Display existing products
    if products:
        st.markdown("---")
        st.markdown("**Added Products**")

        for i, prod in enumerate(products):
            col1, col2, col3 = st.columns([3, 1, 1])
            with col1:
                st.markdown(f"**{prod['asin']}** ({prod.get('domain', 'com')})")
                if prod.get("scraped_reviews_count"):
                    st.caption(f"✅ {prod['scraped_reviews_count']} reviews scraped")
                else:
                    st.caption("No reviews scraped yet")

            with col2:
                if st.button("🔍 Scrape", key=f"scrape_amazon_{i}"):
                    st.info("Review scraping requires product import first")

            with col3:
                if st.button("🗑️ Remove", key=f"remove_amazon_{i}"):
                    products.pop(i)
                    data["products"] = products
                    service.update_section(UUID(session["id"]), "amazon_data", data)
                    st.rerun()
    else:
        st.info("No Amazon products added yet.")


# ============================================
# TAB 4: PRODUCT ASSETS
# ============================================


def render_product_assets_tab(session: dict):
    """Render Product Assets section."""
    service = get_onboarding_service()

    data = session.get("product_assets") or {}

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("**Product Images**")
        st.caption("Upload high-quality images with transparent backgrounds for ad generation.")

        uploaded_files = st.file_uploader(
            "Upload Images",
            type=["png", "jpg", "jpeg", "webp"],
            accept_multiple_files=True,
            key="product_images",
        )

        if uploaded_files:
            images = data.get("images") or []
            cols = st.columns(4)
            for i, f in enumerate(uploaded_files):
                with cols[i % 4]:
                    st.image(f, width=100)
                    st.caption(f.name)
                # Track uploaded files
                if f.name not in [img.get("filename") for img in images]:
                    images.append({"filename": f.name, "has_transparent_bg": False})
            data["images"] = images
            # TODO: Upload to Supabase storage

    with col2:
        st.markdown("**Product Dimensions**")
        st.caption("Physical dimensions for accurate rendering at correct scale.")

        dims = data.get("dimensions") or {}

        dim_col1, dim_col2, dim_col3 = st.columns(3)
        with dim_col1:
            width = st.text_input("Width", value=dims.get("width", ""), key="dim_width")
        with dim_col2:
            height = st.text_input("Height", value=dims.get("height", ""), key="dim_height")
        with dim_col3:
            depth = st.text_input("Depth", value=dims.get("depth", ""), key="dim_depth")

        dim_unit = st.selectbox(
            "Unit",
            options=["inches", "cm"],
            index=0 if dims.get("unit", "inches") == "inches" else 1,
            key="dim_unit",
        )

        st.markdown("---")
        st.markdown("**Product Weight**")

        weight_data = data.get("weight") or {}
        weight_col1, weight_col2 = st.columns(2)
        with weight_col1:
            weight_val = st.number_input(
                "Weight",
                value=float(weight_data.get("value", 0)),
                min_value=0.0,
                key="weight_value",
            )
        with weight_col2:
            weight_unit = st.selectbox(
                "Unit",
                options=["lbs", "kg", "oz", "g"],
                index=["lbs", "kg", "oz", "g"].index(weight_data.get("unit", "lbs"))
                if weight_data.get("unit") in ["lbs", "kg", "oz", "g"]
                else 0,
                key="weight_unit",
            )

    # Save button
    if st.button("💾 Save Product Assets", type="primary", key="save_assets"):
        data.update(
            {
                "dimensions": {
                    "width": width,
                    "height": height,
                    "depth": depth,
                    "unit": dim_unit,
                },
                "weight": {
                    "value": weight_val,
                    "unit": weight_unit,
                },
            }
        )
        service.update_section(UUID(session["id"]), "product_assets", data)
        st.success("Saved!")
        st.rerun()


# ============================================
# TAB 5: COMPETITORS
# ============================================


def render_competitors_tab(session: dict):
    """Render Competitors section."""
    service = get_onboarding_service()

    competitors = session.get("competitors") or []

    st.markdown("Add competitor information for competitive analysis.")

    # Add competitor form
    with st.form("add_competitor_form"):
        st.markdown("**Add New Competitor**")

        col1, col2 = st.columns(2)

        with col1:
            comp_name = st.text_input("Competitor Name *", key="comp_name")
            comp_website = st.text_input(
                "Website URL", placeholder="https://competitor.com", key="comp_website"
            )
            comp_amazon = st.text_input(
                "Amazon URL", placeholder="https://amazon.com/...", key="comp_amazon"
            )

        with col2:
            comp_fb_page = st.text_input(
                "Facebook Page URL",
                placeholder="https://facebook.com/competitor",
                key="comp_fb_page",
            )
            comp_ad_library = st.text_input(
                "Ad Library URL",
                placeholder="https://facebook.com/ads/library/?...",
                key="comp_ad_library",
            )

        submitted = st.form_submit_button("➕ Add Competitor", type="primary")
        if submitted:
            if comp_name:
                competitors.append(
                    {
                        "name": comp_name,
                        "website_url": comp_website,
                        "amazon_url": comp_amazon,
                        "facebook_page_url": comp_fb_page,
                        "ad_library_url": comp_ad_library,
                        "scraped": False,
                    }
                )
                service.update_section(UUID(session["id"]), "competitors", competitors)
                st.success(f"Added competitor: {comp_name}")
                st.rerun()
            else:
                st.warning("Please enter a competitor name")

    # Display existing competitors
    if competitors:
        st.markdown("---")
        st.markdown(f"**Added Competitors ({len(competitors)})**")

        for i, comp in enumerate(competitors):
            with st.expander(f"🏢 {comp['name']}", expanded=False):
                col1, col2 = st.columns([3, 1])

                with col1:
                    if comp.get("website_url"):
                        st.markdown(f"🌐 Website: {comp['website_url']}")
                    if comp.get("amazon_url"):
                        st.markdown(f"📦 Amazon: {comp['amazon_url']}")
                    if comp.get("facebook_page_url"):
                        st.markdown(f"📘 Facebook: {comp['facebook_page_url']}")
                    if comp.get("ad_library_url"):
                        st.markdown(f"📊 Ad Library: {comp['ad_library_url']}")

                with col2:
                    if st.button("🗑️ Remove", key=f"remove_comp_{i}"):
                        competitors.pop(i)
                        service.update_section(UUID(session["id"]), "competitors", competitors)
                        st.rerun()
    else:
        st.info("No competitors added yet.")


# ============================================
# TAB 6: TARGET AUDIENCE
# ============================================


def render_target_audience_tab(session: dict):
    """Render Target Audience section."""
    service = get_onboarding_service()

    data = session.get("target_audience") or {}

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("**Demographics**")
        demographics = data.get("demographics") or {}

        age_range = st.text_input(
            "Age Range",
            value=demographics.get("age_range", ""),
            placeholder="e.g., 25-45",
            key="demo_age",
        )

        gender = st.selectbox(
            "Primary Gender",
            options=["All", "Female", "Male", "Other"],
            index=["All", "Female", "Male", "Other"].index(demographics.get("gender", "All"))
            if demographics.get("gender") in ["All", "Female", "Male", "Other"]
            else 0,
            key="demo_gender",
        )

        location = st.text_input(
            "Location",
            value=demographics.get("location", ""),
            placeholder="e.g., USA, Urban areas",
            key="demo_location",
        )

        income = st.text_input(
            "Income Level",
            value=demographics.get("income_level", ""),
            placeholder="e.g., $75k-150k",
            key="demo_income",
        )

    with col2:
        st.markdown("**Pain Points** * (one per line)")
        pain_points_str = st.text_area(
            "Pain Points",
            value="\n".join(data.get("pain_points") or []),
            height=120,
            placeholder="What problems does your target audience face?\n\nExample:\n- Don't have time to cook healthy meals\n- Worried about their dog's joint health",
            key="pain_points",
            label_visibility="collapsed",
        )

        st.markdown("**Desires / Goals** * (one per line)")
        desires_str = st.text_area(
            "Desires & Goals",
            value="\n".join(data.get("desires_goals") or []),
            height=120,
            placeholder="What does your target audience want to achieve?\n\nExample:\n- Want their dog to stay active and playful\n- Want peace of mind about pet health",
            key="desires_goals",
            label_visibility="collapsed",
        )

    # Notes
    st.markdown("---")
    notes = st.text_area(
        "Additional Notes",
        value=data.get("notes", ""),
        height=80,
        placeholder="Any other relevant information about the target audience...",
        key="audience_notes",
    )

    # Save button
    if st.button("💾 Save Target Audience", type="primary", key="save_audience"):
        data.update(
            {
                "demographics": {
                    "age_range": age_range,
                    "gender": gender,
                    "location": location,
                    "income_level": income,
                },
                "pain_points": [p.strip() for p in pain_points_str.split("\n") if p.strip()],
                "desires_goals": [d.strip() for d in desires_str.split("\n") if d.strip()],
                "notes": notes,
            }
        )
        service.update_section(UUID(session["id"]), "target_audience", data)
        st.success("Saved!")
        st.rerun()


# ============================================
# MAIN PAGE
# ============================================

st.title("🚀 Client Onboarding")
st.markdown("Collect and organize information for new client onboarding.")
st.markdown("---")

# Session selector
render_session_selector()

# Main content (only if session selected)
if st.session_state.onboarding_session_id:
    service = get_onboarding_service()
    session = service.get_session(UUID(st.session_state.onboarding_session_id))

    if session:
        # Sidebar
        render_sidebar(session)

        # Main tabs
        st.markdown("---")

        tabs = st.tabs(
            [
                "1️⃣ Brand Basics",
                "2️⃣ Facebook/Meta",
                "3️⃣ Amazon",
                "4️⃣ Product Assets",
                "5️⃣ Competitors",
                "6️⃣ Target Audience",
            ]
        )

        with tabs[0]:
            render_brand_basics_tab(session)

        with tabs[1]:
            render_facebook_tab(session)

        with tabs[2]:
            render_amazon_tab(session)

        with tabs[3]:
            render_product_assets_tab(session)

        with tabs[4]:
            render_competitors_tab(session)

        with tabs[5]:
            render_target_audience_tab(session)
    else:
        st.error("Session not found. Please select or create a new session.")
else:
    st.info("👆 Select an existing session or create a new one to get started.")
