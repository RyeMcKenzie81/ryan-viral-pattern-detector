"""
Veo Avatars - AI Video Generation with Brand Avatars.

This page allows users to:
- Create and manage brand avatars with reference images
- Generate avatar images using Gemini (Nano Banana pattern)
- Generate videos using Google Veo 3.1 with character consistency
- View and manage generated videos
"""

import streamlit as st
import asyncio
from datetime import datetime
from uuid import UUID
import base64

# Apply nest_asyncio for Streamlit compatibility
import nest_asyncio
nest_asyncio.apply()

# Page config (must be first Streamlit call)
st.set_page_config(
    page_title="Veo Avatars",
    page_icon="🎬",
    layout="wide"
)

# Authentication
from viraltracker.ui.auth import require_auth
require_auth()

# Initialize session state
if 'selected_avatar_id' not in st.session_state:
    st.session_state.selected_avatar_id = None
if 'generating_video' not in st.session_state:
    st.session_state.generating_video = False
if 'generation_result' not in st.session_state:
    st.session_state.generation_result = None


# ============================================================================
# Helper Functions
# ============================================================================

def get_supabase_client():
    """Get Supabase client."""
    from viraltracker.core.database import get_supabase_client
    return get_supabase_client()


def get_avatar_service():
    """Create fresh AvatarService instance."""
    from viraltracker.services.avatar_service import AvatarService
    return AvatarService()


def get_veo_service():
    """Create fresh VeoService instance."""
    from viraltracker.services.veo_service import VeoService
    return VeoService()


def get_product_images(product_id: str):
    """Fetch product images."""
    try:
        db = get_supabase_client()
        result = db.table("product_images").select("*").eq(
            "product_id", product_id
        ).execute()
        return result.data or []
    except Exception as e:
        st.error(f"Failed to fetch product images: {e}")
        return []


def get_products_for_brand(brand_id: str):
    """Fetch products for a brand."""
    try:
        db = get_supabase_client()
        result = db.table("products").select("id, name").eq(
            "brand_id", brand_id
        ).order("name").execute()
        return result.data or []
    except Exception as e:
        st.error(f"Failed to fetch products: {e}")
        return []


def run_async(coro):
    """Run async coroutine in Streamlit."""
    return asyncio.get_event_loop().run_until_complete(coro)


def download_image_from_storage(storage_path: str) -> bytes:
    """Download image from Supabase storage."""
    try:
        db = get_supabase_client()
        parts = storage_path.split("/", 1)
        bucket = parts[0]
        path = parts[1] if len(parts) > 1 else storage_path
        return db.storage.from_(bucket).download(path)
    except Exception as e:
        st.error(f"Failed to download image: {e}")
        return None


def get_signed_url(storage_path: str, expires_in: int = 3600) -> str:
    """Get signed URL for storage path."""
    try:
        db = get_supabase_client()
        parts = storage_path.split("/", 1)
        bucket = parts[0]
        path = parts[1] if len(parts) > 1 else storage_path
        result = db.storage.from_(bucket).create_signed_url(path, expires_in)
        return result.get("signedURL", "")
    except Exception:
        return ""


# ============================================================================
# Avatar Management Section
# ============================================================================

