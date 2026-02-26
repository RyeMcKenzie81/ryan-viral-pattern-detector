"""
Video Studio - Video recreation pipeline UI.

Tabs:
1. Candidates - View and manage scored recreation candidates
2. Recreation - Generate videos from approved candidates (audio-first workflow)
3. History - Browse completed recreations with cost tracking

Part of the Video Tools Suite (Phase 5).
"""

import asyncio
import json
import streamlit as st
from datetime import datetime

# Page config (must be first Streamlit call)
st.set_page_config(
    page_title="Video Studio",
    page_icon="🎬",
    layout="wide",
)

# Authentication
from viraltracker.ui.auth import require_auth
require_auth()
from viraltracker.ui.utils import require_feature
require_feature("video_tools", "Video Tools")


# ============================================================================
# Helper Functions
# ============================================================================

def get_recreation_service():
    """Get VideoRecreationService instance."""
    from viraltracker.services.video_recreation_service import VideoRecreationService
    return VideoRecreationService()


def get_analysis_service():
    """Get InstagramAnalysisService instance."""
    from viraltracker.services.instagram_analysis_service import InstagramAnalysisService
    return InstagramAnalysisService()


def get_org_id() -> str:
    """Get current organization ID."""
    from viraltracker.ui.utils import get_current_organization_id
    return get_current_organization_id()


