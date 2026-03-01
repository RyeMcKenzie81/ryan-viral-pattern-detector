"""
Video Studio - Video recreation pipeline UI.

Tabs:
1. Candidates - View and manage scored recreation candidates
2. Recreation - Generate videos from approved candidates (audio-first workflow)
3. History - Browse completed recreations with cost tracking
4. Manual Creator - Build multi-scene videos from scratch with avatar + Kling Omni

Part of the Video Tools Suite (Phase 5).
"""

import asyncio
import json
import streamlit as st
from datetime import datetime
from uuid import uuid4

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


def get_manual_video_service():
    """Get ManualVideoService instance."""
    from viraltracker.services.manual_video_service import ManualVideoService
    return ManualVideoService()


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

# Manual Creator session state
if "vs_manual_scenes" not in st.session_state:
    st.session_state.vs_manual_scenes = []
if "vs_manual_frame_gallery" not in st.session_state:
    st.session_state.vs_manual_frame_gallery = []
if "vs_manual_session_id" not in st.session_state:
    st.session_state.vs_manual_session_id = str(uuid4())
if "vs_manual_final_video" not in st.session_state:
    st.session_state.vs_manual_final_video = None


# ============================================================================
# Brand Selector
# ============================================================================

st.title("🎬 Video Studio")

from viraltracker.ui.utils import render_brand_selector
brand_id = render_brand_selector(key="video_studio_brand_selector")
if not brand_id:
    st.stop()

org_id = get_org_id()

# Superusers have org_id="all" — resolve to the brand's actual org for DB queries
if org_id == "all":
    try:
        from viraltracker.core.database import get_supabase_client as _get_sb
        _brand_row = _get_sb().table("brands").select("organization_id").eq("id", brand_id).single().execute()
        org_id = _brand_row.data["organization_id"]
    except Exception:
        st.warning("Could not determine organization for this brand.")
        st.stop()


# ============================================================================
# Tabs
# ============================================================================

