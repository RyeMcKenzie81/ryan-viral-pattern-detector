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

        # Aspect Ratio / Size
        # Strict API limits: '720x1280', '1280x720', '1024x1792', '1792x1024'
        resolution_options = {
            "1280x720": "Landscape (1280x720) 16:9",
            "1792x1024": "Wide Landscape (1792x1024) ~1.75:1",
            "720x1280": "Portrait (720x1280) 9:16",
            "1024x1792": "Tall Portrait (1024x1792) ~1:1.75"
        }
        selected_res = st.selectbox(
            "Video Format",
            options=list(resolution_options.keys()),
            format_func=lambda x: resolution_options[x],
            index=0
        )
    
    with col_conf2:
        # Duration - Sora 2 only supports 4, 8, 12 seconds
        duration = st.select_slider("Duration (seconds)", options=[4, 8, 12], value=4)
        
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
    
    # Reference Image Source
    ref_source = st.radio("Reference Image Source", ["Upload File", "Database Asset"], horizontal=True)
    
    ref_img_data = None
    ref_img_mime = "image/jpeg"
    
    if ref_source == "Upload File":
        uploaded_file = st.file_uploader("Reference Image (Optional)", type=['jpg', 'png', 'webp'])
        if uploaded_file:
            ref_img_data = uploaded_file.getvalue()
            ref_img_mime = uploaded_file.type
            st.image(uploaded_file, caption="Preview", width=200)
            
    else: # Database Asset
        from viraltracker.core.database import get_supabase_client
        supabase = get_supabase_client()
        
        # 1. Fetch Brands
        try:
            brands_resp = supabase.table("brands").select("id, name").order("name").execute()
            brands = brands_resp.data or []
            brand_map = {b["name"]: b["id"] for b in brands}
            
            selected_brand_name = st.selectbox("Select Brand", options=list(brand_map.keys()))
            
            if selected_brand_name:
                brand_id = brand_map[selected_brand_name]
                
                # 2. Fetch Products
                products_resp = supabase.table("products").select("id, name").eq("brand_id", brand_id).execute()
                products = products_resp.data or []
                product_map = {p["name"]: p for p in products}
                
                selected_product_name = st.selectbox("Select Product", options=list(product_map.keys()))
                
                if selected_product_name:
                    product = product_map[selected_product_name]
                        except Exception as e:
                            st.error(f"Failed to load preview: {e}")
                    else:
                        st.warning("No main image set for this product.")
                        
        except Exception as e:
            st.error(f"Database Error: {e}")

    
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
        
        # Fetch DB image bytes if needed
        if ref_source == "Database Asset" and db_storage_path:
             try:
                 from viraltracker.core.database import get_supabase_client
                 supabase = get_supabase_client()
                 
                 if "/" in db_storage_path:
                     bucket, path = db_storage_path.split("/", 1)
                 else:
                     bucket = "products" 
                     path = db_storage_path
                     
                 ref_img_data = supabase.storage.from_(bucket).download(path)
                 
                 # Simple mime detection
                 if path.lower().endswith(".png"):
                     ref_img_mime = "image/png"
                 elif path.lower().endswith(".webp"):
                     ref_img_mime = "image/webp"
                 else:
                     ref_img_mime = "image/jpeg"
             except Exception as e:
                 status_container.error(f"Failed to download asset: {e}")
                 st.stop()

        try:
            import time # Import time for dry run simulation
            if dry_run:
                # Mock simulation
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
                            duration_seconds=duration,
                            resolution=selected_res,
                            reference_image_data=ref_img_data,
                            reference_image_mime=ref_img_mime
                        )
                    
                    result = asyncio.run(run_gen())
                status_container.success(f"Generation Complete! Cost: ${result['cost']:.2f}")

            # Display Result
            if result.get("video_data"):
                # Display binary video
                video_container.video(result["video_data"], format="video/mp4")
            elif result.get("url"):
                # Fallback URL (e.g. for dry run)
                video_container.video(result["url"])
                
            with st.expander("Raw API Response", expanded=False):
                st.json(result.get("raw_response") or result)
                    
        except Exception as e:
            status_container.error(f"Generation Failed: {str(e)}")
