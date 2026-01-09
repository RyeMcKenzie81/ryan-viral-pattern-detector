"""
Client Onboarding - Streamlit page for collecting client information.

Features:
- Multi-section data entry form (5 tabs: Brand, Facebook, Products, Competitors, Audience)
- Per-product data collection (Amazon URL, dimensions, target audience)
- Auto-scraping with manual triggers
- Completeness tracker in sidebar
- Interview question generator
- Import to production (creates brand, products, competitors)

Part of the Client Onboarding Pipeline.
"""

import streamlit as st
import asyncio
import nest_asyncio
import time
from datetime import datetime
from uuid import UUID

# Allow nested event loops (needed for Pydantic AI agent.run_sync() in async context)
nest_asyncio.apply()

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


def get_ad_analysis_service():
    """Get AdAnalysisService instance."""
    from viraltracker.services.ad_analysis_service import AdAnalysisService

    return AdAnalysisService()


def get_group_resume_status(group: dict, max_ads: int = 50) -> dict:
    """
    Check how many ads in a group have already been analyzed.

    Returns dict with:
        - already_analyzed: count of ads already in DB
        - remaining: count of ads still to analyze
        - total: total ads (capped at max_ads)
        - has_resume: bool indicating if there's progress to resume
    """
    ads = group.get("ads", [])[:max_ads]
    if not ads:
        return {"already_analyzed": 0, "remaining": 0, "total": 0, "has_resume": False}

    # Get ad_archive_ids from the group
    ad_archive_ids = [
        ad.get('ad_archive_id') or ad.get('id')
        for ad in ads
        if ad.get('ad_archive_id') or ad.get('id')
    ]

    # Filter out None/empty values
    ad_archive_ids = [aid for aid in ad_archive_ids if aid and aid != 'None']

    if not ad_archive_ids:
        return {"already_analyzed": 0, "remaining": len(ads), "total": len(ads), "has_resume": False}

    try:
        ad_service = get_ad_analysis_service()
        already_done = ad_service._get_analyzed_ad_ids(ad_archive_ids)
        already_count = len(already_done)
        remaining = len(ads) - already_count
        return {
            "already_analyzed": already_count,
            "remaining": remaining,
            "total": len(ads),
            "has_resume": already_count > 0
        }
    except Exception:
        return {"already_analyzed": 0, "remaining": len(ads), "total": len(ads), "has_resume": False}


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
        "products": "Products",
        "competitors": "Competitors",
        "target_audience": "Target Audience",
    }

    for section_key, section_label in section_names.items():
        section_status = sections.get(section_key, {})

        if section_key in ("competitors", "products"):
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

    # Compliance Restrictions
    st.markdown("---")
    st.markdown("### ⚠️ Compliance Restrictions")
    st.caption(
        "Claims that must NOT appear in any ads for this brand. "
        "These apply to ALL products and offer variants."
    )

    disallowed_claims = data.get("disallowed_claims") or []
    disallowed_claims_str = st.text_area(
        "Disallowed Claims (one per line)",
        value="\n".join(disallowed_claims),
        height=100,
        placeholder="No FDA approval claims\nNo competitor name mentions\nNo medical treatment claims\nNo cure/treat language",
        key="brand_disallowed_claims",
    )

    # Save button
    if st.button("💾 Save Brand Basics", type="primary", key="save_brand_basics"):
        data.update(
            {
                "name": name,
                "website_url": website_url,
                "brand_voice": brand_voice,
                "disallowed_claims": [c.strip() for c in disallowed_claims_str.split("\n") if c.strip()],
            }
        )
        service.update_section(UUID(session["id"]), "brand_basics", data)
        st.success("Saved!")
        st.rerun()


# ============================================
# TAB 2: FACEBOOK/META
# ============================================


