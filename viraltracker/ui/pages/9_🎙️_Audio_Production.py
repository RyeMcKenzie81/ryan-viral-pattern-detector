"""
Audio Production UI

Streamlit interface for:
- Pasting/uploading ELS scripts
- Generating audio via ElevenLabs
- Reviewing and selecting takes
- Exporting final audio files
"""

import streamlit as st
import asyncio
from pathlib import Path
from datetime import datetime

# Page config (must be first)
st.set_page_config(
    page_title="Audio Production",
    page_icon="🎙️",
    layout="wide"
)

# Authentication
from viraltracker.ui.auth import require_auth
require_auth()

# Initialize session state
if 'audio_session_id' not in st.session_state:
    st.session_state.audio_session_id = None
if 'audio_workflow_running' not in st.session_state:
    st.session_state.audio_workflow_running = False
if 'audio_workflow_result' not in st.session_state:
    st.session_state.audio_workflow_result = None
if 'els_input' not in st.session_state:
    st.session_state.els_input = ""
if 'export_zip' not in st.session_state:
    st.session_state.export_zip = None
if 'export_filename' not in st.session_state:
    st.session_state.export_filename = None


def get_supabase_client():
    """Get Supabase client."""
    from viraltracker.core.database import get_supabase_client
    return get_supabase_client()


# ============================================================================
# Async Helpers
# ============================================================================

async def run_audio_workflow(els_content: str, project_name: str = "trash-panda"):
    """Run the complete audio workflow."""
    from viraltracker.agent.dependencies import AgentDependencies
    from viraltracker.agent.agents.audio_production_agent import complete_audio_workflow

    # Create a mock RunContext for the workflow
    class MockRunContext:
        def __init__(self, deps):
            self.deps = deps

    deps = AgentDependencies.create(project_name=project_name)
    ctx = MockRunContext(deps)

    return await complete_audio_workflow(ctx, els_content, project_name)


async def load_session(session_id: str):
    """Load a production session."""
    from viraltracker.services.audio_production_service import AudioProductionService
    service = AudioProductionService()
    return await service.get_session(session_id)


async def load_recent_sessions():
    """Load recent sessions for sidebar."""
    from viraltracker.services.audio_production_service import AudioProductionService
    service = AudioProductionService()
    return await service.get_recent_sessions()


async def regenerate_beat(session_id, beat_id, direction, pace, stability, style):
    """Regenerate a beat with new settings."""
    from viraltracker.agent.dependencies import AgentDependencies
    from viraltracker.agent.agents.audio_production_agent import regenerate_beat_audio

    class MockRunContext:
        def __init__(self, deps):
            self.deps = deps

    deps = AgentDependencies.create()
    ctx = MockRunContext(deps)

    return await regenerate_beat_audio(
        ctx, session_id, beat_id,
        new_direction=direction if direction else None,
        new_pace=pace if pace != "normal" else None,
        stability=stability,
        style=style
    )


async def select_take_async(session_id, beat_id, take_id):
    """Select a take."""
    from viraltracker.services.audio_production_service import AudioProductionService
    service = AudioProductionService()
    await service.select_take(session_id, beat_id, take_id)


async def export_session(session_id):
    """Export selected takes."""
    from viraltracker.services.audio_production_service import AudioProductionService
    service = AudioProductionService()
    return await service.export_selected_takes(session_id)


async def load_voice_profiles():
    """Load voice profiles."""
    from viraltracker.services.audio_production_service import AudioProductionService
    service = AudioProductionService()
    return await service.get_all_voice_profiles()


async def get_audio_url(storage_path: str) -> str:
    """Get a signed URL for audio playback."""
    from viraltracker.services.audio_production_service import AudioProductionService
    service = AudioProductionService()
    return await service.get_audio_url(storage_path)


async def download_audio_data(storage_path: str) -> bytes:
    """Download audio data from storage."""
    from viraltracker.services.audio_production_service import AudioProductionService
    service = AudioProductionService()
    return await service.download_audio(storage_path)


# ============================================================================
# UI Components
# ============================================================================

def render_sidebar():
    """Render sidebar with sessions and profiles."""
    st.sidebar.header("Sessions")

    # Load recent sessions
    try:
        sessions = asyncio.run(load_recent_sessions())

        for s in sessions[:10]:
            status_emoji = {
                'draft': '📝',
                'generating': '⏳',
                'in_progress': '🎵',
                'completed': '✅',
                'exported': '📦'
            }.get(s.get('status', ''), '❓')

            title = s.get('video_title', 'Untitled')[:25]
            if st.sidebar.button(f"{status_emoji} {title}", key=f"load_{s['id']}"):
                st.session_state.audio_session_id = s['id']
                st.session_state.audio_workflow_result = None
                st.rerun()
    except Exception as e:
        st.sidebar.caption(f"Could not load sessions: {e}")

    st.sidebar.divider()

    if st.sidebar.button("New Session"):
        st.session_state.audio_session_id = None
        st.session_state.audio_workflow_result = None
        st.rerun()

    st.sidebar.divider()

    # Voice profiles
    with st.sidebar.expander("Voice Profiles"):
        try:
            profiles = asyncio.run(load_voice_profiles())
            for p in profiles:
                st.markdown(f"**{p.display_name}**")
                st.caption(f"stability={p.stability}, style={p.style}, speed={p.speed}")
        except Exception as e:
            st.caption(f"Error: {e}")


