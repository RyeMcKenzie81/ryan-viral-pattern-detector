"""
Content Pipeline - End-to-end content creation workflow for Trash Panda Economics.

MVP 1: Topic Discovery
- Create new content project
- Discover and evaluate topics using ChatGPT
- Select topic for script generation

Future MVPs will add:
- Script generation and review
- Asset management
- Editor handoff
- Comic path
"""

import streamlit as st
import asyncio
import json
import logging
from datetime import datetime
from uuid import UUID
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)

# Page config
st.set_page_config(
    page_title="Content Pipeline",
    page_icon="📝",
    layout="wide"
)

# Authentication
from viraltracker.ui.auth import require_auth
require_auth()

# Initialize session state
if 'pipeline_brand_id' not in st.session_state:
    st.session_state.pipeline_brand_id = None
if 'pipeline_project_id' not in st.session_state:
    st.session_state.pipeline_project_id = None
if 'discovered_topics' not in st.session_state:
    st.session_state.discovered_topics = []
if 'discovery_running' not in st.session_state:
    st.session_state.discovery_running = False
if 'selected_topic' not in st.session_state:
    st.session_state.selected_topic = None
if 'current_script' not in st.session_state:
    st.session_state.current_script = None
if 'script_review' not in st.session_state:
    st.session_state.script_review = None
if 'script_generating' not in st.session_state:
    st.session_state.script_generating = False
if 'selected_failed_items' not in st.session_state:
    st.session_state.selected_failed_items = set()
if 'revision_running' not in st.session_state:
    st.session_state.revision_running = False
# Audio tab state (MVP 3)
if 'els_converting' not in st.session_state:
    st.session_state.els_converting = False
if 'audio_generating' not in st.session_state:
    st.session_state.audio_generating = False
if 'current_els' not in st.session_state:
    st.session_state.current_els = None
# Assets tab state (MVP 4)
if 'asset_extracting' not in st.session_state:
    st.session_state.asset_extracting = False
if 'extracted_assets' not in st.session_state:
    st.session_state.extracted_assets = []
# Asset generation state (MVP 5)
if 'asset_generating' not in st.session_state:
    st.session_state.asset_generating = False
if 'generation_progress' not in st.session_state:
    st.session_state.generation_progress = 0
# SFX tab state
if 'sfx_extracting' not in st.session_state:
    st.session_state.sfx_extracting = False
if 'sfx_generating' not in st.session_state:
    st.session_state.sfx_generating = False
# Handoff tab state (MVP 6)
if 'handoff_generating' not in st.session_state:
    st.session_state.handoff_generating = False
# Comic tab state (Phase 8)
if 'comic_condensing' not in st.session_state:
    st.session_state.comic_condensing = False
if 'comic_evaluating' not in st.session_state:
    st.session_state.comic_evaluating = False
if 'current_comic' not in st.session_state:
    st.session_state.current_comic = None
if 'comic_evaluation' not in st.session_state:
    st.session_state.comic_evaluation = None
# Comic image generation state (Phase 9)
if 'comic_image_generating' not in st.session_state:
    st.session_state.comic_image_generating = False
if 'comic_image_evaluating' not in st.session_state:
    st.session_state.comic_image_evaluating = False
if 'comic_exporting' not in st.session_state:
    st.session_state.comic_exporting = False
if 'comic_revising' not in st.session_state:
    st.session_state.comic_revising = False


def get_supabase_client():
    """Get Supabase client."""
    from viraltracker.core.database import get_supabase_client
    return get_supabase_client()


def get_doc_service():
    """Get DocService instance for knowledge base queries."""
    import os
    from viraltracker.services.knowledge_base import DocService
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None
    return DocService(supabase=get_supabase_client(), openai_api_key=api_key)


def get_gemini_service():
    """Get GeminiService instance."""
    from viraltracker.services.gemini_service import GeminiService
    try:
        return GeminiService()
    except ValueError:
        return None


def get_content_pipeline_service():
    """Get ContentPipelineService instance."""
    from viraltracker.services.content_pipeline.services.content_pipeline_service import ContentPipelineService
    db = get_supabase_client()
    docs = get_doc_service()
    gemini = get_gemini_service()
    return ContentPipelineService(supabase_client=db, docs_service=docs, gemini_service=gemini)


def get_asset_service():
    """Get AssetManagementService instance."""
    from viraltracker.services.content_pipeline.services.asset_service import AssetManagementService
    db = get_supabase_client()
    gemini = get_gemini_service()
    return AssetManagementService(supabase_client=db, gemini_service=gemini)


def get_asset_generation_service():
    """Get AssetGenerationService instance."""
    from viraltracker.services.content_pipeline.services.asset_generation_service import AssetGenerationService
    import os
    db = get_supabase_client()
    gemini = get_gemini_service()
    elevenlabs_key = os.environ.get("ELEVENLABS_API_KEY")
    return AssetGenerationService(
        supabase_client=db,
        gemini_service=gemini,
        elevenlabs_api_key=elevenlabs_key
    )


def get_topic_service():
    """Get TopicDiscoveryService instance."""
    from viraltracker.services.content_pipeline.services.topic_service import TopicDiscoveryService
    db = get_supabase_client()
    docs = get_doc_service()
    return TopicDiscoveryService(supabase_client=db, docs_service=docs)


def get_script_service():
    """Get ScriptGenerationService instance."""
    from viraltracker.services.content_pipeline.services.script_service import ScriptGenerationService
    db = get_supabase_client()
    docs = get_doc_service()
    return ScriptGenerationService(supabase_client=db, docs_service=docs)


def get_handoff_service():
    """Get EditorHandoffService instance."""
    from viraltracker.services.content_pipeline.services.handoff_service import EditorHandoffService
    from viraltracker.services.audio_production_service import AudioProductionService
    db = get_supabase_client()
    audio_service = AudioProductionService()
    asset_service = get_asset_service()
    return EditorHandoffService(
        supabase_client=db,
        audio_service=audio_service,
        asset_service=asset_service
    )


def get_comic_service():
    """Get ComicService instance."""
    from viraltracker.services.content_pipeline.services.comic_service import ComicService
    db = get_supabase_client()
    docs = get_doc_service()
    return ComicService(supabase_client=db, docs_service=docs)


def get_script_data_for_project(project_id: str) -> Optional[Dict]:
    """Load the approved script data for a project."""
    try:
        db = get_supabase_client()
        result = db.table("script_versions").select(
            "script_content"
        ).eq("project_id", project_id).eq("status", "approved").order(
            "version_number", desc=True
        ).limit(1).execute()

        if not result.data:
            return None

        script_content = result.data[0].get("script_content")
        if isinstance(script_content, str):
            return json.loads(script_content)
        return script_content
    except Exception:
        return None


def get_beat_context(script_data: Optional[Dict], script_reference: Any) -> str:
    """
    Get context about how an asset/SFX is used based on beat references.

    Args:
        script_data: The script data with beats array
        script_reference: JSON array of beat IDs (or string/list)

    Returns:
        Formatted string describing usage context
    """
    if not script_data:
        return ""

    # Parse script_reference if it's a string
    beat_ids = script_reference
    if isinstance(script_reference, str):
        try:
            beat_ids = json.loads(script_reference)
        except:
            beat_ids = []

    if not beat_ids:
        return ""

    # Build a lookup map of beats by beat_id
    beats = script_data.get("beats", [])
    beat_map = {b.get("beat_id"): b for b in beats}

    # Gather context from referenced beats
    contexts = []
    for beat_id in beat_ids[:3]:  # Limit to first 3 beats for brevity
        beat = beat_map.get(beat_id)
        if beat:
            beat_name = beat.get("beat_name", beat_id)
            visual = beat.get("visual_notes", "")
            script = beat.get("script", "")[:100]  # First 100 chars of dialogue
            audio = beat.get("audio_notes", "")

            context_parts = [f"**{beat_name}**"]
            if visual:
                context_parts.append(f"Visual: {visual[:150]}")
            if script:
                context_parts.append(f"Script: \"{script}...\"")
            if audio:
                context_parts.append(f"Audio: {audio[:100]}")

            contexts.append(" | ".join(context_parts))

    if len(beat_ids) > 3:
        contexts.append(f"...and {len(beat_ids) - 3} more beats")

    return "\n".join(contexts)


def _build_prompt_preview(asset_name: str, asset_type: str, description: str) -> str:
    """Build a preview of the prompt that will be used for generation."""
    style = (
        "Style similar to 'Cyanide and Happiness' or 'Brewstew'. "
        "Large, smooth, pill-shaped heads with soft 3D shading and gradients, "
        "simple rectangular bodies, and thick black stick-figure limbs. "
        "Clean vector aesthetic. 2D, high contrast."
    )

    if asset_type == "character":
        return f"""A character asset sheet for 2D puppet animation. {style}

The Subject: {description}

The Layout:
- Row 1 (Heads): Four large floating heads showing distinct expressions.
- Row 2 (Bodies): Standard body/torso + detached limbs for rigging.

Background is plain white for easy cropping."""

    elif asset_type == "background":
        return f"""A 16:9 widescreen background scene for 2D animation. {style}

The Scene: {description}

Requirements:
- Wide cinematic composition (16:9 aspect ratio)
- No characters in the scene
- Suitable for layering animated characters on top"""

    elif asset_type == "prop":
        return f"""A single prop/object for 2D animation. {style}

The Object: {description}

Requirements:
- Single object, centered composition
- Plain white background for easy cropping
- Clean edges, suitable for cutout"""

    elif asset_type == "effect":
        return f"""A visual effect overlay for 2D animation. {style}

The Effect: {description}

Requirements:
- Transparent or easily removable background
- Suitable for overlaying on video"""

    else:
        return f"{description}. {style}"


def get_brands():
    """Fetch all brands."""
    try:
        db = get_supabase_client()
        result = db.table("brands").select("id, name").order("name").execute()
        return result.data
    except Exception as e:
        st.error(f"Failed to fetch brands: {e}")
        return []


def get_projects_for_brand(brand_id: str) -> List[Dict]:
    """Fetch content projects for a brand."""
    try:
        db = get_supabase_client()
        result = db.table("content_projects").select("*").eq(
            "brand_id", brand_id
        ).order("created_at", desc=True).execute()
        return result.data or []
    except Exception as e:
        st.error(f"Failed to fetch projects: {e}")
        return []


def get_topics_for_project(project_id: str) -> List[Dict]:
    """Fetch topic suggestions for a project."""
    try:
        db = get_supabase_client()
        result = db.table("topic_suggestions").select("*").eq(
            "project_id", project_id
        ).order("score", desc=True).execute()
        return result.data or []
    except Exception as e:
        st.error(f"Failed to fetch topics: {e}")
        return []


def render_topic_card(topic: Dict, idx: int, project_id: str):
    """Render a single topic suggestion card."""
    score = topic.get('score', 0)
    is_selected = topic.get('is_selected', False)
    quick_approve = topic.get('quick_approve_eligible', False)

    # Determine card styling based on score
    if score >= 90:
        border_color = "#4CAF50"  # Green
        score_color = "green"
    elif score >= 70:
        border_color = "#FF9800"  # Orange
        score_color = "orange"
    else:
        border_color = "#9E9E9E"  # Gray
        score_color = "gray"

    # Card container
    with st.container():
        col1, col2 = st.columns([4, 1])

        with col1:
            # Title with selection indicator
            title = topic.get('title', 'Untitled')
            if is_selected:
                st.markdown(f"### ✅ {title}")
            elif quick_approve:
                st.markdown(f"### ⭐ {title}")
            else:
                st.markdown(f"### {title}")

            # Description
            st.markdown(topic.get('description', ''))

            # Hook options
            hooks = topic.get('hook_options', [])
            if hooks:
                with st.expander("Hook Options"):
                    for i, hook in enumerate(hooks, 1):
                        st.markdown(f"**{i}.** {hook}")

            # Metadata row
            meta_cols = st.columns(4)
            with meta_cols[0]:
                st.caption(f"📊 Emotion: {topic.get('target_emotion', 'N/A')}")
            with meta_cols[1]:
                st.caption(f"📈 Difficulty: {topic.get('difficulty', 'N/A')}")
            with meta_cols[2]:
                st.caption(f"⏰ Timeliness: {topic.get('timeliness', 'N/A')}")
            with meta_cols[3]:
                if quick_approve:
                    st.caption("⭐ Quick Approve Eligible")

            # Reasoning (collapsed)
            if topic.get('reasoning'):
                with st.expander("AI Reasoning"):
                    st.markdown(topic.get('reasoning'))

            if topic.get('improvement_suggestions'):
                with st.expander("Improvement Suggestions"):
                    st.markdown(topic.get('improvement_suggestions'))

        with col2:
            # Score display
            st.metric("Score", f"{score}/100")

            # Select button
            if not is_selected:
                if st.button("Select", key=f"select_topic_{topic.get('id', idx)}"):
                    select_topic(topic.get('id'), project_id)
                    st.rerun()
            else:
                st.success("Selected!")

        st.divider()


def select_topic(topic_id: str, project_id: str):
    """Mark a topic as selected."""
    try:
        db = get_supabase_client()

        # Deselect all topics for this project
        db.table("topic_suggestions").update({
            "is_selected": False
        }).eq("project_id", project_id).execute()

        # Select the chosen topic
        result = db.table("topic_suggestions").update({
            "is_selected": True
        }).eq("id", topic_id).execute()

        if result.data:
            topic = result.data[0]
            # Update project with selected topic
            db.table("content_projects").update({
                "topic_title": topic.get("title"),
                "topic_description": topic.get("description"),
                "topic_score": topic.get("score"),
                "topic_reasoning": topic.get("reasoning"),
                "hook_options": topic.get("hook_options"),
                "workflow_state": "topic_selected"
            }).eq("id", project_id).execute()

            st.session_state.selected_topic = topic
            st.success(f"Selected topic: {topic.get('title')}")

    except Exception as e:
        st.error(f"Failed to select topic: {e}")


async def run_topic_discovery(brand_id: str, project_id: str, num_topics: int, focus_areas: List[str]):
    """Run topic discovery asynchronously."""
    service = get_topic_service()

    # Discover topics
    topics = await service.discover_topics(
        brand_id=UUID(brand_id),
        num_topics=num_topics,
        focus_areas=focus_areas if focus_areas else None
    )

    # Evaluate topics
    topics = await service.evaluate_topics(
        topics=topics,
        brand_id=UUID(brand_id)
    )

    # Save to database
    await service.save_topics_to_db(
        project_id=UUID(project_id),
        topics=topics
    )

    return topics


def render_project_dashboard():
    """Render the main project dashboard."""
    st.header("📝 Content Pipeline")

    # Brand selector
    brands = get_brands()
    if not brands:
        st.warning("No brands found. Please create a brand first.")
        return

    brand_options = {b['name']: b['id'] for b in brands}
    selected_brand_name = st.selectbox(
        "Select Brand",
        options=list(brand_options.keys()),
        key="brand_selector"
    )
    brand_id = brand_options[selected_brand_name]
    st.session_state.pipeline_brand_id = brand_id

    # Tabs for different views
    tab1, tab2 = st.tabs(["📋 Projects", "➕ New Project"])

    with tab1:
        render_projects_list(brand_id)

    with tab2:
        render_new_project_form(brand_id)


def render_projects_list(brand_id: str):
    """Render list of existing projects."""
    projects = get_projects_for_brand(brand_id)

    if not projects:
        st.info("No projects yet. Create a new project to get started!")
        return

    for project in projects:
        with st.expander(
            f"**{project.get('topic_title', 'Untitled Project')}** - {project.get('workflow_state', 'pending')}",
            expanded=project.get('workflow_state') in ['topic_discovery', 'topic_selection']
        ):
            col1, col2 = st.columns([3, 1])

            with col1:
                st.caption(f"Created: {project.get('created_at', '')[:10]}")
                st.caption(f"Status: {project.get('workflow_state', 'unknown')}")

                if project.get('topic_description'):
                    st.markdown(project.get('topic_description'))

            with col2:
                if project.get('topic_score'):
                    st.metric("Topic Score", f"{project.get('topic_score')}/100")

                if st.button("Open", key=f"open_project_{project.get('id')}"):
                    st.session_state.pipeline_project_id = project.get('id')
                    st.rerun()


def render_new_project_form(brand_id: str):
    """Render form to create a new project."""
    st.subheader("Create New Content Project")

    with st.form("new_project_form"):
        # Workflow path selection
        workflow_path = st.radio(
            "Workflow Path",
            options=["both", "video_only", "comic_only"],
            format_func=lambda x: {
                "both": "Both Video & Comic",
                "video_only": "Video Only",
                "comic_only": "Comic Only"
            }[x],
            horizontal=True
        )

        # Topic discovery settings
        st.markdown("### Topic Discovery Settings")
        num_topics = st.slider("Number of Topics to Discover", 5, 20, 10)

        focus_areas_text = st.text_area(
            "Focus Areas (optional)",
            placeholder="Enter focus areas, one per line\nExample:\nInflation\nCrypto crash\nHousing market",
            help="Leave empty for general topic discovery"
        )

        quick_approve = st.checkbox(
            "Enable Quick Approve",
            value=True,
            help="Auto-approve topics scoring 90+ without manual review"
        )

        submitted = st.form_submit_button("Create Project & Discover Topics")

        if submitted:
            # Parse focus areas
            focus_areas = [
                area.strip()
                for area in focus_areas_text.split('\n')
                if area.strip()
            ]

            # Create project
            try:
                db = get_supabase_client()
                project_data = {
                    "brand_id": brand_id,
                    "workflow_state": "topic_discovery",
                    "workflow_data": {
                        "workflow_path": workflow_path,
                        "quick_approve_enabled": quick_approve,
                        "topic_batch_size": num_topics,
                        "focus_areas": focus_areas
                    }
                }
                result = db.table("content_projects").insert(project_data).execute()

                if result.data:
                    project_id = result.data[0]['id']
                    st.session_state.pipeline_project_id = project_id
                    st.session_state.discovery_running = True

                    # Run topic discovery
                    with st.spinner("Discovering topics..."):
                        topics = asyncio.run(run_topic_discovery(
                            brand_id=brand_id,
                            project_id=project_id,
                            num_topics=num_topics,
                            focus_areas=focus_areas
                        ))
                        st.session_state.discovered_topics = topics
                        st.session_state.discovery_running = False

                    st.success(f"Discovered {len(topics)} topics!")
                    st.rerun()

            except Exception as e:
                st.error(f"Failed to create project: {e}")


