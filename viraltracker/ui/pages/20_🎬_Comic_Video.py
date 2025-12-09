"""
Comic Video UI

Streamlit interface for:
- Uploading comic grid images and JSON
- Generating voiceover audio per panel
- Previewing camera movements and effects per panel
- Reviewing audio + video together (parallel view)
- Rendering final vertical video

Phase 5.5: Manual panel adjustments, bulk actions, aspect ratio selection
"""

import streamlit as st
import asyncio
import json
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, List

# Page config (must be first)
st.set_page_config(
    page_title="Comic Video",
    page_icon="🎬",
    layout="wide"
)

# Authentication
from viraltracker.ui.auth import require_auth
from viraltracker.services.comic_video.models import MOOD_EFFECT_PRESETS, PanelMood, EffectType
require_auth()


def get_mood_effects(mood_str: str) -> Dict[str, bool]:
    """Get which effects a mood preset enables.

    Returns a dict with effect names as keys and whether they're enabled as values.
    This includes checking for vignette variants (light/heavy).
    """
    try:
        mood = PanelMood(mood_str)
        preset = MOOD_EFFECT_PRESETS.get(mood)
        if not preset:
            return {"vignette": False, "shake": False, "golden_glow": False, "pulse": False, "red_glow": False, "color_tint": False}

        # Check all effects in ambient and triggered
        all_effects = preset.ambient_effects + preset.triggered_effects
        effect_types = {e.effect_type for e in all_effects}

        # Vignette includes all variants
        has_vignette = any(et in effect_types for et in [
            EffectType.VIGNETTE, EffectType.VIGNETTE_LIGHT, EffectType.VIGNETTE_HEAVY
        ])

        return {
            "vignette": has_vignette,
            "shake": EffectType.SHAKE in effect_types,
            "golden_glow": EffectType.GOLDEN_GLOW in effect_types,
            "pulse": EffectType.PULSE in effect_types,
            "red_glow": EffectType.RED_GLOW in effect_types,
            "color_tint": preset.color_tint is not None,
        }
    except (ValueError, KeyError):
        return {"vignette": False, "shake": False, "golden_glow": False, "pulse": False, "red_glow": False, "color_tint": False}

# Initialize session state
if 'comic_project_id' not in st.session_state:
    st.session_state.comic_project_id = None
if 'comic_workflow_step' not in st.session_state:
    st.session_state.comic_workflow_step = "upload"  # upload, audio, review, render
if 'comic_aspect_ratio' not in st.session_state:
    st.session_state.comic_aspect_ratio = "9:16"  # Default to vertical
if 'render_all_progress' not in st.session_state:
    st.session_state.render_all_progress = None


def get_service():
    """Get ComicVideoService instance."""
    from viraltracker.services.comic_video import ComicVideoService
    return ComicVideoService()


def get_supabase():
    """Get Supabase client."""
    from viraltracker.core.database import get_supabase_client
    return get_supabase_client()


# ============================================================================
# Async Helpers
# ============================================================================

async def create_project(title: str, grid_url: str, comic_json: dict):
    """Create a new comic video project."""
    service = get_service()
    return await service.create_project(title, grid_url, comic_json)


async def get_project(project_id: str):
    """Get project by ID."""
    service = get_service()
    return await service.get_project(project_id)


async def list_projects(limit: int = 10):
    """List recent projects."""
    service = get_service()
    return await service.list_projects(limit=limit)


async def parse_layout(project_id: str):
    """Parse layout from comic JSON."""
    service = get_service()
    return await service.parse_layout(project_id)


async def generate_all_audio(project_id: str, voice_id: str = None):
    """Generate audio for all panels."""
    service = get_service()
    return await service.generate_all_audio(project_id, voice_id=voice_id)


async def regenerate_audio(project_id: str, panel_number: int, voice_id: str = None):
    """Regenerate audio for a panel."""
    service = get_service()
    return await service.regenerate_panel_audio(project_id, panel_number, voice_id=voice_id)


async def generate_instructions(project_id: str):
    """Generate camera/effects instructions."""
    service = get_service()
    return await service.generate_all_instructions(project_id)