def render_facebook_tab(session: dict):
    """Render Facebook/Meta section with ad analysis for offer variants."""
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

    # Save basic info
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
    # AD SCRAPING & ANALYSIS
    # ============================================
    st.markdown("---")
    st.markdown("### 📊 Ad Analysis for Offer Variants")
    st.caption(
        "Scrape your existing Facebook ads to auto-discover landing pages and extract messaging "
        "for offer variants. Ads are grouped by destination URL."
    )

    if not ad_library_url:
        st.info("Enter an Ad Library URL above to enable ad scraping.")
        return

    # Scrape & Group button
    scrape_col1, scrape_col2 = st.columns([1, 3])
    with scrape_col1:
        if st.button("🔍 Scrape & Group Ads", key="scrape_group_ads", type="primary"):
            with st.spinner("Scraping Facebook ads... This may take a few minutes."):
                try:
                    from viraltracker.scrapers.facebook_ads import FacebookAdsScraper

                    scraper = FacebookAdsScraper()
                    df = scraper.search_ad_library(search_url=ad_library_url, count=100)

                    if df.empty:
                        st.warning("No ads found. Check the Ad Library URL.")
                        return

                    # Convert DataFrame to list of dicts for grouping
                    ads_list = df.to_dict('records')

                    # Group by URL using AdAnalysisService
                    ad_service = get_ad_analysis_service()
                    url_groups = ad_service.group_ads_by_url(ads_list)

                    # Store in session data
                    data["scraped_ads_count"] = len(df)
                    data["scraped_at"] = datetime.utcnow().isoformat()
                    data["url_groups"] = [
                        {
                            "normalized_url": g.normalized_url,
                            "display_url": g.display_url,
                            "ad_count": g.ad_count,
                            "preview_text": g.preview_text,
                            "preview_image_url": g.preview_image_url,
                            "status": "pending",  # pending, analyzed, skipped
                            "analysis_data": None,
                            "ads": g.ads,  # Store ads for later analysis
                        }
                        for g in url_groups
                    ]
                    service.update_section(UUID(session["id"]), "facebook_meta", data)
                    st.success(f"Found {len(df)} ads across {len(url_groups)} landing pages!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Scrape failed: {e}")

    with scrape_col2:
        if data.get("scraped_ads_count"):
            scraped_at = data.get("scraped_at", "")[:10] if data.get("scraped_at") else ""
            st.caption(f"✅ {data['scraped_ads_count']} ads scraped ({scraped_at})")

    # Display URL groups
    url_groups = data.get("url_groups") or []
    if url_groups:
        st.markdown("---")
        st.markdown(f"### 📍 Discovered Landing Pages ({len(url_groups)})")
        st.caption(
            "For each landing page, you can analyze the ads to auto-fill an offer variant, "
            "or skip if not relevant. **Select multiple to merge into one variant.**"
        )

        # Initialize selection state
        if "selected_url_groups" not in st.session_state:
            st.session_state.selected_url_groups = set()

        # Count pending groups for merge UI
        pending_indices = [i for i, g in enumerate(url_groups) if g.get("status", "pending") == "pending"]

        # Sync checkbox states to selected_url_groups BEFORE reading for button
        # (Checkboxes update session_state on click, but we need to read that state here)
        for idx in pending_indices:
            checkbox_key = f"select_group_{idx}"
            if checkbox_key in st.session_state:
                if st.session_state[checkbox_key]:
                    st.session_state.selected_url_groups.add(idx)
                else:
                    st.session_state.selected_url_groups.discard(idx)

        # Show merge button if 2+ groups are selected
        selected = st.session_state.selected_url_groups
        selected_pending = [i for i in selected if i in pending_indices]

        if len(selected_pending) >= 2:
            total_ads = sum(url_groups[i]["ad_count"] for i in selected_pending)
            merge_col1, merge_col2 = st.columns([2, 3])
            with merge_col1:
                if st.button(
                    f"🔀 Merge & Analyze Selected ({len(selected_pending)} groups, {total_ads} ads)",
                    type="primary",
                    key="merge_analyze_btn",
                ):
                    _analyze_merged_groups(session, data, list(selected_pending), service)
            with merge_col2:
                if st.button("Clear Selection", key="clear_selection_btn"):
                    st.session_state.selected_url_groups = set()
                    st.rerun()
            st.markdown("---")

        for idx, group in enumerate(url_groups):
            status = group.get("status", "pending")
            status_icon = {"pending": "⏳", "analyzed": "✅", "skipped": "⏭️", "merged": "🔀"}.get(status, "⏳")

            with st.expander(
                f"{status_icon} {group['display_url'][:60]}... ({group['ad_count']} ads)",
                expanded=(status == "pending"),  # Expand all pending groups
            ):
                # Preview row with checkbox for pending items
                if status == "pending":
                    check_col, prev_col1, prev_col2 = st.columns([0.5, 2.5, 1])
                    with check_col:
                        checkbox_key = f"select_group_{idx}"
                        # Initialize checkbox state from selected_url_groups if not yet set
                        if checkbox_key not in st.session_state:
                            st.session_state[checkbox_key] = idx in st.session_state.selected_url_groups
                        # Render checkbox - sync to selected_url_groups happens above before button
                        st.checkbox("", key=checkbox_key, label_visibility="collapsed")
                else:
                    prev_col1, prev_col2 = st.columns([3, 1])

                # Get resume status once for pending groups (used in multiple places)
                resume_status = get_group_resume_status(group) if status == "pending" else None

                with prev_col1:
                    if group.get("preview_text"):
                        st.caption(f"Preview: \"{group['preview_text']}...\"")
                    st.markdown(f"🔗 **URL:** `{group['display_url']}`")

                    # Show resume status for pending groups
                    if status == "pending" and resume_status:
                        if resume_status["has_resume"]:
                            st.caption(
                                f"📊 **Ads:** {group['ad_count']} "
                                f"(✅ {resume_status['already_analyzed']} done, "
                                f"⏳ {resume_status['remaining']} remaining)"
                            )
                        else:
                            st.caption(f"📊 **Ads:** {group['ad_count']}")
                    else:
                        st.caption(f"📊 **Ads:** {group['ad_count']}")

                with prev_col2:
                    if group.get("preview_image_url"):
                        try:
                            st.image(group["preview_image_url"], width=100)
                        except Exception:
                            pass

                # Action buttons
                if status == "pending":
                    action_col1, action_col2 = st.columns(2)
                    with action_col1:
                        # Update button text based on resume status
                        if resume_status["has_resume"]:
                            button_text = f"🔄 Resume ({resume_status['remaining']} remaining)"
                        else:
                            button_text = "🔬 Analyze & Create Variant"

                        if st.button(
                            button_text,
                            key=f"analyze_group_{idx}",
                            type="primary",
                        ):
                            _analyze_ad_group_and_create_variant(session, data, idx, service)

                    with action_col2:
                        if st.button("⏭️ Skip", key=f"skip_group_{idx}"):
                            data["url_groups"][idx]["status"] = "skipped"
                            service.update_section(UUID(session["id"]), "facebook_meta", data)
                            st.rerun()

                elif status == "analyzed":
                    analysis = group.get("analysis_data") or {}
                    st.success(f"✅ Analyzed! Created variant: **{analysis.get('suggested_name', 'Unnamed')}**")

                    # Show extracted data summary
                    with st.container():
                        col1, col2 = st.columns(2)
                        with col1:
                            if analysis.get("pain_points"):
                                st.markdown("**Pain Points:**")
                                for pp in analysis["pain_points"][:3]:
                                    st.caption(f"• {pp}")
                        with col2:
                            if analysis.get("benefits"):
                                st.markdown("**Benefits:**")
                                for b in analysis["benefits"][:3]:
                                    st.caption(f"• {b}")

                        # Mechanism fields if extracted
                        if analysis.get("mechanism_name"):
                            st.markdown(f"**Mechanism:** {analysis['mechanism_name']}")

                elif status == "merged":
                    merged_into = group.get("merged_into_variant", "Unknown")
                    merge_col1, merge_col2 = st.columns([4, 1])
                    with merge_col1:
                        st.info(f"🔀 Merged into variant: **{merged_into}**")
                    with merge_col2:
                        if st.button("🔄 Reset", key=f"reset_merged_{idx}", help="Clear merged status to re-analyze"):
                            data["url_groups"][idx]["status"] = "pending"
                            data["url_groups"][idx].pop("merged_into_variant", None)
                            data["url_groups"][idx].pop("analysis_data", None)
                            service.update_section(UUID(session["id"]), "facebook_meta", data)
                            st.rerun()

                elif status == "skipped":
                    st.caption("Skipped - no variant created")
                    if st.button("↩️ Undo Skip", key=f"unskip_{idx}"):
                        data["url_groups"][idx]["status"] = "pending"
                        service.update_section(UUID(session["id"]), "facebook_meta", data)
                        st.rerun()


def _analyze_ad_group_and_create_variant(session: dict, fb_data: dict, group_idx: int, service):
    """Analyze an ad group and create an offer variant from the results."""
    from viraltracker.services.ad_analysis_service import AdGroup

    group_data = fb_data["url_groups"][group_idx]

    # Reconstruct AdGroup from stored data
    ad_group = AdGroup(
        normalized_url=group_data["normalized_url"],
        display_url=group_data["display_url"],
        ad_count=group_data["ad_count"],
        ads=group_data.get("ads", []),
        preview_text=group_data.get("preview_text"),
        preview_image_url=group_data.get("preview_image_url"),
    )

    # Calculate how many ads will actually be analyzed
    max_ads_to_analyze = min(50, ad_group.ad_count)

    # Progress tracking UI
    st.info(f"🔄 Analyzing up to {max_ads_to_analyze} of {ad_group.ad_count} ads...")
    progress_bar = st.progress(0)
    status_text = st.empty()

    try:
        ad_service = get_ad_analysis_service()

        # Progress callback to update UI
        def progress_callback(current: int, total: int, status: str):
            progress = current / total if total > 0 else 0
            progress_bar.progress(progress)
            status_text.text(f"📊 {status} ({current}/{total} ads processed)")

        # Run async analysis
        synthesis = asyncio.run(
            ad_service.analyze_and_synthesize(
                ad_group,
                max_ads=max_ads_to_analyze,
                progress_callback=progress_callback,
            )
        )

        # Update progress to complete
        progress_bar.progress(1.0)
        resume_info = synthesis.get('_resume_info', {})
        skipped = resume_info.get('skipped_ads', 0)
        if skipped > 0:
            status_text.text(f"✅ Analysis complete! Resumed {skipped} from previous run, "
                           f"analyzed {resume_info.get('new_analyses', 0)} new ads.")
        else:
            status_text.text(f"✅ Analysis complete! Processed {synthesis.get('analyzed_count', 0)} ads.")

        # Store analysis results
        fb_data["url_groups"][group_idx]["status"] = "analyzed"
        fb_data["url_groups"][group_idx]["analysis_data"] = synthesis

        # Auto-create offer variant
        products = session.get("products") or []

        # If no products exist, create a placeholder product first
        if not products:
            brand_name = session.get("client_name") or session.get("session_name") or "Product"
            new_product = {
                "name": f"{brand_name} - Main Product",
                "description": "Auto-created product from ad analysis",
                "amazon_url": "",
                "product_url": group_data["display_url"],
                "offer_variants": [],
            }
            products = [new_product]
            st.info(f"📦 Auto-created product: {new_product['name']}")

        # Add variant to first product
        offer_variants = products[0].get("offer_variants") or []
        new_variant = {
            "name": synthesis.get("suggested_name", "Ad Analysis Variant"),
            "landing_page_url": synthesis.get("landing_page_url", ""),
            "pain_points": synthesis.get("pain_points", []),
            "desires_goals": synthesis.get("desires_goals", []),
            "benefits": synthesis.get("benefits", []),
            "mechanism_name": synthesis.get("mechanism_name", ""),
            "mechanism_problem": synthesis.get("mechanism_problem", ""),
            "mechanism_solution": synthesis.get("mechanism_solution", ""),
            "sample_hooks": synthesis.get("sample_hooks", []),
            "disallowed_claims": [],
            "required_disclaimers": None,
            "is_default": len(offer_variants) == 0,
            "source": "ad_analysis",
            "source_ad_count": synthesis.get("analyzed_count", 0),
        }
        offer_variants.append(new_variant)
        products[0]["offer_variants"] = offer_variants
        service.update_section(UUID(session["id"]), "products", products)

        service.update_section(UUID(session["id"]), "facebook_meta", fb_data)
        st.success(f"✅ Analysis complete! Created variant: **{synthesis.get('suggested_name')}**")
        st.info("👉 Go to the **Products tab** to view and edit the variant details.")
        time.sleep(2)
        st.rerun()

    except Exception as e:
        progress_bar.empty()
        status_text.empty()
        st.error(f"Analysis failed: {e}")
        import traceback
        st.code(traceback.format_exc())


