#!/usr/bin/env python3
"""
Generate two podcast clips of avatar "Mr. Jeff Authority" speaking dialogue
in a podcast studio using Kling Omni Video with voice-bound element.

Workflow:
1. Load avatar data (reference images, voice_id, calibration video)
2. Create a new Kling element with voice binding (element_voice_id)
3. Generate podcast studio keyframe image with Gemini
4. Generate both omni videos with element_list + image_list
5. Poll both tasks to completion

Run: python scripts/generate_podcast_clips.py
"""

import asyncio
import base64
import logging
import os
import sys
from uuid import UUID

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────

AVATAR_ID = UUID("2fb823c6-47a8-4c85-9715-7923ab008a25")
VOICE_ID = "856612906933297203"

DIALOGUE_1 = (
    "we romanticize the act of getting a dog. we think about the cuddles "
    "and the fetch but we don't think about the sacrifice"
)
DIALOGUE_2 = (
    "and I'm not just talking about the money. I'm talking about standing "
    "in the freezing rain at 6:00am praying they finally pee so you can "
    "go back inside."
)

PODCAST_STUDIO_PROMPT = (
    "This exact person sitting at a white quartz desk. "
    "Professional podcast microphone in front of them. "
    "Colored LED lights in the background. "
    "Podcast studio with many lush green plants in the background. "
    "Photorealistic, cinematic lighting, 16:9 aspect ratio."
)

# Duration for each clip (seconds)
VIDEO_DURATION = "10"


def build_video_prompt(dialogue: str) -> str:
    """Build the omni video prompt with element and dialogue.

    Per Kling 3.0 docs:
    - <<<element_1>>> references the first element in element_list
    - Use single quotes for dialogue within prompts
    """
    return (
        "<<<element_1>>> is sitting at a white quartz desk in a professional "
        "podcast studio. A professional podcast microphone is positioned in "
        "front of him. Colored LED lights glow softly in the background. "
        "Lush green plants fill the background shelves. "
        "The man speaks into the microphone with supreme confidence and "
        "captivating energy, making direct eye contact with the camera "
        "like an extremely engaging podcast host.\n\n"
        f"[Speaker: Man, confident and authoritative]: '{dialogue}'"
    )


async def step1_load_avatar():
    """Load avatar data from database."""
    logger.info("=== Step 1: Load avatar data ===")
    from viraltracker.services.avatar_service import AvatarService
    avatar_svc = AvatarService()
    avatar = await avatar_svc.get_avatar(AVATAR_ID)
    if not avatar:
        raise ValueError(f"Avatar {AVATAR_ID} not found")

    logger.info(f"Avatar: {avatar.name}")
    logger.info(f"Brand ID: {avatar.brand_id}")
    logger.info(f"Voice ID: {avatar.kling_voice_id}")
    logger.info(f"Element ID: {avatar.kling_element_id}")
    logger.info(f"Calibration video: {avatar.calibration_video_path}")
    logger.info(f"Reference image 1: {avatar.reference_image_1}")
    return avatar, avatar_svc