async def render_preview(project_id: str, panel_number: int):
    """Render panel preview video."""
    service = get_service()
    return await service.render_panel_preview(project_id, panel_number)


async def approve_panel(project_id: str, panel_number: int):
    """Approve panel audio + video."""
    service = get_service()
    await service.approve_panel(project_id, panel_number)


async def render_final(project_id: str):
    """Render final video."""
    service = get_service()
    return await service.render_final_video(project_id)


async def get_summary(project_id: str):
    """Get project summary."""
    service = get_service()
    return await service.get_project_summary(project_id)


async def get_audio_list(project_id: str):
    """Get all panel audio."""
    from viraltracker.services.comic_video import ComicAudioService
    service = ComicAudioService()
    return await service.get_all_panel_audio(project_id)


async def get_instructions(project_id: str):
    """Get all panel instructions."""
    from viraltracker.services.comic_video import ComicDirectorService
    service = ComicDirectorService()
    return await service.get_all_instructions(project_id)


async def get_signed_url(storage_path: str):
    """Get signed URL for file playback."""
    from viraltracker.services.comic_video import ComicAudioService
    service = ComicAudioService()
    return await service.get_audio_url(storage_path)


async def render_all_panels(project_id: str, aspect_ratio: str, force_rerender: bool = False):
    """Render all panel previews."""
    service = get_service()
    from viraltracker.services.comic_video.models import AspectRatio
    ratio = AspectRatio.from_string(aspect_ratio)
    return await service.render_all_panels(project_id, aspect_ratio=ratio, force_rerender=force_rerender)


async def approve_all_panels(project_id: str):
    """Approve all panels at once."""
    service = get_service()
    return await service.approve_all_panels(project_id)


async def update_project_aspect_ratio(project_id: str, aspect_ratio: str):
    """Update project aspect ratio."""
    service = get_service()
    return await service.update_aspect_ratio(project_id, aspect_ratio)


async def save_panel_overrides(project_id: str, panel_number: int, overrides: dict):
    """Save panel overrides."""
    from viraltracker.services.comic_video import ComicDirectorService
    from viraltracker.services.comic_video.models import PanelOverrides
    service = ComicDirectorService()
    panel_overrides = PanelOverrides(panel_number=panel_number, **overrides)
    return await service.save_overrides(project_id, panel_number, panel_overrides)


async def clear_panel_overrides(project_id: str, panel_number: int):
    """Clear panel overrides (reset to auto)."""
    from viraltracker.services.comic_video import ComicDirectorService
    service = ComicDirectorService()
    return await service.clear_overrides(project_id, panel_number)


async def upload_to_storage(file_bytes: bytes, filename: str, project_id: str):
    """Upload file to Supabase storage."""
    supabase = get_supabase()
    bucket = "comic-video"
    path = f"{project_id}/{filename}"

    # Check if bucket exists, create if not
    try:
        supabase.storage.from_(bucket).upload(
            path,
            file_bytes,
            {"content-type": "image/png" if filename.endswith('.png') else "image/jpeg"}
        )
    except Exception as e:
        if "already exists" not in str(e).lower():
            raise

    return f"{bucket}/{path}"


# ============================================================================
# UI Components
# ============================================================================

def render_sidebar():
    """Render sidebar with project list."""
    st.sidebar.header("🎬 Comic Video Projects")

    # New project button
    if st.sidebar.button("➕ New Project", use_container_width=True):
        st.session_state.comic_project_id = None
        st.session_state.comic_workflow_step = "upload"
        st.rerun()

    st.sidebar.divider()

    # Recent projects
    st.sidebar.subheader("Recent Projects")
    try:
        projects = asyncio.run(list_projects(10))
        for proj in projects:
            status_icon = {
                "draft": "📝",
                "audio_generating": "🔊",
                "audio_ready": "✅",
                "directing": "🎥",
                "ready_for_review": "👀",
                "rendering": "⏳",
                "complete": "🎬",
                "failed": "❌"
            }.get(proj.status.value, "❓")

            if st.sidebar.button(
                f"{status_icon} {proj.title[:20]}...",
                key=f"proj_{proj.project_id}",
                use_container_width=True
            ):
                st.session_state.comic_project_id = proj.project_id
                st.session_state.comic_workflow_step = "review"
                st.rerun()

    except Exception as e:
        st.sidebar.error(f"Error loading projects: {e}")


