#!/usr/bin/env python3
"""
Test script: Two-scene seamless cut video using Kling Omni + Gemini.

Generates two 8-second video scenes that share a single keyframe image used as
both first_frame and end_frame, locking down the background/environment so it
stays consistent across the cut.

Flow:
  1. Generate ONE "anchor" image via Gemini (avatar in the scene)
  2. Upload to Supabase storage, get signed URL
  3. Scene 1: Omni Video with anchor image as first_frame AND end_frame
  4. Scene 2: Omni Video with anchor image as first_frame AND end_frame
  5. Poll both to completion, download to Supabase storage
  6. Print results for manual review

Flags:
  --reuse-images <run_id>     Reuse anchor image from a previous run
  --video-element <elem_id>   Use a video-based element (for voice consistency test)

Run: python scripts/test_two_scene_video.py
     python scripts/test_two_scene_video.py --video-element 123456789

Requires env vars: KLING_ACCESS_KEY, KLING_SECRET_KEY, GEMINI_API_KEY,
                   SUPABASE_URL, SUPABASE_SERVICE_KEY
"""

import asyncio
import base64
import logging
import os
import sys
import uuid
from datetime import datetime, timezone

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from viraltracker.services.kling_video_service import KlingVideoService
from viraltracker.services.kling_models import KlingEndpoint
from viraltracker.services.gemini_service import GeminiService
from viraltracker.services.avatar_service import AvatarService
from viraltracker.core.database import get_supabase_client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)

# ============================================================================
# Config (hardcoded for this test)
# ============================================================================

AVATAR_ID = "2fb823c6-47a8-4c85-9715-7923ab008a25"
BRAND_ID = "bc8461a8-232d-4765-8775-c75eaafc5503"
ELEMENT_ID = "856253468745531453"

# Scene prompts for Kling Omni
SCENE_1_PROMPT = (
    'The <<<element_1>>> is seated at a white quartz table in a podcast studio, '
    'speaking into a podcast microphone. Camera angle is 3/4 view. Colorful LED '
    'lights and lush green plants fill the background. She speaks passionately '
    'and expressively with her hands: "we romanticize the act of getting a dog. '
    "we think about the cuddles and the fetch but we don't think about the sacrifice.\""
)

SCENE_2_PROMPT = (
    'The <<<element_1>>> continues speaking at the white quartz table in the '
    'podcast studio, same 3/4 camera angle, podcast microphone, colorful LED '
    'lights and plants in background. She speaks with increasing intensity, '
    'gesturing emphatically: "and I\'m not just talking about the money. I\'m '
    "talking about standing in the freezing rain at 6:00am praying they finally "
    'pee so you can go back inside."'
)

# Gemini image generation prompt (single anchor image for all keyframes)
ANCHOR_IMAGE_PROMPT = (
    "Generate a photorealistic image of this person seated at a white quartz "
    "table in a modern podcast studio. Camera angle is 3/4 view. She has a "
    "neutral, attentive expression — mouth closed, hands resting naturally on "
    "the table. A podcast microphone is visible. Colorful LED lights (pink, "
    "purple, blue) and lush green plants fill the background. Warm, "
    "professional lighting. 9:16 portrait aspect ratio."
)

STORAGE_BUCKET = "kling-videos"


# ============================================================================
# Helpers
# ============================================================================

async def resolve_org_id(brand_id: str) -> str:
    """Look up organization_id from brand_id."""
    supabase = get_supabase_client()
    result = await asyncio.to_thread(
        lambda: supabase.table("brands")
        .select("organization_id")
        .eq("id", brand_id)
        .single()
        .execute()
    )
    org_id = result.data["organization_id"]
    logger.info(f"Resolved org_id: {org_id} for brand: {brand_id}")
    return org_id