async def step2_create_element_with_voice(avatar, avatar_svc):
    """Create a new Kling element with the voice bound.

    The existing elements were created without voice binding.
    We need a new element with element_voice_id so the element
    carries the voice (since voice_list and element_list are mutually exclusive).
    """
    logger.info("=== Step 2: Create element with voice binding ===")
    from viraltracker.services.kling_video_service import KlingVideoService
    from viraltracker.services.kling_models import KlingEndpoint

    kling = KlingVideoService()

    # Get signed URL for calibration video
    if not avatar.calibration_video_path:
        raise ValueError("Avatar has no calibration video — run element creation first")

    video_url = await avatar_svc._get_video_signed_url(avatar.calibration_video_path)
    logger.info(f"Calibration video URL: {video_url[:80]}...")

    # Resolve org_id from brand
    from viraltracker.core.database import get_supabase_client
    supabase = get_supabase_client()
    brand_row = supabase.table("brands").select("organization_id").eq(
        "id", str(avatar.brand_id)
    ).single().execute()
    org_id = brand_row.data["organization_id"]

    # Create element with voice binding
    gen_result = await kling.create_video_element(
        organization_id=org_id,
        brand_id=str(avatar.brand_id),
        element_name=avatar.name[:20],
        element_description=f"Podcast avatar: {avatar.name}"[:100],
        video_url=video_url,
        element_voice_id=VOICE_ID,
    )

    task_id = gen_result.get("kling_task_id")
    logger.info(f"Element creation submitted: task_id={task_id}")

    # Poll for element completion
    logger.info("Polling for element creation (this may take 2-5 minutes)...")
    poll_result = await kling.poll_task(
        task_id=task_id,
        endpoint_type=KlingEndpoint.ADVANCED_CUSTOM_ELEMENTS,
        timeout_seconds=600,
    )

    task_data = poll_result.get("data", {})
    task_status = task_data.get("task_status", "")

    if task_status != "succeed":
        raise ValueError(
            f"Element creation failed: status={task_status}, "
            f"msg={task_data.get('task_status_msg', '')}"
        )

    # Extract element_id and voice info
    task_result = task_data.get("task_result", {})
    elements = task_result.get("elements", [])
    if not elements:
        raise ValueError("No elements in response")

    element = elements[0]
    element_id = element.get("element_id")
    voice_info = element.get("element_voice_info")

    logger.info(f"Element created: element_id={element_id}")
    logger.info(f"Voice info: {voice_info}")

    await kling.close()
    return element_id, org_id


async def step3_generate_keyframe(avatar, avatar_svc):
    """Generate podcast studio keyframe image using Gemini."""
    logger.info("=== Step 3: Generate keyframe image with Gemini ===")
    from viraltracker.services.gemini_service import GeminiService

    gemini = GeminiService()

    # Download avatar's reference image as base64
    ref_path = avatar.reference_image_1
    if not ref_path:
        raise ValueError("Avatar has no reference_image_1")

    parts = ref_path.split("/", 1)
    bucket = parts[0]
    file_path = parts[1]

    from viraltracker.core.database import get_supabase_client
    supabase = get_supabase_client()
    img_bytes = supabase.storage.from_(bucket).download(file_path)
    ref_base64 = base64.b64encode(img_bytes).decode("utf-8")
    logger.info(f"Downloaded reference image: {len(img_bytes)} bytes")

    # Generate podcast studio image with Gemini
    logger.info("Generating podcast studio keyframe with Gemini...")
    result = await gemini.generate_image(
        prompt=PODCAST_STUDIO_PROMPT,
        reference_images=[ref_base64],
        temperature=0.4,
        image_size="2K",
    )
    logger.info(f"Keyframe generated: {len(result)} chars base64")

    # Upload to Supabase for a signed URL
    keyframe_bytes = base64.b64decode(result)
    keyframe_path = f"{avatar.brand_id}/{AVATAR_ID}/podcast_keyframe.png"

    supabase.storage.from_("avatars").upload(
        keyframe_path,
        keyframe_bytes,
        {"content-type": "image/png", "upsert": "true"},
    )
    logger.info(f"Uploaded keyframe to: avatars/{keyframe_path}")

    # Get signed URL
    signed = supabase.storage.from_("avatars").create_signed_url(
        keyframe_path, 86400
    )
    keyframe_url = signed.get("signedURL", "")
    logger.info(f"Keyframe signed URL: {keyframe_url[:80]}...")

    return keyframe_url


