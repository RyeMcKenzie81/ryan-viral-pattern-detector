"""
Editor Handoff Page - Beat-by-beat view for video editors.

Public shareable page showing:
- Script text per beat
- Visual notes per beat
- Audio player per beat
- Asset thumbnails per beat
- SFX per beat
- Download options (individual + ZIP)

Access via URL: /Editor_Handoff?id=<handoff_id>
"""

import streamlit as st
import asyncio
import json
from uuid import UUID
from typing import Optional, Dict, Any, List
from datetime import datetime

# Page config
st.set_page_config(
    page_title="Editor Handoff",
    page_icon="🎬",
    layout="wide"
)


def get_supabase_client():
    """Get Supabase client."""
    from viraltracker.core.database import get_supabase_client
    return get_supabase_client()


def get_handoff_service():
    """Get EditorHandoffService instance."""
    from viraltracker.services.content_pipeline.services.handoff_service import EditorHandoffService
    from viraltracker.services.audio_production_service import AudioProductionService

    db = get_supabase_client()
    audio_service = AudioProductionService()

    return EditorHandoffService(
        supabase_client=db,
        audio_service=audio_service,
        asset_service=None  # Will use direct URLs
    )


def get_audio_url(storage_path: str) -> Optional[str]:
    """Get signed URL for audio file."""
    if not storage_path:
        return None
    try:
        from viraltracker.services.audio_production_service import AudioProductionService
        audio_service = AudioProductionService()
        return asyncio.run(audio_service.get_audio_url(storage_path))
    except Exception:
        return None


def get_asset_url(storage_path_or_url: str) -> Optional[str]:
    """Get URL for asset (handles both storage paths and signed URLs)."""
    if not storage_path_or_url:
        return None

    # If it's already a full URL, return it
    if storage_path_or_url.startswith("http"):
        return storage_path_or_url

    # Otherwise get a signed URL
    try:
        db = get_supabase_client()
        parts = storage_path_or_url.split("/", 1)
        bucket = parts[0]
        path = parts[1] if len(parts) > 1 else storage_path_or_url
        result = db.storage.from_(bucket).create_signed_url(path, 3600)
        return result.get("signedURL", "")
    except Exception:
        return None


def render_handoff_page(handoff_id: str):
    """Render the handoff page for a specific handoff ID."""
    service = get_handoff_service()

    # Load handoff package
    try:
        package = asyncio.run(service.get_handoff(UUID(handoff_id)))
    except Exception as e:
        st.error(f"Failed to load handoff: {e}")
        return

    if not package:
        st.error("Handoff not found. The link may have expired or be invalid.")
        return

    # Page header
    st.title(f"🎬 {package.title}")
    st.caption(f"Brand: **{package.brand_name}** | Created: {package.created_at.strftime('%Y-%m-%d %H:%M')}")

    # Summary stats
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Beats", len(package.beats))
    with col2:
        duration_sec = package.total_duration_ms / 1000
        st.metric("Duration", f"{duration_sec:.1f}s")
    with col3:
        assets_count = sum(len(b.assets) for b in package.beats)
        st.metric("Assets", assets_count)
    with col4:
        sfx_count = sum(len(b.sfx) for b in package.beats)
        st.metric("SFX", sfx_count)

    st.divider()

    # Full Script section
    with st.expander("📜 **Full Script & Storyboard**", expanded=False):
        for beat in package.beats:
            st.markdown(f"**Beat {beat.beat_number}: {beat.beat_name}** ({beat.character})")
            st.markdown(f"> {beat.script_text}")
            if beat.visual_notes:
                st.caption(f"📍 Visual: {beat.visual_notes}")
            if hasattr(beat, 'audio_notes') and beat.audio_notes:
                st.caption(f"🎵 Audio: {beat.audio_notes}")
            st.markdown("---")

    st.divider()

    # Download buttons
    col_download, col_link = st.columns([1, 2])
    with col_download:
        if st.button("📦 Download All (ZIP)", type="primary", use_container_width=True):
            with st.spinner("Generating ZIP file..."):
                try:
                    zip_data = asyncio.run(service.generate_zip(UUID(handoff_id)))
                    st.download_button(
                        label="📥 Click to Download",
                        data=zip_data,
                        file_name=f"{package.title.replace(' ', '-').lower()}-handoff.zip",
                        mime="application/zip",
                        use_container_width=True
                    )
                except Exception as e:
                    st.error(f"Failed to generate ZIP: {e}")

    with col_link:
        # Copy link button (shows current URL)
        current_url = f"?id={handoff_id}"
        st.code(current_url, language=None)
        st.caption("Share this URL with your editor")

    st.divider()

    # Beat-by-beat view
    st.header("Beat-by-Beat Breakdown")

    for beat in package.beats:
        render_beat_card(beat)