async def generate_anchor_image(
    avatar_service: AvatarService,
) -> bytes:
    """Generate a single anchor image via Gemini.

    Uses the avatar's existing reference images for character consistency.
    This image is used as both first_frame and end_frame for all scenes
    to lock down the background environment.

    Returns:
        Anchor image bytes.
    """
    avatar_id = uuid.UUID(AVATAR_ID)

    # Get all reference images for the avatar
    logger.info("Downloading avatar reference images...")
    ref_images = await avatar_service.get_all_reference_images(avatar_id)
    logger.info(f"Got {len(ref_images)} reference images")

    if not ref_images:
        raise ValueError(f"Avatar {AVATAR_ID} has no reference images")

    # Convert reference images to base64 for Gemini
    ref_images_b64 = [base64.b64encode(img).decode("utf-8") for img in ref_images]

    gemini = avatar_service.gemini

    # Generate anchor image
    logger.info("Generating anchor image (9:16 portrait)...")
    anchor_b64 = await gemini.generate_image(
        prompt=ANCHOR_IMAGE_PROMPT,
        reference_images=ref_images_b64,
        temperature=0.3,
        image_size="2K",
    )
    anchor_bytes = base64.b64decode(anchor_b64)
    logger.info(f"Anchor image: {len(anchor_bytes)} bytes")

    return anchor_bytes


async def upload_and_get_url(
    image_bytes: bytes, path: str
) -> str:
    """Upload image to Supabase storage and return a signed URL.

    Args:
        image_bytes: Raw image bytes.
        path: Storage path within STORAGE_BUCKET.

    Returns:
        Signed URL (1 hour expiry).
    """
    supabase = get_supabase_client()

    await asyncio.to_thread(
        lambda: supabase.storage.from_(STORAGE_BUCKET).upload(
            path, image_bytes, {"content-type": "image/png"}
        )
    )
    logger.info(f"Uploaded image to {STORAGE_BUCKET}/{path}")

    result = await asyncio.to_thread(
        lambda: supabase.storage.from_(STORAGE_BUCKET).create_signed_url(
            path, 3600
        )
    )
    url = result.get("signedURL", "")
    logger.info(f"Signed URL: {url[:80]}...")
    return url


async def generate_scene(
    kling: KlingVideoService,
    org_id: str,
    brand_id: str,
    prompt: str,
    image_list: list[dict],
    scene_label: str,
    aspect_ratio: str = "9:16",
    element_id: str = ELEMENT_ID,
) -> dict:
    """Submit an Omni Video generation and poll to completion.

    Args:
        kling: KlingVideoService instance.
        org_id: Organization UUID.
        brand_id: Brand UUID.
        prompt: Scene prompt with element references.
        image_list: Keyframe image list (first_frame and/or end_frame).
        scene_label: Label for logging (e.g. "Scene 1").
        aspect_ratio: Video aspect ratio (default "9:16").
        element_id: Kling element ID for character consistency.

    Returns:
        Dict with generation results.
    """
    logger.info(f"--- {scene_label}: Submitting Omni Video ({aspect_ratio}, element={element_id}) ---")

    result = await kling.generate_omni_video(
        organization_id=org_id,
        brand_id=brand_id,
        prompt=prompt,
        duration="8",
        mode="pro",
        sound="on",
        image_list=image_list,
        element_list=[{"element_id": element_id}],
        aspect_ratio=aspect_ratio,
    )

    generation_id = result["generation_id"]
    kling_task_id = result["kling_task_id"]
    logger.info(
        f"{scene_label}: generation_id={generation_id}, "
        f"kling_task_id={kling_task_id}, "
        f"estimated_cost=${result.get('estimated_cost_usd', 0):.3f}"
    )

    # Poll to completion
    logger.info(f"{scene_label}: Polling for completion (up to 15 min)...")
    completion = await kling.poll_and_complete(
        generation_id=generation_id,
        kling_task_id=kling_task_id,
        endpoint_type=KlingEndpoint.OMNI_VIDEO,
        timeout_seconds=900,
    )

    status = completion.get("status")
    if status == "succeed":
        logger.info(
            f"{scene_label}: SUCCESS in {completion.get('generation_time_seconds', '?')}s"
        )
        logger.info(f"  Video URL: {completion.get('video_url', 'N/A')[:80]}...")
        logger.info(f"  Storage path: {completion.get('video_storage_path', 'N/A')}")
    else:
        logger.error(
            f"{scene_label}: FAILED - {completion.get('error_message', 'Unknown error')}"
        )

    return completion


# ============================================================================
# Main
# ============================================================================

