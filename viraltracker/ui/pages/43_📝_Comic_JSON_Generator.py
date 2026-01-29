"""
Comic JSON Generator

Accepts a comic strip image and script, analyzes both using AI,
and generates properly formatted JSON for the Comic Video system.
"""

import streamlit as st
import json
import asyncio
import base64
from pathlib import Path
from typing import Optional, Dict, Any, List
import tempfile
import logging

logger = logging.getLogger(__name__)

# Page config
st.set_page_config(
    page_title="Comic JSON Generator",
    page_icon="📝",
    layout="wide"
)

# Authentication
from viraltracker.ui.auth import require_auth
require_auth()

# Organization selector for usage tracking
from viraltracker.ui.utils import render_organization_selector
org_id = render_organization_selector(key="comic_json_org_selector")
if not org_id:
    st.warning("Please select a workspace to continue.")
    st.stop()

# Initialize session state
if "comic_json_result" not in st.session_state:
    st.session_state.comic_json_result = None
if "comic_analysis" not in st.session_state:
    st.session_state.comic_analysis = None
if "script_analysis" not in st.session_state:
    st.session_state.script_analysis = None

def get_gemini_service():
    """Get Gemini service for vision analysis with usage tracking."""
    from viraltracker.services.gemini_service import GeminiService
    from viraltracker.services.usage_tracker import UsageTracker
    from viraltracker.core.database import get_supabase_client
    from viraltracker.ui.auth import get_current_user_id
    from viraltracker.ui.utils import get_current_organization_id

    service = GeminiService()

    # Set up usage tracking if org context available
    org_id = get_current_organization_id()
    if org_id and org_id != "all":
        try:
            db = get_supabase_client()
            tracker = UsageTracker(db)
            service.set_tracking_context(tracker, get_current_user_id(), org_id)
        except Exception as e:
            logger.warning(f"Failed to set up usage tracking: {e}")

    return service

async def analyze_comic_layout(image_bytes: bytes, filename: str) -> Dict[str, Any]:
    """
    Use Gemini to analyze comic strip layout.

    Returns:
        Dict with grid_structure, panel descriptions, etc.
    """
    gemini = get_gemini_service()

    prompt = """Analyze this comic strip image and provide a detailed JSON response with:

1. **Grid Layout**: Count the rows and how many panels are in each row.
   - Look carefully at panel borders/gutters
   - Note any wide panels that span multiple columns
   - Note any tall panels that span multiple rows

2. **Panel Details**: For each panel (numbered 1 to N, left-to-right, top-to-bottom):
   - panel_number
   - row (which row it's in, 1-indexed)
   - column_span (1 if normal, 2+ if wide)
   - visible_text (any text/dialogue visible in the panel)
   - scene_description (brief description of what's shown)
   - mood (dramatic, positive, negative, warning, neutral, celebration, etc.)
   - characters (who/what is in the panel)

Return ONLY valid JSON in this exact format:
{
  "total_panels": <number>,
  "total_rows": <number>,
  "grid_structure": [
    {"row": 1, "columns": <num_cols_in_row>, "panels": [<panel_numbers>]},
    ...
  ],
  "panels": [
    {
      "panel_number": 1,
      "row": 1,
      "column_span": 1,
      "visible_text": "text if any",
      "scene_description": "description",
      "mood": "mood",
      "characters": ["character1", "character2"]
    },
    ...
  ]
}

Be precise about the grid layout - this is critical for video generation."""

    try:
        # Convert bytes to base64 for Gemini
        image_base64 = base64.b64encode(image_bytes).decode('utf-8')

        # Use the analyze_image method
        result = await gemini.analyze_image(image_base64, prompt)

        # Parse JSON from response
        json_str = result
        if "```json" in result:
            json_str = result.split("```json")[1].split("```")[0]
        elif "```" in result:
            json_str = result.split("```")[1].split("```")[0]

        return json.loads(json_str.strip())

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse comic analysis JSON: {e}")
        return {"error": str(e), "raw_response": result if 'result' in locals() else "No response"}
    except Exception as e:
        logger.error(f"Comic analysis failed: {e}")
        return {"error": str(e)}

