#!/usr/bin/env python3
"""Test script for Video Recreation Pipeline (Phase 4).

Tests the scoring → adaptation → audio → VEO clip generation → assembly pipeline
against real data in the database.

Usage:
    python scripts/test_video_recreation.py                  # Score + adapt only (no generation cost)
    python scripts/test_video_recreation.py --generate       # Full pipeline including VEO generation
    python scripts/test_video_recreation.py --step score     # Only scoring
    python scripts/test_video_recreation.py --step adapt     # Score + adapt
    python scripts/test_video_recreation.py --step audio     # Score + adapt + audio
    python scripts/test_video_recreation.py --step clips     # Score + adapt + audio + clips
    python scripts/test_video_recreation.py --step assemble  # Full pipeline

Requires:
    - Analyzed Instagram outlier posts in the database (run Content Analysis first)
    - GEMINI_API_KEY env var (for storyboard adaptation)
    - ELEVENLABS_API_KEY env var (for audio generation, --step audio+)
    - VEO/Gemini access (for clip generation, --step clips+)
"""

import argparse
import asyncio
import json
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from uuid import UUID


WONDER_PAWS_BRAND_ID = UUID("bc8461a8-232d-4765-8775-c75eaafc5503")

STEPS = ["score", "adapt", "audio", "clips", "assemble"]


def print_header(text: str):
    print(f"\n{'='*60}")
    print(text)
    print(f"{'='*60}")


def print_section(text: str):
    print(f"\n--- {text} ---")


def print_cost(cost_dict: dict):
    print(f"  Kling:      ${cost_dict.get('kling_cost', 0):.2f}")
    print(f"  VEO:        ${cost_dict.get('veo_cost', 0):.2f}")
    print(f"  ElevenLabs: ${cost_dict.get('elevenlabs_cost', 0):.2f}")
    print(f"  Total:      ${cost_dict.get('total_estimated', 0):.2f}")