def render_avatar_management(brand_id: str):
    """Render avatar management section."""
    st.subheader("🎭 Brand Avatars")

    # Fetch avatars
    async def fetch_avatars():
        service = get_avatar_service()
        return await service.list_avatars(brand_id=UUID(brand_id))

    avatars = run_async(fetch_avatars())

    # Create new avatar form
    with st.expander("➕ Create New Avatar", expanded=not avatars):
        with st.form("create_avatar_form"):
            name = st.text_input("Avatar Name", placeholder="e.g., Sarah - Brand Ambassador")
            description = st.text_area(
                "Description",
                placeholder="Friendly, professional woman in her 30s...",
                height=100
            )
            generation_prompt = st.text_area(
                "Generation Prompt (for AI image creation)",
                placeholder="Professional woman, 30s, friendly smile, business casual...",
                height=100,
                help="This prompt will be used to generate avatar images via Gemini"
            )

            col1, col2 = st.columns(2)
            with col1:
                aspect_ratio = st.selectbox(
                    "Default Aspect Ratio",
                    options=["16:9", "9:16"],
                    help="16:9 for landscape, 9:16 for portrait videos"
                )
            with col2:
                resolution = st.selectbox(
                    "Default Resolution",
                    options=["720p", "1080p", "4k"],
                    index=1
                )

            # Reference images upload
            st.markdown("**Reference Images (up to 3)**")
            uploaded_files = st.file_uploader(
                "Upload reference images",
                type=["png", "jpg", "jpeg", "webp"],
                accept_multiple_files=True,
                help="Upload 1-3 reference images for character consistency"
            )

            submitted = st.form_submit_button("Create Avatar")

            if submitted and name:
                async def create_avatar():
                    from viraltracker.services.avatar_service import AvatarService
                    from viraltracker.services.veo_models import BrandAvatarCreate, AspectRatio, Resolution

                    service = AvatarService()
                    ref_images = [f.read() for f in uploaded_files[:3]] if uploaded_files else None

                    data = BrandAvatarCreate(
                        brand_id=UUID(brand_id),
                        name=name,
                        description=description if description else None,
                        generation_prompt=generation_prompt if generation_prompt else None,
                        default_aspect_ratio=AspectRatio(aspect_ratio),
                        default_resolution=Resolution(resolution)
                    )
                    return await service.create_avatar(data, reference_images=ref_images)

                with st.spinner("Creating avatar..."):
                    avatar = run_async(create_avatar())
                    st.success(f"Created avatar: {avatar.name}")
                    st.rerun()

    # Display existing avatars
    if avatars:
        st.markdown("**Existing Avatars:**")
        for avatar in avatars:
            render_avatar_card(avatar, brand_id)
    else:
        st.info("No avatars created yet. Create one above!")


def render_avatar_card(avatar, brand_id: str):
    """Render a single avatar card."""
    with st.expander(f"🎭 {avatar.name}", expanded=st.session_state.selected_avatar_id == str(avatar.id)):
        col1, col2 = st.columns([1, 2])

        with col1:
            # Display reference images
            ref_images = avatar.reference_images
            if ref_images:
                st.markdown("**Reference Images:**")
                for i, path in enumerate(ref_images, 1):
                    url = get_signed_url(path)
                    if url:
                        st.image(url, caption=f"Ref {i}", width=150)
            else:
                st.info("No reference images")

            # Upload new reference image
            new_ref = st.file_uploader(
                "Add reference image",
                type=["png", "jpg", "jpeg"],
                key=f"upload_{avatar.id}"
            )
            if new_ref:
                slot = len(ref_images) + 1
                if slot <= 3:
                    async def add_ref():
                        service = get_avatar_service()
                        return await service.add_reference_image(
                            avatar.id, new_ref.read(), slot
                        )
                    with st.spinner("Uploading..."):
                        run_async(add_ref())
                        st.success("Reference image added!")
                        st.rerun()
                else:
                    st.warning("Maximum 3 reference images")

        with col2:
            st.markdown(f"**Description:** {avatar.description or 'No description'}")
            st.markdown(f"**Generation Prompt:** {avatar.generation_prompt or 'Not set'}")
            st.markdown(f"**Default Settings:** {avatar.default_aspect_ratio.value} / {avatar.default_resolution.value} / {avatar.default_duration_seconds}s")

            # Generate new reference image button
            if avatar.generation_prompt:
                if st.button("🎨 Generate New Reference Image", key=f"gen_ref_{avatar.id}"):
                    async def gen_image():
                        service = get_avatar_service()
                        slot = len(avatar.reference_images) + 1
                        if slot > 3:
                            slot = 3  # Replace last image
                        return await service.generate_and_save_avatar_image(
                            avatar.id,
                            avatar.generation_prompt,
                            slot=slot
                        )

                    with st.spinner("Generating image with Gemini..."):
                        try:
                            path = run_async(gen_image())
                            if path:
                                st.success("Generated new reference image!")
                                st.rerun()
                            else:
                                st.error("Failed to generate image")
                        except Exception as e:
                            st.error(f"Error: {e}")

            # Select avatar for video generation
            if st.button("✅ Select for Video", key=f"select_{avatar.id}"):
                st.session_state.selected_avatar_id = str(avatar.id)
                st.rerun()

            # Delete avatar
            if st.button("🗑️ Delete Avatar", key=f"delete_{avatar.id}", type="secondary"):
                async def delete():
                    service = get_avatar_service()
                    return await service.delete_avatar(avatar.id)

                if run_async(delete()):
                    st.success("Avatar deleted")
                    st.rerun()


# ============================================================================
# Video Generation Section
# ============================================================================

