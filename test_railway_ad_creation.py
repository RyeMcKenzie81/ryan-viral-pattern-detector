#!/usr/bin/env python3
"""
Test Railway API Ad Creation Endpoint

Uses the same parameters as the local test (test_parallel_workflows.py)
to verify the Railway production API works end-to-end.

Usage:
    # Set API key environment variable
    export VIRALTRACKER_API_KEY="your-api-key"

    # Run test
    python test_railway_ad_creation.py
"""

import base64
import os
import sys
import json
import requests
from pathlib import Path
from datetime import datetime


# Railway API Configuration
RAILWAY_API_URL = "https://ryan-viral-pattern-detector-production.up.railway.app/api/ad-creation/create"

# Test Parameters (same as local test)
TEST_PRODUCT_ID = "83166c93-632f-47ef-a929-922230e05f82"
REFERENCE_IMAGE = "ad3-example.jpg"


def load_reference_image() -> tuple[str, str]:
    """Load and base64 encode reference image."""
    image_path = Path(__file__).parent / "test_images" / "reference_ads" / REFERENCE_IMAGE

    if not image_path.exists():
        print(f"❌ ERROR: Reference image not found at {image_path}")
        sys.exit(1)

    with open(image_path, 'rb') as f:
        image_data = base64.b64encode(f.read()).decode('utf-8')

    return image_data, REFERENCE_IMAGE


def test_railway_api():
    """Test Railway API endpoint with the same parameters as local test."""

    print("=" * 80)
    print("RAILWAY API AD CREATION TEST")
    print("=" * 80)
    print(f"Railway URL: {RAILWAY_API_URL}")
    print(f"Product ID: {TEST_PRODUCT_ID}")
    print(f"Reference Image: {REFERENCE_IMAGE}")
    print("=" * 80)
    print()

    # Get API key from environment
    api_key = os.environ.get("VIRALTRACKER_API_KEY")
    if not api_key:
        print("❌ ERROR: VIRALTRACKER_API_KEY environment variable not set")
        print("Set it with: export VIRALTRACKER_API_KEY='your-api-key'")
        sys.exit(1)

    # Load reference image
    print("📁 Loading reference image...")
    reference_ad_base64, filename = load_reference_image()
    print(f"✅ Loaded {filename} ({len(reference_ad_base64)} chars base64)")
    print()

    # Build request payload (matches AdCreationRequest model)
    payload = {
        "product_id": TEST_PRODUCT_ID,
        "reference_ad_base64": reference_ad_base64,
        "reference_ad_filename": filename,
        "project_id": None  # Optional
    }

    # Set headers
    headers = {
        "Content-Type": "application/json",
        "X-API-Key": api_key
    }

    # Make request
    print("🚀 Sending request to Railway API...")
    print(f"⏰ Started at: {datetime.now().isoformat()}")
    print()

    try:
        response = requests.post(
            RAILWAY_API_URL,
            json=payload,
            headers=headers,
            timeout=300  # 5 minute timeout (workflow can be slow)
        )

        print(f"📨 Response Status: {response.status_code}")
        print()

        # Parse response
        try:
            response_data = response.json()
        except json.JSONDecodeError:
            print("❌ ERROR: Response is not valid JSON")
            print(f"Raw response: {response.text[:500]}")
            sys.exit(1)

        # Check if successful
        if response.status_code == 200:
            print("=" * 80)
            print("✅ SUCCESS - Ad Creation Workflow Completed")
            print("=" * 80)
            print()

            # Extract key metrics
            success = response_data.get('success', False)
            ad_run_id = response_data.get('ad_run_id')
            data = response_data.get('data', {})

            print(f"Success: {success}")
            print(f"Ad Run ID: {ad_run_id}")
            print()

            if data:
                print("WORKFLOW SUMMARY:")
                print("-" * 80)
                print(f"Product: {data.get('product', {}).get('name', 'Unknown')}")
                print(f"Reference Ad: {data.get('reference_ad_path', 'N/A')}")
                print()

                # Generated ads summary
                generated_ads = data.get('generated_ads', [])
                approved_count = data.get('approved_count', 0)
                rejected_count = data.get('rejected_count', 0)
                flagged_count = data.get('flagged_count', 0)

                print(f"📊 RESULTS:")
                print(f"   Total Ads Generated: {len(generated_ads)}")
                print(f"   ✅ Approved: {approved_count}")
                print(f"   ❌ Rejected: {rejected_count}")
                print(f"   🚩 Flagged: {flagged_count}")
                print()

                # Individual ad details
                print("GENERATED ADS:")
                print("-" * 80)
                for i, ad in enumerate(generated_ads, 1):
                    status = ad.get('final_status', 'unknown')
                    prompt_idx = ad.get('prompt_index', '?')
                    storage_path = ad.get('storage_path', 'N/A')

                    status_emoji = {
                        'approved': '✅',
                        'rejected': '❌',
                        'flagged': '🚩'
                    }.get(status, '❓')

                    print(f"Ad {i} (Prompt {prompt_idx}): {status_emoji} {status.upper()}")
                    print(f"   Path: {storage_path}")

                    # Claude review
                    claude_review = ad.get('claude_review', {})
                    if claude_review:
                        print(f"   Claude: {claude_review.get('status', 'N/A')}")

                    # Gemini review
                    gemini_review = ad.get('gemini_review', {})
                    if gemini_review:
                        print(f"   Gemini: {gemini_review.get('status', 'N/A')}")

                    print()

                # Summary
                summary = data.get('summary', '')
                if summary:
                    print("SUMMARY:")
                    print("-" * 80)
                    print(summary)
                    print()

            print("=" * 80)
            print(f"⏰ Completed at: {datetime.now().isoformat()}")
            print("=" * 80)

        else:
            # Error response
            print("=" * 80)
            print("❌ ERROR - Request Failed")
            print("=" * 80)
            print()
            print(f"Status Code: {response.status_code}")
            print(f"Error: {response_data.get('error', 'Unknown error')}")
            print(f"Detail: {response_data.get('detail', 'N/A')}")
            print(f"Timestamp: {response_data.get('timestamp', 'N/A')}")
            print()

            # Full response for debugging
            print("FULL RESPONSE:")
            print("-" * 80)
            print(json.dumps(response_data, indent=2))
            print()

            sys.exit(1)

    except requests.exceptions.Timeout:
        print("❌ ERROR: Request timed out after 5 minutes")
        print("The workflow may still be running on Railway.")
        sys.exit(1)

    except requests.exceptions.RequestException as e:
        print(f"❌ ERROR: Request failed - {e}")
        sys.exit(1)

    except KeyboardInterrupt:
        print("\n⚠️  Test interrupted by user")
        sys.exit(1)


if __name__ == "__main__":
    test_railway_api()