async def main():
    parser = argparse.ArgumentParser(description="Test Video Recreation Pipeline")
    parser.add_argument(
        "--step",
        choices=STEPS,
        default="adapt",
        help="How far to run the pipeline (default: adapt = score + adapt, no generation cost)",
    )
    parser.add_argument(
        "--generate",
        action="store_true",
        help="Shorthand for --step assemble (full pipeline with real generation)",
    )
    parser.add_argument(
        "--brand-id",
        type=str,
        default=str(WONDER_PAWS_BRAND_ID),
        help="Brand UUID to test with (default: Wonder Paws)",
    )
    parser.add_argument(
        "--voice-id",
        type=str,
        default=None,
        help="ElevenLabs voice ID for audio generation",
    )
    parser.add_argument(
        "--candidate-id",
        type=str,
        default=None,
        help="Resume from an existing candidate ID (skip scoring)",
    )
    args = parser.parse_args()

    if args.generate:
        args.step = "assemble"

    max_step = STEPS.index(args.step)

    from viraltracker.core.database import get_supabase_client
    from viraltracker.services.video_recreation_service import (
        VideoRecreationService,
        estimate_generation_cost,
        SCENE_TALKING_HEAD,
    )

    supabase = get_supabase_client()
    service = VideoRecreationService(supabase=supabase)
    brand_id = args.brand_id

    # Get org_id
    brand_result = supabase.table("brands").select(
        "organization_id, name"
    ).eq("id", brand_id).limit(1).execute()

    if not brand_result.data:
        print(f"ERROR: Brand {brand_id} not found")
        return

    org_id = brand_result.data[0]["organization_id"]
    brand_name = brand_result.data[0]["name"]
    print_header(f"Video Recreation Pipeline Test")
    print(f"Brand: {brand_name} ({brand_id})")
    print(f"Org:   {org_id}")
    print(f"Steps: {' → '.join(STEPS[:max_step+1])}")

    candidate_id = args.candidate_id

    # ================================================================
    # Step 1: Score Candidates
    # ================================================================

    if max_step >= 0 and not candidate_id:
        print_header("Step 1: Score Candidates")

        scored = service.score_candidates(brand_id, org_id, limit=10)

        if not scored:
            print("No analyzed outlier posts found.")
            print("Run Content Analysis on the Instagram Content page first.")
            return

        print(f"Scored {len(scored)} candidates:\n")
        for i, c in enumerate(scored):
            print(
                f"  {i+1}. Score: {c['composite_score']:.0%} "
                f"(eng={c['score_components']['engagement']:.0%}, "
                f"hook={c['score_components']['hook_quality']:.0%}, "
                f"feas={c['score_components']['recreation_feasibility']:.0%}, "
                f"avatar={c['score_components']['avatar_compatibility']:.0%}) "
                f"TH={'yes' if c.get('has_talking_head') else 'no'} "
                f"scenes={c.get('scene_types', [])}"
            )

        # Pick the top candidate
        top = scored[0]
        candidate_id = top.get("id")
        print(f"\nTop candidate: {candidate_id} (score={top['composite_score']:.0%})")

        # Approve it
        service.approve_candidate(candidate_id)
        print("Status → approved")

    if not candidate_id:
        print("ERROR: No candidate to work with")
        return

    # Show cost estimate
    print_section("Cost Estimate (pre-adaptation)")
    estimate = service.get_cost_estimate(candidate_id)
    if estimate:
        print_cost(estimate)
    else:
        print("  (no estimate available — no storyboard yet)")

    if max_step < 1:
        print_header("Done (score only)")
        return

    # ================================================================
    # Step 2: Adapt Storyboard
    # ================================================================

    print_header("Step 2: Adapt Storyboard")

    # Check if already adapted
    candidate = service.get_candidate(candidate_id)
    if candidate and candidate.get("adapted_storyboard"):
        print("Already adapted — skipping LLM call")
        adapted = candidate["adapted_storyboard"]
    else:
        if not os.getenv("GEMINI_API_KEY"):
            print("ERROR: GEMINI_API_KEY not set — cannot adapt storyboard")
            return

        print("Calling Gemini Flash for storyboard adaptation...")
        result = await service.adapt_storyboard(
            candidate_id,
            brand_name=brand_name,
            product_name=brand_name,
            brand_tone="friendly, approachable",
        )

        if not result:
            print("ERROR: Adaptation failed")
            return

        adapted = result.get("adapted_storyboard") or []
        print(f"Adapted storyboard: {len(adapted)} scenes")

    # Display adapted storyboard
    candidate = service.get_candidate(candidate_id)
    adapted = candidate.get("adapted_storyboard") or []

    if candidate.get("adapted_hook"):
        print(f"\nAdapted hook: {candidate['adapted_hook'][:100]}")
    if candidate.get("adapted_script"):
        print(f"Adapted script: {candidate['adapted_script'][:200]}...")

    print_section("Scenes")
    for scene in adapted:
        idx = scene.get("scene_idx", "?")
        stype = scene.get("scene_type", "?")
        dur = scene.get("duration_sec", "?")
        dialogue = scene.get("dialogue", "")
        prompt = scene.get("visual_prompt", "")
        icon = "🗣️" if stype == "talking_head" else "🎥"
        print(f"  Scene {idx} {icon} ({stype}, {dur}s)")
        if dialogue:
            print(f"    Dialogue: {dialogue[:80]}...")
        if prompt:
            print(f"    Prompt:   {prompt[:80]}...")

    # Show updated cost estimate
    print_section("Cost Estimate (post-adaptation)")
    estimate = service.get_cost_estimate(candidate_id)
    if estimate:
        print_cost(estimate)

    if max_step < 2:
        print_header("Done (score + adapt)")
        print(f"Candidate ID: {candidate_id}")
        print("Resume with: python scripts/test_video_recreation.py --step audio "
              f"--candidate-id {candidate_id}")
        return

    # ================================================================
    # Step 3: Generate Audio
    # ================================================================

    print_header("Step 3: Generate Audio Segments")

    if candidate.get("audio_segments"):
        print("Already has audio segments — skipping")
        segments = candidate["audio_segments"]
    else:
        if not os.getenv("ELEVENLABS_API_KEY"):
            print("ERROR: ELEVENLABS_API_KEY not set — cannot generate audio")
            print(f"Resume later with: --step audio --candidate-id {candidate_id}")
            return

        voice_id = args.voice_id
        if not voice_id:
            # Try to find a default voice
            print("No --voice-id specified. Checking for brand avatars...")
            avatars = supabase.table("brand_avatars").select(
                "id, name, voice_id"
            ).eq("brand_id", brand_id).eq("is_active", True).limit(1).execute()

            if avatars.data and avatars.data[0].get("voice_id"):
                voice_id = avatars.data[0]["voice_id"]
                print(f"Using avatar voice: {avatars.data[0]['name']} ({voice_id})")
            else:
                print("ERROR: No --voice-id and no avatar with voice found")
                print(f"Resume with: --step audio --candidate-id {candidate_id} --voice-id YOUR_VOICE_ID")
                return

        # Check if any scenes actually need audio
        talking_scenes = [s for s in adapted if s.get("scene_type") == "talking_head" and s.get("dialogue")]
        if not talking_scenes:
            print("No talking-head scenes with dialogue — skipping audio generation")
            print("(All scenes are B-roll, will use VEO without audio)")
        else:
            print(f"Generating audio for {len(talking_scenes)} talking-head scenes...")
            result = await service.generate_audio_segments(candidate_id, voice_id=voice_id)
            if not result:
                print("ERROR: Audio generation failed")
                return
            segments = result.get("audio_segments") or []

        # Refresh candidate
        candidate = service.get_candidate(candidate_id)

    segments = candidate.get("audio_segments") or []
    for seg in segments:
        icon = "🔊" if seg.get("has_audio") else "🔇"
        print(
            f"  Scene {seg.get('scene_idx')}: {icon} "
            f"{seg.get('duration_sec', 0):.1f}s "
            f"{'→ ' + seg.get('audio_storage_path', '') if seg.get('has_audio') else '(no audio)'}"
        )

    total_dur = candidate.get("total_audio_duration_sec", 0)
    print(f"\nTotal duration: {total_dur:.1f}s")

    if max_step < 3:
        print_header("Done (score + adapt + audio)")
        print(f"Candidate ID: {candidate_id}")
        print(f"Resume with: python scripts/test_video_recreation.py --step clips "
              f"--candidate-id {candidate_id}")
        return

    # ================================================================
    # Step 4: Generate Video Clips (VEO only)
    # ================================================================

    print_header("Step 4: Generate Video Clips (VEO only)")
    print("⚠️  Using VEO for ALL scenes (engine_override='veo')")
    print("    This will incur VEO generation costs!")

    if candidate.get("generated_clips"):
        clips = candidate["generated_clips"]
        succeeded = [c for c in clips if c.get("status") == "succeed"]
        if succeeded:
            print(f"Already has {len(succeeded)}/{len(clips)} successful clips — skipping")
        else:
            print("Previous clips failed, regenerating...")
            result = await service.generate_video_clips(
                candidate_id, engine_override="veo"
            )
            if not result:
                print("ERROR: Clip generation failed")
                return
            candidate = service.get_candidate(candidate_id)
            clips = candidate.get("generated_clips") or []
    else:
        print("Generating clips (this may take several minutes)...")
        result = await service.generate_video_clips(
            candidate_id, engine_override="veo"
        )
        if not result:
            print("ERROR: Clip generation failed")
            return
        candidate = service.get_candidate(candidate_id)
        clips = candidate.get("generated_clips") or []

    for clip in clips:
        status_icon = "✅" if clip.get("status") == "succeed" else "❌"
        print(
            f"  Scene {clip.get('scene_idx')}: {status_icon} "
            f"{clip.get('engine')} {clip.get('duration_sec', 0):.1f}s "
            f"cost=${clip.get('estimated_cost_usd', 0):.2f} "
            f"{clip.get('storage_path', '') or clip.get('error', '')}"
        )

    total_cost = candidate.get("total_generation_cost_usd", 0)
    print(f"\nTotal generation cost: ${total_cost:.2f}")

    succeeded = [c for c in clips if c.get("status") == "succeed"]
    if not succeeded:
        print("\nERROR: No clips succeeded — cannot assemble")
        return

    if max_step < 4:
        print_header("Done (score + adapt + audio + clips)")
        print(f"Candidate ID: {candidate_id}")
        print(f"Resume with: python scripts/test_video_recreation.py --step assemble "
              f"--candidate-id {candidate_id}")
        return

    # ================================================================
    # Step 5: Assemble Final Video
    # ================================================================

    print_header("Step 5: Assemble Final Video (FFmpeg)")

    if candidate.get("final_video_path"):
        print(f"Already assembled: {candidate['final_video_path']}")
    else:
        print(f"Concatenating {len(succeeded)} clips...")
        result = await service.concatenate_clips(candidate_id)
        if not result:
            print("ERROR: Assembly failed")
            return
        candidate = service.get_candidate(candidate_id)

    print_header("DONE — Final Result")
    print(f"Candidate ID:  {candidate_id}")
    print(f"Status:        {candidate.get('status')}")
    print(f"Final video:   {candidate.get('final_video_path')}")
    print(f"Duration:      {candidate.get('final_video_duration_sec')}s")
    print(f"Total cost:    ${candidate.get('total_generation_cost_usd', 0):.2f}")
    print(f"Engine:        {candidate.get('generation_engine')}")

    overlays = candidate.get("text_overlay_instructions")
    if overlays:
        print(f"\nText overlay instructions ({len(overlays)} items):")
        print(json.dumps(overlays, indent=2)[:500])


if __name__ == "__main__":
    asyncio.run(main())
