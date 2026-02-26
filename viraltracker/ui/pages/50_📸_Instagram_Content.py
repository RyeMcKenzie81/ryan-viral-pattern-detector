"""
Instagram Content Library - Research and discover high-performing Instagram content.

Tabs:
1. Watched Accounts - Add/remove IG accounts to monitor per brand
2. Content Library - Browse scraped posts with filters and engagement stats
3. Top Content - Outlier dashboard showing highest-performing posts
4. Analysis - Gemini-powered content analysis (Pass 1 structural, Pass 2 production)

Part of the Video Tools Suite (Phases 1 & 2).
"""

import asyncio
import streamlit as st
from datetime import datetime

# Page config (must be first Streamlit call)
st.set_page_config(
    page_title="Instagram Content",
    page_icon="📸",
    layout="wide",
)

# Authentication
from viraltracker.ui.auth import require_auth
require_auth()
from viraltracker.ui.utils import require_feature
require_feature("instagram_content", "Instagram Content")


# ============================================================================
# Helper Functions
# ============================================================================

def get_service():
    """Get InstagramContentService instance."""
    from viraltracker.services.instagram_content_service import InstagramContentService
    return InstagramContentService()


def get_analysis_service():
    """Get InstagramAnalysisService instance."""
    from viraltracker.services.instagram_analysis_service import InstagramAnalysisService
    return InstagramAnalysisService()


def get_org_id() -> str:
    """Get current organization ID."""
    from viraltracker.ui.utils import get_current_organization_id
    return get_current_organization_id()


def format_number(n) -> str:
    """Format large numbers for display (e.g., 1.2K, 3.4M)."""
    if n is None:
        return "—"
    n = int(n)
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def format_date(date_str) -> str:
    """Format a date string for display."""
    if not date_str:
        return "Never"
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        return dt.strftime("%b %d, %Y %H:%M")
    except Exception:
        return str(date_str)[:16]


# ============================================================================
# Session State
# ============================================================================

if "ig_scraping" not in st.session_state:
    st.session_state.ig_scraping = False
if "ig_calculating_outliers" not in st.session_state:
    st.session_state.ig_calculating_outliers = False
if "ig_downloading_media" not in st.session_state:
    st.session_state.ig_downloading_media = False
if "ig_analyzing" not in st.session_state:
    st.session_state.ig_analyzing = False
if "ig_batch_analyzing" not in st.session_state:
    st.session_state.ig_batch_analyzing = False


# ============================================================================
# Main Page
# ============================================================================

st.title("📸 Instagram Content Library")

# Brand selector
from viraltracker.ui.utils import render_brand_selector
brand_id = render_brand_selector(key="ig_content_brand_selector")
if not brand_id:
    st.stop()

org_id = get_org_id()
service = get_service()

# Stats bar
stats = service.get_content_stats(brand_id, org_id)
col1, col2, col3, col4 = st.columns(4)
col1.metric("Watched Accounts", stats["watched_accounts"])
col2.metric("Total Posts", format_number(stats["total_posts"]))
col3.metric("Outlier Posts", format_number(stats["outlier_posts"]))
col4.metric("Media Downloaded", format_number(stats["media_downloaded"]))

# Tabs
tab_accounts, tab_library, tab_top, tab_analysis = st.tabs([
    "Watched Accounts",
    "Content Library",
    "Top Content",
    "Analysis",
])


# ============================================================================
# Tab 1: Watched Accounts
# ============================================================================

