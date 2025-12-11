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
    elif workflow_state in ['topic_selected', 'script_generation', 'script_review', 'script_approval', 'script_approved']:
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

    # Tabs for script workflow
    tab1, tab2, tab3 = st.tabs(["Generate", "Review", "Approve"])

    with tab1:
        render_script_generation_tab(project)

    with tab2:
        render_script_review_tab(project)

    with tab3:
        render_script_approval_tab(project)


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

        if st.button("Generate Script", type="primary", disabled=st.session_state.script_generating):
            st.session_state.script_generating = True

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


def render_review_results(review: Dict):
    """Render review checklist results."""
    overall_score = review.get('overall_score', 0)
    ready = review.get('ready_for_approval', False)

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
            with st.expander(f"**{category.replace('_', ' ').title()}**"):
                for item_name, result in items.items():
                    passed = result.get('passed', False)
                    notes = result.get('notes', '')
                    icon = "✅" if passed else "❌"
                    st.markdown(f"{icon} **{item_name.replace('_', ' ').title()}**: {notes}")

    # Issues found
    issues = review.get('issues_found', [])
    if issues:
        st.markdown("### Issues Found")
        for issue in issues:
            severity = issue.get('severity', 'medium')
            color = {"high": "red", "medium": "orange", "low": "blue"}.get(severity, "gray")
            st.markdown(f":{color}[**{severity.upper()}**] {issue.get('issue', '')}")
            st.caption(f"Location: {issue.get('location', 'N/A')} | Suggestion: {issue.get('suggestion', '')}")

    # Improvement suggestions
    suggestions = review.get('improvement_suggestions', [])
    if suggestions:
        st.markdown("### Improvement Suggestions")
        for suggestion in suggestions:
            st.markdown(f"- {suggestion}")


def render_script_approval_tab(project: Dict):
    """Render the script approval tab."""
    project_id = project.get('id')
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

    if status == 'approved':
        st.success("Script has been approved!")
        st.markdown(f"**Approved at:** {current_script.get('approved_at', 'N/A')}")
        if current_script.get('human_notes'):
            st.markdown(f"**Notes:** {current_script.get('human_notes')}")
        return

    if workflow_state not in ['script_approval', 'script_review']:
        st.info("Complete the review before approving.")
        return

    st.markdown("### Approve or Revise Script")

    # Show review summary if available
    checklist_results = current_script.get('checklist_results')
    if checklist_results:
        overall_score = checklist_results.get('overall_score', 0) if isinstance(checklist_results, dict) else 0
        st.metric("Review Score", f"{overall_score}/100")

    col1, col2 = st.columns(2)

    with col1:
        approval_notes = st.text_area(
            "Approval Notes (optional)",
            placeholder="Add any notes about this approval..."
        )

        if st.button("Approve Script", type="primary"):
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

    with col2:
        revision_notes = st.text_area(
            "Revision Notes",
            placeholder="Describe what changes are needed..."
        )

        if st.button("Request Revision"):
            if not revision_notes:
                st.warning("Please provide revision notes")
            else:
                try:
                    # Update project to trigger revision
                    db = get_supabase_client()
                    workflow_data = project.get('workflow_data', {})
                    workflow_data['script_revision_notes'] = revision_notes

                    db.table("content_projects").update({
                        "workflow_state": "script_generation",
                        "workflow_data": workflow_data
                    }).eq("id", project_id).execute()

                    st.info("Revision requested. Return to Generate tab to create a new version.")
                    st.rerun()

                except Exception as e:
                    st.error(f"Failed to request revision: {e}")


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