def render_new_session():
    """Render new session creation UI."""
    st.header("Create New Audio Session")

    tab1, tab2 = st.tabs(["Paste ELS Script", "Upload File"])

    with tab1:
        els_content = st.text_area(
            "ElevenLabs Script (ELS Format)",
            height=400,
            placeholder="""[META]
video_title: My Video Title
project: trash-panda
default_character: every-coon

[BEAT: 01_hook]
name: Hook
---
[DIRECTION: Punchy and direct]
[PACE: fast]
Your script here.
[PAUSE: 100ms]
[END_BEAT]""",
            key="els_input_area"
        )

        if els_content:
            st.session_state.els_input = els_content

            # Validate
            try:
                from viraltracker.services.els_parser_service import validate_els
                validation = validate_els(els_content)

                if validation.errors:
                    for err in validation.errors:
                        st.error(f"Error: {err}")
                else:
                    st.success(f"Valid script - {validation.beat_count} beats")

                    for warn in validation.warnings:
                        st.warning(f"Warning: {warn}")

                    if validation.character_count:
                        chars = ", ".join(
                            f"{k} ({v})" for k, v in validation.character_count.items()
                        )
                        st.caption(f"Characters: {chars}")

                    # Generate button
                    if st.button(
                        "Generate Audio",
                        type="primary",
                        disabled=st.session_state.audio_workflow_running
                    ):
                        st.session_state.audio_workflow_running = True
                        st.rerun()
            except Exception as e:
                st.error(f"Validation error: {e}")

    with tab2:
        uploaded = st.file_uploader("Upload ELS file", type=["els", "txt", "md"])

        if uploaded:
            content = uploaded.read().decode()
            st.text_area("Preview", content, height=300, disabled=True)

            try:
                from viraltracker.services.els_parser_service import validate_els
                validation = validate_els(content)

                if validation.is_valid:
                    st.success(f"Valid script - {validation.beat_count} beats")
                    if st.button("Generate Audio", type="primary"):
                        st.session_state.els_input = content
                        st.session_state.audio_workflow_running = True
                        st.rerun()
                else:
                    for err in validation.errors:
                        st.error(err)
            except Exception as e:
                st.error(f"Error: {e}")

    # Run workflow if triggered
    if st.session_state.audio_workflow_running:
        els = st.session_state.get('els_input', '')
        if els:
            st.info("Generating audio... This may take a few minutes.")
            st.warning("Please wait. Do not refresh the page.")

            try:
                result = asyncio.run(run_audio_workflow(els))
                st.session_state.audio_workflow_result = result
                st.session_state.audio_session_id = result['session_id']
                st.session_state.audio_workflow_running = False
                st.rerun()
            except Exception as e:
                st.session_state.audio_workflow_running = False
                st.error(f"Workflow failed: {str(e)}")


def render_session_editor():
    """Render session editing interface."""
    try:
        session = asyncio.run(load_session(st.session_state.audio_session_id))
    except Exception as e:
        st.error(f"Failed to load session: {e}")
        return

    # Header
    col1, col2, col3 = st.columns([3, 1, 1])
    with col1:
        st.header(f"{session.video_title}")
    with col2:
        status_emoji = {
            'draft': '📝',
            'generating': '⏳',
            'in_progress': '🎵',
            'completed': '✅',
            'exported': '📦'
        }
        st.metric("Status", f"{status_emoji.get(session.status, '❓')} {session.status}")
    with col3:
        st.metric("Beats", len(session.beats))

    # Action bar
    col1, col2, col3 = st.columns(3)

    with col1:
        has_selections = any(b.selected_take_id for b in session.beats)
        if st.button("Export Selected", disabled=not has_selections):
            with st.spinner("Preparing download..."):
                import zipfile
                import io

                zip_buffer = io.BytesIO()
                file_count = 0

                with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
                    for bwt in session.beats:
                        if not bwt.selected_take_id:
                            continue
                        selected_take = next(
                            (t for t in bwt.takes if t.take_id == bwt.selected_take_id), None
                        )
                        if not selected_take:
                            continue

                        audio_path_str = selected_take.audio_path
                        filename = f"{bwt.beat.beat_id}.mp3"

                        try:
                            if audio_path_str.startswith("audio-production/"):
                                # Download from Supabase Storage
                                audio_data = asyncio.run(download_audio_data(audio_path_str))
                                zf.writestr(filename, audio_data)
                            else:
                                # Local file
                                local_path = Path(audio_path_str)
                                if local_path.exists():
                                    zf.write(local_path, filename)
                            file_count += 1
                        except Exception as e:
                            st.warning(f"Failed to export {bwt.beat.beat_id}: {e}")

                zip_buffer.seek(0)

                if file_count > 0:
                    st.session_state['export_zip'] = zip_buffer.getvalue()
                    st.session_state['export_filename'] = f"{session.video_title.replace(' ', '_')}_audio.zip"
                    st.success(f"Ready! {file_count} files prepared.")
                    st.rerun()
                else:
                    st.error("No files could be exported")

        # Show download button if export is ready
        if st.session_state.get('export_zip'):
            st.download_button(
                label="Download ZIP",
                data=st.session_state['export_zip'],
                file_name=st.session_state.get('export_filename', 'audio_export.zip'),
                mime="application/zip"
            )

    with col2:
        if st.button("Refresh"):
            st.rerun()

    with col3:
        if st.button("Back to New"):
            st.session_state.audio_session_id = None
            st.rerun()

    st.divider()

    # Beat list
    for bwt in session.beats:
        render_beat_row(session.session_id, bwt)