def _analyze_merged_groups(session: dict, fb_data: dict, group_indices: list, service):
    """Analyze multiple URL groups together and create a single merged variant."""
    from viraltracker.services.ad_analysis_service import AdGroup

    # Combine all ads from selected groups
    all_ads = []
    all_urls = []
    total_ad_count = 0

    for idx in group_indices:
        group_data = fb_data["url_groups"][idx]
        all_ads.extend(group_data.get("ads", []))
        all_urls.append(group_data["display_url"])
        total_ad_count += group_data["ad_count"]

    # Create a merged AdGroup
    # Use the URL with most ads as the primary URL
    primary_idx = max(group_indices, key=lambda i: fb_data["url_groups"][i]["ad_count"])
    primary_group = fb_data["url_groups"][primary_idx]

    merged_group = AdGroup(
        normalized_url=primary_group["normalized_url"],
        display_url=primary_group["display_url"],
        ad_count=total_ad_count,
        ads=all_ads,
        preview_text=primary_group.get("preview_text"),
        preview_image_url=primary_group.get("preview_image_url"),
    )

    # Calculate how many ads will actually be analyzed
    max_ads_to_analyze = min(100, total_ad_count)

    # Progress tracking UI
    st.info(f"🔄 Analyzing up to {max_ads_to_analyze} ads from {len(group_indices)} URL groups...")
    progress_bar = st.progress(0)
    status_text = st.empty()

    try:
        ad_service = get_ad_analysis_service()

        # Progress callback to update UI
        def progress_callback(current: int, total: int, status: str):
            progress = current / total if total > 0 else 0
            progress_bar.progress(progress)
            status_text.text(f"📊 {status} ({current}/{total} ads processed)")

        # Run async analysis with higher ad limit for merged groups
        synthesis = asyncio.run(
            ad_service.analyze_and_synthesize(
                merged_group,
                max_ads=max_ads_to_analyze,
                progress_callback=progress_callback,
            )
        )

        # Update progress to complete
        progress_bar.progress(1.0)
        resume_info = synthesis.get('_resume_info', {})
        skipped = resume_info.get('skipped_ads', 0)
        if skipped > 0:
            status_text.text(f"✅ Analysis complete! Resumed {skipped} from previous run, "
                           f"analyzed {resume_info.get('new_analyses', 0)} new ads.")
        else:
            status_text.text(f"✅ Analysis complete! Processed {synthesis.get('analyzed_count', 0)} ads.")

        # Generate variant name from common theme
        variant_name = _infer_merged_variant_name(all_urls, synthesis)

        # Mark all selected groups as merged
        for idx in group_indices:
            fb_data["url_groups"][idx]["status"] = "merged"
            fb_data["url_groups"][idx]["merged_into_variant"] = variant_name
            fb_data["url_groups"][idx]["analysis_data"] = synthesis

        # Auto-create offer variant
        products = session.get("products") or []

        # If no products exist, create a placeholder product first
        if not products:
            # Infer product name from the variant/brand
            brand_name = session.get("client_name") or session.get("session_name") or "Product"
            new_product = {
                "name": f"{brand_name} - Main Product",
                "description": "Auto-created product from ad analysis",
                "amazon_url": "",
                "product_url": primary_group["display_url"],
                "offer_variants": [],
            }
            products = [new_product]
            st.info(f"📦 Auto-created product: {new_product['name']}")

        # Add variant to first product
        offer_variants = products[0].get("offer_variants") or []
        new_variant = {
            "name": variant_name,
            "landing_page_url": primary_group["display_url"],
            "pain_points": synthesis.get("pain_points", []),
            "desires_goals": synthesis.get("desires_goals", []),
            "benefits": synthesis.get("benefits", []),
            "mechanism_name": synthesis.get("mechanism_name", ""),
            "mechanism_problem": synthesis.get("mechanism_problem", ""),
            "mechanism_solution": synthesis.get("mechanism_solution", ""),
            "sample_hooks": synthesis.get("sample_hooks", []),
            "disallowed_claims": [],
            "required_disclaimers": None,
            "is_default": len(offer_variants) == 0,
            "source": "ad_analysis_merged",
            "source_ad_count": synthesis.get("analyzed_count", 0),
            "source_urls": all_urls,  # Track all merged URLs
        }
        offer_variants.append(new_variant)
        products[0]["offer_variants"] = offer_variants
        service.update_section(UUID(session["id"]), "products", products)

        service.update_section(UUID(session["id"]), "facebook_meta", fb_data)

        # Clear selection
        st.session_state.selected_url_groups = set()

        st.success(f"✅ Merged analysis complete! Created variant: **{variant_name}** with {synthesis.get('analyzed_count', 0)} ads analyzed.")
        st.info("👉 Go to the **Products tab** to view and edit the variant details.")
        time.sleep(2)  # Give user time to see the message
        st.rerun()

    except Exception as e:
        progress_bar.empty()
        status_text.empty()
        st.error(f"Merged analysis failed: {e}")
        import traceback
        st.code(traceback.format_exc())


def _infer_merged_variant_name(urls: list, synthesis: dict) -> str:
    """Infer a good variant name from merged URLs and synthesis data."""
    # Look for common patterns in URLs
    common_terms = []
    url_parts = [url.lower().split("/")[-1].replace("-", " ") for url in urls]

    # Find common words across URLs
    if url_parts:
        first_words = set(url_parts[0].split())
        for url_part in url_parts[1:]:
            first_words &= set(url_part.split())

        # Filter out generic words
        generic = {"pages", "page", "com", "www", "https", "http", "support", "for", "the", "a", "an"}
        common_terms = [w for w in first_words if w not in generic and len(w) > 2]

    if common_terms:
        # Use common terms as base
        name_base = " ".join(sorted(common_terms, key=len, reverse=True)[:3])
        return f"{name_base.title()} Angle"

    # Fall back to synthesis suggested name or first benefit
    if synthesis.get("suggested_name"):
        return synthesis["suggested_name"]
    if synthesis.get("benefits"):
        return f"{synthesis['benefits'][0][:30]} Angle"

    return "Merged Ad Analysis Variant"