def _run_async(coro):
    """Run async coroutine from sync Streamlit context."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, coro)
                return future.result(timeout=300)
        return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


def format_number(n) -> str:
    """Format large numbers."""
    if n is None:
        return "—"
    n = int(n)
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def format_date(date_str) -> str:
    """Format a date string."""
    if not date_str:
        return "—"
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        return dt.strftime("%b %d, %Y %H:%M")
    except Exception:
        return str(date_str)[:16]


def format_cost(cost) -> str:
    """Format USD cost."""
    if cost is None:
        return "—"
    return f"${float(cost):.2f}"


def score_color(score) -> str:
    """Return color hex for a 0-1 score."""
    if score is None:
        return "#888"
    s = float(score)
    if s >= 0.7:
        return "#22c55e"  # green
    if s >= 0.4:
        return "#eab308"  # yellow
    return "#ef4444"      # red


def score_bar(score, label: str = "") -> str:
    """Render a colored score bar as markdown."""
    if score is None:
        return f"**{label}**: —"
    s = float(score)
    pct = int(s * 100)
    color = score_color(score)
    return f"**{label}**: :{color}[{'█' * (pct // 10)}{'░' * (10 - pct // 10)}] {pct}%"


# ============================================================================
# Session State
# ============================================================================

if "vs_scoring" not in st.session_state:
    st.session_state.vs_scoring = False
if "vs_selected_candidate" not in st.session_state:
    st.session_state.vs_selected_candidate = None


# ============================================================================
# Brand Selector
# ============================================================================

st.title("🎬 Video Studio")

from viraltracker.ui.utils import render_brand_selector
brand_id = render_brand_selector(key="video_studio_brand_selector")
if not brand_id:
    st.stop()

org_id = get_org_id()


# ============================================================================
# Tabs
# ============================================================================

tab_candidates, tab_recreation, tab_history = st.tabs([
    "📊 Candidates",
    "🎬 Recreation",
    "📁 History",
])


# ============================================================================
# Tab 1: Candidates
# ============================================================================

with tab_candidates:
    st.subheader("Recreation Candidates")
    st.caption("Scored from analyzed Instagram outlier content. Higher scores = better recreation potential.")

    col_actions, col_filter = st.columns([2, 1])

    with col_actions:
        if st.button("🔄 Score New Candidates", disabled=st.session_state.vs_scoring):
            st.session_state.vs_scoring = True
            with st.spinner("Scoring analyzed content..."):
                svc = get_recreation_service()
                scored = svc.score_candidates(brand_id, org_id)
                st.session_state.vs_scoring = False
                if scored:
                    st.success(f"Scored {len(scored)} candidates")
                else:
                    st.info("No analyzed content found. Analyze outlier posts first on the Instagram Content page.")
            st.rerun()

    with col_filter:
        status_filter = st.selectbox(
            "Status",
            ["All", "candidate", "approved", "rejected"],
            key="vs_status_filter",
        )

    # Load candidates
    svc = get_recreation_service()
    status_val = None if status_filter == "All" else status_filter
    candidates = svc.list_candidates(brand_id, org_id, status=status_val, limit=50)

    if not candidates:
        st.info("No candidates yet. Click 'Score New Candidates' to analyze content.")
    else:
        for cand in candidates:
            post = cand.get("posts") or {}
            account = post.get("accounts") or {}
            username = account.get("platform_username", "unknown")
            score = cand.get("composite_score", 0)
            components = cand.get("score_components") or {}
            status = cand.get("status", "candidate")
            has_th = cand.get("has_talking_head", False)

            # Status badge
            status_icons = {
                "candidate": "🟡",
                "approved": "✅",
                "rejected": "❌",
                "generating": "⏳",
                "completed": "🎉",
                "failed": "💥",
            }
            icon = status_icons.get(status, "❓")

            with st.expander(
                f"{icon} @{username} — Score: {score:.0%} — "
                f"{'🗣️ Talking Head' if has_th else '🎥 B-Roll'} — "
                f"{format_number(post.get('views'))} views",
                expanded=False,
            ):
                col_score, col_details, col_actions = st.columns([1, 2, 1])

                with col_score:
                    st.markdown(f"### {score:.0%}")
                    st.markdown(f"**Engagement**: {components.get('engagement', 0):.0%}")
                    st.markdown(f"**Hook Quality**: {components.get('hook_quality', 0):.0%}")
                    st.markdown(f"**Feasibility**: {components.get('recreation_feasibility', 0):.0%}")
                    st.markdown(f"**Avatar Fit**: {components.get('avatar_compatibility', 0):.0%}")

                with col_details:
                    st.markdown(f"**Caption**: {(post.get('caption') or '')[:200]}...")
                    st.markdown(
                        f"**Engagement**: {format_number(post.get('views'))} views, "
                        f"{format_number(post.get('likes'))} likes, "
                        f"{format_number(post.get('comments'))} comments"
                    )
                    scene_types = cand.get("scene_types") or []
                    if scene_types:
                        st.markdown(f"**Scenes**: {', '.join(scene_types)}")
                    if post.get("post_url"):
                        st.markdown(f"[View Original Post]({post['post_url']})")

                with col_actions:
                    cid = cand["id"]
                    if status == "candidate":
                        if st.button("✅ Approve", key=f"approve_{cid}"):
                            svc.approve_candidate(cid)
                            st.rerun()
                        if st.button("❌ Reject", key=f"reject_{cid}"):
                            svc.reject_candidate(cid)
                            st.rerun()

                    # Cost estimate
                    estimate = svc.get_cost_estimate(cid)
                    if estimate:
                        st.markdown(f"**Est. Cost**: {format_cost(estimate.get('total_estimated'))}")
                        st.caption(
                            f"Kling: {format_cost(estimate.get('kling_cost'))}, "
                            f"VEO: {format_cost(estimate.get('veo_cost'))}, "
                            f"Audio: {format_cost(estimate.get('elevenlabs_cost'))}"
                        )

                    if status in ("approved", "candidate"):
                        if st.button("🎬 Recreate", key=f"recreate_{cid}"):
                            st.session_state.vs_selected_candidate = cid
                            st.rerun()


# ============================================================================
# Tab 2: Recreation
# ============================================================================

with tab_recreation:
    st.subheader("Video Recreation")

    selected_id = st.session_state.vs_selected_candidate

    if not selected_id:
        st.info("Select a candidate from the Candidates tab to begin recreation.")

        # Also show any approved candidates as quick picks
        svc = get_recreation_service()
        approved = svc.list_candidates(brand_id, org_id, status="approved", limit=10)
        if approved:
            st.markdown("### Approved Candidates")
            for cand in approved:
                post = cand.get("posts") or {}
                account = post.get("accounts") or {}
                if st.button(
                    f"@{account.get('platform_username', '?')} — {cand['composite_score']:.0%}",
                    key=f"pick_{cand['id']}",
                ):
                    st.session_state.vs_selected_candidate = cand["id"]
                    st.rerun()
    else:
        svc = get_recreation_service()
        candidate = svc.get_candidate(selected_id)

        if not candidate:
            st.error("Candidate not found.")
            st.session_state.vs_selected_candidate = None
            st.stop()

        post = candidate.get("posts") or {}
        account = post.get("accounts") or {}
        st.markdown(
            f"**Source**: @{account.get('platform_username', '?')} — "
            f"Score: {candidate.get('composite_score', 0):.0%} — "
            f"Status: {candidate.get('status')}"
        )

        if st.button("← Back to candidates"):
            st.session_state.vs_selected_candidate = None
            st.rerun()

        st.divider()

        # ---- Original Storyboard (read-only) ----
        col_original, col_adapted = st.columns(2)

        with col_original:
            st.markdown("#### Original Storyboard")
            analysis_id = candidate.get("analysis_id")
            if analysis_id:
                analysis_svc = get_analysis_service()
                analysis = analysis_svc.supabase.table("ad_video_analysis").select(
                    "storyboard, full_transcript, hook_transcript_spoken, production_storyboard"
                ).eq("id", analysis_id).single().execute()

                if analysis.data:
                    row = analysis.data
                    if row.get("hook_transcript_spoken"):
                        st.markdown(f"**Hook**: {row['hook_transcript_spoken']}")
                    if row.get("full_transcript"):
                        with st.expander("Full Transcript"):
                            st.text(row["full_transcript"])
                    storyboard = row.get("storyboard") or []
                    for i, scene in enumerate(storyboard):
                        ts = scene.get("timestamp_sec", "?")
                        desc = scene.get("scene_description", "")
                        st.markdown(f"**{ts}s**: {desc}")
                else:
                    st.caption("Analysis not available")
            else:
                st.caption("No analysis linked")

        with col_adapted:
            st.markdown("#### Adapted Storyboard")
            adapted = candidate.get("adapted_storyboard")

            if adapted:
                if candidate.get("adapted_hook"):
                    st.markdown(f"**Hook**: {candidate['adapted_hook']}")
                if candidate.get("adapted_script"):
                    with st.expander("Full Script"):
                        st.text(candidate["adapted_script"])

                for scene in adapted:
                    idx = scene.get("scene_idx", "?")
                    stype = scene.get("scene_type", "?")
                    dur = scene.get("duration_sec", "?")
                    prompt = scene.get("visual_prompt", scene.get("dialogue", ""))
                    icon = "🗣️" if stype == "talking_head" else "🎥"
                    st.markdown(f"**Scene {idx}** {icon} ({dur}s): {prompt[:100]}")
            else:
                st.caption("Not adapted yet")

        st.divider()

        # ---- Recreation Actions ----
        st.markdown("#### Recreation Steps")

        step1, step2, step3, step4 = st.columns(4)

        with step1:
            has_adapted = bool(candidate.get("adapted_storyboard"))
            st.markdown(f"**1. Adapt** {'✅' if has_adapted else '⬜'}")
            if not has_adapted:
                brand_name = st.text_input("Brand name", key="vs_brand_name")
                product_name = st.text_input("Product name", key="vs_product_name")
                if st.button("Adapt Storyboard"):
                    with st.spinner("Adapting storyboard with AI..."):
                        result = _run_async(svc.adapt_storyboard(
                            selected_id,
                            brand_name=brand_name,
                            product_name=product_name,
                        ))
                        if result:
                            st.success("Storyboard adapted!")
                            st.rerun()
                        else:
                            st.error("Adaptation failed")

        with step2:
            has_audio = bool(candidate.get("audio_segments"))
            st.markdown(f"**2. Audio** {'✅' if has_audio else '⬜'}")
            if has_adapted and not has_audio:
                voice_id = st.text_input("ElevenLabs Voice ID", key="vs_voice_id")
                if voice_id and st.button("Generate Audio"):
                    with st.spinner("Generating audio segments..."):
                        result = _run_async(svc.generate_audio_segments(
                            selected_id, voice_id=voice_id
                        ))
                        if result:
                            st.success("Audio generated!")
                            st.rerun()
                        else:
                            st.error("Audio generation failed")
            elif has_audio:
                segments = candidate.get("audio_segments") or []
                audio_count = sum(1 for s in segments if s.get("has_audio"))
                total_dur = candidate.get("total_audio_duration_sec", 0)
                st.caption(f"{audio_count} audio segments, {total_dur:.1f}s total")

        with step3:
            has_clips = bool(candidate.get("generated_clips"))
            successful_clips = [
                c for c in (candidate.get("generated_clips") or [])
                if c.get("status") == "succeed"
            ]
            st.markdown(f"**3. Clips** {'✅' if successful_clips else '⬜'}")
            if has_adapted and not has_clips:
                mode = st.selectbox("Quality", ["std", "pro"], key="vs_kling_mode")
                engine_choice = st.selectbox(
                    "Engine",
                    ["Auto (recommended)", "VEO only", "Kling only"],
                    key="vs_engine_choice",
                    help="Auto routes talking-head → Kling, B-roll → VEO. Use 'VEO only' if Kling keys are not configured.",
                )
                engine_override = None
                if engine_choice == "VEO only":
                    engine_override = "veo"
                elif engine_choice == "Kling only":
                    engine_override = "kling"

                if st.button("Generate Video Clips"):
                    with st.spinner("Generating clips (this may take several minutes)..."):
                        result = _run_async(svc.generate_video_clips(
                            selected_id, mode=mode, engine_override=engine_override
                        ))
                        if result:
                            st.success("Clips generated!")
                            st.rerun()
                        else:
                            st.error("Clip generation failed")
            elif has_clips:
                clips = candidate.get("generated_clips") or []
                ok = sum(1 for c in clips if c.get("status") == "succeed")
                st.caption(f"{ok}/{len(clips)} clips succeeded")

        with step4:
            has_final = bool(candidate.get("final_video_path"))
            st.markdown(f"**4. Final** {'✅' if has_final else '⬜'}")
            if successful_clips and not has_final:
                if st.button("Assemble Final Video"):
                    with st.spinner("Concatenating clips..."):
                        result = _run_async(svc.concatenate_clips(selected_id))
                        if result:
                            st.success("Video assembled!")
                            st.rerun()
                        else:
                            st.error("Assembly failed")
            elif has_final:
                st.caption(f"Duration: {candidate.get('final_video_duration_sec', '?')}s")
                st.caption(f"Cost: {format_cost(candidate.get('total_generation_cost_usd'))}")
                # Download link
                final_path = candidate["final_video_path"]
                try:
                    from viraltracker.config import get_supabase_client
                    sb = get_supabase_client()
                    parts = final_path.split("/", 1)
                    signed = sb.storage.from_(parts[0]).create_signed_url(parts[1], 3600)
                    if signed and signed.get("signedURL"):
                        st.markdown(f"[Download Final Video]({signed['signedURL']})")
                except Exception:
                    st.caption(f"Path: `{final_path}`")

        # ---- Text Overlay Instructions ----
        overlays = candidate.get("text_overlay_instructions")
        if overlays:
            with st.expander("Text Overlay Instructions (for human editor)"):
                st.json(overlays)


# ============================================================================
# Tab 3: History
# ============================================================================

with tab_history:
    st.subheader("Recreation History")

    svc = get_recreation_service()
    history_status = st.selectbox(
        "Filter by status",
        ["completed", "failed", "generating", "All"],
        key="vs_history_status",
    )

    status_val = None if history_status == "All" else history_status
    history = svc.list_candidates(brand_id, org_id, status=status_val, limit=30)

    if not history:
        st.info("No recreation history yet.")
    else:
        for cand in history:
            post = cand.get("posts") or {}
            account = post.get("accounts") or {}
            username = account.get("platform_username", "?")
            status = cand.get("status")
            cost = cand.get("total_generation_cost_usd")
            final_path = cand.get("final_video_path")
            created = format_date(cand.get("created_at"))

            status_icons = {
                "completed": "🎉",
                "failed": "💥",
                "generating": "⏳",
            }
            icon = status_icons.get(status, "📄")

            with st.expander(
                f"{icon} @{username} — {status} — {format_cost(cost)} — {created}",
                expanded=False,
            ):
                col_info, col_clips = st.columns([1, 2])

                with col_info:
                    st.markdown(f"**Status**: {status}")
                    st.markdown(f"**Score**: {cand.get('composite_score', 0):.0%}")
                    st.markdown(f"**Engine**: {cand.get('generation_engine', '—')}")
                    st.markdown(f"**Cost**: {format_cost(cost)}")
                    if cand.get("final_video_duration_sec"):
                        st.markdown(f"**Duration**: {cand['final_video_duration_sec']:.1f}s")
                    if post.get("post_url"):
                        st.markdown(f"[Original Post]({post['post_url']})")

                with col_clips:
                    clips = cand.get("generated_clips") or []
                    if clips:
                        st.markdown("**Generated Clips:**")
                        for clip in clips:
                            idx = clip.get("scene_idx", "?")
                            engine = clip.get("engine", "?")
                            clip_status = clip.get("status", "?")
                            dur = clip.get("duration_sec", "?")
                            st.markdown(
                                f"Scene {idx}: {engine} — {clip_status} — {dur}s"
                            )

                    if final_path:
                        st.markdown("**Final Video**: Available in storage")
                        st.code(final_path, language=None)

                    overlays = cand.get("text_overlay_instructions")
                    if overlays:
                        st.download_button(
                            "Download Overlay Instructions (JSON)",
                            data=json.dumps(overlays, indent=2),
                            file_name=f"overlays_{cand['id'][:8]}.json",
                            mime="application/json",
                            key=f"dl_overlays_{cand['id']}",
                        )