def render_beat_row(session_id: str, bwt):
    """Render a single beat with audio player."""
    beat = bwt.beat

    with st.container():
        col1, col2, col3 = st.columns([1, 2, 3])

        with col1:
            st.markdown(f"**{beat.beat_number:02d}**")
            st.caption(beat.character.value)

        with col2:
            st.markdown(f"**{beat.beat_name}**")
            with st.expander("Script"):
                st.text(beat.combined_script)
                if beat.primary_direction:
                    st.caption(f"Direction: {beat.primary_direction}")

        with col3:
            takes = bwt.takes

            if takes:
                # Take selector
                take_options = {
                    f"Take {i+1} ({t.audio_duration_ms/1000:.1f}s)": t.take_id
                    for i, t in enumerate(takes)
                }

                current = bwt.selected_take_id
                current_label = next(
                    (k for k, v in take_options.items() if v == current),
                    list(take_options.keys())[0] if take_options else None
                )

                if take_options:
                    selected_label = st.selectbox(
                        "Take",
                        list(take_options.keys()),
                        index=list(take_options.keys()).index(current_label) if current_label else 0,
                        key=f"select_{beat.beat_id}",
                        label_visibility="collapsed"
                    )

                    selected_take_id = take_options[selected_label]

                    # Update if changed
                    if selected_take_id != current:
                        asyncio.run(select_take_async(session_id, beat.beat_id, selected_take_id))
                        st.rerun()

                    # Audio player
                    selected_take = next(
                        (t for t in takes if t.take_id == selected_take_id), None
                    )
                    if selected_take:
                        audio_path_str = selected_take.audio_path
                        # Check if it's a storage path or local path
                        if audio_path_str.startswith("audio-production/"):
                            # Fetch from Supabase Storage
                            try:
                                audio_url = asyncio.run(get_audio_url(audio_path_str))
                                if audio_url:
                                    st.audio(audio_url, format="audio/mp3")
                                else:
                                    st.warning("Could not get audio URL")
                            except Exception as e:
                                st.warning(f"Audio error: {e}")
                        else:
                            # Local file path
                            audio_path = Path(audio_path_str)
                            if audio_path.exists():
                                st.audio(str(audio_path), format="audio/mp3")
                            else:
                                st.warning("Audio file not found")

                # Revise button
                if st.button("Revise", key=f"revise_{beat.beat_id}"):
                    st.session_state[f"show_revise_{beat.beat_id}"] = True
            else:
                st.caption("No audio generated")

        # Revise panel
        if st.session_state.get(f"show_revise_{beat.beat_id}"):
            with st.expander("Revise Settings", expanded=True):
                new_dir = st.text_input(
                    "Direction",
                    value=beat.primary_direction or "",
                    key=f"dir_{beat.beat_id}"
                )

                c1, c2, c3 = st.columns(3)
                with c1:
                    pace = st.selectbox(
                        "Pace",
                        ["slow", "deliberate", "normal", "quick", "fast", "chaos"],
                        index=2,
                        key=f"pace_{beat.beat_id}"
                    )
                with c2:
                    stab = st.slider(
                        "Stability",
                        0.0, 1.0, 0.35,
                        key=f"stab_{beat.beat_id}"
                    )
                with c3:
                    style = st.slider(
                        "Style",
                        0.0, 1.0, 0.45,
                        key=f"style_{beat.beat_id}"
                    )

                c1, c2 = st.columns(2)
                with c1:
                    if st.button("Generate", key=f"gen_{beat.beat_id}"):
                        with st.spinner("Generating..."):
                            asyncio.run(
                                regenerate_beat(session_id, beat.beat_id, new_dir, pace, stab, style)
                            )
                            st.session_state[f"show_revise_{beat.beat_id}"] = False
                            st.rerun()
                with c2:
                    if st.button("Cancel", key=f"cancel_{beat.beat_id}"):
                        st.session_state[f"show_revise_{beat.beat_id}"] = False
                        st.rerun()

        st.divider()


# ============================================================================
# Main
# ============================================================================

st.title("Audio Production")
st.markdown("**Generate voice audio from ElevenLabs Script (ELS) files**")

render_sidebar()

if st.session_state.audio_session_id:
    render_session_editor()
else:
    render_new_session()