with tab_accounts:
    st.subheader("Manage Watched Accounts")
    st.caption("Add Instagram accounts to monitor for content research. Only outlier posts will have media downloaded to save storage.")

    # Add new account form
    with st.form("add_account_form"):
        col_user, col_notes, col_freq = st.columns([2, 2, 1])
        with col_user:
            new_username = st.text_input(
                "Instagram Username",
                placeholder="username (without @)",
            )
        with col_notes:
            new_notes = st.text_input("Notes (optional)", placeholder="Why are we watching this account?")
        with col_freq:
            new_freq = st.selectbox(
                "Scrape Frequency",
                options=[24, 72, 168, 336],
                format_func=lambda h: {24: "Daily", 72: "Every 3 days", 168: "Weekly", 336: "Bi-weekly"}[h],
                index=2,
            )

        submitted = st.form_submit_button("Add Account", type="primary")
        if submitted and new_username:
            try:
                result = service.add_watched_account(
                    brand_id=brand_id,
                    username=new_username,
                    organization_id=org_id,
                    notes=new_notes or None,
                    scrape_frequency_hours=new_freq,
                )
                st.success(f"Added @{new_username.strip().lstrip('@').lower()} to watch list")
                st.rerun()
            except ValueError as e:
                st.error(str(e))
            except Exception as e:
                st.error(f"Error adding account: {e}")

    st.divider()

    # List existing accounts
    accounts = service.list_watched_accounts(brand_id, org_id, include_inactive=True)

    if not accounts:
        st.info("No watched accounts yet. Add an Instagram account above to start monitoring content.")
    else:
        # Batch actions
        col_scrape, col_outlier, col_download = st.columns(3)
        with col_scrape:
            if st.button("Scrape All Active", type="primary", disabled=st.session_state.ig_scraping):
                st.session_state.ig_scraping = True
                with st.spinner("Scraping all active accounts..."):
                    try:
                        result = service.scrape_all_active(brand_id, org_id, force=False)
                        st.success(
                            f"Scraped {result['accounts_scraped']} accounts, "
                            f"{result['total_posts']} posts. "
                            f"({result['accounts_skipped']} skipped, {len(result['errors'])} errors)"
                        )
                        if result["errors"]:
                            for err in result["errors"]:
                                st.warning(f"@{err['username']}: {err['error']}")
                    except Exception as e:
                        st.error(f"Scrape failed: {e}")
                    finally:
                        st.session_state.ig_scraping = False
                        st.rerun()

        with col_outlier:
            if st.button("Calculate Outliers", disabled=st.session_state.ig_calculating_outliers):
                st.session_state.ig_calculating_outliers = True
                with st.spinner("Calculating outliers..."):
                    try:
                        result = service.calculate_outliers(brand_id, org_id)
                        st.success(
                            f"Found {result['outliers_found']} outliers "
                            f"out of {result['total_posts']} posts"
                        )
                    except Exception as e:
                        st.error(f"Outlier detection failed: {e}")
                    finally:
                        st.session_state.ig_calculating_outliers = False
                        st.rerun()

        with col_download:
            if st.button("Download Outlier Media", disabled=st.session_state.ig_downloading_media):
                st.session_state.ig_downloading_media = True
                with st.spinner("Downloading media for outlier posts..."):
                    try:
                        result = service.download_outlier_media(brand_id, org_id)
                        st.success(
                            f"Downloaded {result['downloaded']} files. "
                            f"({result['failed']} failed, {result['skipped']} already had media)"
                        )
                    except Exception as e:
                        st.error(f"Download failed: {e}")
                    finally:
                        st.session_state.ig_downloading_media = False
                        st.rerun()

        st.divider()

        # Account cards
        for watched in accounts:
            account = watched.get("accounts", {})
            username = account.get("platform_username", "unknown")
            is_active = watched.get("is_active", True)

            with st.container(border=True):
                col_info, col_stats, col_actions = st.columns([3, 2, 1])

                with col_info:
                    status_icon = "🟢" if is_active else "🔴"
                    verified = " ✓" if account.get("is_verified") else ""
                    st.markdown(f"### {status_icon} @{username}{verified}")
                    if account.get("display_name"):
                        st.caption(account["display_name"])
                    if account.get("bio"):
                        st.text(account["bio"][:150] + ("..." if len(account.get("bio", "")) > 150 else ""))
                    if watched.get("notes"):
                        st.caption(f"Notes: {watched['notes']}")

                with col_stats:
                    st.metric("Followers", format_number(account.get("follower_count")))
                    st.caption(f"Last scraped: {format_date(watched.get('last_scraped_at'))}")

                with col_actions:
                    # Individual scrape
                    if is_active:
                        if st.button("Scrape", key=f"scrape_{watched['id']}"):
                            with st.spinner(f"Scraping @{username}..."):
                                try:
                                    result = service.scrape_account(watched["id"], force=True)
                                    if result.get("skipped_reason"):
                                        st.warning(result["skipped_reason"])
                                    else:
                                        st.success(f"{result['posts_scraped']} posts scraped")
                                        st.rerun()
                                except Exception as e:
                                    st.error(str(e))

                    # Activate/deactivate
                    if is_active:
                        if st.button("Deactivate", key=f"deactivate_{watched['id']}"):
                            service.remove_watched_account(watched["id"])
                            st.rerun()
                    else:
                        if st.button("Reactivate", key=f"reactivate_{watched['id']}"):
                            service.reactivate_watched_account(watched["id"])
                            st.rerun()