async def analyze_script(script_text: str, panel_count: int) -> Dict[str, Any]:
    """
    Use Gemini to analyze and structure the script.

    Args:
        script_text: Raw script text
        panel_count: Expected number of panels

    Returns:
        Dict with structured script per panel
    """
    gemini = get_gemini_service()

    prompt = f"""Analyze this comic script and structure it for a {panel_count}-panel comic video.

The video needs TWO types of audio per panel:
1. **Narrator**: Professional voice speaking proper English sentences
2. **Raccoon**: Character voice speaking in broken/simple English

For each panel, identify:
- panel_number (1 to {panel_count})
- panel_type (TITLE, ACT 1, ACT 2, ACT 3, ACT 4, OUTRO, or specific like "ACT 1 - THE BASICS")
- header_text (short header shown on screen, can be null)
- dialogue (visual text shown in comic)
- segments (array of speaker + text for audio generation)

SCRIPT:
{script_text}

Return ONLY valid JSON in this exact format:
{{
  "panels": [
    {{
      "panel_number": 1,
      "panel_type": "TITLE",
      "header_text": "HEADER TEXT" or null,
      "dialogue": "Visual dialogue text",
      "segments": [
        {{"speaker": "narrator", "text": "Proper English narration for this panel."}},
        {{"speaker": "raccoon", "text": "Broken English raccoon speak here."}}
      ]
    }},
    ...
  ]
}}

Rules:
- Narrator speaks in complete, proper sentences
- Raccoon speaks in simple/broken English (no articles, simple words)
- Every panel needs at least one segment
- Title/Outro panels might only have narrator
- Match the tone and content to each panel's purpose"""

    try:
        # Use Gemini model directly for text generation
        result = gemini.model.generate_content(prompt)
        response_text = result.text

        # Parse JSON from response
        json_str = response_text
        if "```json" in response_text:
            json_str = response_text.split("```json")[1].split("```")[0]
        elif "```" in response_text:
            json_str = response_text.split("```")[1].split("```")[0]

        return json.loads(json_str.strip())

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse script analysis JSON: {e}")
        return {"error": str(e), "raw_response": response_text if 'response_text' in locals() else "No response"}
    except Exception as e:
        logger.error(f"Script analysis failed: {e}")
        return {"error": str(e)}

def merge_analyses(comic_analysis: Dict, script_analysis: Dict) -> Dict[str, Any]:
    """
    Merge comic layout analysis with script analysis into final JSON.
    """
    if "error" in comic_analysis:
        return {"error": f"Comic analysis failed: {comic_analysis['error']}"}
    if "error" in script_analysis:
        return {"error": f"Script analysis failed: {script_analysis['error']}"}

    # Build the final JSON structure
    result = {
        "comic_title": "",  # User can fill in
        "video_title": "",  # User can fill in
        "total_panels": comic_analysis.get("total_panels", 0),
        "structure": {},
        "visual_flow": {
            "reading_order": "Left to right, top to bottom"
        },
        "layout_recommendation": {
            "format": f"{comic_analysis.get('total_rows', 1)} rows",
            "grid_structure": comic_analysis.get("grid_structure", [])
        },
        "panels": [],
        "video_production": {
            "canvas_size": [1080, 1920],
            "fps": 30
        }
    }

    # Create panel lookup from script
    script_panels = {p["panel_number"]: p for p in script_analysis.get("panels", [])}

    # Merge comic and script data for each panel
    for comic_panel in comic_analysis.get("panels", []):
        panel_num = comic_panel["panel_number"]
        script_panel = script_panels.get(panel_num, {})

        merged_panel = {
            "panel_number": panel_num,
            "panel_type": script_panel.get("panel_type", "CONTENT"),
            "scene": comic_panel.get("scene_description", ""),
            "mood": comic_panel.get("mood", "neutral"),
            "header_text": script_panel.get("header_text"),
            "dialogue": script_panel.get("dialogue", comic_panel.get("visible_text", "")),
            "segments": script_panel.get("segments", []),
            "characters": comic_panel.get("characters", []),
            "visual_description": comic_panel.get("scene_description", "")
        }

        result["panels"].append(merged_panel)

    return result

def render_json_editor(json_data: Dict) -> Dict:
    """Render an editable JSON view."""
    json_str = json.dumps(json_data, indent=2)
    edited = st.text_area(
        "Edit JSON (if needed)",
        value=json_str,
        height=500,
        key="json_editor"
    )

    try:
        return json.loads(edited)
    except json.JSONDecodeError:
        st.error("Invalid JSON - please fix syntax errors")
        return json_data

# Main UI
st.title("📝 Comic JSON Generator")
st.markdown("Generate properly formatted JSON for the Comic Video system by analyzing your comic strip and script.")

# Two column layout for inputs
col1, col2 = st.columns(2)

with col1:
    st.subheader("1. Upload Comic Strip")
    uploaded_image = st.file_uploader(
        "Upload your comic strip image",
        type=["png", "jpg", "jpeg", "webp"],
        key="comic_upload"
    )

    if uploaded_image:
        st.image(uploaded_image, caption="Uploaded Comic", use_container_width=True)