def render_upload_step():
    """Render upload/create project step."""
    st.header("📤 Create New Comic Video Project")

    st.markdown("""
    Upload your comic grid image and paste the comic JSON to get started.

    **Requirements:**
    - Comic grid image (PNG/JPG, ~4000×6000px recommended)
    - Comic JSON with panel metadata (from comic generator)
    """)

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Comic Grid Image")
        uploaded_image = st.file_uploader(
            "Upload comic grid",
            type=["png", "jpg", "jpeg"],
            help="The master comic image containing all panels"
        )

        if uploaded_image:
            st.image(uploaded_image, caption="Preview", use_container_width=True)

    with col2:
        st.subheader("Comic JSON")
        json_input = st.text_area(
            "Paste comic JSON",
            height=400,
            help="JSON output from comic generator with panels and layout"
        )

        # Validate JSON
        comic_json = None
        if json_input:
            try:
                comic_json = json.loads(json_input)
                panels = comic_json.get("panels", [])
                st.success(f"✅ Valid JSON with {len(panels)} panels")
            except json.JSONDecodeError as e:
                st.error(f"❌ Invalid JSON: {e}")

    st.divider()

    # Project title
    title = st.text_input(
        "Project Title",
        placeholder="e.g., Inflation Island Episode 1"
    )

    # Create project button
    if st.button("🚀 Create Project", type="primary", disabled=not (uploaded_image and comic_json and title)):
        with st.spinner("Creating project..."):
            try:
                # Upload image
                project_id = str(asyncio.run(asyncio.sleep(0)) or "temp")  # Placeholder
                import uuid
                temp_project_id = str(uuid.uuid4())

                image_bytes = uploaded_image.read()
                grid_url = asyncio.run(upload_to_storage(
                    image_bytes,
                    f"comic_grid.{uploaded_image.name.split('.')[-1]}",
                    temp_project_id
                ))

                # Create project
                project = asyncio.run(create_project(title, grid_url, comic_json))

                # Parse layout
                asyncio.run(parse_layout(project.project_id))

                st.session_state.comic_project_id = project.project_id
                st.session_state.comic_workflow_step = "audio"
                st.success(f"✅ Project created: {project.project_id}")
                st.rerun()

            except Exception as e:
                st.error(f"❌ Error: {e}")


def render_audio_step():
    """Render audio generation step."""
    project_id = st.session_state.comic_project_id

    st.header("🔊 Generate Panel Audio")

    try:
        project = asyncio.run(get_project(project_id))
        if not project:
            st.error("Project not found")
            return

        st.info(f"Project: **{project.title}** | Status: {project.status.value}")

        # Voice selection
        col1, col2 = st.columns([2, 1])
        with col1:
            voice_id = st.selectbox(
                "Voice",
                options=[
                    ("21m00Tcm4TlvDq8ikWAM", "Rachel (Default)"),
                    ("EXAVITQu4vr4xnSDxMaL", "Bella"),
                    ("ErXwobaYiN019PkySvjV", "Antoni"),
                ],
                format_func=lambda x: x[1]
            )[0]

        with col2:
            panel_count = len(project.comic_json.get("panels", []))
            st.metric("Panels to Generate", panel_count)

        # Generate button
        if st.button("🎙️ Generate All Audio", type="primary"):
            with st.spinner("Generating voiceover for all panels..."):
                try:
                    progress = st.progress(0)
                    audio_list = asyncio.run(generate_all_audio(project_id, voice_id))
                    progress.progress(100)
                    st.success(f"✅ Generated audio for {len(audio_list)} panels")
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ Error: {e}")

        # Show existing audio
        st.divider()
        st.subheader("Panel Audio")

        audio_list = asyncio.run(get_audio_list(project_id))
        if audio_list:
            for audio in audio_list:
                with st.expander(f"Panel {audio.panel_number}: {audio.text_content[:50]}..."):
                    col1, col2 = st.columns([2, 1])
                    with col1:
                        # Audio player
                        try:
                            audio_url = asyncio.run(get_signed_url(audio.audio_url))
                            st.audio(audio_url)
                        except:
                            st.warning("Audio preview unavailable")

                        st.caption(f"Duration: {audio.duration_ms/1000:.1f}s | Voice: {audio.voice_name}")

                    with col2:
                        if st.button("🔄 Regenerate", key=f"regen_{audio.panel_number}"):
                            with st.spinner("Regenerating..."):
                                asyncio.run(regenerate_audio(project_id, audio.panel_number, voice_id))
                                st.rerun()

        # Continue button
        if audio_list:
            st.divider()
            if st.button("➡️ Continue to Review", type="primary"):
                # Generate instructions
                with st.spinner("Generating camera instructions..."):
                    asyncio.run(generate_instructions(project_id))
                st.session_state.comic_workflow_step = "review"
                st.rerun()

    except Exception as e:
        st.error(f"Error: {e}")