def render_project_detail(project_id: str):
    """Render detailed view of a single project."""
    try:
        db = get_supabase_client()
        result = db.table("content_projects").select("*").eq("id", project_id).execute()
        if not result.data:
            st.error("Project not found")
            return
        project = result.data[0]
    except Exception as e:
        st.error(f"Failed to load project: {e}")
        return

    # Back button
    if st.button("← Back to Projects"):
        st.session_state.pipeline_project_id = None
        st.rerun()

    # Project header
    st.header(project.get('topic_title', 'New Project'))
    st.caption(f"Status: **{project.get('workflow_state', 'pending')}**")

    # Different views based on workflow state
    workflow_state = project.get('workflow_state', 'pending')

    if workflow_state in ['pending', 'topic_discovery', 'topic_evaluation', 'topic_selection']:
        render_topic_selection_view(project)
    elif workflow_state in ['topic_selected', 'script_generation', 'script_review', 'script_approval', 'script_approved', 'els_ready', 'audio_production', 'audio_complete', 'handoff_ready', 'handoff_generated', 'comic_evaluation', 'comic_approved']:
        render_script_view(project)
    else:
        st.info(f"Workflow state '{workflow_state}' not yet implemented")


def render_topic_selection_view(project: Dict):
    """Render the topic selection interface."""
    project_id = project.get('id')

    # Tabs for topic discovery
    tab1, tab2 = st.tabs(["📝 Topics", "🔄 Discover More"])

    with tab1:
        topics = get_topics_for_project(project_id)

        if not topics:
            st.info("No topics discovered yet. Use the 'Discover More' tab to generate topics.")
        else:
            # Summary stats
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("Total Topics", len(topics))
            with col2:
                high_score = len([t for t in topics if t.get('score', 0) >= 90])
                st.metric("High Scoring (90+)", high_score)
            with col3:
                selected = [t for t in topics if t.get('is_selected')]
                st.metric("Selected", len(selected))
            with col4:
                avg_score = sum(t.get('score', 0) for t in topics) / len(topics) if topics else 0
                st.metric("Avg Score", f"{avg_score:.0f}")

            st.divider()

            # Topic cards
            for idx, topic in enumerate(topics):
                render_topic_card(topic, idx, project_id)

    with tab2:
        st.subheader("Discover More Topics")

        with st.form("discover_more_form"):
            num_topics = st.slider("Number of Topics", 5, 20, 10)

            focus_areas_text = st.text_area(
                "Focus Areas (optional)",
                placeholder="Enter focus areas, one per line"
            )

            if st.form_submit_button("Discover Topics"):
                focus_areas = [
                    area.strip()
                    for area in focus_areas_text.split('\n')
                    if area.strip()
                ]

                with st.spinner("Discovering topics..."):
                    try:
                        topics = asyncio.run(run_topic_discovery(
                            brand_id=project.get('brand_id'),
                            project_id=project_id,
                            num_topics=num_topics,
                            focus_areas=focus_areas
                        ))
                        st.success(f"Discovered {len(topics)} new topics!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Discovery failed: {e}")


async def run_script_generation(project_id: str, topic: Dict, brand_id: str):
    """Run script generation asynchronously."""
    service = get_script_service()

    # Generate script
    script_data = await service.generate_script(
        project_id=UUID(project_id),
        topic=topic,
        brand_id=UUID(brand_id)
    )

    # Save to database
    await service.save_script_to_db(
        project_id=UUID(project_id),
        script_data=script_data
    )

    return script_data


async def run_script_review(script_data: Dict, brand_id: str):
    """Run script review asynchronously."""
    service = get_script_service()

    review_result = await service.review_script(
        script_data=script_data,
        brand_id=UUID(brand_id)
    )

    return review_result


def render_script_view(project: Dict):
    """Render the script generation and review interface."""
    project_id = project.get('id')
    brand_id = project.get('brand_id')
    workflow_state = project.get('workflow_state', 'pending')

    # Show selected topic info
    st.subheader("Selected Topic")
    col1, col2 = st.columns([3, 1])
    with col1:
        st.markdown(f"**{project.get('topic_title', 'Untitled')}**")
        st.markdown(project.get('topic_description', ''))
    with col2:
        if project.get('topic_score'):
            st.metric("Score", f"{project.get('topic_score')}/100")

    st.divider()

    # Tabs for script workflow - include Audio, Assets, SFX, Handoff, and Comic tabs
    tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8 = st.tabs([
        "Generate", "Review", "Approve", "Audio", "Assets", "SFX", "Handoff", "Comic"
    ])

    with tab1:
        render_script_generation_tab(project)

    with tab2:
        render_script_review_tab(project)

    with tab3:
        render_script_approval_tab(project)

    with tab4:
        render_audio_tab(project)

    with tab5:
        render_assets_tab(project)

    with tab6:
        render_sfx_tab(project)

    with tab7:
        render_handoff_tab(project)

    with tab8:
        render_comic_tab(project)


def render_script_generation_tab(project: Dict):
    """Render the script generation tab."""
    project_id = project.get('id')
    brand_id = project.get('brand_id')
    workflow_state = project.get('workflow_state', 'pending')

    # Check for existing scripts
    try:
        db = get_supabase_client()
        scripts = db.table("script_versions").select("*").eq(
            "project_id", project_id
        ).order("version_number", desc=True).execute()
        existing_scripts = scripts.data or []
    except Exception:
        existing_scripts = []

    if existing_scripts:
        st.success(f"Script v{existing_scripts[0].get('version_number')} generated")

        # Show script content
        script_content = existing_scripts[0].get('script_content')
        if script_content:
            try:
                script_data = json.loads(script_content) if isinstance(script_content, str) else script_content
                render_script_beats(script_data)
            except Exception as e:
                st.error(f"Failed to parse script: {e}")

    else:
        # No script yet - show generation form
        st.markdown("### Generate Script")
        st.markdown("Generate a full video script based on the selected topic using Claude Opus 4.5.")

        # Get topic data
        topic = {
            "title": project.get('topic_title'),
            "description": project.get('topic_description'),
            "hook_options": project.get('hook_options', []),
            "target_emotion": project.get('workflow_data', {}).get('target_emotion', 'curiosity')
        }

        col_gen, col_reset = st.columns([3, 1])
        with col_gen:
            generate_clicked = st.button("Generate Script", type="primary", disabled=st.session_state.script_generating)
        with col_reset:
            if st.session_state.script_generating:
                if st.button("Reset", help="Click if generation is stuck"):
                    st.session_state.script_generating = False
                    st.rerun()

        if generate_clicked:
            st.session_state.script_generating = True
            st.rerun()  # Rerun to show spinner state

        if st.session_state.script_generating and not generate_clicked:
            with st.spinner("Generating script with Claude Opus 4.5... (this may take 30-60 seconds)"):
                try:
                    script_data = asyncio.run(run_script_generation(
                        project_id=project_id,
                        topic=topic,
                        brand_id=brand_id
                    ))
                    st.session_state.current_script = script_data
                    st.session_state.script_generating = False

                    # Update workflow state
                    db = get_supabase_client()
                    db.table("content_projects").update({
                        "workflow_state": "script_review"
                    }).eq("id", project_id).execute()

                    st.success("Script generated!")
                    st.rerun()

                except Exception as e:
                    st.session_state.script_generating = False
                    st.error(f"Script generation failed: {e}")


def render_script_beats(script_data: Dict):
    """Render the script beats in a readable format."""
    st.markdown(f"**Title:** {script_data.get('title', 'Untitled')}")
    st.markdown(f"**Duration:** ~{script_data.get('target_duration_seconds', 180)} seconds")
    st.markdown(f"**Hook Formula:** {script_data.get('hook_formula_used', 'N/A')}")

    beats = script_data.get('beats', [])
    if beats:
        st.markdown("### Script Beats")
        for beat in beats:
            with st.expander(f"**{beat.get('beat_name', 'Beat')}** ({beat.get('timestamp_start', '')} - {beat.get('timestamp_end', '')})"):
                st.markdown(f"**Character:** {beat.get('character', 'narrator')}")
                st.markdown("**Script:**")
                st.text(beat.get('script', ''))
                if beat.get('visual_notes'):
                    st.markdown(f"**Visuals:** {beat.get('visual_notes')}")
                if beat.get('audio_notes'):
                    st.markdown(f"**Audio:** {beat.get('audio_notes')}")


def render_script_review_tab(project: Dict):
    """Render the script review tab."""
    project_id = project.get('id')
    brand_id = project.get('brand_id')

    # Get current script
    try:
        db = get_supabase_client()
        scripts = db.table("script_versions").select("*").eq(
            "project_id", project_id
        ).order("version_number", desc=True).execute()
        existing_scripts = scripts.data or []
    except Exception:
        existing_scripts = []

    if not existing_scripts:
        st.info("No script to review yet. Generate a script first.")
        return

    current_script = existing_scripts[0]

    # Check for existing review
    checklist_results = current_script.get('checklist_results')

    if checklist_results:
        st.success("Script has been reviewed")
        render_review_results(checklist_results)
    else:
        st.markdown("### Review Script Against Bible Checklist")
        st.markdown("Claude will review the script against the Production Bible checklist items.")

        if st.button("Run Review", type="primary"):
            with st.spinner("Reviewing script against bible checklist..."):
                try:
                    # Get script data
                    script_content = current_script.get('script_content')
                    script_data = json.loads(script_content) if isinstance(script_content, str) else script_content

                    review_result = asyncio.run(run_script_review(
                        script_data=script_data,
                        brand_id=brand_id
                    ))
                    st.session_state.script_review = review_result

                    # Save review to database
                    service = get_script_service()
                    asyncio.run(service.save_review_to_db(
                        script_version_id=UUID(current_script.get('id')),
                        review_data=review_result
                    ))

                    # Update workflow state
                    db.table("content_projects").update({
                        "workflow_state": "script_approval"
                    }).eq("id", project_id).execute()

                    st.success("Review complete!")
                    st.rerun()

                except Exception as e:
                    st.error(f"Review failed: {e}")


def render_review_results(review: Dict, show_checkboxes: bool = False) -> List[Dict]:
    """Render review checklist results with optional selection checkboxes.

    Args:
        review: Review data dictionary
        show_checkboxes: If True, show checkboxes next to failed items for selection

    Returns:
        List of all failed items (for building revision prompts)
    """
    overall_score = review.get('overall_score', 0)
    ready = review.get('ready_for_approval', False)
    failed_items = []

    col1, col2 = st.columns(2)
    with col1:
        st.metric("Overall Score", f"{overall_score}/100")
    with col2:
        if ready:
            st.success("Ready for Approval")
        else:
            st.warning("Revisions Recommended")

    # Checklist results
    checklist = review.get('checklist_results', {})
    if checklist:
        st.markdown("### Checklist Results")

        for category, items in checklist.items():
            # Count failed items in category
            category_failed = sum(1 for r in items.values() if not r.get('passed', False))
            category_label = f"**{category.replace('_', ' ').title()}**"
            if category_failed > 0:
                category_label += f" ({category_failed} failed)"

            with st.expander(category_label):
                for item_name, result in items.items():
                    passed = result.get('passed', False)
                    notes = result.get('notes', '')
                    icon = "✅" if passed else "❌"

                    if not passed:
                        # Track failed item
                        item_key = f"checklist:{category}:{item_name}"
                        failed_item = {
                            "type": "checklist",
                            "key": item_key,
                            "category": category,
                            "item": item_name,
                            "notes": notes,
                            "display": f"{category.replace('_', ' ').title()} - {item_name.replace('_', ' ').title()}: {notes}"
                        }
                        failed_items.append(failed_item)

                        if show_checkboxes:
                            # Show checkbox for failed item
                            col_check, col_text = st.columns([0.1, 0.9])
                            with col_check:
                                checked = st.checkbox(
                                    "Select",
                                    key=f"chk_{item_key}",
                                    value=item_key in st.session_state.selected_failed_items,
                                    label_visibility="collapsed"
                                )
                                if checked:
                                    st.session_state.selected_failed_items.add(item_key)
                                elif item_key in st.session_state.selected_failed_items:
                                    st.session_state.selected_failed_items.discard(item_key)
                            with col_text:
                                st.markdown(f"{icon} **{item_name.replace('_', ' ').title()}**: {notes}")
                        else:
                            st.markdown(f"{icon} **{item_name.replace('_', ' ').title()}**: {notes}")
                    else:
                        st.markdown(f"{icon} **{item_name.replace('_', ' ').title()}**: {notes}")

    # Issues found
    issues = review.get('issues_found', [])
    if issues:
        st.markdown("### Issues Found")
        for idx, issue in enumerate(issues):
            severity = issue.get('severity', 'medium')
            color = {"high": "red", "medium": "orange", "low": "blue"}.get(severity, "gray")
            issue_text = issue.get('issue', '')
            location = issue.get('location', 'N/A')
            suggestion = issue.get('suggestion', '')

            # Track as failed item
            item_key = f"issue:{idx}:{issue_text[:30]}"
            failed_item = {
                "type": "issue",
                "key": item_key,
                "severity": severity,
                "issue": issue_text,
                "location": location,
                "suggestion": suggestion,
                "display": f"[{severity.upper()}] {issue_text} (Location: {location})"
            }
            failed_items.append(failed_item)

            if show_checkboxes:
                col_check, col_text = st.columns([0.1, 0.9])
                with col_check:
                    checked = st.checkbox(
                        "Select",
                        key=f"chk_{item_key}",
                        value=item_key in st.session_state.selected_failed_items,
                        label_visibility="collapsed"
                    )
                    if checked:
                        st.session_state.selected_failed_items.add(item_key)
                    elif item_key in st.session_state.selected_failed_items:
                        st.session_state.selected_failed_items.discard(item_key)
                with col_text:
                    st.markdown(f":{color}[**{severity.upper()}**] {issue_text}")
                    st.caption(f"Location: {location} | Suggestion: {suggestion}")
            else:
                st.markdown(f":{color}[**{severity.upper()}**] {issue_text}")
                st.caption(f"Location: {location} | Suggestion: {suggestion}")

    # Improvement suggestions
    suggestions = review.get('improvement_suggestions', [])
    if suggestions:
        st.markdown("### Improvement Suggestions")
        for suggestion in suggestions:
            st.markdown(f"- {suggestion}")

    return failed_items


def build_revision_prompt_from_selections(
    failed_items: List[Dict],
    selected_keys: set
) -> str:
    """Build a revision prompt from selected failed items.

    Args:
        failed_items: List of all failed item dictionaries
        selected_keys: Set of selected item keys

    Returns:
        Formatted revision prompt string
    """
    selected_items = [item for item in failed_items if item['key'] in selected_keys]

    if not selected_items:
        return ""

    prompt_lines = ["Please revise the script to fix the following issues:\n"]

    # Group checklist items by category
    checklist_items = [i for i in selected_items if i['type'] == 'checklist']
    issue_items = [i for i in selected_items if i['type'] == 'issue']

    if checklist_items:
        prompt_lines.append("## Checklist Failures to Fix:")
        for item in checklist_items:
            category = item['category'].replace('_', ' ').title()
            item_name = item['item'].replace('_', ' ').title()
            notes = item.get('notes', '')
            prompt_lines.append(f"- **{category} - {item_name}**: {notes}")
        prompt_lines.append("")

    if issue_items:
        prompt_lines.append("## Specific Issues to Fix:")
        for item in issue_items:
            issue = item.get('issue', '')
            location = item.get('location', 'Unknown')
            suggestion = item.get('suggestion', '')
            prompt_lines.append(f"- **{issue}**")
            prompt_lines.append(f"  - Location: {location}")
            if suggestion:
                prompt_lines.append(f"  - Suggested fix: {suggestion}")
        prompt_lines.append("")

    return "\n".join(prompt_lines)


async def run_script_revision_and_review(
    project_id: str,
    script_data: Dict,
    revision_notes: str,
    brand_id: str,
    review_result: Optional[Dict] = None
) -> Dict:
    """Run script revision followed by automatic re-review.

    Args:
        project_id: Project UUID string
        script_data: Current script data
        revision_notes: Revision instructions (passed as human_notes)
        brand_id: Brand UUID string
        review_result: Optional review result from previous review

    Returns:
        Dictionary with revised script and new review results
    """
    service = get_script_service()

    # Use empty review result if not provided
    if review_result is None:
        review_result = {}

    # Revise the script using the correct API signature
    revised_script = await service.revise_script(
        original_script=script_data,
        review_result=review_result,
        brand_id=UUID(brand_id),
        human_notes=revision_notes
    )

    # Save revised script
    await service.save_script_to_db(
        project_id=UUID(project_id),
        script_data=revised_script
    )

    # Automatically run review on revised script
    review_result = await service.review_script(
        script_data=revised_script,
        brand_id=UUID(brand_id)
    )

    # Get the latest script version ID to save review
    db = get_supabase_client()
    scripts = db.table("script_versions").select("id").eq(
        "project_id", project_id
    ).order("version_number", desc=True).limit(1).execute()

    if scripts.data:
        await service.save_review_to_db(
            script_version_id=UUID(scripts.data[0]['id']),
            review_data=review_result
        )

    return {
        "revised_script": revised_script,
        "review_result": review_result
    }


