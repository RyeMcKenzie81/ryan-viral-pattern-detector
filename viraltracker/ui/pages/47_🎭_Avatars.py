"""
Avatars - Brand Avatar Management with Kling Element Creation.

This page allows users to:
- Create and manage brand avatars with 4-angle reference images
- Generate angle-specific images using Gemini (frontal, 3/4, side, full body)
- Create Kling elements for character consistency in video generation
- Generate videos using Google Veo 3.1 with character consistency
- View and manage generated videos
"""

import streamlit as st
import asyncio
from uuid import UUID

# Page config (must be first Streamlit call)
st.set_page_config(
    page_title="Avatars",
    page_icon="🎭",
    layout="wide"
)

# Authentication
from viraltracker.ui.auth import require_auth
require_auth()
from viraltracker.ui.utils import require_feature
require_feature("veo_avatars", "Veo Avatars")

# Initialize session state
if 'selected_avatar_id' not in st.session_state:
    st.session_state.selected_avatar_id = None
if 'generating_video' not in st.session_state:
    st.session_state.generating_video = False
if 'generation_result' not in st.session_state:
    st.session_state.generation_result = None
if 'angle_gen_progress' not in st.session_state:
    st.session_state.angle_gen_progress = None

# Angle labels for display
ANGLE_LABELS = {1: "Frontal", 2: "3/4 View", 3: "Side Profile", 4: "Full Body"}


# ============================================================================
# Helper Functions
# ============================================================================

def get_supabase_client():
    """Get Supabase client."""
    from viraltracker.core.database import get_supabase_client
    return get_supabase_client()

def get_avatar_service():
    """Create fresh AvatarService instance with usage tracking."""
    from viraltracker.services.avatar_service import AvatarService
    from viraltracker.services.usage_tracker import UsageTracker
    from viraltracker.ui.auth import get_current_user_id
    from viraltracker.ui.utils import get_current_organization_id

    service = AvatarService()

    # Set up usage tracking if org context available
    org_id = get_current_organization_id()
    if org_id and org_id != "all":
        tracker = UsageTracker(get_supabase_client())
        service.set_tracking_context(tracker, get_current_user_id(), org_id)

    return service

def get_veo_service():
    """Create fresh VeoService instance with usage tracking."""
    from viraltracker.services.veo_service import VeoService
    from viraltracker.services.usage_tracker import UsageTracker
    from viraltracker.ui.auth import get_current_user_id
    from viraltracker.ui.utils import get_current_organization_id

    service = VeoService()

    # Set up usage tracking if org context available
    org_id = get_current_organization_id()
    if org_id and org_id != "all":
        tracker = UsageTracker(get_supabase_client())
        service.set_tracking_context(tracker, get_current_user_id(), org_id)

    return service

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
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()

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
# Avatar Management Section (Rewritten for 4-angle workflow)
# ============================================================================

