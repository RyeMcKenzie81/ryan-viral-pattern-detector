"""
Sora MVP - Standalone page for testing Sora video generation.
"""

import streamlit as st
import asyncio
from datetime import datetime

from viraltracker.core.config import Config
from viraltracker.services.content_pipeline.services.sora_service import SoraService
from viraltracker.ui.auth import require_auth

# Auth protection
# Auth protection
st.set_page_config(
    page_title="Sora Video Generator (MVP)",
    page_icon="🎥",
    layout="wide"
)

require_auth()

# Header
st.title("🎥 Sora Video Generator (MVP)")
st.markdown("Direct interface for testing OpenAI's Sora 2 API.")

# Initialize Service
# Note: Using st.cache_resource would be better, but direct instantiation ensures freshness for MVP
if "sora_service" not in st.session_state:
    st.session_state.sora_service = SoraService()

service = st.session_state.sora_service

# Configuration
with st.expander("Configuration", expanded=True):
    col_conf1, col_conf2, col_conf3 = st.columns(3)
    
    with col_conf1:
        # Model Selection
        model_options = list(Config.SORA_MODELS.keys())
        selected_model_key = st.radio(
            "Select Model",
            options=model_options,
            format_func=lambda x: f"{x} (${Config.SORA_MODELS[x]:.2f}/s)"
        )
    
    with col_conf2:
        # Duration
        duration = st.slider("Duration (seconds)", min_value=5, max_value=20, value=5, step=1)
        
        # Dry Run Toggle
        dry_run = st.checkbox("Dry Run (Simulate API Call)", value=True, help="Uncheck to spend real money")

    with col_conf3:
        # Cost Estimation
        estimated_cost = service.estimate_cost(duration, selected_model_key)
        st.metric("Estimated Cost", f"${estimated_cost:.2f}")
        
        if selected_model_key == 'sora-2-pro-2025-10-06':
            st.warning("⚠️ PRO model ($0.50/s)")
        else:
            st.success("✅ Standard model ($0.10/s)")


# Main Interface
col1, col2 = st.columns([2, 1])

with col1:
    st.subheader("Prompt")
    prompt = st.text_area(
        "Describe your video",
        height=150,
        placeholder="A cinematic drone shot of a futuristic cyberpunk city with neon lights reflecting in rain puddles..."
    )
    
    generate_btn = st.button("🚀 Generate Video", type="primary", use_container_width=True)

with col2:
    st.subheader("Result")
    # Placeholders
    video_container = st.empty()
    status_container = st.empty()

# Generation Logic
if generate_btn:
    if not prompt:
        st.error("Please enter a prompt.")
    else:
        status_container.info(f"Generating ({dry_run=})... this may take a minute.")
        
        try:
            if dry_run:
                # Mock simulation
                import time
                progress_bar = st.progress(0)
                for i in range(100):
                    time.sleep(0.02)
                    progress_bar.progress(i + 1)
                
                # Mock result
                result = {
                    "url": "https://www.w3schools.com/html/mov_bbb.mp4", # Dummy video
                    "model": selected_model_key,
                    "duration": duration,
                    "cost": 0.00,
                    "prompt": prompt,
                    "mock": True
                }
                status_container.success(f"Dry Run Complete! (Saved ${estimated_cost:.2f})")
            
            else:
                # Real API Call
                with st.spinner("Talking to OpenAI..."):
                    # Async wrapper for Streamlit
                    async def run_gen():
                        return await service.generate_video(
                            prompt=prompt,
                            model=selected_model_key,
                            duration_seconds=duration
                        )
                    
                    result = asyncio.run(run_gen())
                status_container.success(f"Generation Complete! Cost: ${result['cost']:.2f}")

            # Display Result
            if result.get("url"):
                video_container.video(result["url"])
                
                with st.expander("Raw API Response", expanded=False):
                    st.json(result)
                    
        except Exception as e:
            status_container.error(f"Generation Failed: {str(e)}")