with col2:
    st.subheader("2. Paste Script")
    script_text = st.text_area(
        "Paste your comic script here",
        height=300,
        placeholder="""Example format:

Panel 1 (Title):
Narrator: "Welcome to Rate Cuts Explained by Raccoons."
Header: RATE CUTS EXPLAINED

Panel 2:
Narrator: "The Federal Reserve controls the price of money."
Raccoon: "Fed control price of money. When cut rates... money become CHEAP!"
Header: THE BASICS

...""",
        key="script_input"
    )

# Titles input
st.subheader("3. Comic Details")
title_col1, title_col2 = st.columns(2)
with title_col1:
    comic_title = st.text_input("Comic Title", placeholder="Rate Cuts Explained by Raccoons")
with title_col2:
    video_title = st.text_input("Video Title", placeholder="Why Good News Makes You Poorer")

# Analyze button
st.divider()

if st.button("🔍 Analyze & Generate JSON", type="primary", disabled=not (uploaded_image and script_text)):
    with st.spinner("Analyzing comic layout..."):
        # Analyze comic
        image_bytes = uploaded_image.getvalue()
        comic_analysis = asyncio.run(analyze_comic_layout(image_bytes, uploaded_image.name))
        st.session_state.comic_analysis = comic_analysis

        if "error" not in comic_analysis:
            st.success(f"Detected {comic_analysis.get('total_panels', 0)} panels in {comic_analysis.get('total_rows', 0)} rows")
        else:
            st.error(f"Comic analysis error: {comic_analysis.get('error')}")

    if "error" not in st.session_state.comic_analysis:
        with st.spinner("Analyzing script..."):
            panel_count = st.session_state.comic_analysis.get("total_panels", 18)
            script_analysis = asyncio.run(analyze_script(script_text, panel_count))
            st.session_state.script_analysis = script_analysis

            if "error" not in script_analysis:
                st.success(f"Parsed script for {len(script_analysis.get('panels', []))} panels")
            else:
                st.error(f"Script analysis error: {script_analysis.get('error')}")

    # Merge results
    if (st.session_state.comic_analysis and "error" not in st.session_state.comic_analysis and
        st.session_state.script_analysis and "error" not in st.session_state.script_analysis):

        merged = merge_analyses(st.session_state.comic_analysis, st.session_state.script_analysis)

        # Add titles
        merged["comic_title"] = comic_title or "Untitled Comic"
        merged["video_title"] = video_title or "Untitled Video"

        st.session_state.comic_json_result = merged
        st.success("JSON generated successfully!")

# Display results
if st.session_state.comic_json_result:
    st.divider()
    st.subheader("4. Generated JSON")

    # Tabs for different views
    tab1, tab2, tab3 = st.tabs(["📄 Full JSON", "🔍 Layout Analysis", "🎭 Script Analysis"])

    with tab1:
        # Editable JSON
        edited_json = render_json_editor(st.session_state.comic_json_result)
        st.session_state.comic_json_result = edited_json

        # Download button
        json_str = json.dumps(edited_json, indent=2)
        st.download_button(
            "📥 Download JSON",
            data=json_str,
            file_name=f"{edited_json.get('comic_title', 'comic').replace(' ', '_').lower()}.json",
            mime="application/json"
        )

        # Copy to clipboard helper
        st.code(json_str, language="json")

    with tab2:
        if st.session_state.comic_analysis:
            st.json(st.session_state.comic_analysis)

    with tab3:
        if st.session_state.script_analysis:
            st.json(st.session_state.script_analysis)

# Help section
with st.expander("ℹ️ How to use this tool"):
    st.markdown("""
    ### Step 1: Upload Comic Strip
    Upload your comic strip image (PNG, JPG, JPEG, or WebP). The AI will analyze:
    - Grid layout (rows and columns)
    - Panel boundaries and sizes
    - Scene descriptions
    - Mood per panel

    ### Step 2: Paste Script
    Paste your comic script. The AI will parse:
    - Panel numbers and types
    - Header text
    - Dialogue
    - Multi-speaker segments (narrator + character)

    ### Script Format Tips
    ```
    Panel 1 (Title):
    Narrator: "Proper English narration here."
    Header: HEADER TEXT

    Panel 2:
    Narrator: "The narrator explains things properly."
    Raccoon: "Raccoon speak simple. No fancy words."
    Header: SECTION HEADER
    Dialogue: "Visual text shown in panel"
    ```

    ### Step 3: Review & Edit
    - Review the generated JSON
    - Edit any fields that need adjustment
    - Download or copy the final JSON

    ### Step 4: Use in Comic Video
    - Go to the Comic Video page
    - Paste your JSON
    - Upload your comic image
    - Generate the video!
    """)
