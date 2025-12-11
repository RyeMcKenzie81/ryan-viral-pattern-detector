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
from datetime import datetime
from uuid import UUID
from typing import Optional, Dict, Any, List

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


def get_content_pipeline_service():
    """Get ContentPipelineService instance."""
    from viraltracker.services.content_pipeline.services.content_pipeline_service import ContentPipelineService
    db = get_supabase_client()
    docs = get_doc_service()
    return ContentPipelineService(supabase_client=db, docs_service=docs)


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
    elif workflow_state in ['topic_selected', 'script_generation', 'script_review', 'script_approval', 'script_approved', 'els_ready', 'audio_production', 'audio_complete']:
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

    # Tabs for script workflow - include Audio tab
    tab1, tab2, tab3, tab4 = st.tabs(["Generate", "Review", "Approve", "Audio"])

    with tab1:
        render_script_generation_tab(project)

    with tab2:
        render_script_review_tab(project)

    with tab3:
        render_script_approval_tab(project)

    with tab4:
        render_audio_tab(project)


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
    db = get_supabase_client()
    return AudioProductionService(supabase=db)


def get_els_parser_service():
    """Get ELSParserService instance."""
    from viraltracker.services.els_parser_service import ELSParserService
    return ELSParserService()


def get_elevenlabs_service():
    """Get ElevenLabsService instance."""
    from viraltracker.services.elevenlabs_service import ElevenLabsService
    db = get_supabase_client()
    return ElevenLabsService(supabase=db)


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
    parse_result = els_parser.parse_els(els_content)

    # Create audio session
    session = audio_service.create_session(
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
    results = []
    for beat in parse_result.beats:
        try:
            take = await elevenlabs.generate_beat_audio(
                beat=beat,
                output_dir=f"audio_production/{session.session_id}",
                session_id=session.session_id
            )
            audio_service.save_take(session.session_id, take)
            audio_service.select_take(session.session_id, beat.beat_id, take.take_id)
            results.append({"beat_id": beat.beat_id, "status": "success", "take_id": str(take.take_id)})
        except Exception as e:
            results.append({"beat_id": beat.beat_id, "status": "error", "error": str(e)})

    return {
        "session_id": str(session.session_id),
        "beat_results": results,
        "total_beats": len(parse_result.beats),
        "successful": sum(1 for r in results if r["status"] == "success")
    }


def render_audio_tab(project: Dict):
    """Render the audio production tab."""
    project_id = project.get('id')
    brand_id = project.get('brand_id')
    workflow_state = project.get('workflow_state', 'pending')

    # Check if script is approved
    script_approved = workflow_state in ['script_approved', 'els_ready', 'audio_production', 'audio_complete']

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

    # Handle ELS conversion
    if st.session_state.els_converting and not existing_els:
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

    # Status indicator
    status_colors = {
        'draft': 'orange',
        'generating': 'blue',
        'in_progress': 'green',
        'completed': 'green',
        'exported': 'gray'
    }
    st.caption(f"Status: :{status_colors.get(status, 'gray')}[{status}]")

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

    if not takes:
        st.info("No audio takes generated yet.")
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
        with st.expander(f"**{beat_id}** ({len(beat_takes)} take{'s' if len(beat_takes) > 1 else ''})", expanded=True):
            for take in beat_takes:
                render_audio_take(take, session_id, beat_id)

    st.divider()

    # Export section
    st.markdown("#### Export")
    selected_count = sum(1 for t in takes if t.get('is_selected'))
    total_beats = len(beats_takes)

    if selected_count == total_beats:
        st.success(f"All {total_beats} beats have selected takes.")

        if st.button("Export Selected Takes (ZIP)", type="primary"):
            with st.spinner("Preparing export..."):
                try:
                    audio_service = get_audio_production_service()
                    zip_data = audio_service.export_selected_takes_zip(UUID(session_id))

                    st.download_button(
                        label="Download ZIP",
                        data=zip_data,
                        file_name=f"audio_{session_id[:8]}.zip",
                        mime="application/zip"
                    )
                except Exception as e:
                    st.error(f"Export failed: {e}")
    else:
        st.warning(f"Select takes for all beats before exporting. ({selected_count}/{total_beats} selected)")


def render_audio_take(take: Dict, session_id: str, beat_id: str):
    """Render a single audio take with playback controls."""
    take_id = take.get('id')
    is_selected = take.get('is_selected', False)
    duration_ms = take.get('audio_duration_ms', 0)
    audio_path = take.get('audio_path', '')

    col1, col2, col3 = st.columns([3, 1, 1])

    with col1:
        # Audio player
        if audio_path:
            try:
                audio_service = get_audio_production_service()
                audio_url = audio_service.get_audio_url(audio_path)
                st.audio(audio_url)
            except Exception:
                st.caption(f"Audio: {audio_path}")
        else:
            st.caption("No audio file")

    with col2:
        duration_sec = duration_ms / 1000 if duration_ms else 0
        st.caption(f"{duration_sec:.1f}s")

    with col3:
        if is_selected:
            st.success("Selected", icon="✓")
        else:
            if st.button("Select", key=f"select_{take_id}"):
                try:
                    audio_service = get_audio_production_service()
                    audio_service.select_take(UUID(session_id), beat_id, UUID(take_id))
                    st.rerun()
                except Exception as e:
                    st.error(f"Failed to select: {e}")


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