def _analyze_amazon_listing(session: dict, products: list, prod_idx: int, service):
    """Analyze Amazon listing and pre-fill product/variant data."""
    prod = products[prod_idx]
    # Read from product or session state (for edit mode where URL isn't saved yet)
    amazon_url = prod.get("amazon_url") or st.session_state.get(f"amazon_url_{prod_idx}")

    if not amazon_url:
        st.warning("No Amazon URL provided")
        return

    # Save the URL to product so it persists
    prod["amazon_url"] = amazon_url

    with st.spinner("Analyzing Amazon listing... This may take 2-3 minutes."):
        try:
            amazon_service = get_amazon_service()
            result = amazon_service.analyze_listing_for_onboarding(
                amazon_url=amazon_url,
                include_reviews=True,
                max_reviews=200,
            )

            if not result.get("success"):
                st.error(f"Analysis failed: {result.get('error', 'Unknown error')}")
                return

            # Store raw analysis
            prod["amazon_analysis"] = result

            # Pre-fill product info
            product_info = result.get("product_info", {})
            if product_info.get("title") and not prod.get("description"):
                prod["description"] = product_info["title"]

            if product_info.get("dimensions"):
                dims = product_info["dimensions"]
                raw_str = dims.get("raw", "") if isinstance(dims, dict) else str(dims)

                # Parse raw dimension string like "3.82 x 1.89 x 1.85 inches; 2.08 ounces"
                parsed_dims = {"raw": raw_str}
                if raw_str:
                    import re
                    # Try to extract dimensions (W x H x D format)
                    dim_match = re.search(r'([\d.]+)\s*x\s*([\d.]+)\s*x\s*([\d.]+)\s*(inches?|in|cm|mm)?', raw_str, re.I)
                    if dim_match:
                        parsed_dims["width"] = dim_match.group(1)
                        parsed_dims["height"] = dim_match.group(2)
                        parsed_dims["depth"] = dim_match.group(3)
                        parsed_dims["unit"] = dim_match.group(4) or "inches"

                    # Try to extract weight if it's in the same string (after semicolon)
                    weight_match = re.search(r';\s*([\d.]+)\s*(ounces?|oz|pounds?|lbs?|kg|g)\b', raw_str, re.I)
                    if weight_match:
                        weight_val = weight_match.group(1)
                        weight_unit = weight_match.group(2).lower()
                        # Normalize unit names
                        if weight_unit in ['ounce', 'ounces']:
                            weight_unit = 'oz'
                        elif weight_unit in ['pound', 'pounds']:
                            weight_unit = 'lbs'
                        prod["weight"] = {"value": float(weight_val), "unit": weight_unit}

                prod["dimensions"] = parsed_dims

            if product_info.get("weight") and not prod.get("weight"):
                weight = product_info["weight"]
                if isinstance(weight, dict) and weight.get("raw"):
                    # Try to parse weight string
                    import re
                    raw_w = weight["raw"]
                    w_match = re.search(r'([\d.]+)\s*(ounces?|oz|pounds?|lbs?|kg|g)\b', raw_w, re.I)
                    if w_match:
                        weight_val = w_match.group(1)
                        weight_unit = w_match.group(2).lower()
                        if weight_unit in ['ounce', 'ounces']:
                            weight_unit = 'oz'
                        elif weight_unit in ['pound', 'pounds']:
                            weight_unit = 'lbs'
                        prod["weight"] = {"value": float(weight_val), "unit": weight_unit}
                    else:
                        prod["weight"] = {"raw": raw_w}
                else:
                    prod["weight"] = weight

            # Save product images from Amazon
            if product_info.get("images"):
                prod["images"] = product_info["images"][:10]

            # Create offer variant from Amazon messaging
            messaging = result.get("messaging", {})
            if messaging.get("benefits") or messaging.get("pain_points"):
                offer_variants = prod.get("offer_variants") or []

                # Check if Amazon variant already exists
                amazon_variant_exists = any(
                    ov.get("source") == "amazon_analysis" for ov in offer_variants
                )

                if not amazon_variant_exists:
                    new_variant = {
                        "name": f"Amazon Angle ({product_info.get('asin', 'Unknown')})",
                        "landing_page_url": amazon_url,
                        "pain_points": messaging.get("pain_points", [])[:7],
                        "desires_goals": messaging.get("desires_goals", [])[:7],
                        "benefits": messaging.get("benefits", [])[:7],
                        "disallowed_claims": [],
                        "required_disclaimers": None,
                        "is_default": len(offer_variants) == 0,
                        "source": "amazon_analysis",
                        "source_review_count": len(messaging.get("customer_language", [])),
                    }
                    offer_variants.append(new_variant)
                    prod["offer_variants"] = offer_variants

            # Update session
            products[prod_idx] = prod
            service.update_section(UUID(session["id"]), "products", products)

            # Show summary
            st.success("Amazon listing analyzed!")
            st.markdown("**Extracted:**")
            if product_info.get("title"):
                st.caption(f"• Title: {product_info['title'][:80]}...")
            if product_info.get("bullets"):
                st.caption(f"• {len(product_info['bullets'])} product bullets")
            if messaging.get("pain_points"):
                st.caption(f"• {len(messaging['pain_points'])} pain points from reviews")
            if messaging.get("benefits"):
                st.caption(f"• {len(messaging['benefits'])} benefits")
            if product_info.get("images"):
                st.caption(f"• {len(product_info['images'])} product images")

            st.rerun()

        except Exception as e:
            st.error(f"Amazon analysis failed: {e}")
            import traceback
            st.code(traceback.format_exc())


# ============================================
# TAB 3: PRODUCTS
# ============================================