# ============================================================================
# Tab 2: Content Library
# ============================================================================

with tab_library:
    st.subheader("Content Library")

    # Filters
    col_days, col_type, col_outlier_filter = st.columns(3)
    with col_days:
        days_back = st.selectbox(
            "Time Range",
            options=[7, 14, 30, 60, 90],
            format_func=lambda d: f"Last {d} days",
            index=2,
            key="lib_days",
        )
    with col_type:
        media_filter = st.selectbox(
            "Media Type",
            options=[None, "video", "image", "text"],
            format_func=lambda x: "All Types" if x is None else x.capitalize(),
            key="lib_media_type",
        )
    with col_outlier_filter:
        outliers_only = st.checkbox("Outliers Only", value=False, key="lib_outliers_only")

    # Fetch posts
    posts = service.get_top_content(
        brand_id=brand_id,
        organization_id=org_id,
        days=days_back,
        limit=100,
        outliers_only=outliers_only,
        media_type=media_filter,
    )

    if not posts:
        st.info("No posts found. Try scraping accounts first or adjusting filters.")
    else:
        st.caption(f"Showing {len(posts)} posts")

        # Display as table
        for post in posts:
            account = post.get("accounts", {})
            with st.container(border=True):
                col_account, col_content, col_engagement = st.columns([1, 3, 2])

                with col_account:
                    st.markdown(f"**@{account.get('platform_username', '?')}**")
                    st.caption(format_date(post.get("posted_at")))
                    if post.get("is_outlier"):
                        score = post.get("outlier_score")
                        st.markdown(f"⭐ **Outlier** (z={score:.1f})" if score else "⭐ **Outlier**")
                    media_badge = post.get("media_type") or post.get("video_type") or ""
                    if media_badge:
                        st.caption(f"Type: {media_badge}")

                with col_content:
                    caption_text = post.get("caption", "") or ""
                    if len(caption_text) > 200:
                        caption_text = caption_text[:200] + "..."
                    st.text(caption_text if caption_text else "(no caption)")
                    if post.get("post_url"):
                        st.markdown(f"[View on Instagram]({post['post_url']})")

                with col_engagement:
                    eng_cols = st.columns(4)
                    eng_cols[0].metric("Views", format_number(post.get("views")))
                    eng_cols[1].metric("Likes", format_number(post.get("likes")))
                    eng_cols[2].metric("Comments", format_number(post.get("comments")))
                    duration = post.get("length_sec")
                    if duration:
                        eng_cols[3].metric("Duration", f"{duration}s")


# ============================================================================
# Tab 3: Top Content (Outlier Dashboard)
# ============================================================================

with tab_top:
    st.subheader("Top Content - Outlier Dashboard")

    col_range, col_method = st.columns(2)
    with col_range:
        top_days = st.selectbox(
            "Time Range",
            options=[7, 14, 30, 60, 90],
            format_func=lambda d: f"Last {d} days",
            index=2,
            key="top_days",
        )
    with col_method:
        st.info("Outlier detection uses z-score method by default. Click 'Calculate Outliers' in the Watched Accounts tab to update.")

    # Get outlier posts
    outlier_posts = service.get_top_content(
        brand_id=brand_id,
        organization_id=org_id,
        days=top_days,
        limit=50,
        outliers_only=True,
    )

    if not outlier_posts:
        st.info("No outlier posts found. Run 'Calculate Outliers' in the Watched Accounts tab first.")
    else:
        st.success(f"Found {len(outlier_posts)} outlier posts")

        # Summary metrics
        if outlier_posts:
            total_views = sum(p.get("views") or 0 for p in outlier_posts)
            avg_likes = sum(p.get("likes") or 0 for p in outlier_posts) / len(outlier_posts)
            video_count = sum(1 for p in outlier_posts if p.get("media_type") == "video" or p.get("video_type"))

            mcol1, mcol2, mcol3 = st.columns(3)
            mcol1.metric("Total Outlier Views", format_number(total_views))
            mcol2.metric("Avg Likes per Outlier", format_number(int(avg_likes)))
            mcol3.metric("Video Outliers", video_count)

        st.divider()

        # Outlier cards
        for rank, post in enumerate(outlier_posts, 1):
            account = post.get("accounts", {})
            score = post.get("outlier_score")

            with st.container(border=True):
                col_rank, col_info, col_metrics = st.columns([0.5, 3, 2])

                with col_rank:
                    st.markdown(f"### #{rank}")
                    if score is not None:
                        st.caption(f"z={score:.1f}")

                with col_info:
                    st.markdown(f"**@{account.get('platform_username', '?')}** — {format_date(post.get('posted_at'))}")
                    caption_text = post.get("caption", "") or ""
                    if len(caption_text) > 300:
                        caption_text = caption_text[:300] + "..."
                    st.text(caption_text if caption_text else "(no caption)")
                    if post.get("post_url"):
                        st.markdown(f"[View on Instagram]({post['post_url']})")

                with col_metrics:
                    m1, m2, m3, m4 = st.columns(4)
                    m1.metric("Views", format_number(post.get("views")))
                    m2.metric("Likes", format_number(post.get("likes")))
                    m3.metric("Comments", format_number(post.get("comments")))
                    m4.metric("Shares", format_number(post.get("shares")))

                    # Show media info
                    media = service.get_post_media(post["id"])
                    if media:
                        st.caption(f"📁 {len(media)} media files downloaded")