def render_script_approval_tab(project: Dict):
    """Render the script approval tab with interactive revision selection."""
    project_id = project.get('id')
    brand_id = project.get('brand_id')
    workflow_state = project.get('workflow_state', 'pending')

    # Get current script
    try:
        db = get_supabase_client()
        scripts = db.table("script_versions").select("*").eq(
            "project_id", project_id
        ).order("version_number", desc=True).execute()
        existing_scripts = scripts.data or []
    except Exception:
        existing_scripts = []

    if not existing_scripts:
        st.info("No script to approve yet.")
        return

    current_script = existing_scripts[0]
    status = current_script.get('status', 'draft')
    version_num = current_script.get('version_number', 1)

    if status == 'approved':
        st.success("Script has been approved!")
        st.markdown(f"**Approved at:** {current_script.get('approved_at', 'N/A')}")
        if current_script.get('human_notes'):
            st.markdown(f"**Notes:** {current_script.get('human_notes')}")
        return

    if workflow_state not in ['script_approval', 'script_review']:
        st.info("Complete the review before approving.")
        return

    st.markdown(f"### Script v{version_num} - Approve or Revise")

    # Show review results with checkboxes
    checklist_results = current_script.get('checklist_results')
    failed_items = []

    if checklist_results:
        st.markdown("#### Review Results")
        st.caption("Select failed items to include in targeted revision, or use 'Revise All' to fix everything.")
        failed_items = render_review_results(checklist_results, show_checkboxes=True)

        # Show selection count
        selected_count = len(st.session_state.selected_failed_items)
        total_failed = len(failed_items)
        if total_failed > 0:
            st.info(f"Selected {selected_count} of {total_failed} failed items")

    st.divider()

    # Action buttons section
    st.markdown("#### Actions")

    # Check if revision is running
    if st.session_state.revision_running:
        st.warning("Revision in progress...")
        return

    # Row 1: Approve button
    col_approve, col_spacer = st.columns([1, 2])
    with col_approve:
        approval_notes = st.text_area(
            "Approval Notes (optional)",
            placeholder="Add any notes about this approval...",
            key="approval_notes"
        )
        if st.button("Approve Script", type="primary", use_container_width=True):
            try:
                service = get_script_service()
                asyncio.run(service.approve_script(
                    script_version_id=UUID(current_script.get('id')),
                    project_id=UUID(project_id),
                    human_notes=approval_notes
                ))

                db = get_supabase_client()
                db.table("content_projects").update({
                    "workflow_state": "script_approved"
                }).eq("id", project_id).execute()

                st.success("Script approved!")
                st.rerun()

            except Exception as e:
                st.error(f"Approval failed: {e}")

    st.divider()

    # Row 2: Revision buttons
    st.markdown("#### Request Revisions")

    col1, col2, col3 = st.columns(3)

    with col1:
        # Revise Selected button
        selected_count = len(st.session_state.selected_failed_items)
        revise_selected_disabled = selected_count == 0

        if st.button(
            f"Revise Selected ({selected_count})",
            disabled=revise_selected_disabled,
            use_container_width=True,
            help="Revise only the selected failed items"
        ):
            # Build revision prompt from selections
            revision_prompt = build_revision_prompt_from_selections(
                failed_items,
                st.session_state.selected_failed_items
            )

            if revision_prompt:
                st.session_state.revision_running = True

                # Get script data
                script_content = current_script.get('script_content')
                script_data = json.loads(script_content) if isinstance(script_content, str) else script_content

                with st.spinner("Revising script and running review... (this may take 60-90 seconds)"):
                    try:
                        result = asyncio.run(run_script_revision_and_review(
                            project_id=project_id,
                            script_data=script_data,
                            revision_notes=revision_prompt,
                            brand_id=brand_id,
                            review_result=checklist_results
                        ))

                        # Clear selections
                        st.session_state.selected_failed_items = set()
                        st.session_state.revision_running = False

                        new_score = result['review_result'].get('overall_score', 0)
                        st.success(f"Revision complete! New score: {new_score}/100")
                        st.rerun()

                    except Exception as e:
                        st.session_state.revision_running = False
                        st.error(f"Revision failed: {e}")

    with col2:
        # Revise All button
        if st.button(
            "Revise All Failed",
            disabled=len(failed_items) == 0,
            use_container_width=True,
            help="Revise all failed items at once"
        ):
            # Build prompt for all failed items
            all_keys = {item['key'] for item in failed_items}
            revision_prompt = build_revision_prompt_from_selections(
                failed_items,
                all_keys
            )

            if revision_prompt:
                st.session_state.revision_running = True

                # Get script data
                script_content = current_script.get('script_content')
                script_data = json.loads(script_content) if isinstance(script_content, str) else script_content

                with st.spinner("Revising all issues and running review... (this may take 60-90 seconds)"):
                    try:
                        result = asyncio.run(run_script_revision_and_review(
                            project_id=project_id,
                            script_data=script_data,
                            revision_notes=revision_prompt,
                            brand_id=brand_id,
                            review_result=checklist_results
                        ))

                        # Clear selections
                        st.session_state.selected_failed_items = set()
                        st.session_state.revision_running = False

                        new_score = result['review_result'].get('overall_score', 0)
                        st.success(f"Revision complete! New score: {new_score}/100")
                        st.rerun()

                    except Exception as e:
                        st.session_state.revision_running = False
                        st.error(f"Revision failed: {e}")

    with col3:
        # Clear selections button
        if st.button(
            "Clear Selections",
            disabled=selected_count == 0,
            use_container_width=True
        ):
            st.session_state.selected_failed_items = set()
            st.rerun()

    # Manual revision option (collapsed by default)
    with st.expander("Manual Revision Notes"):
        manual_revision_notes = st.text_area(
            "Custom Revision Notes",
            placeholder="Describe specific changes you want...",
            help="Use this for custom revision requests beyond the checklist items"
        )

        if st.button("Submit Manual Revision"):
            if not manual_revision_notes:
                st.warning("Please provide revision notes")
            else:
                st.session_state.revision_running = True

                # Get script data
                script_content = current_script.get('script_content')
                script_data = json.loads(script_content) if isinstance(script_content, str) else script_content

                with st.spinner("Processing manual revision..."):
                    try:
                        result = asyncio.run(run_script_revision_and_review(
                            project_id=project_id,
                            script_data=script_data,
                            revision_notes=manual_revision_notes,
                            brand_id=brand_id,
                            review_result=checklist_results
                        ))

                        st.session_state.revision_running = False
                        new_score = result['review_result'].get('overall_score', 0)
                        st.success(f"Revision complete! New score: {new_score}/100")
                        st.rerun()

                    except Exception as e:
                        st.session_state.revision_running = False
                        st.error(f"Manual revision failed: {e}")


# =========================================================================
# Audio Tab Functions (MVP 3)
# =========================================================================

def get_audio_production_service():
    """Get AudioProductionService instance."""
    from viraltracker.services.audio_production_service import AudioProductionService
    return AudioProductionService()


def get_els_parser_service():
    """Get ELSParserService instance."""
    from viraltracker.services.els_parser_service import ELSParserService
    return ELSParserService()


def get_elevenlabs_service():
    """Get ElevenLabsService instance."""
    from viraltracker.services.elevenlabs_service import ElevenLabsService
    return ElevenLabsService()


async def run_els_conversion(project_id: str, script_version_id: str, script_data: Dict, brand_id: str):
    """Convert script to ELS format and save to database."""
    service = get_script_service()

    # Convert to ELS
    els_content = service.convert_to_els(script_data)

    # Save to database
    els_id = await service.save_els_to_db(
        project_id=UUID(project_id),
        script_version_id=UUID(script_version_id),
        els_content=els_content
    )

    return {"els_id": str(els_id), "els_content": els_content}


async def run_audio_generation(project_id: str, els_content: str, els_version_id: str):
    """Create audio session and generate audio for all beats."""
    audio_service = get_audio_production_service()
    els_parser = get_els_parser_service()
    elevenlabs = get_elevenlabs_service()
    script_service = get_script_service()

    # Parse ELS
    parse_result = els_parser.parse(els_content)

    # Create audio session
    session = await audio_service.create_session(
        video_title=parse_result.video_title,
        project_name=parse_result.project,
        beats=[beat.model_dump() for beat in parse_result.beats],
        source_els=els_content
    )

    # Link session to project
    await script_service.link_audio_session(
        project_id=UUID(project_id),
        els_version_id=UUID(els_version_id),
        audio_session_id=session.session_id
    )

    # Generate audio for each beat
    from pathlib import Path
    from viraltracker.services.ffmpeg_service import FFmpegService
    ffmpeg = FFmpegService()

    results = []
    errors = []
    for beat in parse_result.beats:
        try:
            output_path = Path(f"audio_production/{session.session_id}")
            output_path.mkdir(parents=True, exist_ok=True)

            # Generate audio to local file
            take = await elevenlabs.generate_beat_audio(
                beat=beat,
                output_dir=output_path,
                session_id=str(session.session_id)
            )

            local_file = Path(take.audio_path)

            # Get duration using FFmpeg
            duration_ms = ffmpeg.get_duration_ms(local_file)
            take.audio_duration_ms = duration_ms

            # Upload to Supabase Storage
            with open(local_file, 'rb') as f:
                audio_data = f.read()

            storage_path = await audio_service.upload_audio(
                session_id=str(session.session_id),
                filename=local_file.name,
                audio_data=audio_data
            )

            # Update take with storage path (not local path)
            take.audio_path = storage_path

            # Save take and select it
            await audio_service.save_take(str(session.session_id), take)
            await audio_service.select_take(str(session.session_id), beat.beat_id, take.take_id)

            # Clean up local file
            local_file.unlink(missing_ok=True)

            results.append({"beat_id": beat.beat_id, "status": "success", "take_id": str(take.take_id)})
        except Exception as e:
            import traceback
            error_detail = f"{beat.beat_id}: {str(e)}\n{traceback.format_exc()}"
            errors.append(error_detail)
            results.append({"beat_id": beat.beat_id, "status": "error", "error": str(e)})

    # If all beats failed, raise with details
    if errors and len(errors) == len(parse_result.beats):
        raise Exception(f"All beats failed. First error: {errors[0]}")

    return {
        "session_id": str(session.session_id),
        "beat_results": results,
        "total_beats": len(parse_result.beats),
        "successful": sum(1 for r in results if r["status"] == "success")
    }


async def regenerate_single_beat(session_id: str, beat_id: str, beat_info: Dict, session: Dict):
    """Regenerate audio for a single beat."""
    from pathlib import Path
    from viraltracker.services.ffmpeg_service import FFmpegService
    from viraltracker.services.audio_models import ScriptBeat, Pace, Character

    audio_service = get_audio_production_service()
    elevenlabs = get_elevenlabs_service()
    ffmpeg = FFmpegService()

    # Convert beat_info dict to ScriptBeat model
    # Handle character enum
    char_str = beat_info.get('character', 'every-coon')
    try:
        character = Character(char_str)
    except ValueError:
        character = Character.EVERY_COON

    # Handle pace enum
    pace_str = beat_info.get('primary_pace', 'normal')
    if isinstance(pace_str, str):
        try:
            pace = Pace(pace_str.lower())
        except ValueError:
            pace = Pace.NORMAL
    else:
        pace = Pace.NORMAL

    beat = ScriptBeat(
        beat_id=beat_id,
        beat_number=beat_info.get('beat_number', 1),
        beat_name=beat_info.get('beat_name', beat_id),
        character=character,
        lines=[],  # Not used for generation
        combined_script=beat_info.get('combined_script', '') or beat_info.get('script', ''),
        primary_direction=beat_info.get('primary_direction', ''),
        primary_pace=pace,
        pause_after_ms=beat_info.get('pause_after_ms', 100)
    )

    output_path = Path(f"audio_production/{session_id}")
    output_path.mkdir(parents=True, exist_ok=True)

    # Generate audio
    take = await elevenlabs.generate_beat_audio(
        beat=beat,
        output_dir=output_path,
        session_id=session_id
    )

    local_file = Path(take.audio_path)

    # Get duration
    duration_ms = ffmpeg.get_duration_ms(local_file)
    take.audio_duration_ms = duration_ms

    # Upload to storage
    with open(local_file, 'rb') as f:
        audio_data = f.read()

    storage_path = await audio_service.upload_audio(
        session_id=session_id,
        filename=local_file.name,
        audio_data=audio_data
    )

    take.audio_path = storage_path

    # Save take (don't auto-select, let user choose)
    await audio_service.save_take(session_id, take)

    # Clean up local file
    local_file.unlink(missing_ok=True)

    return take


def render_audio_tab(project: Dict):
    """Render the audio production tab."""
    project_id = project.get('id')
    brand_id = project.get('brand_id')
    workflow_state = project.get('workflow_state', 'pending')

    # Check if script is approved
    script_approved = workflow_state in [
        'script_approved', 'els_ready', 'audio_production', 'audio_complete',
        'handoff_ready', 'handoff_generated'
    ]

    if not script_approved:
        st.info("Approve your script first before generating audio.")
        st.caption("The Audio tab becomes available after script approval.")
        return

    st.markdown("### Audio Production")

    # Get current script
    try:
        db = get_supabase_client()
        scripts = db.table("script_versions").select("*").eq(
            "project_id", project_id
        ).eq("status", "approved").order("version_number", desc=True).limit(1).execute()

        if not scripts.data:
            st.warning("No approved script found.")
            return

        current_script = scripts.data[0]
        script_content = current_script.get('script_content')
        script_data = json.loads(script_content) if isinstance(script_content, str) else script_content

    except Exception as e:
        st.error(f"Failed to load script: {e}")
        return

    # Check for existing ELS
    try:
        els_result = db.table("els_versions").select("*").eq(
            "project_id", project_id
        ).eq("source_type", "video").order("version_number", desc=True).limit(1).execute()
        existing_els = els_result.data[0] if els_result.data else None
    except Exception:
        existing_els = None

    # Check for existing audio session
    audio_session_id = project.get('audio_session_id')
    audio_session = None
    if audio_session_id:
        try:
            session_result = db.table("audio_production_sessions").select("*").eq(
                "id", audio_session_id
            ).execute()
            audio_session = session_result.data[0] if session_result.data else None
        except Exception:
            audio_session = None

    # Step 1: ELS Conversion
    st.markdown("#### Step 1: Convert Script to ELS")

    if existing_els:
        st.success(f"ELS v{existing_els.get('version_number')} ready")

        # Show ELS content in expander
        with st.expander("View ELS Script", expanded=False):
            st.code(existing_els.get('els_content', ''), language='text')

        # Option to regenerate
        if st.button("Regenerate ELS", help="Create a new ELS version from the current script"):
            st.session_state.els_converting = True
            st.rerun()

    else:
        st.info("Convert your approved script to ELS format for audio production.")

        if st.button("Convert to ELS", type="primary", disabled=st.session_state.els_converting):
            st.session_state.els_converting = True
            st.rerun()

    # Handle ELS conversion (both new and regenerate)
    if st.session_state.els_converting:
        with st.spinner("Converting script to ELS format..."):
            try:
                result = asyncio.run(run_els_conversion(
                    project_id=project_id,
                    script_version_id=current_script.get('id'),
                    script_data=script_data,
                    brand_id=brand_id
                ))
                st.session_state.els_converting = False
                st.session_state.current_els = result['els_content']
                st.success("ELS conversion complete!")
                st.rerun()

            except Exception as e:
                st.session_state.els_converting = False
                st.error(f"ELS conversion failed: {e}")

    # Step 2: Audio Generation
    st.markdown("#### Step 2: Generate Audio")

    if not existing_els:
        st.caption("Convert to ELS first before generating audio.")
        return

    if audio_session:
        st.success(f"Audio session active: {audio_session.get('status', 'unknown')}")

        # Show beat-by-beat results
        render_audio_session_details(audio_session, project_id)

    else:
        st.info("Generate voiceover audio for each beat using ElevenLabs.")

        beat_count = len(script_data.get('beats', []))
        st.caption(f"This will generate audio for {beat_count} beats.")

        col1, col2 = st.columns([1, 3])
        with col1:
            if st.button("Generate Audio", type="primary", disabled=st.session_state.audio_generating):
                st.session_state.audio_generating = True
                st.rerun()

        with col2:
            if st.session_state.audio_generating:
                st.warning("Audio generation in progress...")

    # Handle audio generation
    if st.session_state.audio_generating and not audio_session:
        progress_placeholder = st.empty()
        with progress_placeholder.container():
            with st.spinner(f"Generating audio... This may take 1-2 minutes."):
                try:
                    result = asyncio.run(run_audio_generation(
                        project_id=project_id,
                        els_content=existing_els.get('els_content'),
                        els_version_id=existing_els.get('id')
                    ))
                    st.session_state.audio_generating = False

                    if result['successful'] == result['total_beats']:
                        st.success(f"Audio generated for all {result['total_beats']} beats!")
                    else:
                        st.warning(f"Generated {result['successful']}/{result['total_beats']} beats. Some failed.")

                    st.rerun()

                except Exception as e:
                    st.session_state.audio_generating = False
                    st.error(f"Audio generation failed: {e}")


