"""
Instagram Content Library - Research and discover high-performing Instagram content.

Tabs:
1. Watched Accounts - Add/remove IG accounts to monitor per brand
2. Content Library - Browse scraped posts with filters and engagement stats
3. Top Content - Outlier dashboard showing highest-performing posts

Part of the Video Tools Suite (Phase 1).
"""

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
tab_accounts, tab_library, tab_top = st.tabs([
    "Watched Accounts",
    "Content Library",
    "Top Content",
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
