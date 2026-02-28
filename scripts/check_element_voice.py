#!/usr/bin/env python3
"""Quick script to query existing Kling elements and check for voice_info."""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from viraltracker.services.kling_video_service import KlingVideoService

# Task IDs from our test runs (task_id is what we query, not element_id)
TASK_IDS = [
    ("856504805471813710", "~1.5 hours ago"),
    ("856508498128683087", "~5 min ago"),
]


async def main():
    kling = KlingVideoService()
    try:
        for task_id, label in TASK_IDS:
            print(f"\n{'='*60}")
            print(f"Task: {task_id} ({label})")
            print(f"{'='*60}")
            try:
                result = await kling.query_element(task_id)
                data = result.get("data", {})
                task_result = data.get("task_result", {})
                elements = task_result.get("elements", [])

                if not elements:
                    print("  No elements in response")
                    continue

                el = elements[0]
                print(f"  element_id: {el.get('element_id')}")
                print(f"  element_name: {el.get('element_name')}")
                print(f"  element_type: {el.get('element_type')}")
                print(f"  status: {el.get('status')}")
                print(f"  Keys: {list(el.keys())}")

                voice_info = el.get("element_voice_info")
                if voice_info:
                    print(f"  *** VOICE INFO FOUND ***")
                    print(f"  voice_id: {voice_info.get('voice_id')}")
                    print(f"  voice_name: {voice_info.get('voice_name')}")
                    print(f"  trial_url: {voice_info.get('trial_url', '')[:80]}...")
                else:
                    print(f"  element_voice_info: NOT PRESENT")

            except Exception as e:
                print(f"  Error: {e}")
    finally:
        await kling.close()


if __name__ == "__main__":
    asyncio.run(main())