# ============================================================================
# Tab 4: Analysis
# ============================================================================

def _run_async(coro):
    """Run an async coroutine from sync Streamlit context."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, coro).result()
        return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


def _render_eval_badge(eval_scores: dict) -> str:
    """Render eval score as a colored badge."""
    if not eval_scores:
        return ""
    overall = eval_scores.get("overall_score", 0)
    if overall >= 0.8:
        return f"Eval: {overall:.0%}"
    elif overall >= 0.6:
        return f"Eval: {overall:.0%}"
    else:
        return f"Eval: {overall:.0%} (needs review)"


def _render_video_analysis(analysis: dict):
    """Render a video analysis result in expandable sections."""
    # Header info
    col_status, col_model, col_eval = st.columns(3)
    with col_status:
        status = analysis.get("status", "unknown")
        if status == "ok":
            st.success("Pass 1 Complete")
        elif status == "validation_failed":
            st.warning("Validation Issues")
        else:
            st.error(f"Status: {status}")

    with col_model:
        st.caption(f"Model: {analysis.get('model_used', '?')}")
        if analysis.get("production_storyboard"):
            st.caption("Pass 2: Complete")
        else:
            st.caption("Pass 2: Not run")

    with col_eval:
        eval_scores = analysis.get("eval_scores", {})
        if eval_scores:
            st.caption(_render_eval_badge(eval_scores))

    # People detection
    if analysis.get("has_talking_head"):
        st.info(f"Talking Head detected | {analysis.get('people_detected', 0)} people")

    # Transcript
    with st.expander("Transcript", expanded=False):
        transcript = analysis.get("full_transcript", "")
        if transcript:
            st.text(transcript)
        else:
            st.caption("No transcript extracted")

        segments = analysis.get("transcript_segments") or []
        if segments:
            st.caption(f"{len(segments)} segments")
            for seg in segments[:10]:
                st.caption(
                    f"[{seg.get('start_sec', 0):.1f}s - {seg.get('end_sec', 0):.1f}s] "
                    f"{seg.get('text', '')}"
                )
            if len(segments) > 10:
                st.caption(f"... and {len(segments) - 10} more segments")

    # Hook analysis
    with st.expander("Hook Analysis", expanded=False):
        hook_cols = st.columns(2)
        with hook_cols[0]:
            st.markdown("**Spoken hook:**")
            st.text(analysis.get("hook_transcript_spoken") or "(none)")
            st.markdown("**Overlay hook:**")
            st.text(analysis.get("hook_transcript_overlay") or "(none)")
        with hook_cols[1]:
            st.markdown(f"**Hook type:** {analysis.get('hook_type', '?')}")
            st.markdown(f"**Visual type:** {analysis.get('hook_visual_type', '?')}")
            st.markdown("**Visual description:**")
            st.text(analysis.get("hook_visual_description") or "(none)")

        signals = analysis.get("hook_effectiveness_signals") or {}
        if signals:
            st.caption(
                f"Spoken: {'Yes' if signals.get('spoken_present') else 'No'} | "
                f"Overlay: {'Yes' if signals.get('overlay_present') else 'No'} | "
                f"Combo score: {signals.get('combination_score', 0):.1f}"
            )

    # Storyboard
    with st.expander("Storyboard", expanded=False):
        storyboard = analysis.get("storyboard") or []
        if storyboard:
            for scene in storyboard:
                ts = scene.get("timestamp_sec", 0)
                desc = scene.get("scene_description", "")
                elements = ", ".join(scene.get("key_elements", []))
                overlay = scene.get("text_overlay")
                st.markdown(f"**{ts:.1f}s** — {desc}")
                if elements:
                    st.caption(f"Elements: {elements}")
                if overlay:
                    st.caption(f"Text: {overlay}")
                st.divider()
        else:
            st.caption("No storyboard extracted")

    # Production storyboard (Pass 2)
    if analysis.get("production_storyboard"):
        with st.expander("Production Shot Sheet (Pass 2)", expanded=False):
            for beat in analysis["production_storyboard"]:
                idx = beat.get("beat_index", "?")
                start = beat.get("timestamp_start_sec", 0)
                end = beat.get("timestamp_end_sec", 0)
                st.markdown(f"**Beat {idx}** ({start:.1f}s - {end:.1f}s)")
                st.caption(
                    f"Camera: {beat.get('camera_shot_type', '?')} | "
                    f"Movement: {beat.get('camera_movement', '?')} | "
                    f"Angle: {beat.get('camera_angle', '?')}"
                )
                st.caption(f"Subject: {beat.get('subject_action', '?')}")
                st.caption(f"Audio: {beat.get('audio_type', '?')}")
                st.caption(f"Transition: {beat.get('transition_to_next', '?')}")
                st.divider()

    # Eval scores detail
    with st.expander("Eval Scores (VA-1 to VA-8)", expanded=False):
        eval_scores = analysis.get("eval_scores") or {}
        if eval_scores:
            check_names = {
                "va1_duration_match": "VA-1 Duration Match",
                "va2_transcript_present": "VA-2 Transcript Present",
                "va3_storyboard_coverage": "VA-3 Storyboard Coverage",
                "va4_timestamp_monotonicity": "VA-4 Timestamp Monotonicity",
                "va5_segment_coverage": "VA-5 Segment Coverage",
                "va6_hook_window": "VA-6 Hook Window",
                "va7_json_completeness": "VA-7 JSON Completeness",
                "va8_overlay_coherence": "VA-8 Overlay Coherence",
            }
            for key, label in check_names.items():
                score = eval_scores.get(key)
                if score is not None:
                    icon = "+" if score >= 0.8 else ("~" if score >= 0.5 else "-")
                    st.caption(f"[{icon}] {label}: {score:.0%}")
            st.markdown(f"**Overall: {eval_scores.get('overall_score', 0):.0%}**")
        else:
            st.caption("No eval scores")


def _render_image_analysis(analysis: dict):
    """Render an image analysis result."""
    st.markdown(f"**{analysis.get('image_description', '(no description)')[:200]}**")
    if analysis.get("image_style"):
        st.caption(f"Style: {analysis['image_style']}")
    if analysis.get("image_text_content"):
        st.caption(f"Text in image: {analysis['image_text_content']}")
    if analysis.get("recreation_notes"):
        with st.expander("Recreation Notes"):
            st.text(analysis["recreation_notes"])
    if analysis.get("people_detected", 0) > 0:
        st.caption(f"People: {analysis['people_detected']}")


with tab_analysis:
    st.subheader("Content Analysis")
    st.caption(
        "Two-pass Gemini analysis: Pass 1 (Flash) extracts transcript, hooks, storyboard. "
        "Pass 2 (Pro) adds production shot sheet for approved candidates."
    )

    analysis_service = get_analysis_service()

    # Batch analyze button
    if st.button(
        "Analyze All Outliers",
        type="primary",
        disabled=st.session_state.ig_batch_analyzing,
        help="Run Pass 1 analysis on all outlier posts with downloaded media",
    ):
        st.session_state.ig_batch_analyzing = True
        with st.spinner("Running batch analysis (this may take a few minutes)..."):
            try:
                result = _run_async(
                    analysis_service.batch_analyze_outliers(brand_id, org_id)
                )
                st.success(
                    f"Analyzed {result['analyzed']} posts. "
                    f"({result['skipped']} skipped, {result['failed']} failed)"
                )
                if result.get("errors"):
                    for err in result["errors"][:5]:
                        st.warning(f"Media {err['media_id']}: {err['error'][:100]}")
            except Exception as e:
                st.error(f"Batch analysis failed: {e}")
            finally:
                st.session_state.ig_batch_analyzing = False
                st.rerun()

    st.divider()

    # Show existing analyses
    analyses = analysis_service.get_analyses_for_brand(brand_id, org_id, limit=50)

    if not analyses:
        st.info(
            "No analyses yet. Use 'Analyze All Outliers' above, or analyze "
            "individual posts from the outlier list below."
        )

        # Show outlier posts that can be analyzed
        st.subheader("Posts Available for Analysis")
        outlier_posts_for_analysis = service.get_top_content(
            brand_id=brand_id,
            organization_id=org_id,
            days=90,
            limit=20,
            outliers_only=True,
        )

        for post in outlier_posts_for_analysis:
            post_account = post.get("accounts", {})
            post_media = service.get_post_media(post["id"])

            if not post_media:
                continue

            with st.container(border=True):
                col_pinfo, col_paction = st.columns([3, 1])
                with col_pinfo:
                    st.markdown(
                        f"**@{post_account.get('platform_username', '?')}** — "
                        f"{format_date(post.get('posted_at'))}"
                    )
                    caption_text = post.get("caption", "") or ""
                    st.caption(caption_text[:150] if caption_text else "(no caption)")
                    st.caption(
                        f"Views: {format_number(post.get('views'))} | "
                        f"Likes: {format_number(post.get('likes'))} | "
                        f"{len(post_media)} media files"
                    )

                with col_paction:
                    has_video = any(m.get("media_type") == "video" for m in post_media)
                    btn_label = "Analyze Video" if has_video else "Analyze Images"

                    if st.button(btn_label, key=f"analyze_{post['id']}"):
                        with st.spinner("Analyzing..."):
                            try:
                                for media in post_media:
                                    if media.get("media_type") == "video":
                                        _run_async(
                                            analysis_service.analyze_video(
                                                media["id"], org_id
                                            )
                                        )
                                    elif media.get("media_type") == "image":
                                        _run_async(
                                            analysis_service.analyze_image(
                                                media["id"], org_id
                                            )
                                        )
                                st.success("Analysis complete!")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Analysis failed: {e}")
    else:
        st.success(f"{len(analyses)} analyzed posts")

        # Filter by status
        status_options = ["All", "ok", "validation_failed", "error"]
        analysis_filter = st.selectbox(
            "Filter by status",
            options=status_options,
            key="analysis_status_filter",
        )

        filtered = analyses
        if analysis_filter != "All":
            filtered = [a for a in analyses if a.get("status") == analysis_filter]

        for analysis in filtered:
            post_data = analysis.get("posts") or {}
            account_data = post_data.get("accounts") or {}
            username = account_data.get("platform_username", "?")

            with st.container(border=True):
                # Header row
                col_header, col_pass2 = st.columns([4, 1])
                with col_header:
                    st.markdown(
                        f"**@{username}** — "
                        f"{post_data.get('caption', '')[:80] if post_data.get('caption') else '(no caption)'}"
                    )
                    st.caption(
                        f"Views: {format_number(post_data.get('views'))} | "
                        f"Likes: {format_number(post_data.get('likes'))} | "
                        f"Duration: {analysis.get('video_duration_sec', '?')}s | "
                        f"Talking head: {'Yes' if analysis.get('has_talking_head') else 'No'}"
                    )

                with col_pass2:
                    if not analysis.get("production_storyboard"):
                        if st.button("Deep Analysis", key=f"pass2_{analysis['id']}"):
                            with st.spinner("Running Pass 2 (Pro model)..."):
                                try:
                                    _run_async(
                                        analysis_service.deep_production_analysis(
                                            analysis["id"]
                                        )
                                    )
                                    st.success("Pass 2 complete!")
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Pass 2 failed: {e}")
                    else:
                        st.caption("Pass 2 done")

                # Expandable analysis details
                with st.expander("View Analysis", expanded=False):
                    _render_video_analysis(analysis)
