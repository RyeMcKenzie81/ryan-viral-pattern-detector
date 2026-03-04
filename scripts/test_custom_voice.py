#!/usr/bin/env python3
"""Test the new Create Custom Voice endpoint directly with httpx + JWT.

Bypasses the service layer to isolate the Kling API call.
"""

import asyncio
import json
import os
import time

import httpx
import jwt

ACCESS_KEY = os.environ.get("KLING_ACCESS_KEY", "")
SECRET_KEY = os.environ.get("KLING_SECRET_KEY", "")
BASE_URL = "https://api-singapore.klingai.com"

# Video URL from our previously created element (stored in Kling's CDN)
# This is the video Kling stored when we created element 856528387816046601
KLING_VIDEO_URL = "https://v15-kling.klingai.com/bs2/upload-ylab-stunt/se/ai_portal_queue_element_avatar_video_uploader/b2f06d03-6133-472c-aa3b-e6f3ea53dc69.mp4?x-expires=1741266082&x-signature=LFZGFOtmI00CfhfgFa3OSTNnZ5o%3D"


def get_jwt():
    """Generate a fresh JWT token."""
    now = time.time()
    headers = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "iss": ACCESS_KEY,
        "exp": int(now) + 1800,
        "nbf": int(now) - 30,
    }
    return jwt.encode(payload, SECRET_KEY, headers=headers)


def get_headers():
    return {
        "Authorization": f"Bearer {get_jwt()}",
        "Content-Type": "application/json",
    }


async def test_create_voice():
    """Test creating a custom voice."""
    print(f"Access Key: {ACCESS_KEY[:10]}...")
    print(f"Secret Key: {SECRET_KEY[:10]}...")

    video_url = ""

    async with httpx.AsyncClient(timeout=60.0) as client:
        # Step 1: First verify we can query an existing element
        print("\n" + "=" * 60)
        print("Step 1: Query existing element (verify auth works)")
        print("=" * 60)

        try:
            resp = await client.get(
                f"{BASE_URL}/v1/general/advanced-custom-elements/856528333369769993",
                headers=get_headers(),
            )
            print(f"  Status: {resp.status_code}")
            if resp.status_code == 200:
                data = resp.json()
                print(f"  Code: {data.get('code')}")
                elements = data.get("data", {}).get("task_result", {}).get("elements", [])
                if elements:
                    el = elements[0]
                    print(f"  element_id: {el.get('element_id')}")
                    # Get the video URL from the element
                    videos = el.get("element_video_list", {}).get("refer_videos", [])
                    if videos:
                        video_url = videos[0].get("video_url", "")
                        print(f"  Video URL: {video_url[:120]}...")
                        print(f"  Full Video URL length: {len(video_url)}")
                    print(f"  Has voice_info: {'element_voice_info' in el}")
                    print(f"  Keys: {list(el.keys())}")
            else:
                print(f"  Response: {resp.text[:500]}")
        except Exception as e:
            print(f"  Error: {e}")

        # Step 2: List existing custom voices
        print("\n" + "=" * 60)
        print("Step 2: List existing custom voices")
        print("=" * 60)

        try:
            resp = await client.get(
                f"{BASE_URL}/v1/general/custom-voices?pageNum=1&pageSize=10",
                headers=get_headers(),
            )
            print(f"  Status: {resp.status_code}")
            data = resp.json()
            print(f"  Response: {json.dumps(data, indent=2, default=str)}")
        except Exception as e:
            print(f"  Error: {e}")

        # Step 3: Create custom voice from video URL
        # Use the FRESH video URL from the element query (not the expired hardcoded one)
        print("\n" + "=" * 60)
        print("Step 3: Create custom voice from video URL")
        print("=" * 60)

        if not video_url:
            print("  ERROR: No video URL available from element query")
            return

        payload = {
            "voice_name": "test_voice_v2",
            "voice_url": video_url,
        }
        print(f"  Payload: {json.dumps(payload, indent=2)}")

        try:
            resp = await client.post(
                f"{BASE_URL}/v1/general/custom-voices",
                json=payload,
                headers=get_headers(),
            )
            print(f"  Status: {resp.status_code}")
            data = resp.json()
            print(f"  Response: {json.dumps(data, indent=2, default=str)}")

            task_id = data.get("data", {}).get("task_id")
            if not task_id:
                print("  No task_id returned, stopping")
                return

            print(f"  Task ID: {task_id}")

        except Exception as e:
            print(f"  Error: {e}")
            return

        # Step 4: Poll for voice creation
        print("\n" + "=" * 60)
        print("Step 4: Polling for voice creation completion")
        print("=" * 60)

        voice_id = None
        for attempt in range(1, 41):
            await asyncio.sleep(15)

            try:
                resp = await client.get(
                    f"{BASE_URL}/v1/general/custom-voices/{task_id}",
                    headers=get_headers(),
                )
                data = resp.json()
                status = data.get("data", {}).get("task_status", "")

                print(f"\n  Attempt {attempt}/40: status={status}")

                if attempt <= 3 or attempt % 5 == 0 or status in ("succeed", "failed"):
                    print(f"  Response: {json.dumps(data, indent=2, default=str)}")

                if status == "failed":
                    print("  FAILED!")
                    return

                if status == "succeed":
                    voices = data.get("data", {}).get("task_result", {}).get("voices", [])
                    if voices:
                        voice = voices[0]
                        voice_id = voice.get("voice_id")
                        print(f"\n  SUCCESS!")
                        print(f"  voice_id: {voice_id}")
                        print(f"  voice_name: {voice.get('voice_name')}")
                        print(f"  trial_url: {voice.get('trial_url', '')[:120]}")
                        print(f"  owned_by: {voice.get('owned_by')}")
                    break

            except Exception as e:
                print(f"  Error: {e}")

        if voice_id:
            print(f"\n\nVOICE CREATED SUCCESSFULLY: {voice_id}")
            print(f"Use this in element creation: element_voice_id={voice_id}")
        else:
            print("\n\nVoice creation did not complete in time")


if __name__ == "__main__":
    asyncio.run(test_create_voice())