def render_avatar_management(brand_id: str):
    """Render avatar management section with 4-angle generation workflow."""
    st.subheader("Brand Avatars")
    st.caption(
        "Create avatars with 4 reference angles for Kling element creation: "
        "Frontal, 3/4 View, Side Profile, and Full Body."
    )

    # Fetch avatars
    async def fetch_avatars():
        service = get_avatar_service()
        return await service.list_avatars(brand_id=UUID(brand_id))

    avatars = run_async(fetch_avatars())

    # Create new avatar form
    with st.expander("Create New Avatar", expanded=not avatars):
        with st.form("create_avatar_form"):
            name = st.text_input("Avatar Name", placeholder="e.g., Sarah - Brand Ambassador")
            description = st.text_area(
                "Description",
                placeholder="Friendly, professional woman in her 30s...",
                height=100
            )
            generation_prompt = st.text_area(
                "Generation Prompt (for AI image creation)",
                placeholder="Professional woman, 30s, friendly smile, business casual, brown hair...",
                height=100,
                help="Describe the character's appearance. This will be combined with angle-specific prompts."
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

            submitted = st.form_submit_button("Create Avatar")

            if submitted and name:
                async def create_avatar():
                    from viraltracker.services.veo_models import BrandAvatarCreate, AspectRatio, Resolution

                    service = get_avatar_service()
                    data = BrandAvatarCreate(
                        brand_id=UUID(brand_id),
                        name=name,
                        description=description if description else None,
                        generation_prompt=generation_prompt if generation_prompt else None,
                        default_aspect_ratio=AspectRatio(aspect_ratio),
                        default_resolution=Resolution(resolution)
                    )
                    return await service.create_avatar(data)

                with st.spinner("Creating avatar..."):
                    avatar = run_async(create_avatar())
                    st.success(f"Created avatar: {avatar.name}")
                    st.rerun()

    # Display existing avatars
    if avatars:
        for avatar in avatars:
            render_avatar_card(avatar, brand_id)
    else:
        st.info("No avatars created yet. Create one above!")


def render_avatar_card(avatar, brand_id: str):
    """Render a single avatar card with 4-angle grid."""
    # Build header with status indicators
    ref_count = avatar.reference_image_count
    element_status = "Element Ready" if avatar.kling_element_id else ""
    header = f"{avatar.name} ({ref_count}/4 angles"
    if element_status:
        header += f", {element_status}"
    header += ")"

    with st.expander(header, expanded=st.session_state.selected_avatar_id == str(avatar.id)):
        # Avatar info row
        col_info, col_actions = st.columns([3, 1])
        with col_info:
            st.markdown(f"**Description:** {avatar.description or 'No description'}")
            if avatar.generation_prompt:
                st.markdown(f"**Generation Prompt:** {avatar.generation_prompt[:200]}{'...' if len(avatar.generation_prompt or '') > 200 else ''}")
            st.markdown(f"**Default Settings:** {avatar.default_aspect_ratio.value} / {avatar.default_resolution.value} / {avatar.default_duration_seconds}s")

        with col_actions:
            if st.button("Select for Video", key=f"select_{avatar.id}"):
                st.session_state.selected_avatar_id = str(avatar.id)
                st.rerun()

            if st.button("Delete Avatar", key=f"delete_{avatar.id}", type="secondary"):
                async def delete():
                    service = get_avatar_service()
                    return await service.delete_avatar(avatar.id)

                if run_async(delete()):
                    st.success("Avatar deleted")
                    st.rerun()

        st.divider()

        # ---- 4-Angle Reference Image Grid ----
        st.markdown("**Reference Angles**")

        cols = st.columns(4)
        for slot in range(1, 5):
            label = ANGLE_LABELS[slot]
            ref_path = getattr(avatar, f"reference_image_{slot}")

            with cols[slot - 1]:
                st.markdown(f"**{label}**")

                if ref_path:
                    url = get_signed_url(ref_path)
                    if url:
                        st.image(url, use_container_width=True)

                    # Remove button
                    if st.button("Remove", key=f"remove_{avatar.id}_{slot}"):
                        async def remove_ref(s=slot):
                            service = get_avatar_service()
                            return await service.remove_reference_image(avatar.id, s)
                        run_async(remove_ref())
                        st.rerun()
                else:
                    st.markdown("*No image*")

                # Upload button (always available)
                uploaded = st.file_uploader(
                    f"Upload {label}",
                    type=["png", "jpg", "jpeg", "webp"],
                    key=f"upload_{avatar.id}_{slot}",
                    label_visibility="collapsed",
                )
                if uploaded:
                    async def upload_ref(s=slot, f=uploaded):
                        service = get_avatar_service()
                        return await service.add_reference_image(avatar.id, f.read(), s)
                    with st.spinner("Uploading..."):
                        run_async(upload_ref())
                        st.rerun()

                # Generate button (disabled if prior slot empty for sequential consistency)
                if avatar.generation_prompt:
                    # For slot 1: always available. For slots 2-4: need slot 1 at minimum.
                    can_generate = (slot == 1) or (avatar.reference_image_1 is not None)
                    if st.button(
                        f"Generate",
                        key=f"gen_{avatar.id}_{slot}",
                        disabled=not can_generate,
                        use_container_width=True,
                    ):
                        async def gen_angle(s=slot):
                            service = get_avatar_service()
                            return await service.generate_angle_image(avatar.id, s)

                        with st.spinner(f"Generating {label}..."):
                            try:
                                path = run_async(gen_angle())
                                if path:
                                    st.success(f"Generated {label}!")
                                    st.rerun()
                                else:
                                    st.warning(f"Generation skipped (safety filter). Try adjusting the prompt.")
                            except Exception as e:
                                st.error(f"Error: {e}")

        # ---- Generate All Missing Angles Button ----
        if avatar.generation_prompt:
            missing_slots = [
                s for s in range(1, 5)
                if getattr(avatar, f"reference_image_{s}") is None
            ]

            if missing_slots:
                st.divider()
                if st.button(
                    f"Generate All Missing Angles ({len(missing_slots)} remaining)",
                    key=f"gen_all_{avatar.id}",
                    type="primary",
                    use_container_width=True,
                ):
                    progress_text = st.empty()
                    progress_bar = st.progress(0)
                    generated = 0
                    skipped = 0

                    for i, slot in enumerate(missing_slots):
                        label = ANGLE_LABELS[slot]
                        progress_text.markdown(f"Generating **{label}** ({i+1}/{len(missing_slots)})...")
                        progress_bar.progress((i) / len(missing_slots))

                        async def gen_one(s=slot):
                            service = get_avatar_service()
                            return await service.generate_angle_image(avatar.id, s)

                        try:
                            path = run_async(gen_one())
                            if path:
                                generated += 1
                            else:
                                skipped += 1
                                st.warning(f"Skipped {label} (safety filter)")
                        except Exception as e:
                            skipped += 1
                            st.warning(f"Failed {label}: {e}")

                    progress_bar.progress(1.0)
                    progress_text.markdown(f"Done! Generated {generated}, skipped {skipped}.")
                    st.rerun()

        # ---- Visual Verification Strip ----
        all_filled = all(
            getattr(avatar, f"reference_image_{s}") is not None
            for s in range(1, 5)
        )
        if all_filled:
            st.divider()
            st.markdown("**Visual Verification** — Review consistency before creating element:")
            verify_cols = st.columns(4)
            for slot in range(1, 5):
                ref_path = getattr(avatar, f"reference_image_{slot}")
                with verify_cols[slot - 1]:
                    url = get_signed_url(ref_path)
                    if url:
                        st.image(url, use_container_width=True)
                    st.caption(ANGLE_LABELS[slot])

        # ---- Kling Element Section ----
        st.divider()
        st.markdown("**Kling Element**")

        if avatar.kling_element_id:
            st.success(f"Element ID: `{avatar.kling_element_id}`")
        else:
            has_frontal = avatar.reference_image_1 is not None
            if not has_frontal:
                st.info("Upload or generate a frontal image (slot 1) to enable element creation.")
            else:
                if ref_count < 4:
                    st.warning(f"Only {ref_count}/4 angles filled. Recommend all 4 for best results.")
                st.caption("Review the images above for consistency before creating the element.")

                if st.button("Create Kling Element", key=f"create_element_{avatar.id}", type="primary"):
                    from viraltracker.ui.utils import get_current_organization_id
                    org_id = get_current_organization_id()

                    with st.spinner("Creating Kling element (may take 1-2 minutes)..."):
                        try:
                            async def create_el():
                                service = get_avatar_service()
                                return await service.create_kling_element(
                                    avatar_id=avatar.id,
                                    organization_id=org_id,
                                    brand_id=brand_id,
                                )

                            element_id = run_async(create_el())
                            if element_id:
                                st.success(f"Element created: `{element_id}`")
                                st.rerun()
                            else:
                                st.error("Element creation failed. Check logs for details.")
                        except Exception as e:
                            st.error(f"Element creation failed: {e}")


# ============================================================================
# Video Generation Section (unchanged)
# ============================================================================

def get_offer_variants(product_id: str):
    """Fetch offer variants for a product."""
    try:
        db = get_supabase_client()
        result = db.table("product_offer_variants").select("*").eq(
            "product_id", product_id
        ).order("name").execute()
        return result.data or []
    except Exception:
        return []

def get_offer_variant_images(offer_variant_id: str):
    """Get images associated with an offer variant via junction table."""
    try:
        db = get_supabase_client()
        result = db.table("offer_variant_images").select(
            "*, product_images(*)"
        ).eq("offer_variant_id", offer_variant_id).order("display_order").execute()
        images = []
        for record in result.data or []:
            if record.get("product_images"):
                images.append(record["product_images"])
        return images
    except Exception:
        return []

def render_video_generation(brand_id: str):
    """Render video generation section."""
    st.subheader("Generate Video with Veo 3.1")

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
        st.warning("Select an avatar from the Avatar Manager tab, or generate a video without avatar reference")

    # =========================================================================
    # Product & Image Selection (OUTSIDE form for dynamic updates)
    # =========================================================================
    st.markdown("### Optional: Product Reference Image")

    products = get_products_for_brand(brand_id)
    product_options = {"None": None}
    product_options.update({p["name"]: p["id"] for p in products})

    col1, col2 = st.columns(2)
    with col1:
        selected_product_name = st.selectbox(
            "Select Product",
            options=list(product_options.keys()),
            key="veo_product_select",
            help="Select a product to choose an image from"
        )
    selected_product_id = product_options[selected_product_name]

    # Show offer variants if product selected
    selected_variant_id = None
    if selected_product_id:
        variants = get_offer_variants(selected_product_id)
        if variants:
            with col2:
                variant_options = {"All images": None}
                variant_options.update({v["name"]: v["id"] for v in variants})
                selected_variant_name = st.selectbox(
                    "Filter by Offer Variant",
                    options=list(variant_options.keys()),
                    key="veo_variant_select",
                    help="Filter images to show only those from a specific offer variant"
                )
                selected_variant_id = variant_options[selected_variant_name]

    # Show images for selected product (filtered by variant if selected)
    selected_image_path = None
    if selected_product_id:
        if selected_variant_id:
            product_images = get_offer_variant_images(selected_variant_id)
        else:
            product_images = get_product_images(selected_product_id)

        if product_images:
            st.markdown(f"**Select an image to use as reference:** ({len(product_images)} images)")

            cols = st.columns(4)
            for i, img in enumerate(product_images):
                storage_path = img.get('storage_path', '')
                is_main = img.get('is_main', False)
                notes = img.get('notes', '')

                with cols[i % 4]:
                    url = get_signed_url(storage_path)
                    if url:
                        st.image(url, width=150)

                        label = "Main" if is_main else f"Image {i+1}"
                        if notes:
                            label += f" ({notes[:20]}...)" if len(notes) > 20 else f" ({notes})"

                        if st.button(
                            f"Select: {label}",
                            key=f"select_img_{img['id']}",
                            use_container_width=True
                        ):
                            st.session_state.selected_product_image_path = storage_path
                            st.rerun()

            if st.session_state.get('selected_product_image_path'):
                st.info(f"Selected: {st.session_state.selected_product_image_path.split('/')[-1]}")
                selected_image_path = st.session_state.selected_product_image_path

                if st.button("Clear Selection"):
                    st.session_state.selected_product_image_path = None
                    st.rerun()
        else:
            st.info("No images found for this product")

    st.markdown("---")

    # =========================================================================
    # Video Generation Form
    # =========================================================================
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

        st.markdown("### Product Settings")
        col1, col2 = st.columns(2)
        with col1:
            product_dimensions = st.text_input(
                "Product Dimensions (optional)",
                placeholder="e.g., 8-inch tall bottle, 3 inches wide",
                help="Helps AI maintain consistent product size and prevent morphing"
            )
        with col2:
            strict_product_mode = st.checkbox(
                "Strict Product Mode",
                value=True,
                help="Adds extra prompts to preserve product packaging, text, and labels"
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
            rate = 0.40 if model_variant == "standard" else 0.15
            estimated_cost = duration * rate
            st.metric("Estimated Cost", f"${estimated_cost:.2f}")

        negative_prompt = st.text_input(
            "Negative Prompt (optional)",
            value="",
            help="Content to avoid in generation. Leave empty if not supported by your API."
        )

        submitted = st.form_submit_button("Generate Video", type="primary")

        if submitted and prompt:
            st.session_state.generating_video = True

            async def generate():
                from viraltracker.services.veo_models import (
                    VeoGenerationRequest, VeoConfig, AspectRatio, Resolution, ModelVariant
                )

                service = get_veo_service()

                ref_images = []

                if selected_avatar:
                    avatar_service = get_avatar_service()
                    avatar_refs = await avatar_service.get_all_reference_images(selected_avatar.id)
                    ref_images.extend(avatar_refs)

                if selected_image_path:
                    img_bytes = download_image_from_storage(selected_image_path)
                    if img_bytes and len(ref_images) < 3:
                        ref_images.append(img_bytes)

                enhanced_prompt = prompt

                if product_dimensions:
                    enhanced_prompt += f" The product is {product_dimensions}."

                if strict_product_mode and selected_image_path:
                    enhanced_prompt += " IMPORTANT: Maintain exact product appearance as shown in reference image. Do not alter, modify, or regenerate any text, labels, or logos on the product packaging. Keep product proportions and colors exactly as shown."

                request = VeoGenerationRequest(
                    brand_id=UUID(brand_id),
                    avatar_id=selected_avatar.id if selected_avatar else None,
                    product_id=UUID(selected_product_id) if selected_product_id else None,
                    prompt=enhanced_prompt,
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

            with st.spinner("Generating video with Veo 3.1... This may take 1-6 minutes."):
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
        st.subheader("Generated Video")

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

            if st.button("Download Video"):
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

        if st.button("Clear Result"):
            st.session_state.generation_result = None
            st.rerun()

# ============================================================================
# Video History Section (unchanged)
# ============================================================================

def render_video_history(brand_id: str):
    """Render video generation history."""
    st.subheader("Generation History")

    async def fetch_history():
        service = get_veo_service()
        return await service.list_generations(brand_id=UUID(brand_id), limit=20)

    generations = run_async(fetch_history())

    if not generations:
        st.info("No videos generated yet")
        return

    for gen in generations:
        status_emoji = "+" if gen.status.value == "completed" else "x" if gen.status.value == "failed" else "..."

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

                if st.button("Delete", key=f"del_gen_{gen.id}"):
                    async def delete():
                        service = get_veo_service()
                        return await service.delete_generation(gen.id)

                    if run_async(delete()):
                        st.success("Deleted")
                        st.rerun()

# ============================================================================
# Main Page
# ============================================================================

st.title("Avatars")
st.markdown("""
Manage brand avatars with guided 4-angle reference images for consistent character generation.
- **Frontal** — Primary identity anchor for Kling elements
- **3/4 View** — Bridges frontal and side angles
- **Side Profile** — Jawline, ear, and hair details
- **Full Body** — Complete outfit and proportions
""")

# Brand selector
from viraltracker.ui.utils import render_brand_selector
brand_id = render_brand_selector(key="veo_avatars_brand_selector")
if not brand_id:
    st.stop()

# Tabs for different sections
tab1, tab2, tab3 = st.tabs(["Avatar Manager", "Veo Video", "History"])

with tab1:
    render_avatar_management(brand_id)

with tab2:
    render_video_generation(brand_id)

with tab3:
    render_video_history(brand_id)