def render_products_tab(session: dict):
    """Render Products section - per-product data collection."""
    service = get_onboarding_service()

    products = session.get("products") or []

    st.markdown("Add products that will be advertised. Each product can have its own Amazon URL, dimensions, and target audience.")

    # Add product form
    with st.form("add_product_form"):
        st.markdown("**Add New Product**")

        col1, col2 = st.columns(2)

        with col1:
            prod_name = st.text_input("Product Name *", key="new_prod_name")
            prod_description = st.text_area(
                "Description",
                height=80,
                placeholder="Brief description of the product...",
                key="new_prod_description",
            )
            prod_url = st.text_input(
                "Product URL",
                placeholder="https://brand.com/product-name",
                key="new_prod_url",
            )

        with col2:
            amazon_url = st.text_input(
                "Amazon URL",
                placeholder="https://amazon.com/dp/B0XXXXX...",
                key="new_prod_amazon_url",
            )
            st.caption("ASIN will be auto-extracted from the URL")

        submitted = st.form_submit_button("➕ Add Product", type="primary")
        if submitted:
            if prod_name:
                # Extract ASIN if Amazon URL provided
                asin = None
                if amazon_url:
                    try:
                        amazon_service = get_amazon_service()
                        asin, _ = amazon_service.parse_amazon_url(amazon_url)
                    except Exception:
                        pass

                new_product = {
                    "name": prod_name,
                    "description": prod_description,
                    "product_url": prod_url,
                    "amazon_url": amazon_url,
                    "asin": asin,
                    "dimensions": {},
                    "weight": {},
                    "target_audience": {},
                    "images": [],
                    "offer_variants": [],  # Landing page variants with messaging
                }
                products.append(new_product)
                service.update_section(UUID(session["id"]), "products", products)
                st.success(f"Added product: {prod_name}")
                st.rerun()
            else:
                st.warning("Please enter a product name")

    # Display existing products
    if products:
        st.markdown("---")
        st.markdown(f"**Products ({len(products)})**")

        for i, prod in enumerate(products):
            with st.expander(f"📦 {prod.get('name', 'Unnamed')}", expanded=False):
                col1, col2 = st.columns([3, 1])

                with col1:
                    # Basic info
                    if prod.get("description"):
                        st.caption(prod["description"])
                    if prod.get("product_url"):
                        st.markdown(f"🌐 Product URL: {prod['product_url']}")
                    if prod.get("amazon_url"):
                        asin_display = f" (ASIN: {prod['asin']})" if prod.get("asin") else ""
                        st.markdown(f"📦 Amazon: {prod['amazon_url']}{asin_display}")

                        # Amazon analysis button
                        amz_col1, amz_col2 = st.columns([1, 3])
                        with amz_col1:
                            if st.button("🔬 Analyze Listing", key=f"analyze_amazon_{i}"):
                                _analyze_amazon_listing(session, products, i, service)
                        with amz_col2:
                            if prod.get("amazon_analysis"):
                                st.caption("✅ Amazon data extracted")

                    # Dimensions & Weight
                    dims = prod.get("dimensions") or {}
                    weight = prod.get("weight") or {}
                    if dims.get("width") or dims.get("height") or weight.get("value"):
                        st.markdown("---")
                        dim_col1, dim_col2, dim_col3 = st.columns(3)
                        with dim_col1:
                            if dims:
                                unit = dims.get("unit", "inches")
                                dim_str = f"{dims.get('width', '?')} x {dims.get('height', '?')} x {dims.get('depth', '?')} {unit}"
                                st.caption(f"📐 Dimensions: {dim_str}")
                        with dim_col2:
                            if weight.get("value"):
                                st.caption(f"⚖️ Weight: {weight['value']} {weight.get('unit', 'lbs')}")

                    # Target audience
                    ta = prod.get("target_audience") or {}
                    if ta.get("pain_points") or ta.get("desires_goals"):
                        st.markdown("---")
                        st.markdown("**Product-specific Target Audience:**")
                        if ta.get("pain_points"):
                            st.caption(f"Pain points: {', '.join(ta['pain_points'][:3])}...")
                        if ta.get("desires_goals"):
                            st.caption(f"Desires: {', '.join(ta['desires_goals'][:3])}...")

                with col2:
                    if st.button("🗑️ Remove", key=f"remove_prod_{i}"):
                        products.pop(i)
                        service.update_section(UUID(session["id"]), "products", products)
                        st.rerun()

                # Edit product details
                st.markdown("---")

                # Product name (editable)
                prod_name_edit = st.text_input(
                    "Product Name",
                    value=prod.get("name", ""),
                    key=f"prod_name_{i}",
                )

                # Amazon URL field (editable)
                amazon_url = st.text_input(
                    "Amazon URL",
                    value=prod.get("amazon_url", ""),
                    placeholder="https://www.amazon.com/dp/...",
                    key=f"amazon_url_{i}",
                )
                if amazon_url and "amazon.com" in amazon_url:
                    try:
                        amazon_service = get_amazon_service()
                        asin, _ = amazon_service.parse_amazon_url(amazon_url)
                        if asin:
                            st.caption(f"ASIN will be extracted: {asin}")
                    except Exception:
                        pass

                    # Show Analyze Listing button if URL provided
                    if st.button("🔬 Analyze Listing", key=f"analyze_amazon_edit_{i}"):
                        _analyze_amazon_listing(session, products, i, service)

                edit_col1, edit_col2 = st.columns(2)

                with edit_col1:
                    st.markdown("**Dimensions**")
                    dims = prod.get("dimensions") or {}
                    dim_c1, dim_c2, dim_c3 = st.columns(3)
                    with dim_c1:
                        width = st.text_input("Width", value=dims.get("width", ""), key=f"dim_w_{i}")
                    with dim_c2:
                        height = st.text_input("Height", value=dims.get("height", ""), key=f"dim_h_{i}")
                    with dim_c3:
                        depth = st.text_input("Depth", value=dims.get("depth", ""), key=f"dim_d_{i}")
                    dim_unit = st.selectbox(
                        "Unit",
                        options=["inches", "cm"],
                        index=0 if dims.get("unit", "inches") == "inches" else 1,
                        key=f"dim_unit_{i}",
                    )

                    st.markdown("**Weight**")
                    weight = prod.get("weight") or {}
                    wt_c1, wt_c2 = st.columns(2)
                    with wt_c1:
                        weight_val = st.number_input(
                            "Weight",
                            value=float(weight.get("value", 0)),
                            min_value=0.0,
                            key=f"weight_val_{i}",
                        )
                    with wt_c2:
                        weight_unit = st.selectbox(
                            "Unit",
                            options=["lbs", "kg", "oz", "g"],
                            index=["lbs", "kg", "oz", "g"].index(weight.get("unit", "lbs"))
                            if weight.get("unit") in ["lbs", "kg", "oz", "g"]
                            else 0,
                            key=f"weight_unit_{i}",
                        )

                with edit_col2:
                    st.markdown("**Product Target Audience** (optional override)")
                    st.caption("Leave blank to use brand-level target audience")
                    ta = prod.get("target_audience") or {}

                    pain_points_str = st.text_area(
                        "Pain Points (one per line)",
                        value="\n".join(ta.get("pain_points") or []),
                        height=80,
                        key=f"prod_pain_{i}",
                    )

                    desires_str = st.text_area(
                        "Desires/Goals (one per line)",
                        value="\n".join(ta.get("desires_goals") or []),
                        height=80,
                        key=f"prod_desires_{i}",
                    )

                # ============================================
                # PRODUCT IMAGES SECTION
                # ============================================
                images = prod.get("images") or []
                if images:
                    st.markdown("---")
                    st.markdown("### 🖼️ Product Images")
                    st.caption(f"Scraped from Amazon listing ({len(images)} images)")

                    # Display images in a row (up to 5)
                    img_cols = st.columns(min(len(images), 5))
                    for img_idx, img_url in enumerate(images[:5]):
                        with img_cols[img_idx]:
                            try:
                                st.image(img_url, width=100)
                            except Exception:
                                st.caption("⚠️ Failed")

                    if len(images) > 5:
                        st.caption(f"... and {len(images) - 5} more images")

                # ============================================
                # OFFER VARIANTS SECTION
                # ============================================
                st.markdown("---")
                st.markdown("### 🎯 Offer Variants (Landing Pages)")
                st.caption(
                    "Add different landing pages for different marketing angles. "
                    "Each variant has its own URL and messaging (pain points, desires)."
                )

                offer_variants = prod.get("offer_variants") or []

                # Display existing offer variants
                if offer_variants:
                    for ov_idx, ov in enumerate(offer_variants):
                        default_badge = " ⭐" if ov.get("is_default") else ""
                        variant_name = ov.get('name', 'Unnamed')

                        # Header row with name, details toggle, and delete button
                        ov_col1, ov_col2, ov_col3 = st.columns([3, 1, 1])
                        with ov_col1:
                            st.markdown(f"**{variant_name}{default_badge}**")
                            st.caption(f"🔗 {ov.get('landing_page_url', 'No URL')}")
                        with ov_col2:
                            # Toggle for showing details
                            detail_key = f"show_ov_details_{i}_{ov_idx}"
                            if detail_key not in st.session_state:
                                st.session_state[detail_key] = False
                            if st.button(
                                "📋 Details" if not st.session_state[detail_key] else "➖ Hide",
                                key=f"toggle_details_{i}_{ov_idx}",
                            ):
                                st.session_state[detail_key] = not st.session_state[detail_key]
                                st.rerun()
                        with ov_col3:
                            if st.button("🗑️", key=f"remove_ov_{i}_{ov_idx}", help="Remove variant"):
                                offer_variants.pop(ov_idx)
                                prod["offer_variants"] = offer_variants
                                products[i] = prod
                                service.update_section(UUID(session["id"]), "products", products)
                                st.rerun()

                        # Show detail view if toggled
                        if st.session_state.get(f"show_ov_details_{i}_{ov_idx}", False):
                            detail_col1, detail_col2 = st.columns(2)

                            with detail_col1:
                                st.markdown("**Pain Points:**")
                                if ov.get("pain_points"):
                                    for pp in ov["pain_points"]:
                                        st.caption(f"• {pp}")
                                else:
                                    st.caption("_None_")

                                st.markdown("**Desires/Goals:**")
                                if ov.get("desires_goals"):
                                    for dg in ov["desires_goals"]:
                                        st.caption(f"• {dg}")
                                else:
                                    st.caption("_None_")

                            with detail_col2:
                                st.markdown("**Benefits:**")
                                if ov.get("benefits"):
                                    for b in ov["benefits"]:
                                        st.caption(f"• {b}")
                                else:
                                    st.caption("_None_")

                                st.markdown("**Mechanism:**")
                                if ov.get("mechanism_name"):
                                    st.caption(f"Name: {ov['mechanism_name']}")
                                if ov.get("mechanism_problem"):
                                    st.caption(f"UMP: {ov['mechanism_problem']}")
                                if ov.get("mechanism_solution"):
                                    st.caption(f"UMS: {ov['mechanism_solution']}")
                                if not any(ov.get(k) for k in ["mechanism_name", "mechanism_problem", "mechanism_solution"]):
                                    st.caption("_None_")

                            # Source info
                            if ov.get("source"):
                                st.caption(f"📊 Source: {ov['source']} | Reviews: {ov.get('source_review_count', 'N/A')}")

                        st.markdown("")  # Spacing between variants

                # Add new offer variant form (use toggle instead of nested expander)
                show_add_form_key = f"show_add_variant_{i}"
                if show_add_form_key not in st.session_state:
                    st.session_state[show_add_form_key] = len(offer_variants) == 0

                if st.button(
                    "➕ Add Offer Variant" if not st.session_state[show_add_form_key] else "➖ Hide Form",
                    key=f"toggle_add_ov_{i}",
                ):
                    st.session_state[show_add_form_key] = not st.session_state[show_add_form_key]
                    st.rerun()

                if st.session_state[show_add_form_key]:
                    st.markdown("---")
                    ov_name = st.text_input(
                        "Variant Name *",
                        placeholder="e.g., Blood Pressure Angle",
                        key=f"ov_name_{i}",
                    )

                    # Landing Page URL with Analyze button
                    url_col1, url_col2 = st.columns([4, 1])
                    with url_col1:
                        ov_url = st.text_input(
                            "Landing Page URL *",
                            placeholder="https://brand.com/blood-pressure",
                            key=f"ov_url_{i}",
                        )
                    with url_col2:
                        st.markdown("")  # Spacing
                        analyze_clicked = st.button(
                            "🔍 Analyze",
                            key=f"analyze_lp_{i}",
                            help="Scrape the landing page to auto-fill fields",
                            disabled=not ov_url,
                        )

                    # Handle analyze button click
                    if analyze_clicked and ov_url:
                        with st.spinner("Analyzing landing page..."):
                            try:
                                from viraltracker.services.product_offer_variant_service import (
                                    ProductOfferVariantService,
                                )

                                pov_service = ProductOfferVariantService()
                                analysis = pov_service.analyze_landing_page(ov_url)

                                if analysis.get("success"):
                                    # Store analysis in session state for pre-filling
                                    st.session_state[f"lp_analysis_{i}"] = analysis
                                    st.success("Page analyzed! Review the pre-filled fields below.")
                                    st.rerun()
                                else:
                                    st.error(f"Analysis failed: {analysis.get('error')}")
                            except Exception as e:
                                st.error(f"Error analyzing page: {e}")

                    # Get any stored analysis for pre-filling
                    lp_analysis = st.session_state.get(f"lp_analysis_{i}") or {}

                    ov_pain = st.text_area(
                        "Pain Points (one per line)",
                        value="\n".join(lp_analysis.get("pain_points", [])) if lp_analysis else "",
                        placeholder="High blood pressure\nCholesterol concerns\nHeart health worries",
                        height=80,
                        key=f"ov_pain_{i}",
                    )
                    ov_desires = st.text_area(
                        "Desires/Goals (one per line)",
                        value="\n".join(lp_analysis.get("desires_goals", [])) if lp_analysis else "",
                        placeholder="Better cardiovascular health\nMore energy\nPeace of mind",
                        height=80,
                        key=f"ov_desires_{i}",
                    )
                    ov_benefits = st.text_area(
                        "Key Benefits (one per line)",
                        value="\n".join(lp_analysis.get("benefits", [])) if lp_analysis else "",
                        placeholder="Supports healthy blood pressure\nPromotes circulation",
                        height=68,
                        key=f"ov_benefits_{i}",
                    )

                    # Compliance section
                    st.markdown("---")
                    st.markdown("**⚠️ Compliance (optional)**")
                    ov_disallowed = st.text_area(
                        "Disallowed Claims (one per line)",
                        placeholder="Cannot claim lowers blood pressure\nNo FDA approval claims",
                        height=68,
                        key=f"ov_disallowed_{i}",
                    )
                    ov_disclaimers = st.text_area(
                        "Required Disclaimers",
                        placeholder="These statements have not been evaluated by the FDA...",
                        height=68,
                        key=f"ov_disclaimers_{i}",
                    )

                    st.markdown("---")
                    ov_default = st.checkbox(
                        "Set as default variant",
                        value=len(offer_variants) == 0,  # First variant is default
                        key=f"ov_default_{i}",
                    )

                    if st.button("➕ Add Variant", key=f"add_ov_{i}"):
                        if ov_name and ov_url:
                            # Clear other defaults if setting this as default
                            if ov_default:
                                for existing_ov in offer_variants:
                                    existing_ov["is_default"] = False

                            new_variant = {
                                "name": ov_name,
                                "landing_page_url": ov_url,
                                "pain_points": [p.strip() for p in ov_pain.split("\n") if p.strip()],
                                "desires_goals": [d.strip() for d in ov_desires.split("\n") if d.strip()],
                                "benefits": [b.strip() for b in ov_benefits.split("\n") if b.strip()],
                                "disallowed_claims": [c.strip() for c in ov_disallowed.split("\n") if c.strip()],
                                "required_disclaimers": ov_disclaimers.strip() if ov_disclaimers else None,
                                "is_default": ov_default or len(offer_variants) == 0,
                            }
                            offer_variants.append(new_variant)
                            prod["offer_variants"] = offer_variants
                            products[i] = prod
                            service.update_section(UUID(session["id"]), "products", products)

                            # Clear the analysis from session state
                            if f"lp_analysis_{i}" in st.session_state:
                                del st.session_state[f"lp_analysis_{i}"]

                            st.success(f"Added variant: {ov_name}")
                            st.rerun()
                        else:
                            st.warning("Please enter variant name and landing page URL")

                # Save product updates
                if st.button("💾 Save Product Details", key=f"save_prod_{i}"):
                    # Save product name
                    if prod_name_edit:
                        prod["name"] = prod_name_edit

                    # Save Amazon URL and extract ASIN
                    prod["amazon_url"] = amazon_url
                    if amazon_url and "amazon.com" in amazon_url:
                        try:
                            amazon_service = get_amazon_service()
                            asin, _ = amazon_service.parse_amazon_url(amazon_url)
                            if asin:
                                prod["asin"] = asin
                        except Exception:
                            pass

                    prod["dimensions"] = {
                        "width": width,
                        "height": height,
                        "depth": depth,
                        "unit": dim_unit,
                    }
                    prod["weight"] = {
                        "value": weight_val,
                        "unit": weight_unit,
                    }
                    prod["target_audience"] = {
                        "pain_points": [p.strip() for p in pain_points_str.split("\n") if p.strip()],
                        "desires_goals": [d.strip() for d in desires_str.split("\n") if d.strip()],
                    }
                    products[i] = prod
                    service.update_section(UUID(session["id"]), "products", products)
                    st.success(f"Saved {prod['name']}!")
                    st.rerun()
    else:
        st.info("No products added yet. Add at least one product to advertise.")