async def main():
    logger.info("=" * 70)
    logger.info("Two-Scene Seamless Cut Test")
    logger.info("=" * 70)

    # Check for --reuse-images <run_id> flag to skip Gemini re-generation
    reuse_run_id = None
    if "--reuse-images" in sys.argv:
        idx = sys.argv.index("--reuse-images")
        if idx + 1 < len(sys.argv):
            reuse_run_id = sys.argv[idx + 1]
        else:
            logger.error("--reuse-images requires a run_id argument")
            sys.exit(1)

    # Check for --video-element <element_id> to test video element with voice
    video_element_id = None
    if "--video-element" in sys.argv:
        idx = sys.argv.index("--video-element")
        if idx + 1 < len(sys.argv):
            video_element_id = sys.argv[idx + 1]
            logger.info(f"Using video element ID: {video_element_id} (voice consistency test)")
        else:
            logger.error("--video-element requires an element_id argument")
            sys.exit(1)

    # Determine which element to use
    active_element_id = video_element_id or ELEMENT_ID
    element_type = "video" if video_element_id else "image"
    logger.info(f"Element: {active_element_id} (type: {element_type})")

    # 1. Resolve org_id
    org_id = await resolve_org_id(BRAND_ID)

    # 2. Initialize services
    avatar_service = AvatarService()
    kling = KlingVideoService()

    try:
        if reuse_run_id:
            # Reuse previously uploaded anchor image
            logger.info(f"\n--- Step 1+2: Reusing anchor image from run {reuse_run_id} ---")
            run_id = reuse_run_id
            supabase = get_supabase_client()
            anchor_signed = await asyncio.to_thread(
                lambda: supabase.storage.from_(STORAGE_BUCKET).create_signed_url(
                    f"two_scene_test/{run_id}/anchor.png", 3600
                )
            )
            anchor_url = anchor_signed.get("signedURL", "")
            logger.info(f"Anchor URL: {anchor_url[:80]}...")
        else:
            # 3. Generate single anchor image via Gemini
            logger.info("\n--- Step 1: Generating anchor image via Gemini (9:16) ---")
            anchor_bytes = await generate_anchor_image(avatar_service)

            # 4. Upload image to Supabase and get signed URL
            logger.info("\n--- Step 2: Uploading anchor image to Supabase ---")
            run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            anchor_url = await upload_and_get_url(
                anchor_bytes,
                f"two_scene_test/{run_id}/anchor.png",
            )

        # 5. Generate both scenes (same anchor image as first_frame + end_frame)
        logger.info("\n--- Step 3: Generating video scenes (9:16, same anchor frame) ---")

        # Both scenes use the same image as first_frame AND end_frame
        # This locks down the background environment across the cut
        scene_images = [
            {"image_url": anchor_url, "type": "first_frame"},
            {"image_url": anchor_url, "type": "end_frame"},
        ]

        # Run scenes sequentially (Kling concurrency limits)
        scene_1_result = await generate_scene(
            kling, org_id, BRAND_ID, SCENE_1_PROMPT, scene_images, "Scene 1",
            element_id=active_element_id,
        )

        scene_2_result = await generate_scene(
            kling, org_id, BRAND_ID, SCENE_2_PROMPT, scene_images, "Scene 2",
            element_id=active_element_id,
        )

        # 6. Print summary
        logger.info("\n" + "=" * 70)
        logger.info("RESULTS SUMMARY")
        logger.info("=" * 70)
        logger.info(f"Run ID: {run_id}")
        logger.info(f"Element: {active_element_id} (type: {element_type})")
        logger.info(f"Anchor image: {STORAGE_BUCKET}/two_scene_test/{run_id}/anchor.png")
        logger.info(f"Orientation: 9:16 (portrait)")
        logger.info(f"Keyframe strategy: same anchor as first_frame + end_frame (both scenes)")
        logger.info("")
        logger.info(f"Scene 1 status: {scene_1_result.get('status')}")
        logger.info(f"  Storage: {scene_1_result.get('video_storage_path', 'N/A')}")
        logger.info(f"  Time:    {scene_1_result.get('generation_time_seconds', 'N/A')}s")
        logger.info("")
        logger.info(f"Scene 2 status: {scene_2_result.get('status')}")
        logger.info(f"  Storage: {scene_2_result.get('video_storage_path', 'N/A')}")
        logger.info(f"  Time:    {scene_2_result.get('generation_time_seconds', 'N/A')}s")
        logger.info("")
        if element_type == "video":
            logger.info("VOICE CONSISTENCY TEST: Listen to both scenes — they should use the SAME voice.")
        logger.info("Download both videos and play back-to-back to verify seamless cut + consistent background.")

    finally:
        await kling.close()


if __name__ == "__main__":
    asyncio.run(main())