def render_audio_session_details(session: Dict, project_id: str):
    """Render the audio session details with playback and take management."""
    session_id = session.get('id')
    status = session.get('status', 'unknown')

    # Status indicator with reset option
    col1, col2 = st.columns([3, 1])
    with col1:
        status_colors = {
            'draft': 'orange',
            'generating': 'blue',
            'in_progress': 'green',
            'completed': 'green',
            'exported': 'gray'
        }
        st.caption(f"Status: :{status_colors.get(status, 'gray')}[{status}]")

    with col2:
        if st.button("Reset & Regenerate", help="Delete this session and regenerate audio"):
            try:
                db = get_supabase_client()
                # Clear links
                db.table("content_projects").update({
                    "audio_session_id": None
                }).eq("audio_session_id", session_id).execute()
                db.table("els_versions").update({
                    "audio_session_id": None
                }).eq("audio_session_id", session_id).execute()
                # Delete takes and session
                db.table("audio_takes").delete().eq("session_id", session_id).execute()
                db.table("audio_production_sessions").delete().eq("id", session_id).execute()
                st.session_state.audio_generating = True
                st.rerun()
            except Exception as e:
                st.error(f"Reset failed: {e}")

    # Get takes for this session
    try:
        db = get_supabase_client()
        takes_result = db.table("audio_takes").select("*").eq(
            "session_id", session_id
        ).order("beat_id").execute()
        takes = takes_result.data or []
    except Exception as e:
        st.error(f"Failed to load takes: {e}")
        return

    # Get beat info from session's beats_json
    beats_json = session.get('beats_json', [])
    beats_by_id = {b.get('beat_id'): b for b in beats_json} if beats_json else {}

    if not takes:
        st.warning("No audio takes generated yet. Audio generation may have failed.")

        # Get ELS for retry
        try:
            db = get_supabase_client()
            els_result = db.table("els_versions").select("*").eq(
                "audio_session_id", session_id
            ).limit(1).execute()
            existing_els = els_result.data[0] if els_result.data else None
        except Exception:
            existing_els = None

        if existing_els and st.button("Retry Audio Generation", type="primary"):
            st.session_state.audio_generating = True
            # Clear the session so it can be recreated
            try:
                db.table("content_projects").update({
                    "audio_session_id": None
                }).eq("audio_session_id", session_id).execute()
                db.table("els_versions").update({
                    "audio_session_id": None
                }).eq("id", existing_els.get('id')).execute()
                db.table("audio_production_sessions").delete().eq("id", session_id).execute()
            except Exception as e:
                st.error(f"Failed to reset session: {e}")
            st.rerun()
        return

    # Group takes by beat
    beats_takes = {}
    for take in takes:
        beat_id = take.get('beat_id')
        if beat_id not in beats_takes:
            beats_takes[beat_id] = []
        beats_takes[beat_id].append(take)

    st.markdown("#### Audio Takes")
    st.caption("Click play to preview. Selected takes will be used for export.")

    # Render each beat's takes
    for beat_id, beat_takes in beats_takes.items():
        beat_info = beats_by_id.get(beat_id, {})
        beat_name = beat_info.get('beat_name', beat_id)

        # Check if regenerating this beat
        if st.session_state.get(f"regenerating_{beat_id}"):
            with st.expander(f"**{beat_name}** - Regenerating...", expanded=True):
                with st.spinner(f"Regenerating {beat_id}..."):
                    try:
                        # Regenerate this beat
                        asyncio.run(regenerate_single_beat(
                            session_id=session_id,
                            beat_id=beat_id,
                            beat_info=beat_info,
                            session=session
                        ))
                        del st.session_state[f"regenerating_{beat_id}"]
                        st.rerun()
                    except Exception as e:
                        del st.session_state[f"regenerating_{beat_id}"]
                        st.error(f"Regeneration failed: {e}")
        else:
            with st.expander(f"**{beat_name}** ({len(beat_takes)} take{'s' if len(beat_takes) > 1 else ''})", expanded=True):
                # Sort takes by created_at to show oldest first
                sorted_takes = sorted(beat_takes, key=lambda t: t.get('created_at', ''))
                for i, take in enumerate(sorted_takes, 1):
                    render_audio_take(take, session_id, beat_id, beat_info, take_number=i, total_takes=len(sorted_takes))

    st.divider()

    # Completion section
    st.markdown("#### Complete Audio")
    selected_count = sum(1 for t in takes if t.get('is_selected'))
    total_beats = len(beats_takes)

    if selected_count == total_beats:
        st.success(f"All {total_beats} beats have selected takes. Audio is ready!")
        st.caption("You can proceed to the next pipeline step, or export audio files for manual use.")

        col1, col2 = st.columns(2)
        with col1:
            if st.button("Mark Audio Complete", type="primary", help="Proceed to next pipeline step"):
                try:
                    db = get_supabase_client()
                    db.table("content_projects").update({
                        "workflow_state": "audio_complete"
                    }).eq("id", project_id).execute()
                    db.table("audio_production_sessions").update({
                        "status": "completed"
                    }).eq("id", session_id).execute()
                    st.success("Audio marked complete!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Failed: {e}")
    else:
        st.warning(f"Select takes for all beats before completing. ({selected_count}/{total_beats} selected)")


def render_audio_take(take: Dict, session_id: str, beat_id: str, beat_info: Optional[Dict] = None, take_number: int = 1, total_takes: int = 1):
    """Render a single audio take with playback controls."""
    take_id = take.get('id')
    is_selected = take.get('is_selected', False)
    duration_ms = take.get('audio_duration_ms', 0)
    audio_path = take.get('audio_path', '')
    direction = take.get('direction_used', '')

    # Show take number header
    if total_takes > 1:
        st.markdown(f"**Take {take_number}** {'(latest)' if take_number == total_takes else ''}")
        st.divider()

    # Show beat info only on first take
    if beat_info and take_number == 1:
        character = beat_info.get('character', 'every-coon')
        script_text = beat_info.get('combined_script', '') or beat_info.get('script', '')

        # Character badge
        char_colors = {
            'every-coon': 'blue',
            'boomer': 'orange',
            'fed': 'gray',
            'whale': 'violet',
            'wojak': 'red',
            'chad': 'green'
        }
        st.caption(f":{char_colors.get(character, 'gray')}[{character}]")

        # Script text (truncated)
        if script_text:
            display_text = script_text[:200] + "..." if len(script_text) > 200 else script_text
            st.markdown(f"*\"{display_text}\"*")

        if direction:
            st.caption(f"Direction: {direction}")

    col1, col2, col3, col4 = st.columns([4, 1, 1, 1])

    with col1:
        # Audio player
        if audio_path:
            try:
                audio_service = get_audio_production_service()
                audio_url = asyncio.run(audio_service.get_audio_url(audio_path))
                st.audio(audio_url)
            except Exception as e:
                st.caption(f"Audio: {audio_path} ({e})")
        else:
            st.caption("No audio file")

    with col2:
        duration_sec = duration_ms / 1000 if duration_ms else 0
        st.caption(f"{duration_sec:.1f}s")

    with col3:
        if is_selected:
            st.success("Selected")
        else:
            if st.button("Select", key=f"select_{take_id}"):
                try:
                    audio_service = get_audio_production_service()
                    asyncio.run(audio_service.select_take(session_id, beat_id, UUID(take_id)))
                    st.rerun()
                except Exception as e:
                    st.error(f"Failed to select: {e}")

    with col4:
        if st.button("Regen", key=f"regen_{beat_id}_{take_id}", help="Regenerate this beat"):
            st.session_state[f"regenerating_{beat_id}"] = True
            st.rerun()


# =========================================================================
# Assets Tab Functions (MVP 4)
# =========================================================================

async def run_asset_extraction(script_version_id: str, script_data: Dict, brand_id: str):
    """Run asset extraction using Gemini AI."""
    service = get_asset_service()

    # Extract requirements from script
    requirements = await service.extract_requirements(
        script_version_id=UUID(script_version_id),
        script_data=script_data
    )

    # Match against existing library
    matched, unmatched = service.match_existing_assets(
        requirements=requirements,
        brand_id=UUID(brand_id)
    )

    return {"matched": matched, "unmatched": unmatched, "all": matched + unmatched}


def render_assets_tab(project: Dict):
    """Render the assets management tab."""
    project_id = project.get('id')
    brand_id = project.get('brand_id')
    workflow_state = project.get('workflow_state', 'pending')

    # Check if script is approved (assets require an approved script)
    script_approved = workflow_state in [
        'script_approved', 'els_ready', 'audio_production', 'audio_complete',
        'asset_extraction', 'asset_matching', 'asset_generation', 'asset_review',
        'handoff_ready', 'handoff_generated'
    ]

    if not script_approved:
        st.info("Approve your script first before extracting assets.")
        st.caption("The Assets tab becomes available after script approval.")
        return

    st.markdown("### Visual Asset Management")

    # Get current script
    try:
        db = get_supabase_client()
        scripts = db.table("script_versions").select("*").eq(
            "project_id", project_id
        ).eq("status", "approved").order("version_number", desc=True).limit(1).execute()

        if not scripts.data:
            st.warning("No approved script found.")
            return

        current_script = scripts.data[0]
        script_content = current_script.get('script_content')
        script_data = json.loads(script_content) if isinstance(script_content, str) else script_content

    except Exception as e:
        st.error(f"Failed to load script: {e}")
        return

    # Check for existing asset requirements
    try:
        req_result = db.table("project_asset_requirements").select(
            "*, comic_assets(*)"
        ).eq("project_id", project_id).order("asset_type").execute()
        existing_requirements = req_result.data or []
    except Exception:
        existing_requirements = []

    # Sub-tabs for asset workflow
    asset_tab1, asset_tab2, asset_tab3, asset_tab4, asset_tab5 = st.tabs([
        "Extract", "Generate", "Review", "Library", "Upload"
    ])

    with asset_tab1:
        render_asset_extraction(project_id, brand_id, current_script, script_data, existing_requirements)

    with asset_tab2:
        render_asset_generation(project_id, brand_id, existing_requirements)

    with asset_tab3:
        render_asset_review(project_id, brand_id, existing_requirements)

    with asset_tab4:
        render_asset_library(brand_id)

    with asset_tab5:
        render_asset_upload(brand_id)


def render_asset_extraction(project_id: str, brand_id: str, current_script: Dict, script_data: Dict, existing_requirements: List[Dict]):
    """Render the asset extraction interface."""

    if existing_requirements:
        st.success(f"Found {len(existing_requirements)} asset requirements")

        # Summary stats
        service = get_asset_service()
        summary = service.get_asset_summary(existing_requirements)

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Total Assets", summary['total'])
        with col2:
            st.metric("Matched", summary['by_status']['matched'])
        with col3:
            st.metric("Needed", summary['by_status']['needed'])
        with col4:
            st.metric("Generated", summary['by_status']['generated'])

        st.divider()

        # Group by type
        st.markdown("#### Assets by Type")

        # Characters
        characters = [r for r in existing_requirements if r.get('asset_type') == 'character']
        if characters:
            with st.expander(f"Characters ({len(characters)})", expanded=True):
                render_requirement_list(characters, project_id)

        # Props
        props = [r for r in existing_requirements if r.get('asset_type') == 'prop']
        if props:
            with st.expander(f"Props ({len(props)})", expanded=False):
                render_requirement_list(props, project_id)

        # Backgrounds
        backgrounds = [r for r in existing_requirements if r.get('asset_type') == 'background']
        if backgrounds:
            with st.expander(f"Backgrounds ({len(backgrounds)})", expanded=False):
                render_requirement_list(backgrounds, project_id)

        # Effects
        effects = [r for r in existing_requirements if r.get('asset_type') == 'effect']
        if effects:
            with st.expander(f"Effects ({len(effects)})", expanded=False):
                render_requirement_list(effects, project_id)

        st.divider()

        # Re-extraction option
        if st.button("Re-Extract Assets", help="Clear and re-extract assets from script"):
            with st.spinner("Clearing existing requirements..."):
                try:
                    service = get_asset_service()
                    asyncio.run(service.clear_requirements(UUID(project_id)))
                    st.session_state.asset_extracting = True
                    st.rerun()
                except Exception as e:
                    st.error(f"Failed to clear: {e}")

    else:
        st.info("Extract visual assets from your approved script using Gemini AI.")
        st.caption("This will identify characters, props, backgrounds, and effects from the script's visual notes.")

        # Show preview of visual notes
        beats = script_data.get('beats', [])
        notes_count = sum(1 for b in beats if b.get('visual_notes'))
        st.caption(f"Found {notes_count} beats with visual notes.")

        if st.button("Extract Assets", type="primary", disabled=st.session_state.asset_extracting):
            st.session_state.asset_extracting = True
            st.rerun()

    # Handle extraction
    if st.session_state.asset_extracting:
        with st.spinner("Extracting assets with Gemini AI... This may take 15-30 seconds."):
            try:
                result = asyncio.run(run_asset_extraction(
                    script_version_id=current_script.get('id'),
                    script_data=script_data,
                    brand_id=brand_id
                ))

                # Save to database
                service = get_asset_service()
                all_requirements = result['all']

                if all_requirements:
                    asyncio.run(service.save_requirements(
                        project_id=UUID(project_id),
                        requirements=all_requirements
                    ))

                st.session_state.asset_extracting = False
                st.session_state.extracted_assets = all_requirements

                matched_count = len(result['matched'])
                unmatched_count = len(result['unmatched'])
                st.success(f"Extracted {len(all_requirements)} assets! ({matched_count} matched, {unmatched_count} need generation)")
                st.rerun()

            except Exception as e:
                st.session_state.asset_extracting = False
                st.error(f"Asset extraction failed: {e}")


def render_asset_generation(project_id: str, brand_id: str, existing_requirements: List[Dict]):
    """Render the asset generation interface."""
    st.markdown("### Generate Missing Assets")

    # Filter for assets that need generation
    needed = [r for r in existing_requirements if r.get('status') == 'needed']
    generating = [r for r in existing_requirements if r.get('status') == 'generating']
    failed = [r for r in existing_requirements if r.get('status') == 'generation_failed']
    skipped = [r for r in existing_requirements if r.get('status') == 'skipped']

    if not needed and not generating and not failed:
        if not existing_requirements:
            st.info("Extract assets from your script first (Extract tab).")
        else:
            msg = "All assets are matched or generated! Check the Review tab for generated assets."
            if skipped:
                msg += f" ({len(skipped)} skipped for editor)"
            st.success(msg)
        return

    # Summary
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Need Generation", len(needed))
    with col2:
        st.metric("Currently Generating", len(generating))
    with col3:
        st.metric("Failed", len(failed))
    with col4:
        st.metric("Skipped", len(skipped))

    st.divider()

    # Show assets needing generation
    if needed:
        st.markdown("#### Assets to Generate")
        for req in needed:
            with st.container():
                col1, col2, col3, col4 = st.columns([3, 1, 1, 1])
                with col1:
                    st.markdown(f"**{req.get('asset_name', 'Unknown')}** ({req.get('asset_type', 'prop')})")
                    desc = req.get('asset_description', '')
                    if desc:
                        st.caption(desc[:150] + "..." if len(desc) > 150 else desc)
                    # Show preview of the actual prompt that will be built
                    with st.expander("View prompt preview", expanded=False):
                        preview_prompt = _build_prompt_preview(
                            req.get('asset_name', 'unknown'),
                            req.get('asset_type', 'prop'),
                            desc or req.get('asset_name', '').replace('-', ' ')
                        )
                        st.code(preview_prompt, language=None)
                with col2:
                    st.caption(f":orange[Needed]")
                with col3:
                    # Individual generate button
                    if st.button("Generate", key=f"gen_single_{req.get('id')}", disabled=st.session_state.asset_generating):
                        with st.spinner(f"Generating {req.get('asset_name')}..."):
                            try:
                                service = get_asset_generation_service()
                                result = asyncio.run(service.generate_single(
                                    requirement=req,
                                    brand_id=UUID(brand_id),
                                    project_id=UUID(project_id)
                                ))
                                if result.get('success'):
                                    st.success(f"Generated {req.get('asset_name')}!")
                                else:
                                    st.error(f"Failed: {result.get('error', 'Unknown error')}")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Generation failed: {e}")
                with col4:
                    # Skip button - editor will handle
                    if st.button("Skip", key=f"skip_{req.get('id')}", help="Editor will create this asset"):
                        db = get_supabase_client()
                        db.table("project_asset_requirements").update(
                            {"status": "skipped"}
                        ).eq("id", req.get('id')).execute()
                        st.rerun()

        st.divider()

        # Batch generate button
        if st.button(
            f"Generate All {len(needed)} Assets",
            type="primary",
            disabled=st.session_state.asset_generating,
            help="Generate all missing assets using Gemini AI (with rate limiting)"
        ):
            st.session_state.asset_generating = True
            st.rerun()

    # Handle generation
    if st.session_state.asset_generating and needed:
        st.warning("Generating assets... This may take several minutes. Do not close this page.")

        progress_bar = st.progress(0)
        status_text = st.empty()

        try:
            service = get_asset_generation_service()

            # Generate batch
            result = asyncio.run(service.generate_batch(
                requirements=needed,
                brand_id=UUID(brand_id),
                project_id=UUID(project_id),
                delay_between=3.0  # Rate limiting
            ))

            st.session_state.asset_generating = False

            success_count = len(result.get('successful', []))
            fail_count = len(result.get('failed', []))

            if success_count > 0:
                st.success(f"Generated {success_count} assets successfully!")
            if fail_count > 0:
                st.warning(f"{fail_count} assets failed to generate. You can retry them.")

            st.rerun()

        except Exception as e:
            st.session_state.asset_generating = False
            st.error(f"Generation failed: {e}")

    # Show failed generations with retry option
    if failed:
        st.markdown("#### Failed Generations")

        # Retry All Failed button
        col1, col2 = st.columns([1, 3])
        with col1:
            if st.button(f"Retry All {len(failed)} Failed", type="primary"):
                db = get_supabase_client()
                for req in failed:
                    db.table("project_asset_requirements").update(
                        {"status": "needed"}
                    ).eq("id", req.get('id')).execute()
                st.success(f"Reset {len(failed)} assets to 'needed' - they'll generate with the next batch")
                st.rerun()

        for req in failed:
            with st.container():
                col1, col2 = st.columns([3, 1])
                with col1:
                    st.markdown(f"**{req.get('asset_name', 'Unknown')}**")
                with col2:
                    if st.button("Retry", key=f"retry_{req.get('id')}"):
                        # Reset status to needed
                        db = get_supabase_client()
                        db.table("project_asset_requirements").update(
                            {"status": "needed"}
                        ).eq("id", req.get('id')).execute()
                        st.rerun()

    # Show skipped assets with unskip option
    if skipped:
        st.markdown("#### Skipped (Editor Will Handle)")
        st.caption("These assets won't be generated - the editor will create them.")
        for req in skipped:
            with st.container():
                col1, col2 = st.columns([3, 1])
                with col1:
                    st.markdown(f"**{req.get('asset_name', 'Unknown')}** ({req.get('asset_type', 'prop')})")
                with col2:
                    if st.button("Unskip", key=f"unskip_{req.get('id')}"):
                        db = get_supabase_client()
                        db.table("project_asset_requirements").update(
                            {"status": "needed"}
                        ).eq("id", req.get('id')).execute()
                        st.rerun()