def render_video_generation(brand_id: str):
    """Render video generation section."""
    st.subheader("🎬 Generate Video with Veo 3.1")

    # Get selected avatar
    selected_avatar = None
    if st.session_state.selected_avatar_id:
        async def get_avatar():
            service = get_avatar_service()
            return await service.get_avatar(UUID(st.session_state.selected_avatar_id))
        selected_avatar = run_async(get_avatar())

    if selected_avatar:
        st.success(f"**Selected Avatar:** {selected_avatar.name}")
    else:
        st.warning("Select an avatar above, or generate a video without avatar reference")

    # Video generation form
    with st.form("generate_video_form"):
        st.markdown("### Video Prompt")

        prompt = st.text_area(
            "Main Prompt",
            placeholder="A professional woman in business attire presenting a product...",
            height=100,
            help="Describe the main subject and scene"
        )

        col1, col2 = st.columns(2)
        with col1:
            action_description = st.text_input(
                "Action",
                placeholder="holds up product and smiles at camera",
                help="What should the subject do?"
            )
        with col2:
            background_description = st.text_input(
                "Background",
                placeholder="clean white studio with soft lighting",
                help="Describe the background/setting"
            )

        dialogue = st.text_area(
            "Dialogue (Veo 3.1 generates audio)",
            placeholder="This amazing product will change your life!",
            height=80,
            help="What should the subject say? Veo 3.1 generates synchronized audio"
        )

        st.markdown("### Video Settings")
        col1, col2, col3 = st.columns(3)
        with col1:
            aspect_ratio = st.selectbox(
                "Aspect Ratio",
                options=["16:9", "9:16"],
                index=0 if not selected_avatar else (
                    0 if selected_avatar.default_aspect_ratio.value == "16:9" else 1
                )
            )
        with col2:
            resolution = st.selectbox(
                "Resolution",
                options=["720p", "1080p", "4k"],
                index=1,
                help="Note: 1080p and 4k require 8s duration"
            )
        with col3:
            duration = st.selectbox(
                "Duration",
                options=[4, 6, 8],
                index=2,
                help="1080p/4k and reference images require 8s"
            )

        col1, col2 = st.columns(2)
        with col1:
            model_variant = st.selectbox(
                "Model Variant",
                options=["standard", "fast"],
                help="Standard: $0.40/sec (higher quality), Fast: $0.15/sec"
            )
        with col2:
            # Calculate estimated cost
            rate = 0.40 if model_variant == "standard" else 0.15
            estimated_cost = duration * rate
            st.metric("Estimated Cost", f"${estimated_cost:.2f}")

        negative_prompt = st.text_input(
            "Negative Prompt",
            value="blurry, low quality, distorted, deformed, ugly, bad anatomy",
            help="Content to avoid in generation"
        )

        # Optional: Include product image
        st.markdown("### Optional: Product Reference")
        products = get_products_for_brand(brand_id)
        product_options = {"None": None}
        product_options.update({p["name"]: p["id"] for p in products})
        selected_product_name = st.selectbox(
            "Include Product Image",
            options=list(product_options.keys()),
            help="Select a product to include its image as reference"
        )
        selected_product_id = product_options[selected_product_name]

        submitted = st.form_submit_button("🚀 Generate Video", type="primary")

        if submitted and prompt:
            st.session_state.generating_video = True

            async def generate():
                from viraltracker.services.veo_service import VeoService
                from viraltracker.services.veo_models import (
                    VeoGenerationRequest, VeoConfig, AspectRatio, Resolution, ModelVariant
                )

                service = VeoService()

                # Collect reference images
                ref_images = []

                # Add avatar reference images
                if selected_avatar:
                    avatar_service = get_avatar_service()
                    avatar_refs = await avatar_service.get_all_reference_images(selected_avatar.id)
                    ref_images.extend(avatar_refs)

                # Add product image if selected
                if selected_product_id:
                    product_images = get_product_images(selected_product_id)
                    if product_images:
                        # Use main image or first image
                        main_img = next(
                            (img for img in product_images if img.get('is_main')),
                            product_images[0] if product_images else None
                        )
                        if main_img and main_img.get('storage_path'):
                            img_bytes = download_image_from_storage(main_img['storage_path'])
                            if img_bytes and len(ref_images) < 3:
                                ref_images.append(img_bytes)

                # Build request
                request = VeoGenerationRequest(
                    brand_id=UUID(brand_id),
                    avatar_id=selected_avatar.id if selected_avatar else None,
                    product_id=UUID(selected_product_id) if selected_product_id else None,
                    prompt=prompt,
                    action_description=action_description if action_description else None,
                    dialogue=dialogue if dialogue else None,
                    background_description=background_description if background_description else None,
                    config=VeoConfig(
                        aspect_ratio=AspectRatio(aspect_ratio),
                        resolution=Resolution(resolution),
                        duration_seconds=duration,
                        negative_prompt=negative_prompt,
                        model_variant=ModelVariant(model_variant)
                    )
                )

                return await service.generate_video(
                    request,
                    reference_image_bytes=ref_images if ref_images else None
                )

            with st.spinner("🎬 Generating video with Veo 3.1... This may take 1-6 minutes."):
                try:
                    result = run_async(generate())
                    st.session_state.generation_result = result
                    st.session_state.generating_video = False

                    if result.is_success:
                        st.success(f"Video generated successfully! Cost: ${result.estimated_cost_usd:.2f}")
                        st.balloons()
                    else:
                        st.error(f"Generation failed: {result.error_message}")

                    st.rerun()
                except Exception as e:
                    st.session_state.generating_video = False
                    st.error(f"Error: {e}")

    # Display generation result
    if st.session_state.generation_result:
        result = st.session_state.generation_result
        st.markdown("---")
        st.subheader("📹 Generated Video")

        if result.is_success and result.video_storage_path:
            video_url = get_signed_url(result.video_storage_path)
            if video_url:
                st.video(video_url)

            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Generation Time", f"{result.generation_time_seconds:.1f}s")
            with col2:
                st.metric("Cost", f"${result.estimated_cost_usd:.2f}")
            with col3:
                st.metric("Status", result.status.value)

            # Download button
            if st.button("📥 Download Video"):
                video_bytes = download_image_from_storage(result.video_storage_path)
                if video_bytes:
                    st.download_button(
                        "Click to Download",
                        data=video_bytes,
                        file_name=f"veo_video_{result.generation_id}.mp4",
                        mime="video/mp4"
                    )
        else:
            st.error(f"Generation failed: {result.error_message}")

        if st.button("🗑️ Clear Result"):
            st.session_state.generation_result = None
            st.rerun()