def render_review_step():
    """Render parallel audio+video review step."""
    project_id = st.session_state.comic_project_id

    st.header("👀 Review Panels")

    try:
        project = asyncio.run(get_project(project_id))
        summary = asyncio.run(get_summary(project_id))

        if not project:
            st.error("Project not found")
            return

        # Project info bar
        st.info(f"**{project.title}** | {summary['total_panels']} panels")

        # Aspect ratio selector and bulk actions
        st.markdown("### Output Settings & Bulk Actions")

        col1, col2, col3, col4 = st.columns([1, 1, 1, 1])

        with col1:
            # Aspect ratio selector
            aspect_options = {
                "9:16": "Vertical (TikTok/Reels)",
                "16:9": "Horizontal (YouTube)",
                "1:1": "Square (Instagram)",
                "4:5": "Portrait (Instagram)"
            }
            current_ratio = st.session_state.comic_aspect_ratio
            new_ratio = st.selectbox(
                "Output Format",
                options=list(aspect_options.keys()),
                format_func=lambda x: aspect_options[x],
                index=list(aspect_options.keys()).index(current_ratio) if current_ratio in aspect_options else 0,
                key="aspect_ratio_select"
            )
            if new_ratio != current_ratio:
                st.session_state.comic_aspect_ratio = new_ratio
                # Update in database
                asyncio.run(update_project_aspect_ratio(project_id, new_ratio))
                st.rerun()

        with col2:
            # Render All button
            force_rerender = st.checkbox("Force re-render", key="force_rerender")
            if st.button("🎬 Render All Panels", type="secondary"):
                with st.spinner("Rendering all panels..."):
                    try:
                        progress_bar = st.progress(0)
                        results = asyncio.run(render_all_panels(
                            project_id,
                            st.session_state.comic_aspect_ratio,
                            force_rerender
                        ))
                        progress_bar.progress(100)
                        successful = len([r for r in results.values() if r])
                        st.success(f"Rendered {successful}/{len(results)} panels")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error: {e}")

        with col3:
            # Approve All button
            all_rendered = summary['instructions']['generated'] > 0
            if st.button("✅ Approve All", type="secondary", disabled=not all_rendered):
                if all_rendered:
                    with st.spinner("Approving all panels..."):
                        try:
                            asyncio.run(approve_all_panels(project_id))
                            st.success("All panels approved!")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error: {e}")

        with col4:
            # Final render button (moved here for visibility)
            ready = summary["ready_for_final_render"]
            if st.button("🎥 Render Final", type="primary" if ready else "secondary", disabled=not ready):
                if ready:
                    with st.spinner("Rendering final video..."):
                        try:
                            final_url = asyncio.run(render_final(project_id))
                            st.success("Final video rendered!")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error: {e}")

        st.divider()

        # Status metrics
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Total Panels", summary["total_panels"])
        with col2:
            st.metric("Audio", f"{summary['audio']['approved']}/{summary['audio']['generated']}")
        with col3:
            st.metric("Video Previews", f"{summary['instructions']['approved']}/{summary['instructions']['generated']}")
        with col4:
            ready = "✅" if summary["ready_for_final_render"] else "❌"
            st.metric("Ready to Render", ready)

        st.divider()

        # Load data
        audio_list = asyncio.run(get_audio_list(project_id))
        instructions = asyncio.run(get_instructions(project_id))

        audio_map = {a.panel_number: a for a in audio_list}
        instr_map = {i.panel_number: i for i in instructions}

        # Panel by panel review
        panels = project.comic_json.get("panels", [])

        for panel in panels:
            panel_num = panel.get("panel_number", 0)
            if panel_num <= 0:
                continue

            audio = audio_map.get(panel_num)
            instr = instr_map.get(panel_num)

            # Determine approval status
            audio_approved = audio.is_approved if audio else False
            video_approved = instr.is_approved if instr else False
            both_approved = audio_approved and video_approved

            status_icon = "✅" if both_approved else "⏳"

            with st.expander(f"{status_icon} Panel {panel_num}: {panel.get('panel_type', 'CONTENT')}", expanded=not both_approved):
                # Two column layout: video preview | audio + settings
                col1, col2 = st.columns([1, 1])

                with col1:
                    st.markdown("**📹 Video Preview**")

                    if instr and instr.preview_url:
                        try:
                            video_url = asyncio.run(get_signed_url(instr.preview_url))
                            st.video(video_url)
                        except:
                            st.info("Preview video available")
                    else:
                        st.info("No preview yet")

                    # Render preview button
                    if st.button(f"🎬 Render Preview", key=f"preview_{panel_num}"):
                        with st.spinner("Rendering preview..."):
                            try:
                                preview_url = asyncio.run(render_preview(project_id, panel_num))
                                st.success("Preview rendered!")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Error: {e}")

                with col2:
                    st.markdown("**🔊 Audio**")

                    if audio:
                        try:
                            audio_url = asyncio.run(get_signed_url(audio.audio_url))
                            st.audio(audio_url)
                        except:
                            st.warning("Audio unavailable")

                        st.caption(f"Duration: {audio.duration_ms/1000:.1f}s")
                    else:
                        st.warning("No audio generated")

                    # Camera & Effects Settings (using checkbox toggle instead of nested expander)
                    st.markdown("**📷 Camera & Effects**")
                    if instr:
                        # Check for existing overrides
                        has_overrides = instr.user_overrides and instr.user_overrides.has_overrides()

                        # Show current settings summary
                        st.caption(f"Zoom: {instr.camera.start_zoom:.1f}→{instr.camera.end_zoom:.1f} | Mood: {instr.mood.value} | Effects: {len(instr.effects.ambient_effects)}")

                        # Toggle to show/hide edit controls
                        show_settings = st.checkbox(
                            "✏️ Edit Settings" + (" ⚙️" if has_overrides else ""),
                            key=f"show_settings_{panel_num}"
                        )

                        if show_settings:
                            # Current values (from override or auto)
                            current_start_zoom = instr.camera.start_zoom
                            current_end_zoom = instr.camera.end_zoom
                            current_mood = instr.mood.value

                            # Camera settings
                            col_a, col_b = st.columns(2)
                            with col_a:
                                start_zoom = st.slider(
                                    "Start Zoom",
                                    min_value=0.5, max_value=2.0,
                                    value=float(current_start_zoom),
                                    step=0.1,
                                    key=f"start_zoom_{panel_num}"
                                )
                            with col_b:
                                end_zoom = st.slider(
                                    "End Zoom",
                                    min_value=0.5, max_value=2.0,
                                    value=float(current_end_zoom),
                                    step=0.1,
                                    key=f"end_zoom_{panel_num}"
                                )

                            # Mood selector
                            moods = ["neutral", "positive", "warning", "danger", "chaos", "dramatic", "celebration"]
                            mood_idx = moods.index(current_mood) if current_mood in moods else 0
                            selected_mood = st.selectbox(
                                "Mood",
                                options=moods,
                                index=mood_idx,
                                key=f"mood_{panel_num}"
                            )

                            # Get effects that the selected mood enables (so checkboxes reflect mood)
                            mood_effects = get_mood_effects(selected_mood)

                            # Effect toggles - use mood preset as default, allow override
                            st.caption("Effects (from mood preset, adjust as needed):")
                            col_e1, col_e2 = st.columns(2)
                            with col_e1:
                                vignette_on = st.checkbox("Vignette", value=mood_effects["vignette"], key=f"vignette_{panel_num}")
                                shake_on = st.checkbox("Shake", value=mood_effects["shake"], key=f"shake_{panel_num}")
                            with col_e2:
                                golden_on = st.checkbox("Golden Glow", value=mood_effects["golden_glow"], key=f"golden_{panel_num}")
                                pulse_on = st.checkbox("Pulse", value=mood_effects["pulse"], key=f"pulse_{panel_num}")

                            # Color tint
                            tint_on = st.checkbox("Color Tint", value=mood_effects["color_tint"], key=f"tint_on_{panel_num}")
                            tint_color = "#FFD700"
                            if tint_on:
                                tint_color = st.color_picker(
                                    "Tint Color",
                                    value=instr.effects.color_tint or "#FFD700",
                                    key=f"tint_color_{panel_num}"
                                )

                            # Action buttons
                            col_btn1, col_btn2 = st.columns(2)
                            with col_btn1:
                                if st.button("💾 Apply", key=f"apply_{panel_num}"):
                                    # Save all current settings as overrides
                                    overrides = {
                                        "camera_start_zoom": float(start_zoom),
                                        "camera_end_zoom": float(end_zoom),
                                        "mood_override": selected_mood,
                                        "vignette_enabled": vignette_on,
                                        "shake_enabled": shake_on,
                                        "golden_glow_enabled": golden_on,
                                        "pulse_enabled": pulse_on,
                                        "color_tint_enabled": tint_on,
                                    }
                                    if tint_on:
                                        overrides["color_tint_color"] = tint_color

                                    asyncio.run(save_panel_overrides(project_id, panel_num, overrides))
                                    st.success("Saved! Re-render to see changes.")
                                    st.rerun()

                            with col_btn2:
                                if has_overrides:
                                    if st.button("🔄 Reset", key=f"reset_{panel_num}"):
                                        asyncio.run(clear_panel_overrides(project_id, panel_num))
                                        st.success("Reset!")
                                        st.rerun()

                            # Status indicator
                            if has_overrides:
                                st.caption("⚙️ Custom settings active")
                    else:
                        st.info("Generate instructions first")

                # Dialogue text
                st.markdown("**💬 Dialogue**")
                st.caption(panel.get("dialogue", "No dialogue"))

                # Approve button
                if not both_approved:
                    if st.button(f"✅ Approve Panel {panel_num}", key=f"approve_{panel_num}", type="primary"):
                        with st.spinner("Approving..."):
                            asyncio.run(approve_panel(project_id, panel_num))
                            st.rerun()
                else:
                    st.success("✅ Panel approved")

        # Final render section
        st.divider()
        st.subheader("🎬 Final Video")

        if summary["ready_for_final_render"]:
            if project.final_video_url:
                st.success("Final video ready!")
                try:
                    video_url = asyncio.run(get_signed_url(project.final_video_url))
                    st.video(video_url)
                    st.download_button(
                        "⬇️ Download Video",
                        data=video_url,
                        file_name="comic_video.mp4"
                    )
                except:
                    st.info(f"Video URL: {project.final_video_url}")
            else:
                if st.button("🎬 Render Final Video", type="primary"):
                    with st.spinner("Rendering final video... This may take a few minutes."):
                        try:
                            final_url = asyncio.run(render_final(project_id))
                            st.success(f"✅ Final video rendered!")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error: {e}")
        else:
            st.warning("Approve all panels before rendering final video")

    except Exception as e:
        st.error(f"Error: {e}")
        import traceback
        st.code(traceback.format_exc())


# ============================================================================
# Main
# ============================================================================

def main():
    st.title("🎬 Comic Panel Video")

    render_sidebar()

    # Route to appropriate step
    if st.session_state.comic_project_id is None:
        render_upload_step()
    elif st.session_state.comic_workflow_step == "audio":
        render_audio_step()
    else:
        render_review_step()


if __name__ == "__main__":
    main()
else:
    main()