def render_asset_review(project_id: str, brand_id: str, existing_requirements: List[Dict]):
    """Render the asset review/approval interface."""
    st.markdown("### Review Generated Assets")

    # Filter for assets pending review
    generated = [r for r in existing_requirements if r.get('status') == 'generated']
    approved = [r for r in existing_requirements if r.get('status') == 'approved']

    if not generated:
        if approved:
            st.success(f"All generated assets have been reviewed! ({len(approved)} approved)")
        else:
            st.info("No assets pending review. Generate missing assets first (Generate tab).")
        return

    # Load script data once for context lookup
    script_data = get_script_data_for_project(project_id)

    st.info(f"{len(generated)} assets ready for review")

    # Bulk actions
    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("Approve All", type="primary"):
            service = get_asset_generation_service()
            for req in generated:
                asyncio.run(service.approve_asset(
                    requirement_id=UUID(req.get('id')),
                    add_to_library=True,
                    brand_id=UUID(brand_id)
                ))
            st.success(f"Approved {len(generated)} assets!")
            st.rerun()
    with col2:
        if st.button("Reject All & Regenerate"):
            service = get_asset_generation_service()
            for req in generated:
                asyncio.run(service.reject_asset(
                    requirement_id=UUID(req.get('id')),
                    rejection_reason="Bulk rejected"
                ))
            st.warning(f"Rejected {len(generated)} assets - they'll appear in Generate tab")
            st.rerun()

    st.divider()

    # Individual review
    st.markdown("#### Review Each Asset")

    for req in generated:
        req_id = req.get('id')
        name = req.get('asset_name', 'Unknown')
        asset_type = req.get('asset_type', 'prop')
        image_url = req.get('generated_image_url', '')

        with st.container():
            col1, col2 = st.columns([2, 1])

            with col1:
                st.markdown(f"**{name}** ({asset_type})")

                # Show generated image
                if image_url:
                    st.image(image_url, width=300)
                else:
                    st.warning("No image URL available")

                # Description
                desc = req.get('asset_description', '')
                if desc:
                    with st.expander("Description"):
                        st.write(desc)

                # Show usage context from script
                script_ref = req.get('script_reference')
                if script_ref and script_data:
                    context = get_beat_context(script_data, script_ref)
                    if context:
                        with st.expander("📍 Used in these scenes", expanded=True):
                            st.markdown(context)

            with col2:
                st.markdown("**Actions:**")

                # Approve
                if st.button("Approve", key=f"approve_{req_id}", type="primary"):
                    service = get_asset_generation_service()
                    asyncio.run(service.approve_asset(
                        requirement_id=UUID(req_id),
                        add_to_library=True,
                        brand_id=UUID(brand_id)
                    ))
                    st.success(f"Approved '{name}'")
                    st.rerun()

                # Reject & Regenerate (resets to 'needed' status)
                if st.button("Reject & Redo", key=f"reject_{req_id}"):
                    service = get_asset_generation_service()
                    asyncio.run(service.reject_asset(
                        requirement_id=UUID(req_id),
                        rejection_reason="Manual rejection"
                    ))
                    st.info(f"'{name}' sent back to Generate tab")
                    st.rerun()

            st.divider()


def render_requirement_list(requirements: List[Dict], project_id: str):
    """Render a list of asset requirements."""
    for req in requirements:
        status = req.get('status', 'needed')
        name = req.get('asset_name', 'Unknown')
        description = req.get('asset_description', '')[:100]

        # Status badge
        status_colors = {
            'matched': 'green',
            'needed': 'orange',
            'generating': 'blue',
            'generated': 'violet',
            'approved': 'green',
            'generation_failed': 'red',
            'skipped': 'gray'
        }
        status_icons = {
            'matched': '✅',
            'needed': '🔸',
            'generating': '⏳',
            'generated': '🖼️',
            'approved': '✓',
            'generation_failed': '✗',
            'skipped': '⏭️'
        }

        col1, col2, col3 = st.columns([3, 1, 1])

        with col1:
            st.markdown(f"**{name}**")
            if description:
                st.caption(description + "..." if len(req.get('asset_description', '')) > 100 else description)

            # Show matched asset if exists
            if req.get('comic_assets'):
                matched_asset = req['comic_assets']
                if matched_asset.get('image_url'):
                    st.image(matched_asset['image_url'], width=100)

        with col2:
            color = status_colors.get(status, 'gray')
            icon = status_icons.get(status, '•')
            st.markdown(f":{color}[{icon} {status}]")

        with col3:
            # Script references
            refs = req.get('script_reference')
            if refs:
                try:
                    ref_list = json.loads(refs) if isinstance(refs, str) else refs
                    if ref_list:
                        st.caption(f"Beats: {', '.join(ref_list[:3])}")
                except Exception:
                    pass

        st.divider()


def render_asset_library(brand_id: str):
    """Render the asset library browser."""
    st.markdown("#### Asset Library")

    # Filter options
    col1, col2 = st.columns(2)
    with col1:
        filter_type = st.selectbox(
            "Filter by Type",
            options=["All", "character", "prop", "background", "effect"],
            key="asset_library_filter_type"
        )
    with col2:
        core_only = st.checkbox("Core Assets Only", key="asset_library_core_only")

    # Fetch assets
    service = get_asset_service()
    asset_type = None if filter_type == "All" else filter_type
    assets = asyncio.run(service.get_asset_library(
        brand_id=UUID(brand_id),
        asset_type=asset_type,
        core_only=core_only
    ))

    if not assets:
        st.info("No assets in library yet. Upload assets or generate them from scripts.")
        return

    st.caption(f"Showing {len(assets)} assets")

    # Display in grid
    cols = st.columns(4)
    for idx, asset in enumerate(assets):
        col_idx = idx % 4
        with cols[col_idx]:
            with st.container():
                # Image or placeholder
                if asset.get('image_url'):
                    st.image(asset['image_url'], use_container_width=True)
                else:
                    st.markdown("🖼️ *No image*")

                # Name and type
                st.markdown(f"**{asset.get('name', 'Unknown')}**")

                # Type badge
                asset_type = asset.get('asset_type', 'unknown')
                type_colors = {
                    'character': 'blue',
                    'prop': 'orange',
                    'background': 'green',
                    'effect': 'violet'
                }
                st.caption(f":{type_colors.get(asset_type, 'gray')}[{asset_type}]")

                # Core asset badge
                if asset.get('is_core_asset'):
                    st.caption("⭐ Core Asset")

                # Tags
                tags = asset.get('tags', [])
                if tags:
                    st.caption(f"Tags: {', '.join(tags[:3])}")


def render_asset_upload(brand_id: str):
    """Render the asset upload interface."""

    # Sub-tabs for different upload methods
    upload_tab1, upload_tab2, upload_tab3 = st.tabs(["Single Upload", "Batch File Upload", "JSON Import"])

    with upload_tab1:
        render_single_asset_upload(brand_id)

    with upload_tab2:
        render_batch_file_upload(brand_id)

    with upload_tab3:
        render_json_import(brand_id)


def render_single_asset_upload(brand_id: str):
    """Render single asset upload form with file upload support."""
    st.markdown("#### Upload Single Asset")

    with st.form("asset_upload_form"):
        name = st.text_input(
            "Asset Name",
            placeholder="e.g., every-coon-happy",
            help="Use lowercase with hyphens. If uploading a file, name will default to filename."
        )

        asset_type = st.selectbox(
            "Asset Type",
            options=["character", "prop", "background", "effect"]
        )

        description = st.text_area(
            "Description",
            placeholder="Visual description of the asset...",
            help="Describe the asset for future generation prompts"
        )

        tags_input = st.text_input(
            "Tags (comma-separated)",
            placeholder="raccoon, happy, excited",
            help="Add searchable tags"
        )

        is_core = st.checkbox(
            "Mark as Core Asset",
            help="Core assets are always available for matching"
        )

        # File upload
        uploaded_file = st.file_uploader(
            "Upload Image File",
            type=["png", "jpg", "jpeg", "webp"],
            help="Upload image file directly (PNG, JPG, WEBP)"
        )

        # OR URL input
        image_url = st.text_input(
            "OR Image URL",
            placeholder="https://example.com/asset.png",
            help="Alternatively, provide a direct URL to the image"
        )

        submitted = st.form_submit_button("Add Asset")

        if submitted:
            service = get_asset_service()
            tags = [t.strip() for t in tags_input.split(',') if t.strip()] if tags_input else []

            try:
                if uploaded_file:
                    # File upload flow
                    file_data = uploaded_file.read()
                    filename = uploaded_file.name
                    asset_name = name if name else filename.rsplit('.', 1)[0]

                    # Determine content type
                    content_type = uploaded_file.type or "image/png"

                    asset_id = asyncio.run(service.upload_asset_with_file(
                        brand_id=UUID(brand_id),
                        name=asset_name,
                        asset_type=asset_type,
                        file_data=file_data,
                        filename=filename,
                        content_type=content_type,
                        description=description,
                        tags=tags,
                        is_core_asset=is_core
                    ))

                    st.success(f"Asset '{asset_name}' uploaded successfully!")
                    st.rerun()

                elif image_url:
                    # URL flow
                    if not name:
                        st.error("Asset name is required when using URL")
                    else:
                        asset_id = asyncio.run(service.upload_asset(
                            brand_id=UUID(brand_id),
                            name=name,
                            asset_type=asset_type,
                            description=description,
                            tags=tags,
                            image_url=image_url,
                            is_core_asset=is_core
                        ))

                        st.success(f"Asset '{name}' added successfully!")
                        st.rerun()
                else:
                    st.error("Please upload a file or provide an image URL")

            except Exception as e:
                st.error(f"Failed to add asset: {e}")


def render_batch_file_upload(brand_id: str):
    """Render batch file upload interface."""
    st.markdown("#### Batch File Upload")
    st.caption("Upload multiple image files at once. Asset names will be derived from filenames.")

    # Default settings for batch
    col1, col2 = st.columns(2)
    with col1:
        default_type = st.selectbox(
            "Default Asset Type",
            options=["character", "prop", "background", "effect"],
            key="batch_default_type"
        )
    with col2:
        default_core = st.checkbox(
            "Mark All as Core Assets",
            key="batch_default_core"
        )

    default_tags = st.text_input(
        "Default Tags (comma-separated)",
        placeholder="imported, batch",
        help="Tags to apply to all uploaded assets",
        key="batch_default_tags"
    )

    # Multi-file uploader
    uploaded_files = st.file_uploader(
        "Select Image Files",
        type=["png", "jpg", "jpeg", "webp"],
        accept_multiple_files=True,
        help="Select multiple PNG, JPG, or WEBP files"
    )

    if uploaded_files:
        st.info(f"Selected {len(uploaded_files)} files")

        # Preview selected files
        with st.expander("Preview Selected Files", expanded=False):
            cols = st.columns(4)
            for idx, f in enumerate(uploaded_files[:12]):  # Show first 12
                with cols[idx % 4]:
                    st.caption(f.name)

        if st.button("Upload All Files", type="primary"):
            service = get_asset_service()
            tags = [t.strip() for t in default_tags.split(',') if t.strip()] if default_tags else []

            progress_bar = st.progress(0)
            status_text = st.empty()

            successful = 0
            failed = 0

            for idx, uploaded_file in enumerate(uploaded_files):
                try:
                    status_text.text(f"Uploading {uploaded_file.name}...")

                    file_data = uploaded_file.read()
                    filename = uploaded_file.name
                    asset_name = filename.rsplit('.', 1)[0]
                    content_type = uploaded_file.type or "image/png"

                    asyncio.run(service.upload_asset_with_file(
                        brand_id=UUID(brand_id),
                        name=asset_name,
                        asset_type=default_type,
                        file_data=file_data,
                        filename=filename,
                        content_type=content_type,
                        tags=tags,
                        is_core_asset=default_core
                    ))

                    successful += 1

                except Exception as e:
                    st.warning(f"Failed to upload '{uploaded_file.name}': {e}")
                    failed += 1

                progress_bar.progress((idx + 1) / len(uploaded_files))

            status_text.empty()
            progress_bar.empty()

            if failed == 0:
                st.success(f"Successfully uploaded all {successful} assets!")
            else:
                st.warning(f"Uploaded {successful} assets, {failed} failed")

            st.rerun()


def render_json_import(brand_id: str):
    """Render JSON import interface."""
    st.markdown("#### JSON Import")
    st.caption("Import assets from JSON data. Best for assets with URLs already hosted.")

    st.markdown("""
    **Expected JSON format:**
    ```json
    [
        {
            "name": "asset-name",
            "type": "character|prop|background|effect",
            "description": "Visual description",
            "tags": ["tag1", "tag2"],
            "image_url": "https://example.com/image.png",
            "is_core": false
        }
    ]
    ```
    """)

    json_data = st.text_area(
        "Paste JSON Array",
        placeholder='[{"name": "asset-1", "type": "character", "description": "..."}]',
        help="Array of asset objects",
        height=200
    )

    if st.button("Import from JSON"):
        if not json_data:
            st.warning("Please paste JSON data to import")
        else:
            try:
                assets_to_import = json.loads(json_data)
                if not isinstance(assets_to_import, list):
                    st.error("JSON must be an array of asset objects")
                else:
                    service = get_asset_service()
                    imported = 0
                    for asset in assets_to_import:
                        try:
                            asyncio.run(service.upload_asset(
                                brand_id=UUID(brand_id),
                                name=asset.get('name', ''),
                                asset_type=asset.get('type', 'prop'),
                                description=asset.get('description', ''),
                                tags=asset.get('tags', []),
                                image_url=asset.get('image_url'),
                                is_core_asset=asset.get('is_core', False)
                            ))
                            imported += 1
                        except Exception as e:
                            st.warning(f"Failed to import '{asset.get('name')}': {e}")

                    st.success(f"Imported {imported} of {len(assets_to_import)} assets")
                    st.rerun()

            except json.JSONDecodeError as e:
                st.error(f"Invalid JSON: {e}")


# =========================================================================
# SFX Tab Functions
# =========================================================================

def render_sfx_tab(project: Dict):
    """Render the sound effects management tab."""
    project_id = project.get('id')
    brand_id = project.get('brand_id')
    workflow_state = project.get('workflow_state', 'pending')

    # Check if script is approved
    script_approved = workflow_state in [
        'script_approved', 'els_ready', 'audio_production', 'audio_complete',
        'handoff_ready', 'handoff_generated'
    ]

    st.markdown("### Sound Effects (SFX)")

    if not script_approved:
        st.info("Approve your script first before extracting SFX.")
        st.caption("The SFX tab becomes available after script approval.")
        return

    # Get current script
    try:
        db = get_supabase_client()
        scripts = db.table("script_versions").select("*").eq(
            "project_id", project_id
        ).eq("status", "approved").order("version_number", desc=True).limit(1).execute()

        if not scripts.data:
            st.warning("No approved script found.")
            return

        current_script = scripts.data[0]
        script_content = current_script.get("script_content", {})
        if isinstance(script_content, str):
            import json
            script_content = json.loads(script_content)

    except Exception as e:
        st.error(f"Failed to load script: {e}")
        return

    # Load existing SFX requirements
    try:
        sfx_result = db.table("project_sfx_requirements").select("*").eq(
            "project_id", project_id
        ).execute()
        existing_sfx = sfx_result.data or []
    except Exception:
        existing_sfx = []

    # Sub-tabs for SFX workflow
    sfx_tab1, sfx_tab2, sfx_tab3 = st.tabs(["Extract", "Generate", "Review"])

    with sfx_tab1:
        render_sfx_extract(project_id, script_content, existing_sfx)

    with sfx_tab2:
        render_sfx_generate(project_id, brand_id, existing_sfx)

    with sfx_tab3:
        render_sfx_review(project_id, existing_sfx)


