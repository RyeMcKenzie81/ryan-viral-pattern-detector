#!/usr/bin/env python3
"""
Test script for Kling Omni Video API endpoint verification.

Verifies that the scraped API parameters work against the live endpoint.
Run: python scripts/test_omni_api.py

Requires: KLING_ACCESS_KEY and KLING_SECRET_KEY env vars.
"""

import asyncio
import json
import logging
import os
import sys
import time
import uuid

import httpx
import jwt

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

BASE_URL = "https://api-singapore.klingai.com"
OMNI_VIDEO_PATH = "/v1/videos/omni-video"
ELEMENT_PATH = "/v1/general/advanced-custom-elements"


def get_jwt_token() -> str:
    """Generate JWT for Kling API auth (same pattern as kling_video_service.py)."""
    access_key = os.getenv("KLING_ACCESS_KEY")
    secret_key = os.getenv("KLING_SECRET_KEY")
    if not access_key or not secret_key:
        raise ValueError("Set KLING_ACCESS_KEY and KLING_SECRET_KEY env vars")

    now = int(time.time())
    payload = {
        "iss": access_key,
        "exp": now + 1800,  # 30 min expiry
        "nbf": now - 5,
        "iat": now,
    }
    return jwt.encode(payload, secret_key, algorithm="HS256", headers={"typ": "JWT"})


async def test_text_only_omni():
    """Test 1: Minimal text-only Omni request."""
    logger.info("=== Test 1: Text-only Omni Video ===")
    token = get_jwt_token()

    payload = {
        "model_name": "kling-v3-omni",
        "prompt": "A calm ocean wave gently rolling onto a sandy beach at sunset.",
        "sound": "on",
        "duration": "5",
        "mode": "std",
        "aspect_ratio": "16:9",
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            f"{BASE_URL}{OMNI_VIDEO_PATH}",
            json=payload,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )

    logger.info(f"Status: {resp.status_code}")
    data = resp.json()
    logger.info(f"Response: {json.dumps(data, indent=2)}")

    if data.get("code") == 0:
        task_id = data.get("data", {}).get("task_id")
        logger.info(f"SUCCESS: Task created with ID: {task_id}")
        return task_id
    else:
        logger.error(f"FAILED: code={data.get('code')}, message={data.get('message')}")
        return None


async def test_query_task(task_id: str):
    """Test 2: Query task status."""
    logger.info(f"=== Test 2: Query task {task_id} ===")
    token = get_jwt_token()

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.get(
            f"{BASE_URL}{OMNI_VIDEO_PATH}/{task_id}",
            headers={"Authorization": f"Bearer {token}"},
        )

    data = resp.json()
    logger.info(f"Task status: {json.dumps(data, indent=2)}")
    return data


async def main():
    logger.info("Kling Omni Video API Verification")
    logger.info("=" * 60)

    # Test 1: Text-only omni request
    task_id = await test_text_only_omni()

    if task_id:
        # Wait a few seconds then query status
        logger.info("Waiting 5s before querying status...")
        await asyncio.sleep(5)
        await test_query_task(task_id)

    logger.info("\n" + "=" * 60)
    logger.info("Verification complete. Check responses above.")


if __name__ == "__main__":
    asyncio.run(main())