# ============================================================================
# Video History Section
# ============================================================================

def render_video_history(brand_id: str):
    """Render video generation history."""
    st.subheader("📜 Generation History")

    async def fetch_history():
        service = get_veo_service()
        return await service.list_generations(brand_id=UUID(brand_id), limit=20)

    generations = run_async(fetch_history())

    if not generations:
        st.info("No videos generated yet")
        return

    for gen in generations:
        status_emoji = "✅" if gen.status.value == "completed" else "❌" if gen.status.value == "failed" else "⏳"

        with st.expander(f"{status_emoji} {gen.created_at.strftime('%Y-%m-%d %H:%M')} - {gen.prompt[:50]}..."):
            col1, col2 = st.columns([2, 1])

            with col1:
                st.markdown(f"**Prompt:** {gen.prompt}")
                if gen.video_storage_path:
                    url = get_signed_url(gen.video_storage_path)
                    if url:
                        st.video(url)

            with col2:
                st.markdown(f"**Status:** {gen.status.value}")
                if gen.estimated_cost_usd:
                    st.markdown(f"**Cost:** ${gen.estimated_cost_usd:.2f}")

                # Delete button
                if st.button("🗑️ Delete", key=f"del_gen_{gen.id}"):
                    async def delete():
                        service = get_veo_service()
                        return await service.delete_generation(gen.id)

                    if run_async(delete()):
                        st.success("Deleted")
                        st.rerun()


# ============================================================================
# Main Page
# ============================================================================

st.title("🎬 Veo Avatars")
st.markdown("""
Generate AI videos with consistent brand avatars using Google Veo 3.1.
- Create avatars with reference images for character consistency
- Generate avatar images using Gemini (Nano Banana)
- Produce professional videos with synchronized dialogue
""")

# Brand selector
from viraltracker.ui.utils import render_brand_selector
brand_id = render_brand_selector(key="veo_avatars_brand_selector")
if not brand_id:
    st.stop()

# Tabs for different sections
tab1, tab2, tab3 = st.tabs(["🎭 Avatars", "🎬 Generate Video", "📜 History"])

with tab1:
    render_avatar_management(brand_id)

with tab2:
    render_video_generation(brand_id)

with tab3:
    render_video_history(brand_id)