def render_sfx_extract(project_id: str, script_content: Dict, existing_sfx: List[Dict]):
    """Render the SFX extraction interface."""
    st.markdown("#### Extract SFX from Script")

    if existing_sfx:
        st.success(f"Found {len(existing_sfx)} existing SFX requirements")

        # Show summary by status
        status_counts = {}
        for sfx in existing_sfx:
            status = sfx.get('status', 'needed')
            status_counts[status] = status_counts.get(status, 0) + 1

        cols = st.columns(len(status_counts))
        for idx, (status, count) in enumerate(status_counts.items()):
            with cols[idx]:
                st.metric(status.title(), count)

    st.caption("Extract sound effect cues from your script's audio and visual notes.")

    col1, col2 = st.columns([1, 2])
    with col1:
        if st.button(
            "Extract SFX from Script",
            type="primary" if not existing_sfx else "secondary",
            disabled=st.session_state.sfx_extracting
        ):
            st.session_state.sfx_extracting = True
            st.rerun()

    with col2:
        if existing_sfx:
            if st.button("Clear & Re-extract", help="Clear existing SFX and extract fresh"):
                db = get_supabase_client()
                db.table("project_sfx_requirements").delete().eq(
                    "project_id", project_id
                ).execute()
                st.session_state.sfx_extracting = True
                st.rerun()

    # Handle extraction
    if st.session_state.sfx_extracting:
        with st.spinner("Extracting SFX requirements from script..."):
            try:
                service = get_asset_generation_service()
                sfx_requirements = asyncio.run(service.extract_sfx_from_script(script_content))

                # Save to database with smart duration from extraction
                db = get_supabase_client()
                for sfx in sfx_requirements:
                    # Use duration from extraction (music cues are longer)
                    duration = sfx.get("duration_seconds", 2.0)
                    db.table("project_sfx_requirements").insert({
                        "project_id": project_id,
                        "sfx_name": sfx.get("name", "unknown"),
                        "description": sfx.get("description", ""),
                        "script_reference": sfx.get("beat_references", []),
                        "duration_seconds": duration,
                        "status": "needed"
                    }).execute()

                st.session_state.sfx_extracting = False
                st.success(f"Extracted {len(sfx_requirements)} SFX requirements!")
                st.rerun()

            except Exception as e:
                st.session_state.sfx_extracting = False
                st.error(f"Extraction failed: {e}")

    # Show existing SFX list
    if existing_sfx:
        st.divider()
        st.markdown("#### Extracted SFX")
        for sfx in existing_sfx:
            with st.container():
                col1, col2, col3 = st.columns([3, 1, 1])
                with col1:
                    st.markdown(f"**{sfx.get('sfx_name', 'Unknown')}**")
                    st.caption(sfx.get('description', '')[:100] + "..." if len(sfx.get('description', '')) > 100 else sfx.get('description', ''))
                with col2:
                    status = sfx.get('status', 'needed')
                    status_colors = {'needed': 'orange', 'generating': 'blue', 'generated': 'violet', 'approved': 'green', 'rejected': 'red', 'skipped': 'gray'}
                    st.markdown(f":{status_colors.get(status, 'gray')}[{status}]")
                with col3:
                    duration = sfx.get('duration_seconds', 2.0)
                    st.caption(f"{duration}s")


def render_sfx_generate(project_id: str, brand_id: str, existing_sfx: List[Dict]):
    """Render the SFX generation interface."""
    st.markdown("#### Generate Sound Effects")

    # Filter for SFX that need generation
    needed = [s for s in existing_sfx if s.get('status') == 'needed']
    generating = [s for s in existing_sfx if s.get('status') == 'generating']
    failed = [s for s in existing_sfx if s.get('status') == 'rejected']

    if not needed and not generating and not failed:
        if not existing_sfx:
            st.info("Extract SFX from your script first (Extract tab).")
        else:
            st.success("All SFX have been generated! Check the Review tab.")
        return

    # Summary
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Need Generation", len(needed))
    with col2:
        st.metric("Generating", len(generating))
    with col3:
        st.metric("Failed/Rejected", len(failed))

    st.divider()

    # Show SFX needing generation
    if needed:
        st.markdown("#### SFX to Generate")
        for sfx in needed:
            with st.container():
                col1, col2, col3, col4 = st.columns([3, 1, 1, 1])
                with col1:
                    st.markdown(f"**{sfx.get('sfx_name', 'Unknown')}**")
                    st.caption(sfx.get('description', '')[:80])
                with col2:
                    duration = st.number_input(
                        "Duration",
                        min_value=0.5,
                        max_value=22.0,
                        value=float(sfx.get('duration_seconds', 2.0)),
                        step=0.5,
                        key=f"dur_{sfx.get('id')}"
                    )
                with col3:
                    if st.button("Generate", key=f"gen_sfx_{sfx.get('id')}", disabled=st.session_state.sfx_generating):
                        with st.spinner(f"Generating {sfx.get('sfx_name')}..."):
                            try:
                                asyncio.run(generate_single_sfx(sfx, brand_id, duration))
                                st.success(f"Generated!")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Failed: {e}")
                with col4:
                    if st.button("Skip", key=f"skip_sfx_{sfx.get('id')}", help="Editor will handle"):
                        db = get_supabase_client()
                        db.table("project_sfx_requirements").update(
                            {"status": "skipped"}
                        ).eq("id", sfx.get('id')).execute()
                        st.rerun()

        st.divider()

        # Batch generate button
        if st.button(
            f"Generate All {len(needed)} SFX",
            type="primary",
            disabled=st.session_state.sfx_generating
        ):
            st.session_state.sfx_generating = True
            st.rerun()

    # Handle batch generation
    if st.session_state.sfx_generating and needed:
        st.warning("Generating SFX... This may take a while.")
        progress_bar = st.progress(0)

        try:
            total = len(needed)
            for idx, sfx in enumerate(needed):
                progress_bar.progress((idx + 1) / total)
                asyncio.run(generate_single_sfx(sfx, brand_id, sfx.get('duration_seconds', 2.0)))

            st.session_state.sfx_generating = False
            st.success(f"Generated {total} SFX!")
            st.rerun()

        except Exception as e:
            st.session_state.sfx_generating = False
            st.error(f"Generation failed: {e}")

    # Show failed/rejected with retry option
    if failed:
        st.markdown("#### Failed/Rejected SFX")
        if st.button(f"Retry All {len(failed)} Failed"):
            db = get_supabase_client()
            for sfx in failed:
                db.table("project_sfx_requirements").update(
                    {"status": "needed"}
                ).eq("id", sfx.get('id')).execute()
            st.rerun()

        for sfx in failed:
            with st.container():
                col1, col2 = st.columns([3, 1])
                with col1:
                    st.markdown(f"**{sfx.get('sfx_name', 'Unknown')}**")
                with col2:
                    if st.button("Retry", key=f"retry_sfx_{sfx.get('id')}"):
                        db = get_supabase_client()
                        db.table("project_sfx_requirements").update(
                            {"status": "needed"}
                        ).eq("id", sfx.get('id')).execute()
                        st.rerun()


async def generate_single_sfx(sfx: Dict, brand_id: str, duration: float):
    """Generate a single SFX and save to storage."""
    db = get_supabase_client()
    sfx_id = sfx.get('id')

    # Update status to generating
    db.table("project_sfx_requirements").update(
        {"status": "generating"}
    ).eq("id", sfx_id).execute()

    try:
        service = get_asset_generation_service()
        result = await service.generate_sfx(
            description=sfx.get('description', ''),
            duration_seconds=duration
        )

        # Save to storage (use audio-production bucket)
        import base64
        audio_bytes = base64.b64decode(result['audio_base64'])
        storage_path = f"{brand_id}/sfx/{sfx.get('sfx_name', 'unknown')}.mp3"

        db.storage.from_("audio-production").upload(
            storage_path,
            audio_bytes,
            {"content-type": "audio/mpeg", "upsert": "true"}
        )

        # Get public URL
        audio_url = db.storage.from_("audio-production").get_public_url(storage_path)

        # Update database
        db.table("project_sfx_requirements").update({
            "status": "generated",
            "generated_audio_url": audio_url.rstrip("?") if audio_url else "",
            "storage_path": storage_path,
            "duration_seconds": duration
        }).eq("id", sfx_id).execute()

    except Exception as e:
        db.table("project_sfx_requirements").update({
            "status": "rejected",
            "rejection_reason": str(e)
        }).eq("id", sfx_id).execute()
        raise


def render_sfx_review(project_id: str, existing_sfx: List[Dict]):
    """Render the SFX review/approval interface."""
    st.markdown("#### Review Generated SFX")

    # Filter for generated SFX
    generated = [s for s in existing_sfx if s.get('status') == 'generated']
    approved = [s for s in existing_sfx if s.get('status') == 'approved']

    if not generated:
        if approved:
            st.success(f"All SFX have been reviewed! ({len(approved)} approved)")
        else:
            st.info("No SFX pending review. Generate SFX first (Generate tab).")
        return

    # Load script data once for context lookup
    script_data = get_script_data_for_project(project_id)

    st.info(f"{len(generated)} SFX ready for review")

    # Bulk actions
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Approve All", type="primary", key="sfx_approve_all_btn"):
            db = get_supabase_client()
            for sfx in generated:
                db.table("project_sfx_requirements").update(
                    {"status": "approved"}
                ).eq("id", sfx.get('id')).execute()
            st.success(f"Approved {len(generated)} SFX!")
            st.rerun()
    with col2:
        if st.button("Reject All & Regenerate", key="sfx_reject_all_btn"):
            db = get_supabase_client()
            for sfx in generated:
                db.table("project_sfx_requirements").update({
                    "status": "needed",
                    "generated_audio_url": None,
                    "storage_path": None
                }).eq("id", sfx.get('id')).execute()
            st.warning(f"Rejected {len(generated)} SFX - they'll appear in Generate tab")
            st.rerun()

    st.divider()

    # Individual review
    for sfx in generated:
        with st.container():
            st.markdown(f"### {sfx.get('sfx_name', 'Unknown')}")
            st.caption(sfx.get('description', ''))

            # Show usage context from script
            script_ref = sfx.get('script_reference')
            if script_ref and script_data:
                context = get_beat_context(script_data, script_ref)
                if context:
                    with st.expander("📍 Used in these scenes", expanded=True):
                        st.markdown(context)

            # Audio player
            audio_url = sfx.get('generated_audio_url')
            if audio_url:
                st.audio(audio_url)
                st.caption(f"Duration: {sfx.get('duration_seconds', 0)}s")

            # Action buttons
            col1, col2, col3 = st.columns(3)
            with col1:
                if st.button("Approve", key=f"approve_sfx_{sfx.get('id')}", type="primary"):
                    db = get_supabase_client()
                    db.table("project_sfx_requirements").update(
                        {"status": "approved"}
                    ).eq("id", sfx.get('id')).execute()
                    st.success(f"Approved!")
                    st.rerun()
            with col2:
                if st.button("Reject & Redo", key=f"reject_sfx_{sfx.get('id')}"):
                    db = get_supabase_client()
                    db.table("project_sfx_requirements").update({
                        "status": "needed",
                        "generated_audio_url": None,
                        "storage_path": None
                    }).eq("id", sfx.get('id')).execute()
                    st.info(f"Sent back to Generate tab")
                    st.rerun()
            with col3:
                # Adjust duration and regenerate
                new_duration = st.number_input(
                    "New duration",
                    min_value=0.5,
                    max_value=22.0,
                    value=float(sfx.get('duration_seconds', 2.0)),
                    step=0.5,
                    key=f"new_dur_{sfx.get('id')}"
                )
                if st.button("Regenerate", key=f"regen_sfx_{sfx.get('id')}"):
                    db = get_supabase_client()
                    db.table("project_sfx_requirements").update({
                        "status": "needed",
                        "duration_seconds": new_duration,
                        "generated_audio_url": None,
                        "storage_path": None
                    }).eq("id", sfx.get('id')).execute()
                    st.rerun()

            st.divider()


# =========================================================================
# Handoff Tab Functions (MVP 6)
# =========================================================================

def render_handoff_tab(project: Dict):
    """Render the editor handoff tab."""
    project_id = project.get('id')
    brand_id = project.get('brand_id')
    workflow_state = project.get('workflow_state', 'pending')

    # Check if script is approved and audio is complete
    audio_complete = workflow_state in ['audio_complete', 'handoff_ready', 'handoff_generated']

    st.markdown("### Editor Handoff")

    # Check asset status and warn about ungenerated assets
    db = get_supabase_client()
    asset_reqs = db.table("project_asset_requirements").select("*").eq(
        "project_id", project_id
    ).execute().data or []

    needed = [r for r in asset_reqs if r.get('status') == 'needed']
    failed = [r for r in asset_reqs if r.get('status') == 'generation_failed']
    skipped = [r for r in asset_reqs if r.get('status') == 'skipped']

    if needed or failed:
        with st.expander(f"Asset Warning: {len(needed) + len(failed)} assets not generated", expanded=True):
            if needed:
                st.warning(f"**{len(needed)} assets still need generation:** {', '.join(r.get('asset_name', '?') for r in needed[:5])}{'...' if len(needed) > 5 else ''}")
            if failed:
                st.error(f"**{len(failed)} assets failed generation:** {', '.join(r.get('asset_name', '?') for r in failed[:5])}{'...' if len(failed) > 5 else ''}")
            st.caption("You can still generate handoff - the editor will need to create these assets.")

    if skipped:
        st.info(f"{len(skipped)} assets marked for editor to create: {', '.join(r.get('asset_name', '?') for r in skipped[:5])}{'...' if len(skipped) > 5 else ''}")

    if not audio_complete:
        st.info("Complete audio production before generating handoff.")
        st.caption("The Handoff tab becomes available after audio is marked complete.")

        # Show progress
        col1, col2, col3 = st.columns(3)
        with col1:
            script_approved = workflow_state in [
                'script_approved', 'els_ready', 'audio_production', 'audio_complete',
                'handoff_ready', 'handoff_generated'
            ]
            if script_approved:
                st.success("Script approved")
            else:
                st.warning("Script pending")

        with col2:
            if audio_complete:
                st.success("Audio complete")
            else:
                st.warning("Audio pending")

        with col3:
            st.warning("Handoff pending")
        return

    st.caption("Generate a shareable handoff package for your video editor.")

    # Check for existing handoffs
    service = get_handoff_service()
    try:
        existing_handoffs = asyncio.run(service.get_project_handoffs(UUID(project_id)))
    except Exception as e:
        existing_handoffs = []
        st.warning(f"Could not load existing handoffs: {e}")

    if existing_handoffs:
        st.success(f"Found {len(existing_handoffs)} existing handoff(s)")

        # Show most recent handoff
        latest = existing_handoffs[0]
        latest_id = latest.get('id')
        created = latest.get('created_at', '')[:16].replace('T', ' ')

        st.markdown(f"**Latest Handoff:** {created}")

        col1, col2, col3 = st.columns(3)

        with col1:
            # View handoff page
            handoff_url = f"/Editor_Handoff?id={latest_id}"
            if st.button("View Handoff Page", type="primary", use_container_width=True):
                st.markdown(f"[Open Handoff Page]({handoff_url})")
                st.info(f"Share this URL with your editor:\n\n`{handoff_url}`")

        with col2:
            # Download ZIP
            if st.button("Download ZIP", use_container_width=True):
                with st.spinner("Generating ZIP file..."):
                    try:
                        zip_data = asyncio.run(service.generate_zip(UUID(latest_id)))
                        project_title = project.get('topic_title', 'project').replace(' ', '-').lower()
                        st.download_button(
                            label="Click to Download",
                            data=zip_data,
                            file_name=f"{project_title}-handoff.zip",
                            mime="application/zip",
                            use_container_width=True
                        )
                    except Exception as e:
                        st.error(f"Failed to generate ZIP: {e}")

        with col3:
            # Copy link
            st.code(f"?id={latest_id}", language=None)
            st.caption("Copy this URL")

        st.divider()

        # Show handoff summary
        metadata = latest.get('metadata', {})
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Beats", metadata.get('beat_count', 0))
        with col2:
            st.metric("Script Version", f"v{metadata.get('script_version', 1)}")
        with col3:
            has_audio = "Yes" if metadata.get('has_audio') else "No"
            st.metric("Has Audio", has_audio)
        with col4:
            st.metric("Status", metadata.get('workflow_state', 'unknown'))

        st.divider()

        # Regenerate option
        with st.expander("Regenerate Handoff"):
            st.caption("Create a new handoff package with the latest project data.")
            if st.button("Regenerate Handoff", disabled=st.session_state.handoff_generating):
                st.session_state.handoff_generating = True
                st.rerun()

    else:
        # No existing handoffs - show generation UI
        st.info("Generate a handoff package for your video editor.")
        st.markdown("""
        The handoff package includes:
        - Beat-by-beat breakdown with script text
        - Audio files for each beat
        - Visual assets and SFX
        - ZIP download with all files
        - Shareable URL for your editor
        """)

        if st.button("Generate Handoff Package", type="primary", disabled=st.session_state.handoff_generating):
            st.session_state.handoff_generating = True
            st.rerun()

    # Handle handoff generation
    if st.session_state.handoff_generating:
        with st.spinner("Generating handoff package... This may take a moment."):
            try:
                package = asyncio.run(service.generate_handoff(UUID(project_id)))
                st.session_state.handoff_generating = False

                # Update workflow state
                db = get_supabase_client()
                db.table("content_projects").update({
                    "workflow_state": "handoff_generated"
                }).eq("id", project_id).execute()

                st.success(f"Handoff generated! {len(package.beats)} beats packaged.")
                st.rerun()

            except Exception as e:
                st.session_state.handoff_generating = False
                st.error(f"Failed to generate handoff: {e}")


# =============================================================================
# Comic Tab (Phase 8)
# =============================================================================