# ============================================
# TAB 4: COMPETITORS
# ============================================


def _analyze_competitor_amazon(session: dict, competitors: list, comp_idx: int, service):
    """Analyze competitor's Amazon listing to extract product info and messaging."""
    comp = competitors[comp_idx]
    amazon_url = comp.get("amazon_url") or st.session_state.get(f"comp_amazon_url_{comp_idx}")

    if not amazon_url:
        st.warning("No Amazon URL provided")
        return

    # Save the URL
    comp["amazon_url"] = amazon_url

    with st.spinner(f"Analyzing {comp['name']}'s Amazon listing... This may take 2-3 minutes."):
        try:
            amazon_service = get_amazon_service()
            result = amazon_service.analyze_listing_for_onboarding(
                amazon_url=amazon_url,
                include_reviews=True,
                max_reviews=200,
            )

            if not result.get("success"):
                st.error(f"Analysis failed: {result.get('error', 'Unknown error')}")
                return

            # Store the analysis
            comp["amazon_analysis"] = result

            # Store images
            product_info = result.get("product_info", {})
            if product_info.get("images"):
                comp["images"] = product_info["images"][:10]

            # Update and save
            competitors[comp_idx] = comp
            service.update_section(UUID(session["id"]), "competitors", competitors)

            # Show summary
            st.success(f"Analyzed {comp['name']}'s Amazon listing!")
            messaging = result.get("messaging", {})
            if product_info.get("title"):
                st.caption(f"• Product: {product_info['title'][:60]}...")
            if messaging.get("pain_points"):
                st.caption(f"• {len(messaging['pain_points'])} pain points from reviews")
            if messaging.get("desires_goals"):
                st.caption(f"• {len(messaging['desires_goals'])} desires/goals")
            if product_info.get("images"):
                st.caption(f"• {len(product_info['images'])} product images")

            st.rerun()

        except Exception as e:
            st.error(f"Amazon analysis failed: {e}")
            import traceback
            st.code(traceback.format_exc())