tab_candidates, tab_recreation, tab_history, tab_manual = st.tabs([
    "📊 Candidates",
    "🎬 Recreation",
    "📁 History",
    "🎥 Manual Creator",
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

        has_adapted = bool(candidate.get("adapted_storyboard"))
        scene_keyframes = candidate.get("scene_keyframes") or []
        has_keyframes = bool(scene_keyframes) and any(
            kf.get("status") == "completed" for kf in scene_keyframes
        )
        has_clips = bool(candidate.get("generated_clips"))
        successful_clips = [
            c for c in (candidate.get("generated_clips") or [])
            if c.get("status") == "succeed"
        ]
        has_final = bool(candidate.get("final_video_path"))

        # Load avatars for keyframe/clip steps (shared across step2 and step3)
        avatar_list = []
        if has_adapted:
            from viraltracker.core.database import get_supabase_client
            sb = get_supabase_client()
            avatars = sb.table("brand_avatars").select(
                "id, name, kling_element_id"
            ).eq("brand_id", brand_id).execute()
            avatar_list = avatars.data or []

        # ---- Step 1: Adapt Storyboard ----
        with step1:
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

        # ---- Step 2: Keyframes (NEW — for Kling Omni) ----
        with step2:
            st.markdown(f"**2. Keyframes** {'✅' if has_keyframes else '⬜'}")
            if has_adapted:
                if not avatar_list:
                    st.caption("No avatars found for this brand.")
                else:
                    avatar_options = {a["name"]: a["id"] for a in avatar_list}
                    selected_avatar_name = st.selectbox(
                        "Avatar",
                        list(avatar_options.keys()),
                        key="vs_avatar_select",
                    )
                    selected_avatar_id = avatar_options.get(selected_avatar_name)
                    selected_avatar = next(
                        (a for a in avatar_list if a["id"] == selected_avatar_id), {}
                    )

                    # Element status
                    if selected_avatar.get("kling_element_id"):
                        st.caption("Element ready")
                    else:
                        if st.button("Create Element", key="vs_create_element"):
                            with st.spinner("Creating Kling element (this may take a minute)..."):
                                try:
                                    from viraltracker.services.avatar_service import AvatarService
                                    from uuid import UUID
                                    avatar_svc = AvatarService()
                                    element_id = _run_async(avatar_svc.create_kling_element(
                                        avatar_id=UUID(selected_avatar_id),
                                        organization_id=org_id,
                                        brand_id=brand_id,
                                    ))
                                    if element_id:
                                        st.success(f"Element created: {element_id[:12]}...")
                                    else:
                                        st.error("Element creation failed. Check logs for details.")
                                except Exception as e:
                                    st.error(f"Element creation failed: {e}")
                            st.rerun()

                    # Generate keyframes button
                    if not has_keyframes and selected_avatar_id:
                        keyframe_generating = any(
                            kf.get("status") == "generating" for kf in scene_keyframes
                        )
                        if st.button(
                            "Generate Keyframes",
                            key="vs_gen_keyframes",
                            disabled=keyframe_generating,
                        ):
                            with st.spinner("Generating keyframe images..."):
                                result = _run_async(svc.generate_scene_keyframes(
                                    selected_id,
                                    avatar_id=selected_avatar_id,
                                ))
                                if result:
                                    st.success("Keyframes generated!")
                                    st.rerun()
                                else:
                                    st.error("Keyframe generation failed")
                    elif has_keyframes:
                        completed_kf = sum(1 for kf in scene_keyframes if kf.get("status") == "completed")
                        total_kf = len(scene_keyframes)
                        st.caption(f"{completed_kf}/{total_kf} scenes have keyframes")

        # ---- Step 3: Generate Clips ----
        with step3:
            st.markdown(f"**3. Clips** {'✅' if successful_clips else '⬜'}")
            if has_adapted and not has_clips:
                mode = st.selectbox("Quality", ["std", "pro"], key="vs_kling_mode")
                engine_choices = [
                    "Kling Omni (recommended)" if has_keyframes else "Auto (recommended)",
                    "Auto",
                    "VEO only",
                    "Kling only",
                ]
                if has_keyframes and "Auto (recommended)" in engine_choices:
                    engine_choices.remove("Auto (recommended)")
                engine_choice = st.selectbox(
                    "Engine",
                    engine_choices,
                    key="vs_engine_choice",
                    help=(
                        "Kling Omni uses keyframes + element refs for character consistency. "
                        "Auto routes talking-head to Kling Avatar, B-roll to VEO."
                    ),
                )
                engine_override = None
                if engine_choice == "VEO only":
                    engine_override = "veo"
                elif engine_choice == "Kling only":
                    engine_override = "kling"
                elif engine_choice.startswith("Kling Omni"):
                    engine_override = "kling_omni"

                # Get avatar_id for clip generation
                clip_avatar_id = None
                if "vs_avatar_select" in st.session_state:
                    avatar_name = st.session_state.vs_avatar_select
                    if avatar_list:
                        clip_avatar_id = next(
                            (a["id"] for a in avatar_list if a["name"] == avatar_name), None
                        )

                if st.button("Generate Video Clips"):
                    with st.spinner("Generating clips (this may take several minutes)..."):
                        result = _run_async(svc.generate_video_clips(
                            selected_id,
                            avatar_id=clip_avatar_id,
                            mode=mode,
                            engine_override=engine_override,
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

        # ---- Step 4: Assemble Final Video ----
        with step4:
            st.markdown(f"**4. Final** {'✅' if has_final else '⬜'}")
            if successful_clips and not has_final:
                replace_voice = st.checkbox(
                    "Replace voice with ElevenLabs",
                    value=False,
                    key="vs_replace_voice",
                    help="Replace Kling native audio with ElevenLabs voice. Only needed if brand requires a specific voice.",
                )
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


# ============================================================================
# Tab 4: Manual Creator
# ============================================================================

with tab_manual:
    st.subheader("Manual Video Creator")
    st.caption(
        "Build multi-scene videos from scratch. Pick an avatar, generate keyframe images, "
        "write prompts and dialogue per scene, then generate and stitch clips."
    )

    # ---- Global Settings ----
    col_avatar, col_quality, col_ratio = st.columns(3)

    # Load avatars for this brand
    from viraltracker.core.database import get_supabase_client as _get_sb_manual
    _sb_manual = _get_sb_manual()
    _manual_avatars = (
        _sb_manual.table("brand_avatars")
        .select("id, name, kling_element_id, kling_voice_id")
        .eq("brand_id", brand_id)
        .eq("is_active", True)
        .execute()
    )
    manual_avatar_list = _manual_avatars.data or []

    with col_avatar:
        if not manual_avatar_list:
            st.warning("No avatars found. Create one in Avatar Manager first.")
            st.stop()

        avatar_display = {}
        for a in manual_avatar_list:
            has_element = bool(a.get("kling_element_id"))
            has_voice = bool(a.get("kling_voice_id"))
            status = ""
            if has_element and has_voice:
                status = " (Element + Voice ready)"
            elif has_element:
                status = " (Element only)"
            else:
                status = " (No element)"
            avatar_display[f"{a['name']}{status}"] = a["id"]

        selected_avatar_label = st.selectbox(
            "Avatar",
            list(avatar_display.keys()),
            key="vs_manual_avatar",
        )
        manual_avatar_id = avatar_display.get(selected_avatar_label)

        # Warn if no element
        selected_av = next(
            (a for a in manual_avatar_list if a["id"] == manual_avatar_id), {}
        )
        if not selected_av.get("kling_element_id"):
            st.error("This avatar has no Kling element. Create one in Avatar Manager.")

    with col_quality:
        manual_mode = st.selectbox(
            "Quality",
            ["pro", "std"],
            key="vs_manual_mode",
            help="Pro = 1080p, Std = 720p",
        )

    with col_ratio:
        manual_aspect = st.selectbox(
            "Aspect Ratio",
            ["9:16", "16:9", "1:1"],
            key="vs_manual_aspect_ratio",
            help="9:16 for vertical/reels, 16:9 for landscape, 1:1 for square",
        )

    st.divider()

    # ---- Frame Gallery ----
    st.markdown("#### Frame Gallery")
    st.caption("Generate keyframe images to use as start/end frames for scenes.")

    col_frame_input, col_frame_gallery = st.columns([1, 2])

    with col_frame_input:
        frame_prompt = st.text_area(
            "Frame prompt",
            placeholder="Describe the keyframe image (e.g., 'Close-up of avatar holding product, smiling at camera, bright studio lighting')",
            key="vs_manual_frame_prompt",
            height=120,
        )
        if st.button("Generate Frame", disabled=not frame_prompt.strip()):
            with st.spinner("Generating keyframe image via Gemini..."):
                try:
                    svc = get_manual_video_service()
                    result = _run_async(svc.generate_frame(
                        brand_id=brand_id,
                        prompt=frame_prompt.strip(),
                        avatar_id=manual_avatar_id,
                        aspect_ratio=manual_aspect,
                    ))
                    st.session_state.vs_manual_frame_gallery.append(result)
                    st.success("Frame generated!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Frame generation failed: {e}")

    with col_frame_gallery:
        gallery = st.session_state.vs_manual_frame_gallery
        if not gallery:
            st.info("No frames yet. Generate some using the prompt on the left.")
        else:
            # Display as grid (4-across)
            cols = st.columns(4)
            for i, frame in enumerate(gallery):
                with cols[i % 4]:
                    url = frame.get("signed_url", "")
                    if url:
                        st.image(url, caption=f"#{i+1}", width="stretch")
                    else:
                        st.caption(f"#{i+1} (no preview)")
                    st.caption(frame.get("prompt", "")[:40] + "...")
                    if st.button("Remove", key=f"rm_frame_{frame['id']}"):
                        st.session_state.vs_manual_frame_gallery = [
                            f for f in gallery if f["id"] != frame["id"]
                        ]
                        st.rerun()

    st.divider()

    # ---- Scenes ----
    st.markdown("#### Scenes")

    gallery = st.session_state.vs_manual_frame_gallery
    frame_options = ["(None)"] + [
        f"#{i+1}: {f.get('prompt', '')[:30]}..." for i, f in enumerate(gallery)
    ]

    scenes = st.session_state.vs_manual_scenes

    for idx, scene in enumerate(scenes):
        scene_label = f"Scene {idx + 1}"
        status = scene.get("status", "draft")
        status_icons = {
            "draft": "📝",
            "generating": "⏳",
            "succeed": "✅",
            "failed": "❌",
        }
        icon = status_icons.get(status, "📝")

        with st.expander(f"{icon} {scene_label} — {status}", expanded=(status == "draft")):
            col_left, col_right = st.columns([2, 1])

            with col_left:
                scene["prompt"] = st.text_area(
                    "Visual prompt",
                    value=scene.get("prompt", ""),
                    key=f"vs_scene_prompt_{scene['id']}",
                    height=80,
                    placeholder="Describe what happens visually in this scene...",
                )
                scene["dialogue"] = st.text_area(
                    "Dialogue",
                    value=scene.get("dialogue", ""),
                    key=f"vs_scene_dialogue_{scene['id']}",
                    height=60,
                    placeholder="What the avatar says (leave empty for no speech)...",
                )
                scene["duration"] = st.slider(
                    "Duration (seconds)",
                    min_value=3,
                    max_value=15,
                    value=scene.get("duration", 5),
                    key=f"vs_scene_dur_{scene['id']}",
                )

                # Per-scene avatar override
                override_options = ["(Use Global)"] + [
                    a["name"] for a in manual_avatar_list
                ]
                override_choice = st.selectbox(
                    "Avatar override",
                    override_options,
                    key=f"vs_scene_avatar_{scene['id']}",
                )
                if override_choice == "(Use Global)":
                    scene["avatar_override_id"] = None
                else:
                    scene["avatar_override_id"] = next(
                        (a["id"] for a in manual_avatar_list if a["name"] == override_choice),
                        None,
                    )

            with col_right:
                # Frame selection
                start_idx = st.selectbox(
                    "Start frame",
                    range(len(frame_options)),
                    format_func=lambda i: frame_options[i],
                    key=f"vs_scene_start_{scene['id']}",
                )
                scene["start_frame_id"] = (
                    gallery[start_idx - 1]["id"] if start_idx > 0 else None
                )

                end_idx = st.selectbox(
                    "End frame",
                    range(len(frame_options)),
                    format_func=lambda i: frame_options[i],
                    key=f"vs_scene_end_{scene['id']}",
                )
                scene["end_frame_id"] = (
                    gallery[end_idx - 1]["id"] if end_idx > 0 else None
                )

                # Inline quick frame gen
                quick_prompt = st.text_input(
                    "Quick frame prompt",
                    key=f"vs_scene_quick_{scene['id']}",
                    placeholder="Generate a frame...",
                )
                if st.button("Add Frame", key=f"vs_scene_qf_{scene['id']}", disabled=not quick_prompt.strip()):
                    with st.spinner("Generating..."):
                        try:
                            svc = get_manual_video_service()
                            result = _run_async(svc.generate_frame(
                                brand_id=brand_id,
                                prompt=quick_prompt.strip(),
                                avatar_id=manual_avatar_id,
                                aspect_ratio=manual_aspect,
                            ))
                            st.session_state.vs_manual_frame_gallery.append(result)
                            st.success("Frame added to gallery!")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Failed: {e}")

                if scene.get("error"):
                    st.error(scene["error"])

            # Video preview for completed scenes
            if status == "succeed" and scene.get("video_storage_path"):
                st.markdown("**Preview:**")
                storage_path = scene["video_storage_path"]
                parts = storage_path.split("/", 1)
                if len(parts) == 2:
                    signed = _get_sb_manual().storage.from_(parts[0]).create_signed_url(
                        parts[1], 3600
                    )
                    preview_url = signed.get("signedURL", "") if isinstance(signed, dict) else ""
                    if preview_url:
                        st.video(preview_url)
                    else:
                        st.caption(f"Video at: {storage_path[:50]}...")

            # Scene action buttons
            col_gen, col_regen, col_rm = st.columns(3)
            with col_gen:
                if status == "draft" and st.button(
                    "Generate This Scene", key=f"vs_gen_scene_{scene['id']}"
                ):
                    if not scene.get("prompt", "").strip():
                        st.warning("Scene prompt is empty.")
                    else:
                        scene["status"] = "generating"
                        st.rerun()

            with col_regen:
                if status in ("succeed", "failed") and st.button(
                    "Regenerate", key=f"vs_regen_scene_{scene['id']}"
                ):
                    scene["status"] = "generating"
                    scene["generation_id"] = None
                    scene["kling_task_id"] = None
                    scene["video_storage_path"] = None
                    scene["error"] = None
                    st.rerun()

            with col_rm:
                if st.button("Remove Scene", key=f"vs_rm_scene_{scene['id']}"):
                    st.session_state.vs_manual_scenes = [
                        s for s in scenes if s["id"] != scene["id"]
                    ]
                    st.rerun()

    # Handle scene generation (runs after rerun with status=generating)
    for scene in st.session_state.vs_manual_scenes:
        if scene.get("status") == "generating":
            scene_avatar = scene.get("avatar_override_id") or manual_avatar_id
            with st.spinner(f"Generating scene video (this may take 5-10 minutes)..."):
                try:
                    svc = get_manual_video_service()
                    result = _run_async(svc.generate_scene_video(
                        organization_id=org_id,
                        brand_id=brand_id,
                        scene=scene,
                        avatar_id=scene_avatar,
                        frame_gallery=st.session_state.vs_manual_frame_gallery,
                        mode=manual_mode,
                        aspect_ratio=manual_aspect,
                    ))
                    scene["status"] = result.get("status", "failed")
                    scene["generation_id"] = result.get("generation_id")
                    scene["kling_task_id"] = result.get("kling_task_id")
                    scene["video_storage_path"] = result.get("video_storage_path")
                    scene["error"] = result.get("error_message")
                except Exception as e:
                    scene["status"] = "failed"
                    scene["error"] = str(e)
            st.rerun()

    # Add Scene controls
    col_add, col_inherit = st.columns([1, 2])
    with col_add:
        add_scene_clicked = st.button("+ Add Scene")
    with col_inherit:
        inherit_prev = st.checkbox(
            "Inherit from previous scene (prompt, start/end frames)",
            value=False,
            key="vs_manual_inherit_prev",
        )

    if add_scene_clicked:
        new_scene = {
            "id": str(uuid4()),
            "prompt": "",
            "dialogue": "",
            "duration": 5,
            "start_frame_id": None,
            "end_frame_id": None,
            "avatar_override_id": None,
            "status": "draft",
            "generation_id": None,
            "kling_task_id": None,
            "video_storage_path": None,
            "error": None,
        }

        if inherit_prev and scenes:
            prev = scenes[-1]
            new_scene["prompt"] = prev.get("prompt", "")
            new_scene["start_frame_id"] = prev.get("start_frame_id")
            new_scene["end_frame_id"] = prev.get("end_frame_id")
            new_scene["avatar_override_id"] = prev.get("avatar_override_id")
            new_scene["duration"] = prev.get("duration", 5)

        st.session_state.vs_manual_scenes.append(new_scene)
        st.rerun()

    st.divider()

    # ---- Generate & Assemble ----
    st.markdown("#### Generate & Assemble")

    draft_scenes = [s for s in scenes if s.get("status") == "draft" and s.get("prompt", "").strip()]
    successful_scenes = [s for s in scenes if s.get("status") == "succeed" and s.get("video_storage_path")]

    col_cost, col_gen_all, col_stitch = st.columns(3)

    with col_cost:
        if scenes:
            svc = get_manual_video_service()
            estimate = svc.estimate_cost(scenes, mode=manual_mode)
            st.metric("Est. Cost", f"${estimate['total_estimated_cost']:.2f}")
            st.caption(f"Total duration: {estimate['total_duration_sec']}s")
        else:
            st.metric("Est. Cost", "—")

    with col_gen_all:
        if draft_scenes:
            if st.button(f"Generate All ({len(draft_scenes)} draft)"):
                progress = st.progress(0)
                for i, scene in enumerate(draft_scenes):
                    scene_avatar = scene.get("avatar_override_id") or manual_avatar_id
                    st.caption(f"Generating scene {i+1}/{len(draft_scenes)}...")
                    try:
                        svc = get_manual_video_service()
                        result = _run_async(svc.generate_scene_video(
                            organization_id=org_id,
                            brand_id=brand_id,
                            scene=scene,
                            avatar_id=scene_avatar,
                            frame_gallery=st.session_state.vs_manual_frame_gallery,
                            mode=manual_mode,
                            aspect_ratio=manual_aspect,
                        ))
                        scene["status"] = result.get("status", "failed")
                        scene["generation_id"] = result.get("generation_id")
                        scene["kling_task_id"] = result.get("kling_task_id")
                        scene["video_storage_path"] = result.get("video_storage_path")
                        scene["error"] = result.get("error_message")
                    except Exception as e:
                        scene["status"] = "failed"
                        scene["error"] = str(e)
                    progress.progress((i + 1) / len(draft_scenes))
                st.rerun()
        else:
            st.button("Generate All", disabled=True, help="Add scenes with prompts first")

    with col_stitch:
        if len(successful_scenes) >= 2:
            if st.button(f"Stitch {len(successful_scenes)} Clips"):
                with st.spinner("Concatenating clips via FFmpeg..."):
                    try:
                        svc = get_manual_video_service()
                        result = _run_async(svc.concatenate_scenes(
                            scene_clips=successful_scenes,
                            brand_id=brand_id,
                            session_id=st.session_state.vs_manual_session_id,
                        ))
                        st.session_state.vs_manual_final_video = result
                        st.success(
                            f"Final video assembled! Duration: {result.get('duration_sec', '?')}s"
                        )
                        st.rerun()
                    except Exception as e:
                        st.error(f"Stitch failed: {e}")
        else:
            needed = 2 - len(successful_scenes)
            st.button(
                "Stitch Clips",
                disabled=True,
                help=f"Need {needed} more successful scene(s)",
            )

    # Final video player
    final = st.session_state.vs_manual_final_video
    if final and final.get("signed_url"):
        st.markdown("---")
        st.markdown("#### Final Video")
        st.video(final["signed_url"])
        st.caption(
            f"Duration: {final.get('duration_sec', '?')}s | "
            f"Path: {final.get('final_video_path', '')}"
        )