def render_comic_tab(project: Dict):
    """Render the comic condensation tab."""
    from viraltracker.services.content_pipeline.services.comic_service import (
        ComicConfig, AspectRatio, EmotionalPayoff
    )

    project_id = project.get('id')
    workflow_state = project.get('workflow_state', 'pending')

    st.markdown("### Comic Condensation")

    # Check if script is approved
    if workflow_state not in ['script_approved', 'els_ready', 'audio_production', 'audio_complete',
                               'asset_extraction', 'assets_ready', 'handoff_generated',
                               'comic_evaluation', 'comic_approved']:
        st.warning("Script must be approved before creating comics. Complete the Generate → Review → Approve workflow first.")
        return

    # Check for existing comic versions
    try:
        db = get_supabase_client()
        comics = db.table("comic_versions").select("*").eq(
            "project_id", project_id
        ).order("version_number", desc=True).execute()
        existing_comics = comics.data or []
    except Exception as e:
        st.error(f"Failed to load comics: {e}")
        existing_comics = []

    # Sub-tabs for comic workflow
    comic_tab1, comic_tab2, comic_tab3, comic_tab4, comic_tab5 = st.tabs([
        "Condense", "Evaluate", "Approve", "Generate Image", "Export JSON"
    ])

    with comic_tab1:
        render_comic_condense_tab(project, existing_comics)

    with comic_tab2:
        render_comic_evaluate_tab(project, existing_comics)

    with comic_tab3:
        render_comic_approve_tab(project, existing_comics)

    with comic_tab4:
        render_comic_image_tab(project, existing_comics)

    with comic_tab5:
        render_comic_export_tab(project, existing_comics)


def render_comic_condense_tab(project: Dict, existing_comics: List[Dict]):
    """Render the comic condensation sub-tab."""
    from viraltracker.services.content_pipeline.services.comic_service import (
        ComicConfig, AspectRatio, EmotionalPayoff
    )

    project_id = project.get('id')

    if existing_comics:
        latest = existing_comics[0]
        st.success(f"Comic v{latest.get('version_number')} created ({latest.get('panel_count', '?')} panels)")

        # Show comic preview
        comic_script = latest.get('comic_script')
        if comic_script:
            try:
                comic_data = json.loads(comic_script) if isinstance(comic_script, str) else comic_script
                render_comic_preview(comic_data)
            except Exception as e:
                st.error(f"Failed to parse comic: {e}")

        # Option to create new version
        if st.button("Create New Version", type="secondary"):
            st.session_state.current_comic = None

    # Show condensation form
    st.markdown("#### Condensation Settings")

    col1, col2 = st.columns(2)

    with col1:
        # Aspect ratio selection
        aspect_options = {
            "9:16 (TikTok, Reels, Shorts)": AspectRatio.VERTICAL_9_16,
            "16:9 (YouTube, Twitter)": AspectRatio.LANDSCAPE_16_9,
            "1:1 (Instagram Feed)": AspectRatio.SQUARE_1_1,
            "4:5 (Instagram Portrait)": AspectRatio.PORTRAIT_4_5
        }
        aspect_label = st.selectbox("Aspect Ratio", list(aspect_options.keys()))
        aspect_ratio = aspect_options[aspect_label]

        # Platform
        platform = st.selectbox("Target Platform", ["Instagram", "TikTok", "Twitter", "YouTube"])

    with col2:
        # Panel count
        panel_mode = st.radio("Panel Count", ["AI Suggests", "Custom"])
        if panel_mode == "Custom":
            panel_count = st.slider("Number of Panels", 2, 12, 4)
        else:
            panel_count = None  # AI will suggest

        # Emotional payoff
        payoff_options = {
            "Auto (AI Picks)": None,
            "AHA (Insight)": EmotionalPayoff.AHA,
            "HA! (Humor)": EmotionalPayoff.HA,
            "OOF (Relatable Sting)": EmotionalPayoff.OOF
        }
        payoff_label = st.selectbox("Emotional Payoff", list(payoff_options.keys()))
        emotional_payoff = payoff_options[payoff_label]

    # Get approved script
    script_data = get_script_data_for_project(project_id)

    if not script_data:
        st.warning("No approved script found. Please approve a script first.")
        return

    # Condense button
    if st.button("Condense to Comic", type="primary", disabled=st.session_state.comic_condensing):
        st.session_state.comic_condensing = True
        st.rerun()

    # Handle condensation
    if st.session_state.comic_condensing:
        with st.spinner("Condensing script to comic format... This may take 30-60 seconds."):
            try:
                config = ComicConfig(
                    panel_count=panel_count,
                    aspect_ratio=aspect_ratio,
                    target_platform=platform.lower(),
                    emotional_payoff=emotional_payoff
                )

                service = get_comic_service()
                comic_script = asyncio.run(service.condense_to_comic(
                    project_id=UUID(project_id),
                    script_data=script_data,
                    config=config
                ))

                # Save to database
                script_version_id = project.get('current_script_version_id')
                comic_id = asyncio.run(service.save_comic_to_db(
                    project_id=UUID(project_id),
                    comic_script=comic_script,
                    script_version_id=UUID(script_version_id) if script_version_id else None
                ))

                st.session_state.comic_condensing = False
                st.session_state.current_comic = comic_script.to_dict()
                st.success(f"Created {len(comic_script.panels)}-panel comic!")
                st.rerun()

            except Exception as e:
                st.session_state.comic_condensing = False
                st.error(f"Condensation failed: {e}")


def render_comic_evaluate_tab(project: Dict, existing_comics: List[Dict]):
    """Render the comic evaluation sub-tab."""
    project_id = project.get('id')

    if not existing_comics:
        st.info("No comic to evaluate. Create a comic first in the Condense tab.")
        return

    latest = existing_comics[0]
    comic_id = latest.get('id')

    # Check for existing evaluation
    eval_results = latest.get('evaluation_results')

    if eval_results:
        st.markdown("### Evaluation Results")
        render_comic_evaluation(eval_results)

        # Check if revision is needed
        quick_approve = eval_results.get('quick_approve_eligible', False)
        overall_score = eval_results.get('overall_score', 0)

        if not quick_approve:
            st.markdown("---")
            st.markdown("### Revise Comic")
            st.markdown("Use AI to generate an improved version based on the evaluation feedback.")

            revision_notes = st.text_area(
                "Revision Notes (optional)",
                placeholder="Add specific guidance for the revision, e.g., 'Make the punchline sharper' or 'The hook needs more punch'",
                key="comic_revision_notes_input"
            )

            col1, col2 = st.columns(2)
            with col1:
                if st.button("Revise Comic", type="primary", disabled=st.session_state.get('comic_revising', False)):
                    st.session_state.comic_revising = True
                    st.session_state.comic_revision_notes = revision_notes  # Store in different key
                    st.rerun()
            with col2:
                if st.button("Re-evaluate", type="secondary"):
                    st.session_state.comic_evaluation = None
                    st.rerun()
        else:
            st.success("Comic is ready for approval! All scores > 85")
            if st.button("Re-evaluate", type="secondary"):
                st.session_state.comic_evaluation = None
                st.rerun()

    else:
        st.markdown("### Evaluate Comic Script")
        st.markdown("Evaluate the comic for clarity, humor, and flow using the Comic KB best practices.")

        if st.button("Evaluate Comic", type="primary", disabled=st.session_state.comic_evaluating):
            st.session_state.comic_evaluating = True
            st.rerun()

    # Handle evaluation
    if st.session_state.comic_evaluating:
        with st.spinner("Evaluating comic against KB checklist..."):
            try:
                from viraltracker.services.content_pipeline.services.comic_service import ComicScript, ComicPanel, GridLayout, AspectRatio, EmotionalPayoff

                # Parse comic data
                comic_script_data = latest.get('comic_script')
                if isinstance(comic_script_data, str):
                    comic_script_data = json.loads(comic_script_data)

                # Rebuild ComicScript object
                panels = []
                for p in comic_script_data.get('panels', []):
                    panels.append(ComicPanel(
                        panel_number=p.get('panel_number', len(panels) + 1),
                        panel_type=p.get('panel_type', 'BUILD'),
                        dialogue=p.get('dialogue', ''),
                        visual_description=p.get('visual_description', ''),
                        character=p.get('character', 'every-coon'),
                        expression=p.get('expression', 'neutral'),
                        background=p.get('background'),
                        props=p.get('props', [])
                    ))

                grid_data = comic_script_data.get('grid_layout', {})
                grid_layout = GridLayout(
                    cols=grid_data.get('cols', 2),
                    rows=grid_data.get('rows', 2),
                    aspect_ratio=AspectRatio(grid_data.get('aspect_ratio', '9:16'))
                )

                payoff_str = comic_script_data.get('emotional_payoff', 'HA!')
                if payoff_str == 'AHA':
                    emotional_payoff = EmotionalPayoff.AHA
                elif payoff_str == 'OOF':
                    emotional_payoff = EmotionalPayoff.OOF
                else:
                    emotional_payoff = EmotionalPayoff.HA

                comic_script = ComicScript(
                    id=comic_script_data.get('id', str(comic_id)),
                    project_id=str(project_id),
                    version_number=latest.get('version_number', 1),
                    title=comic_script_data.get('title', 'Untitled'),
                    premise=comic_script_data.get('premise', ''),
                    emotional_payoff=emotional_payoff,
                    panels=panels,
                    grid_layout=grid_layout
                )

                service = get_comic_service()
                evaluation = asyncio.run(service.evaluate_comic_script(comic_script))

                # Save evaluation
                asyncio.run(service.save_evaluation_to_db(
                    comic_version_id=UUID(comic_id),
                    evaluation=evaluation
                ))

                st.session_state.comic_evaluating = False
                st.session_state.comic_evaluation = evaluation.to_dict()
                st.success("Evaluation complete!")
                st.rerun()

            except Exception as e:
                st.session_state.comic_evaluating = False
                st.error(f"Evaluation failed: {e}")

    # Handle revision
    if st.session_state.get('comic_revising', False):
        with st.spinner("Revising comic based on evaluation feedback... This may take 30-60 seconds."):
            try:
                from viraltracker.services.content_pipeline.services.comic_service import (
                    ComicScript, ComicPanel, GridLayout, AspectRatio, EmotionalPayoff, ComicEvaluation
                )

                # Parse comic data
                comic_script_data = latest.get('comic_script')
                if isinstance(comic_script_data, str):
                    comic_script_data = json.loads(comic_script_data)

                # Rebuild ComicScript object
                panels = []
                for p in comic_script_data.get('panels', []):
                    panels.append(ComicPanel(
                        panel_number=p.get('panel_number', len(panels) + 1),
                        panel_type=p.get('panel_type', 'BUILD'),
                        dialogue=p.get('dialogue', ''),
                        visual_description=p.get('visual_description', ''),
                        character=p.get('character', 'every-coon'),
                        expression=p.get('expression', 'neutral'),
                        background=p.get('background'),
                        props=p.get('props', [])
                    ))

                grid_data = comic_script_data.get('grid_layout', {})
                grid_layout = GridLayout(
                    cols=grid_data.get('cols', 2),
                    rows=grid_data.get('rows', 2),
                    aspect_ratio=AspectRatio(grid_data.get('aspect_ratio', '9:16'))
                )

                payoff_str = comic_script_data.get('emotional_payoff', 'HA!')
                if payoff_str == 'AHA':
                    emotional_payoff = EmotionalPayoff.AHA
                elif payoff_str == 'OOF':
                    emotional_payoff = EmotionalPayoff.OOF
                else:
                    emotional_payoff = EmotionalPayoff.HA

                comic_script = ComicScript(
                    id=comic_script_data.get('id', str(comic_id)),
                    project_id=str(project_id),
                    version_number=latest.get('version_number', 1),
                    title=comic_script_data.get('title', 'Untitled'),
                    premise=comic_script_data.get('premise', ''),
                    emotional_payoff=emotional_payoff,
                    panels=panels,
                    grid_layout=grid_layout
                )

                # Rebuild ComicEvaluation object
                eval_data = eval_results
                issues = eval_data.get('issues', [])
                evaluation = ComicEvaluation(
                    clarity_score=eval_data.get('clarity_score', 0),
                    clarity_notes=eval_data.get('clarity_notes', ''),
                    humor_score=eval_data.get('humor_score', 0),
                    humor_notes=eval_data.get('humor_notes', ''),
                    flow_score=eval_data.get('flow_score', 0),
                    flow_notes=eval_data.get('flow_notes', ''),
                    overall_score=eval_data.get('overall_score', 0),
                    issues=issues,
                    suggestions=eval_data.get('suggestions', []),
                    ready_for_approval=eval_data.get('ready_for_approval', False),
                    quick_approve_eligible=eval_data.get('quick_approve_eligible', False)
                )

                # Get revision notes
                revision_notes = st.session_state.get('comic_revision_notes', '')

                # Revise the comic
                service = get_comic_service()
                revised_script = asyncio.run(service.revise_comic(
                    comic_script=comic_script,
                    evaluation=evaluation,
                    revision_notes=revision_notes if revision_notes else None
                ))

                # Save to database as new version
                script_version_id = project.get('current_script_version_id')
                new_comic_id = asyncio.run(service.save_comic_to_db(
                    project_id=UUID(project_id),
                    comic_script=revised_script,
                    script_version_id=UUID(script_version_id) if script_version_id else None
                ))

                st.session_state.comic_revising = False
                st.session_state.comic_revision_notes = ''
                st.session_state.current_comic = revised_script.to_dict()
                st.session_state.comic_evaluation = None  # Clear old evaluation
                st.success(f"Created revised comic v{revised_script.version_number}! Please evaluate the new version.")
                st.rerun()

            except Exception as e:
                st.session_state.comic_revising = False
                st.error(f"Revision failed: {e}")


def render_comic_approve_tab(project: Dict, existing_comics: List[Dict]):
    """Render the comic approval sub-tab."""
    project_id = project.get('id')

    if not existing_comics:
        st.info("No comic to approve. Create and evaluate a comic first.")
        return

    latest = existing_comics[0]
    comic_id = latest.get('id')
    status = latest.get('status', 'draft')

    if status == 'approved':
        st.success("Comic approved!")
        approved_at = latest.get('approved_at', '')
        if approved_at:
            st.caption(f"Approved at: {approved_at}")

        # Show comic preview
        comic_script = latest.get('comic_script')
        if comic_script:
            try:
                comic_data = json.loads(comic_script) if isinstance(comic_script, str) else comic_script
                render_comic_preview(comic_data)
            except Exception:
                pass
        return

    # Check evaluation
    eval_results = latest.get('evaluation_results')
    if not eval_results:
        st.warning("Comic must be evaluated before approval. Go to the Evaluate tab first.")
        return

    # Show evaluation summary
    st.markdown("### Evaluation Summary")
    render_comic_evaluation(eval_results)

    # Quick approve check
    quick_approve = eval_results.get('quick_approve_eligible', False)
    if quick_approve:
        st.success("Quick Approve Eligible - All scores > 85")

    # Approval form
    st.markdown("### Approve Comic")
    human_notes = st.text_area("Approval Notes (optional)", placeholder="Any notes for this version...")

    col1, col2 = st.columns(2)
    with col1:
        if st.button("Approve Comic", type="primary"):
            try:
                service = get_comic_service()
                asyncio.run(service.approve_comic(
                    comic_version_id=UUID(comic_id),
                    project_id=UUID(project_id),
                    human_notes=human_notes if human_notes else None
                ))
                st.success("Comic approved!")
                st.rerun()
            except Exception as e:
                st.error(f"Approval failed: {e}")

    with col2:
        if st.button("Request Revision", type="secondary"):
            st.info("Revision feature coming soon. Create a new version in the Condense tab.")