def _scrape_competitor_ads(session: dict, competitors: list, comp_idx: int, service):
    """Scrape competitor's Facebook ads from their Ad Library URL."""
    from datetime import datetime

    comp = competitors[comp_idx]
    ad_library_url = comp.get("ad_library_url")

    if not ad_library_url:
        st.warning("No Ad Library URL provided")
        return

    with st.spinner(f"Scraping {comp['name']}'s Facebook ads... This may take a few minutes."):
        try:
            from viraltracker.scrapers.facebook_ads import FacebookAdsScraper
            from viraltracker.services.ad_analysis_service import AdAnalysisService

            scraper = FacebookAdsScraper()
            df = scraper.search_ad_library(search_url=ad_library_url, count=100)

            if df.empty:
                st.warning("No ads found. Check the Ad Library URL.")
                return

            # Convert DataFrame to list of dicts for grouping
            ads_list = df.to_dict("records")

            # Group by URL
            ad_service = AdAnalysisService()
            url_groups = ad_service.group_ads_by_url(ads_list)

            # Store in competitor data
            comp["scraped_ads_count"] = len(df)
            comp["scraped_at"] = datetime.utcnow().isoformat()
            comp["url_groups"] = [
                {
                    "normalized_url": g.normalized_url,
                    "display_url": g.display_url,
                    "ad_count": len(g.ads),
                    "ads": g.ads[:20],  # Store up to 20 ads per group
                }
                for g in url_groups
            ]

            # Update and save
            competitors[comp_idx] = comp
            service.update_section(UUID(session["id"]), "competitors", competitors)

            st.success(f"Scraped {len(df)} ads from {comp['name']}!")
            st.caption(f"Found {len(url_groups)} unique landing pages")
            st.rerun()

        except Exception as e:
            st.error(f"Ad scrape failed: {e}")
            import traceback
            st.code(traceback.format_exc())