def render_beat_card(beat):
    """Render a single beat card with all its content."""
    # Character color mapping
    char_colors = {
        "every-coon": "#3498db",
        "everycoon": "#3498db",
        "boomer": "#e67e22",
        "fed": "#7f8c8d",
        "whale": "#9b59b6",
        "wojak": "#e74c3c",
        "chad": "#27ae60"
    }

    char_color = char_colors.get(beat.character.lower(), "#95a5a6")

    with st.container():
        # Beat header
        st.markdown(
            f"""
            <div style="
                background: linear-gradient(90deg, {char_color}22, transparent);
                border-left: 4px solid {char_color};
                padding: 10px 15px;
                margin-bottom: 10px;
                border-radius: 0 8px 8px 0;
            ">
                <h3 style="margin: 0; color: {char_color};">
                    Beat {beat.beat_number}: {beat.beat_name}
                </h3>
                <span style="color: #888; font-size: 0.9em;">
                    {beat.character} | {beat.timestamp_start or '0:00'} - {beat.timestamp_end or '?'}
                </span>
            </div>
            """,
            unsafe_allow_html=True
        )

        # Main content columns
        col_script, col_media = st.columns([2, 1])

        with col_script:
            # Script text
            st.markdown("**Script:**")
            st.markdown(
                f"""
                <div style="
                    background: #f8f9fa;
                    padding: 15px;
                    border-radius: 8px;
                    font-size: 1.1em;
                    line-height: 1.6;
                    margin-bottom: 10px;
                ">
                    {beat.script_text}
                </div>
                """,
                unsafe_allow_html=True
            )

            # Visual notes (storyboard)
            if beat.visual_notes:
                st.markdown("**Visual Notes (Storyboard):**")
                st.info(beat.visual_notes)

            # Audio notes (music/SFX cues from script)
            if hasattr(beat, 'audio_notes') and beat.audio_notes:
                st.markdown("**Audio Notes:**")
                st.caption(beat.audio_notes)

            # Editor notes (pacing and style guidance)
            if hasattr(beat, 'editor_notes') and beat.editor_notes:
                st.markdown("**Editor Notes:**")
                st.caption(beat.editor_notes)

        with col_media:
            # Audio player
            st.markdown("**Audio:**")
            if beat.audio_storage_path:
                audio_url = get_audio_url(beat.audio_storage_path)
                if audio_url:
                    st.audio(audio_url)
                    duration_sec = beat.audio_duration_ms / 1000 if beat.audio_duration_ms else 0
                    st.caption(f"Duration: {duration_sec:.1f}s")
                    # Download audio button
                    st.markdown(f"[Download Audio]({audio_url})")
                else:
                    st.caption("Audio available (loading...)")
            else:
                st.caption("No audio")

        # Assets section - organized by type
        if beat.assets:
            st.markdown("**Assets:**")

            # Group assets by type
            asset_groups = {
                'background': [],
                'character': [],
                'prop': [],
                'effect': []
            }
            for asset in beat.assets:
                # Use 'asset_type' key (from handoff service) or fall back to 'type'
                asset_type = (asset.get('asset_type') or asset.get('type') or 'prop').lower()
                if asset_type in asset_groups:
                    asset_groups[asset_type].append(asset)
                else:
                    asset_groups['prop'].append(asset)

            # Render each group with a header
            type_labels = {
                'background': '🏞️ Backgrounds',
                'character': '👤 Characters',
                'prop': '🔧 Props',
                'effect': '✨ Effects'
            }

            for asset_type, label in type_labels.items():
                assets_of_type = asset_groups.get(asset_type, [])
                if assets_of_type:
                    st.markdown(f"**{label}:**")
                    asset_cols = st.columns(min(len(assets_of_type), 4))
                    for idx, asset in enumerate(assets_of_type):
                        with asset_cols[idx % len(asset_cols)]:
                            image_url = get_asset_url(asset.get("image_url", ""))
                            if image_url:
                                st.image(image_url, caption=asset.get("name", "Asset"), width=120)
                            else:
                                st.markdown(
                                    f"""
                                    <div style="
                                        background: #eee;
                                        padding: 10px;
                                        border-radius: 4px;
                                        text-align: center;
                                    ">
                                        {asset.get("name", "Asset")}
                                    </div>
                                    """,
                                    unsafe_allow_html=True
                                )

        # SFX section with audio playback and download
        if beat.sfx:
            st.markdown("**SFX / Music:**")
            for sfx in beat.sfx:
                sfx_name = sfx.get("name", "Sound Effect")
                sfx_duration = sfx.get("duration_seconds", 2.0)
                sfx_url = sfx.get("audio_url")

                col_sfx_name, col_sfx_player, col_sfx_download = st.columns([2, 3, 1])
                with col_sfx_name:
                    # Show if it's music or SFX based on name
                    icon = "🎵" if "music" in sfx_name.lower() else "🔊"
                    st.markdown(f"{icon} **{sfx_name}** ({sfx_duration}s)")
                with col_sfx_player:
                    if sfx_url:
                        st.audio(sfx_url)
                    else:
                        st.caption("Audio not available")
                with col_sfx_download:
                    if sfx_url:
                        st.markdown(f"[Download]({sfx_url})")

        st.divider()


def render_no_handoff_page():
    """Render page when no handoff ID is provided."""
    st.title("🎬 Editor Handoff")
    st.markdown("""
    This page displays editor handoff packages with beat-by-beat breakdowns.

    **To view a handoff:**
    1. Go to the Content Pipeline
    2. Generate a handoff package for your project
    3. Copy the shareable link
    4. Open the link in your browser

    **Or** enter a handoff ID below:
    """)

    handoff_id_input = st.text_input("Handoff ID", placeholder="Enter handoff UUID...")

    if handoff_id_input:
        try:
            UUID(handoff_id_input)
            st.info(f"Loading handoff: {handoff_id_input}")
            render_handoff_page(handoff_id_input)
        except ValueError:
            st.error("Invalid handoff ID format. Please enter a valid UUID.")


def main():
    """Main page entry point."""
    # Get handoff ID from query params
    query_params = st.query_params
    handoff_id = query_params.get("id")

    if handoff_id:
        render_handoff_page(handoff_id)
    else:
        render_no_handoff_page()


if __name__ == "__main__":
    main()
else:
    main()