def render_comic_image_tab(project: Dict, existing_comics: List[Dict]):
    """Render the comic image generation sub-tab."""
    from viraltracker.services.content_pipeline.services.comic_service import (
        ComicScript, ComicPanel, GridLayout, AspectRatio, EmotionalPayoff
    )

    project_id = project.get('id')

    if not existing_comics:
        st.info("No comic to generate images for. Create and approve a comic first.")
        return

    latest = existing_comics[0]
    comic_id = latest.get('id')
    status = latest.get('status', 'draft')

    # Check if comic is approved
    if status != 'approved':
        st.warning("Comic must be approved before generating images. Go to the Approve tab first.")
        return

    # Check for existing generated image
    image_url = latest.get('generated_image_url')
    image_eval = latest.get('image_evaluation')

    if image_url:
        st.markdown("### Generated Comic Image")
        st.image(image_url, caption="Generated Comic")

        # Show evaluation if exists
        if image_eval:
            st.markdown("#### Image Evaluation")
            render_comic_image_evaluation(image_eval)

            # Re-evaluate and regenerate options
            col_btn1, col_btn2 = st.columns(2)
            with col_btn1:
                if st.button("Re-evaluate Image", type="secondary", key="re_eval_image"):
                    try:
                        db = get_supabase_client()
                        db.table("comic_versions").update({
                            "image_evaluation": None
                        }).eq("id", comic_id).execute()
                        st.success("Evaluation cleared. Click 'Evaluate Generated Image' to re-evaluate.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Failed to clear evaluation: {e}")

            # Regenerate with notes option (shown when below threshold)
            if not image_eval.get('passes_threshold', False):
                st.markdown("---")
                st.markdown("### Regenerate Image")
                regen_notes = st.text_area(
                    "Regeneration Notes",
                    placeholder="Add specific guidance for regeneration based on the evaluation feedback, e.g., 'Make text bubbles larger and clearer' or 'Improve character consistency in panels 2-3'",
                    key="image_regen_notes_input"
                )
                if st.button("Regenerate with Notes", type="primary"):
                    st.session_state.comic_image_generating = True
                    st.session_state.comic_image_regen_notes = regen_notes  # Different key
                    st.rerun()

        # Simple regenerate option (always available)
        if st.button("Regenerate Image", type="secondary"):
            st.session_state.comic_image_generating = True
            st.session_state.comic_image_regen_notes = ""  # Different key
            st.rerun()

    else:
        st.markdown("### Generate Comic Image")
        st.markdown("Generate a comic image using Gemini based on the approved comic script.")

        # Character assets info
        st.markdown("#### Character Assets")
        st.info("The image generator will use character assets from the project's approved assets.")

        # Style options
        col1, col2 = st.columns(2)
        with col1:
            style = st.selectbox("Art Style", [
                "Cartoon (Bold lines, flat colors)",
                "Semi-realistic",
                "Manga/Anime",
                "Minimalist"
            ])
        with col2:
            quality = st.selectbox("Quality", ["Standard", "High", "Ultra"])

        # Generate button
        if st.button("Generate Comic Image", type="primary", disabled=st.session_state.get('comic_image_generating', False)):
            st.session_state.comic_image_generating = True
            st.rerun()

    # Handle image generation
    if st.session_state.get('comic_image_generating', False):
        with st.spinner("Generating comic image with Gemini... This may take 1-2 minutes."):
            try:
                # Parse comic data
                comic_script_data = latest.get('comic_script')
                if isinstance(comic_script_data, str):
                    comic_script_data = json.loads(comic_script_data)

                # Rebuild ComicScript object
                panels = []
                for p in comic_script_data.get('panels', []):
                    panels.append(ComicPanel(
                        panel_number=p.get('panel_number', len(panels) + 1),
                        panel_type=p.get('panel_type', 'BUILD'),
                        dialogue=p.get('dialogue', ''),
                        visual_description=p.get('visual_description', ''),
                        character=p.get('character', 'every-coon'),
                        expression=p.get('expression', 'neutral'),
                        background=p.get('background'),
                        props=p.get('props', [])
                    ))

                grid_data = comic_script_data.get('grid_layout', {})
                grid_layout = GridLayout(
                    cols=grid_data.get('cols', 2),
                    rows=grid_data.get('rows', 2),
                    aspect_ratio=AspectRatio(grid_data.get('aspect_ratio', '9:16'))
                )

                payoff_str = comic_script_data.get('emotional_payoff', 'HA!')
                if payoff_str == 'AHA':
                    emotional_payoff = EmotionalPayoff.AHA
                elif payoff_str == 'OOF':
                    emotional_payoff = EmotionalPayoff.OOF
                else:
                    emotional_payoff = EmotionalPayoff.HA

                comic_script = ComicScript(
                    id=comic_script_data.get('id', str(comic_id)),
                    project_id=str(project_id),
                    version_number=latest.get('version_number', 1),
                    title=comic_script_data.get('title', 'Untitled'),
                    premise=comic_script_data.get('premise', ''),
                    emotional_payoff=emotional_payoff,
                    panels=panels,
                    grid_layout=grid_layout
                )

                # Get reference images from approved assets if available
                reference_images = None
                try:
                    db = get_supabase_client()
                    assets_result = db.table("project_assets").select("image_url").eq(
                        "project_id", project_id
                    ).eq("asset_type", "character").eq("status", "approved").limit(3).execute()
                    if assets_result.data:
                        reference_images = [a.get('image_url') for a in assets_result.data if a.get('image_url')]
                except Exception as e:
                    logger.warning(f"Could not fetch reference images: {e}")

                # Generate comic image
                service = get_comic_service()
                gemini = get_gemini_service()

                # Get regeneration notes if any
                regen_notes = st.session_state.get('comic_image_regen_notes', '')

                image_base64 = asyncio.run(service.generate_comic_image(
                    comic_script=comic_script,
                    gemini_service=gemini,
                    reference_images=reference_images,
                    improvement_notes=regen_notes if regen_notes else None
                ))

                # Clear regen notes after use
                st.session_state.comic_image_regen_notes = ""

                # Convert base64 to data URL for display/storage
                # TODO: Upload to Supabase storage for permanent URL
                image_url = f"data:image/png;base64,{image_base64}"

                # Save to database
                asyncio.run(service.save_comic_image_to_db(
                    comic_version_id=UUID(comic_id),
                    image_url=image_url
                ))

                st.session_state.comic_image_generating = False
                st.success("Comic image generated!")
                st.rerun()

            except Exception as e:
                st.session_state.comic_image_generating = False
                st.error(f"Image generation failed: {e}")

    # Evaluate image section
    if image_url and not image_eval:
        st.markdown("---")
        st.markdown("### Evaluate Image")

        if st.button("Evaluate Generated Image", type="primary", disabled=st.session_state.get('comic_image_evaluating', False)):
            st.session_state.comic_image_evaluating = True
            st.rerun()

    if st.session_state.get('comic_image_evaluating', False):
        with st.spinner("Evaluating comic image..."):
            try:
                from viraltracker.services.content_pipeline.services.comic_service import (
                    ComicScript, ComicPanel, GridLayout, AspectRatio, EmotionalPayoff
                )

                # Extract base64 from data URL if needed
                if image_url.startswith("data:"):
                    image_base64 = image_url.split(",", 1)[1]
                else:
                    # If it's a regular URL, we'd need to fetch it - for now just use as-is
                    image_base64 = image_url

                # Rebuild comic script for evaluation
                comic_script_data = latest.get('comic_script')
                if isinstance(comic_script_data, str):
                    comic_script_data = json.loads(comic_script_data)

                panels = []
                for p in comic_script_data.get('panels', []):
                    panels.append(ComicPanel(
                        panel_number=p.get('panel_number', len(panels) + 1),
                        panel_type=p.get('panel_type', 'BUILD'),
                        dialogue=p.get('dialogue', ''),
                        visual_description=p.get('visual_description', ''),
                        character=p.get('character', 'every-coon'),
                        expression=p.get('expression', 'neutral'),
                        background=p.get('background'),
                        props=p.get('props', [])
                    ))

                grid_data = comic_script_data.get('grid_layout', {})
                grid_layout = GridLayout(
                    cols=grid_data.get('cols', 2),
                    rows=grid_data.get('rows', 2),
                    aspect_ratio=AspectRatio(grid_data.get('aspect_ratio', '9:16'))
                )

                payoff_str = comic_script_data.get('emotional_payoff', 'HA!')
                if payoff_str == 'AHA':
                    emotional_payoff = EmotionalPayoff.AHA
                elif payoff_str == 'OOF':
                    emotional_payoff = EmotionalPayoff.OOF
                else:
                    emotional_payoff = EmotionalPayoff.HA

                comic_script = ComicScript(
                    id=comic_script_data.get('id', str(comic_id)),
                    project_id=str(project_id),
                    version_number=latest.get('version_number', 1),
                    title=comic_script_data.get('title', 'Untitled'),
                    premise=comic_script_data.get('premise', ''),
                    emotional_payoff=emotional_payoff,
                    panels=panels,
                    grid_layout=grid_layout
                )

                service = get_comic_service()
                gemini = get_gemini_service()
                evaluation = asyncio.run(service.evaluate_comic_image(
                    image_base64=image_base64,
                    comic_script=comic_script,
                    gemini_service=gemini
                ))

                # Save evaluation
                db = get_supabase_client()
                db.table("comic_versions").update({
                    "image_evaluation": evaluation.to_dict()
                }).eq("id", comic_id).execute()

                st.session_state.comic_image_evaluating = False
                st.success("Image evaluation complete!")
                st.rerun()

            except Exception as e:
                st.session_state.comic_image_evaluating = False
                st.error(f"Image evaluation failed: {e}")


def render_comic_image_evaluation(eval_data: Dict):
    """Render comic image evaluation results."""
    if isinstance(eval_data, str):
        eval_data = json.loads(eval_data)

    col1, col2, col3, col4, col5 = st.columns(5)

    with col1:
        clarity = eval_data.get('visual_clarity_score', 0)
        st.metric("Clarity", f"{clarity}/100")
    with col2:
        accuracy = eval_data.get('character_accuracy_score', 0)
        st.metric("Character", f"{accuracy}/100")
    with col3:
        readability = eval_data.get('text_readability_score', 0)
        st.metric("Text", f"{readability}/100")
    with col4:
        composition = eval_data.get('composition_score', 0)
        st.metric("Composition", f"{composition}/100")
    with col5:
        overall = eval_data.get('overall_score', 0)
        st.metric("Overall", f"{overall}/100")

    # Approval status
    passes = eval_data.get('passes_threshold', False)
    if passes:
        st.success("Image passes threshold (>= 90%) - ready for review")
    else:
        st.warning("Image below threshold - may need regeneration")

    # Dimension notes
    with st.expander("Evaluation Details", expanded=True):
        if eval_data.get('visual_clarity_notes'):
            st.markdown(f"**Clarity:** {eval_data['visual_clarity_notes']}")
        if eval_data.get('character_accuracy_notes'):
            st.markdown(f"**Character:** {eval_data['character_accuracy_notes']}")
        if eval_data.get('text_readability_notes'):
            st.markdown(f"**Text:** {eval_data['text_readability_notes']}")
        if eval_data.get('composition_notes'):
            st.markdown(f"**Composition:** {eval_data['composition_notes']}")
        if eval_data.get('style_consistency_notes'):
            st.markdown(f"**Style:** {eval_data['style_consistency_notes']}")

    # Issues
    issues = eval_data.get('issues', [])
    if issues:
        with st.expander(f"Issues ({len(issues)})"):
            for issue in issues:
                if isinstance(issue, dict):
                    severity = issue.get('severity', 'medium')
                    issue_text = issue.get('issue', str(issue))
                    suggestion = issue.get('suggestion', '')
                    st.markdown(f"**[{severity.upper()}]** {issue_text}")
                    if suggestion:
                        st.caption(f"Suggestion: {suggestion}")
                else:
                    st.markdown(f"- {issue}")

    # Suggestions
    suggestions = eval_data.get('suggestions', [])
    if suggestions:
        with st.expander("Suggestions"):
            for s in suggestions:
                st.markdown(f"- {s}")


def render_comic_export_tab(project: Dict, existing_comics: List[Dict]):
    """Render the comic export (JSON) sub-tab."""
    project_id = project.get('id')

    if not existing_comics:
        st.info("No comic to export. Create and approve a comic first.")
        return

    latest = existing_comics[0]
    comic_id = latest.get('id')
    status = latest.get('status', 'draft')

    # Check if comic is approved and has image
    if status != 'approved':
        st.warning("Comic must be approved before exporting. Go to the Approve tab first.")
        return

    image_url = latest.get('generated_image_url')
    if not image_url:
        st.warning("Comic image must be generated before exporting. Go to the Generate Image tab first.")
        return

    st.markdown("### Export Comic JSON")
    st.markdown("Export the comic in JSON format for use with the video generation tool.")

    # Check for existing export
    export_json = latest.get('export_json')

    if export_json:
        st.success("Export JSON generated!")

        # Display JSON
        with st.expander("View Export JSON"):
            if isinstance(export_json, str):
                export_data = json.loads(export_json)
            else:
                export_data = export_json
            st.json(export_data)

        # Download button
        json_str = json.dumps(export_data, indent=2)
        st.download_button(
            label="Download JSON",
            data=json_str,
            file_name=f"comic_{comic_id}.json",
            mime="application/json"
        )

        # Regenerate option
        if st.button("Regenerate Export", type="secondary"):
            st.session_state.comic_exporting = True
            st.rerun()

    else:
        # Export options
        col1, col2 = st.columns(2)
        with col1:
            include_audio = st.checkbox("Include audio script references", value=True)
        with col2:
            include_assets = st.checkbox("Include asset URLs", value=True)

        if st.button("Generate Export JSON", type="primary", disabled=st.session_state.get('comic_exporting', False)):
            st.session_state.comic_exporting = True
            st.rerun()

    # Handle export generation
    if st.session_state.get('comic_exporting', False):
        with st.spinner("Generating export JSON..."):
            try:
                from viraltracker.services.content_pipeline.services.comic_service import (
                    ComicScript, ComicPanel, GridLayout, AspectRatio, EmotionalPayoff
                )

                # Parse comic data
                comic_script_data = latest.get('comic_script')
                if isinstance(comic_script_data, str):
                    comic_script_data = json.loads(comic_script_data)

                # Rebuild ComicScript object
                panels = []
                for p in comic_script_data.get('panels', []):
                    panels.append(ComicPanel(
                        panel_number=p.get('panel_number', len(panels) + 1),
                        panel_type=p.get('panel_type', 'BUILD'),
                        dialogue=p.get('dialogue', ''),
                        visual_description=p.get('visual_description', ''),
                        character=p.get('character', 'every-coon'),
                        expression=p.get('expression', 'neutral'),
                        background=p.get('background'),
                        props=p.get('props', [])
                    ))

                grid_data = comic_script_data.get('grid_layout', {})
                grid_layout = GridLayout(
                    cols=grid_data.get('cols', 2),
                    rows=grid_data.get('rows', 2),
                    aspect_ratio=AspectRatio(grid_data.get('aspect_ratio', '9:16'))
                )

                payoff_str = comic_script_data.get('emotional_payoff', 'HA!')
                if payoff_str == 'AHA':
                    emotional_payoff = EmotionalPayoff.AHA
                elif payoff_str == 'OOF':
                    emotional_payoff = EmotionalPayoff.OOF
                else:
                    emotional_payoff = EmotionalPayoff.HA

                comic_script = ComicScript(
                    id=comic_script_data.get('id', str(comic_id)),
                    project_id=str(project_id),
                    version_number=latest.get('version_number', 1),
                    title=comic_script_data.get('title', 'Untitled'),
                    premise=comic_script_data.get('premise', ''),
                    emotional_payoff=emotional_payoff,
                    panels=panels,
                    grid_layout=grid_layout
                )

                service = get_comic_service()
                export_json = asyncio.run(service.generate_comic_json(
                    comic_script=comic_script,
                    image_url=image_url
                ))

                # Save to database
                db = get_supabase_client()
                db.table("comic_versions").update({
                    "export_json": export_json
                }).eq("id", comic_id).execute()

                st.session_state.comic_exporting = False
                st.success("Export JSON generated!")
                st.rerun()

            except Exception as e:
                st.session_state.comic_exporting = False
                st.error(f"Export generation failed: {e}")


def render_comic_preview(comic_data: Dict):
    """Render a preview of the comic panels."""
    st.markdown("#### Comic Preview")

    title = comic_data.get('title', 'Untitled')
    premise = comic_data.get('premise', '')
    payoff = comic_data.get('emotional_payoff', '')

    st.markdown(f"**{title}**")
    if premise:
        st.caption(premise)
    if payoff:
        st.caption(f"Payoff: {payoff}")

    panels = comic_data.get('panels', [])
    grid = comic_data.get('grid_layout', {})
    cols = grid.get('cols', 2)

    # Render panels in grid
    for i in range(0, len(panels), cols):
        panel_cols = st.columns(cols)
        for j, col in enumerate(panel_cols):
            idx = i + j
            if idx < len(panels):
                panel = panels[idx]
                with col:
                    with st.container(border=True):
                        panel_type = panel.get('panel_type', 'BUILD')
                        st.markdown(f"**Panel {panel.get('panel_number', idx+1)}** ({panel_type})")
                        st.markdown(f"*{panel.get('character', 'unknown')}*: {panel.get('expression', '')}")
                        st.markdown(f'"{panel.get("dialogue", "")}"')
                        st.caption(panel.get('visual_description', ''))


def render_comic_evaluation(eval_results: Dict):
    """Render comic evaluation results."""
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        clarity = eval_results.get('clarity_score', 0)
        st.metric("Clarity", f"{clarity}/100")
    with col2:
        humor = eval_results.get('humor_score', 0)
        st.metric("Humor", f"{humor}/100")
    with col3:
        flow = eval_results.get('flow_score', 0)
        st.metric("Flow", f"{flow}/100")
    with col4:
        overall = eval_results.get('overall_score', 0)
        st.metric("Overall", f"{overall}/100")

    # Notes
    with st.expander("Evaluation Details"):
        if eval_results.get('clarity_notes'):
            st.markdown(f"**Clarity:** {eval_results['clarity_notes']}")
        if eval_results.get('humor_notes'):
            st.markdown(f"**Humor:** {eval_results['humor_notes']}")
        if eval_results.get('flow_notes'):
            st.markdown(f"**Flow:** {eval_results['flow_notes']}")

    # Issues
    issues = eval_results.get('issues', [])
    if issues:
        with st.expander(f"Issues ({len(issues)})"):
            for issue in issues:
                severity = issue.get('severity', 'low')
                if severity == 'high':
                    st.error(f"**{severity.upper()}**: {issue.get('issue')}")
                elif severity == 'medium':
                    st.warning(f"**{severity.upper()}**: {issue.get('issue')}")
                else:
                    st.info(f"**{severity.upper()}**: {issue.get('issue')}")
                if issue.get('suggestion'):
                    st.caption(f"Suggestion: {issue['suggestion']}")

    # Suggestions
    suggestions = eval_results.get('suggestions', [])
    if suggestions:
        with st.expander("Suggestions"):
            for s in suggestions:
                st.markdown(f"- {s}")


# Main app flow
def main():
    # Check if viewing a specific project
    if st.session_state.pipeline_project_id:
        render_project_detail(st.session_state.pipeline_project_id)
    else:
        render_project_dashboard()


# Run the app
if __name__ == "__main__":
    main()
else:
    main()