def _analyze_competitor_ad_group(
    session: dict, competitors: list, comp_idx: int, grp_idx: int, service
):
    """Analyze a competitor's ad group to extract messaging."""
    comp = competitors[comp_idx]
    url_groups = comp.get("url_groups") or []

    if grp_idx >= len(url_groups):
        st.error("Invalid ad group index")
        return

    group = url_groups[grp_idx]
    ads = group.get("ads", [])

    if not ads:
        st.warning("No ads in this group to analyze")
        return

    with st.spinner(f"Analyzing {len(ads)} ads from {group.get('display_url', 'Unknown')}..."):
        try:
            from viraltracker.services.ad_analysis_service import AdAnalysisService, AdGroup

            ad_service = AdAnalysisService()

            # Reconstruct AdGroup object
            ad_group = AdGroup(
                normalized_url=group["normalized_url"],
                display_url=group["display_url"],
                ads=ads,
            )

            # Run analysis (synchronously for UI)
            import asyncio

            async def run_analysis():
                return await ad_service.analyze_and_synthesize(
                    ad_group=ad_group,
                    max_ads=10,
                )

            result = asyncio.get_event_loop().run_until_complete(run_analysis())

            # Extract messaging from result
            ad_messaging = {
                "pain_points": result.get("pain_points", []),
                "desires": result.get("desires", []),
                "benefits": result.get("benefits", []),
                "hooks": result.get("sample_hooks", []),
                "claims": result.get("claims", []),
                "target_audience": result.get("target_audience"),
                "analyzed_url": group["display_url"],
            }

            # Store in competitor (merge with existing)
            existing = comp.get("ad_messaging") or {}
            for key in ["pain_points", "desires", "benefits", "hooks", "claims"]:
                existing_list = existing.get(key, [])
                new_list = ad_messaging.get(key, [])
                # Merge and dedupe
                merged = list(dict.fromkeys(existing_list + new_list))
                ad_messaging[key] = merged[:10]  # Keep top 10

            comp["ad_messaging"] = ad_messaging

            # Update and save
            competitors[comp_idx] = comp
            service.update_section(UUID(session["id"]), "competitors", competitors)

            st.success(f"Analyzed ads from {group['display_url'][:40]}...")
            st.rerun()

        except Exception as e:
            st.error(f"Ad analysis failed: {e}")
            import traceback
            st.code(traceback.format_exc())


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
                    if comp.get("facebook_page_url"):
                        st.markdown(f"📘 Facebook: {comp['facebook_page_url']}")
                    if comp.get("ad_library_url"):
                        st.markdown(f"📊 Ad Library: {comp['ad_library_url']}")

                with col2:
                    if st.button("🗑️ Remove", key=f"remove_comp_{i}"):
                        competitors.pop(i)
                        service.update_section(UUID(session["id"]), "competitors", competitors)
                        st.rerun()

                # Amazon section with analysis
                st.markdown("---")
                amazon_url = comp.get("amazon_url", "")
                amazon_url = st.text_input(
                    "Amazon URL",
                    value=amazon_url,
                    placeholder="https://www.amazon.com/dp/...",
                    key=f"comp_amazon_url_{i}",
                )

                # Show ASIN if valid Amazon URL
                has_amazon_url = amazon_url and "amazon.com" in amazon_url
                if has_amazon_url:
                    try:
                        amazon_service = get_amazon_service()
                        asin, _ = amazon_service.parse_amazon_url(amazon_url)
                        if asin:
                            st.caption(f"ASIN: {asin}")
                    except Exception:
                        pass

                # Analyze Amazon button (always visible, disabled if no URL)
                amz_col1, amz_col2 = st.columns([1, 3])
                with amz_col1:
                    if st.button(
                        "🔬 Analyze Amazon",
                        key=f"analyze_comp_amazon_{i}",
                        disabled=not has_amazon_url,
                    ):
                        _analyze_competitor_amazon(session, competitors, i, service)
                with amz_col2:
                    if comp.get("amazon_analysis"):
                        st.caption("✅ Amazon data extracted")
                    elif not has_amazon_url:
                        st.caption("Enter Amazon URL to analyze")

                # Show Amazon analysis results if available
                amazon_analysis = comp.get("amazon_analysis") or {}
                if amazon_analysis:
                    product_info = amazon_analysis.get("product_info", {})
                    messaging = amazon_analysis.get("messaging", {})

                    # Product info
                    if product_info.get("title"):
                        st.markdown("**Product Info:**")
                        st.caption(f"📦 {product_info['title'][:100]}...")
                        if product_info.get("price"):
                            st.caption(f"💰 Price: {product_info['price']}")
                        if product_info.get("rating"):
                            st.caption(f"⭐ Rating: {product_info['rating']}")

                    # Show images if available
                    images = comp.get("images") or product_info.get("images") or []
                    if images:
                        st.markdown("**Product Images:**")
                        img_cols = st.columns(min(len(images), 4))
                        for img_idx, img_url in enumerate(images[:4]):
                            with img_cols[img_idx]:
                                try:
                                    st.image(img_url, width=80)
                                except Exception:
                                    pass

                    # Messaging insights
                    if messaging.get("pain_points") or messaging.get("desires_goals"):
                        st.markdown("**Competitor Messaging (from reviews):**")
                        msg_col1, msg_col2 = st.columns(2)
                        with msg_col1:
                            if messaging.get("pain_points"):
                                st.caption("Pain Points:")
                                for pp in messaging["pain_points"][:5]:
                                    st.caption(f"• {pp}")
                        with msg_col2:
                            if messaging.get("desires_goals"):
                                st.caption("Desires/Goals:")
                                for dg in messaging["desires_goals"][:5]:
                                    st.caption(f"• {dg}")

                # ============================================
                # Facebook Ads Section
                # ============================================
                st.markdown("---")
                st.markdown("**Facebook Ads**")

                ad_library_url = comp.get("ad_library_url", "")
                has_ad_library = ad_library_url and "facebook.com" in ad_library_url

                # Scrape Ads button
                fb_col1, fb_col2 = st.columns([1, 3])
                with fb_col1:
                    if st.button(
                        "🔍 Scrape Ads",
                        key=f"scrape_comp_ads_{i}",
                        disabled=not has_ad_library,
                    ):
                        _scrape_competitor_ads(session, competitors, i, service)
                with fb_col2:
                    if comp.get("scraped_ads_count"):
                        scraped_at = comp.get("scraped_at", "")[:10] if comp.get("scraped_at") else ""
                        st.caption(f"✅ {comp['scraped_ads_count']} ads scraped ({scraped_at})")
                    elif not has_ad_library:
                        st.caption("Enter Ad Library URL to scrape ads")

                # Show scraped ad groups
                url_groups = comp.get("url_groups") or []
                if url_groups:
                    st.markdown(f"**Landing Pages Found ({len(url_groups)}):**")
                    for grp_idx, group in enumerate(url_groups[:5]):  # Show top 5
                        grp_col1, grp_col2 = st.columns([3, 1])
                        with grp_col1:
                            st.caption(f"🔗 {group.get('display_url', 'Unknown')[:50]}...")
                            st.caption(f"   {group.get('ad_count', 0)} ads")
                        with grp_col2:
                            # Analyze button for each group
                            if st.button(
                                "📊 Analyze",
                                key=f"analyze_comp_adgroup_{i}_{grp_idx}",
                            ):
                                _analyze_competitor_ad_group(
                                    session, competitors, i, grp_idx, service
                                )

                    if len(url_groups) > 5:
                        st.caption(f"... and {len(url_groups) - 5} more landing pages")

                # Show ad analysis results if available
                ad_messaging = comp.get("ad_messaging") or {}
                if ad_messaging:
                    st.markdown("**Competitor Messaging (from ads):**")
                    ad_msg_col1, ad_msg_col2 = st.columns(2)
                    with ad_msg_col1:
                        if ad_messaging.get("pain_points"):
                            st.caption("Pain Points:")
                            for pp in ad_messaging["pain_points"][:5]:
                                st.caption(f"• {pp}")
                        if ad_messaging.get("hooks"):
                            st.caption("Hooks:")
                            for hook in ad_messaging["hooks"][:3]:
                                st.caption(f"• {hook}")
                    with ad_msg_col2:
                        if ad_messaging.get("desires"):
                            st.caption("Desires:")
                            for d in ad_messaging["desires"][:5]:
                                st.caption(f"• {d}")
                        if ad_messaging.get("benefits"):
                            st.caption("Benefits:")
                            for b in ad_messaging["benefits"][:5]:
                                st.caption(f"• {b}")

                # Save competitor updates
                if st.button("💾 Save Competitor", key=f"save_comp_{i}"):
                    comp["amazon_url"] = amazon_url
                    competitors[i] = comp
                    service.update_section(UUID(session["id"]), "competitors", competitors)
                    st.success(f"Saved {comp['name']}!")
                    st.rerun()
    else:
        st.info("No competitors added yet.")


# ============================================
# TAB 5: TARGET AUDIENCE
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
                "3️⃣ Products",
                "4️⃣ Competitors",
                "5️⃣ Target Audience",
            ]
        )

        with tabs[0]:
            render_brand_basics_tab(session)

        with tabs[1]:
            render_facebook_tab(session)

        with tabs[2]:
            render_products_tab(session)

        with tabs[3]:
            render_competitors_tab(session)

        with tabs[4]:
            render_target_audience_tab(session)
    else:
        st.error("Session not found. Please select or create a new session.")
else:
    st.info("👆 Select an existing session or create a new one to get started.")