async def step4_generate_videos(element_id, org_id, avatar, keyframe_url):
    """Generate both podcast clip videos."""
    logger.info("=== Step 4: Generate both omni videos ===")
    from viraltracker.services.kling_video_service import KlingVideoService
    from viraltracker.services.kling_models import KlingEndpoint

    kling = KlingVideoService()

    image_list = [
        {"image_url": keyframe_url, "type": "first_frame"},
        {"image_url": keyframe_url, "type": "end_frame"},
    ]
    element_list = [{"element_id": element_id}]

    # Generate video 1
    prompt_1 = build_video_prompt(DIALOGUE_1)
    logger.info(f"Video 1 prompt ({len(prompt_1)} chars):\n{prompt_1}")

    result_1 = await kling.generate_omni_video(
        organization_id=org_id,
        brand_id=str(avatar.brand_id),
        prompt=prompt_1,
        duration=VIDEO_DURATION,
        mode="pro",
        sound="on",
        image_list=image_list,
        element_list=element_list,
    )
    gen_id_1 = result_1["generation_id"]
    task_id_1 = result_1["kling_task_id"]
    logger.info(f"Video 1 submitted: gen_id={gen_id_1}, task_id={task_id_1}, cost=${result_1.get('estimated_cost_usd', 0):.2f}")

    # Generate video 2
    prompt_2 = build_video_prompt(DIALOGUE_2)
    logger.info(f"Video 2 prompt ({len(prompt_2)} chars):\n{prompt_2}")

    result_2 = await kling.generate_omni_video(
        organization_id=org_id,
        brand_id=str(avatar.brand_id),
        prompt=prompt_2,
        duration=VIDEO_DURATION,
        mode="pro",
        sound="on",
        image_list=image_list,
        element_list=element_list,
    )
    gen_id_2 = result_2["generation_id"]
    task_id_2 = result_2["kling_task_id"]
    logger.info(f"Video 2 submitted: gen_id={gen_id_2}, task_id={task_id_2}, cost=${result_2.get('estimated_cost_usd', 0):.2f}")

    # Poll both tasks concurrently
    logger.info("Polling both tasks (this may take 5-10 minutes)...")

    async def poll_video(gen_id, task_id, label):
        try:
            final = await kling.poll_and_complete(
                generation_id=gen_id,
                kling_task_id=task_id,
                endpoint_type=KlingEndpoint.OMNI_VIDEO,
                timeout_seconds=900,  # 15 min max
            )
            logger.info(f"{label}: status={final['status']}, "
                       f"video_url={final.get('video_url', 'N/A')[:80]}, "
                       f"storage={final.get('video_storage_path', 'N/A')}, "
                       f"time={final.get('generation_time_seconds', 0):.0f}s")
            return final
        except Exception as e:
            logger.error(f"{label} FAILED: {e}")
            return {"status": "failed", "error": str(e)}

    final_1, final_2 = await asyncio.gather(
        poll_video(gen_id_1, task_id_1, "Video 1"),
        poll_video(gen_id_2, task_id_2, "Video 2"),
    )

    await kling.close()
    return final_1, final_2


async def main():
    logger.info("=" * 60)
    logger.info("Podcast Clip Generator — Mr. Jeff Authority")
    logger.info("=" * 60)

    # Step 1: Load avatar
    avatar, avatar_svc = await step1_load_avatar()

    # Step 2: Create element with voice binding
    element_id, org_id = await step2_create_element_with_voice(avatar, avatar_svc)

    # Step 3: Generate keyframe image
    keyframe_url = await step3_generate_keyframe(avatar, avatar_svc)

    # Step 4: Generate both videos
    final_1, final_2 = await step4_generate_videos(element_id, org_id, avatar, keyframe_url)

    # Summary
    logger.info("\n" + "=" * 60)
    logger.info("RESULTS")
    logger.info("=" * 60)
    logger.info(f"Element ID (voice-bound): {element_id}")
    logger.info(f"Video 1: {final_1.get('status')} — {final_1.get('video_storage_path', 'N/A')}")
    logger.info(f"Video 2: {final_2.get('status')} — {final_2.get('video_storage_path', 'N/A')}")

    if final_1.get("video_url"):
        logger.info(f"Video 1 URL: {final_1['video_url']}")
    if final_2.get("video_url"):
        logger.info(f"Video 2 URL: {final_2['video_url']}")

    total_cost = (
        (final_1.get("estimated_cost_usd") or 0)
        + (final_2.get("estimated_cost_usd") or 0)
    )
    logger.info(f"Estimated total cost: ${total_cost:.2f}")


if __name__ == "__main__":
    asyncio.run(main())
