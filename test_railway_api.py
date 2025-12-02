"""
Test the Railway production API endpoint for ad creation.
"""
import base64
import requests
import json
from pathlib import Path

# Railway API URL
API_URL = "https://ryan-viral-pattern-detector-production.up.railway.app"

# Test product ID (Wonder Paws Collagen 3X)
PRODUCT_ID = "83166c93-632f-47ef-a929-922230e05f82"

# Reference ad image
REFERENCE_AD_PATH = Path(__file__).parent / "test_images" / "reference_ads" / "ad3-example.jpg"

def test_ad_creation_endpoint():
    """Test the /api/ad-creation/create endpoint on Railway."""

    print("=" * 80)
    print("TESTING RAILWAY PRODUCTION API ENDPOINT")
    print("=" * 80)
    print(f"\nAPI URL: {API_URL}")
    print(f"Endpoint: POST /api/ad-creation/create")
    print(f"Product ID: {PRODUCT_ID}")
    print(f"Reference Ad: {REFERENCE_AD_PATH.name}")
    print()

    # Read and encode the reference ad
    print("📸 Reading and encoding reference ad...")
    with open(REFERENCE_AD_PATH, 'rb') as f:
        image_data = base64.b64encode(f.read()).decode('utf-8')
    print(f"   ✅ Encoded {len(image_data)} characters of base64 data")

    # Prepare request payload
    payload = {
        "product_id": PRODUCT_ID,
        "reference_ad_base64": image_data,
        "reference_ad_filename": REFERENCE_AD_PATH.name
    }

    # Make the request
    print(f"\n🚀 Sending POST request to {API_URL}/api/ad-creation/create...")
    print("   This will take several minutes as the agent:")
    print("   1. Uploads reference ad to Supabase")
    print("   2. Analyzes it with Claude vision")
    print("   3. Retrieves product data and hooks")
    print("   4. Generates 5 ads with Gemini")
    print("   5. Reviews each ad with Claude + Gemini")
    print("   6. Saves approved ads to database")
    print()

    try:
        response = requests.post(
            f"{API_URL}/api/ad-creation/create",
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=600  # 10 minute timeout for long-running workflow
        )

        print(f"\n📊 Response Status: {response.status_code}")
        print(f"📊 Response Headers: {dict(response.headers)}")

        if response.status_code == 200:
            result = response.json()
            print("\n" + "=" * 80)
            print("✅ SUCCESS - Ad Creation Workflow Completed!")
            print("=" * 80)
            print(f"\n📋 Ad Run ID: {result.get('ad_run_id')}")
            print(f"📋 Status: {result.get('status')}")
            print(f"\n📊 Generated Ads: {len(result.get('generated_ads', []))}")
            print(f"✅ Approved: {result.get('approved_count', 0)}")
            print(f"❌ Rejected: {result.get('rejected_count', 0)}")
            print(f"⚠️  Flagged: {result.get('flagged_count', 0)}")

            # Show details of each ad
            print("\n" + "=" * 80)
            print("GENERATED ADS DETAILS")
            print("=" * 80)
            for i, ad in enumerate(result.get('generated_ads', []), 1):
                print(f"\n[Ad {i}]")
                print(f"  ID: {ad.get('id')}")
                print(f"  Status: {ad.get('status')}")
                print(f"  Claude Approved: {ad.get('claude_approved')}")
                print(f"  Gemini Approved: {ad.get('gemini_approved')}")
                print(f"  Image URL: {ad.get('image_url', 'N/A')[:80]}...")
                if ad.get('ad_copy'):
                    print(f"  Ad Copy: {ad.get('ad_copy')[:100]}...")

            print("\n" + "=" * 80)
            print("✅ RAILWAY API TEST PASSED!")
            print("=" * 80)

            # Save full response to file
            output_file = Path.home() / "Downloads" / "railway_api_test_response.json"
            with open(output_file, 'w') as f:
                json.dump(result, f, indent=2)
            print(f"\n💾 Full response saved to: {output_file}")

            return True

        else:
            print("\n" + "=" * 80)
            print("❌ FAILED - API Request Failed")
            print("=" * 80)
            print(f"\nStatus Code: {response.status_code}")
            print(f"Response Body:\n{response.text}")
            return False

    except requests.exceptions.Timeout:
        print("\n❌ ERROR: Request timed out after 10 minutes")
        print("   The workflow may still be running on the server.")
        return False

    except Exception as e:
        print(f"\n❌ ERROR: {type(e).__name__}: {str(e)}")
        return False


if __name__ == "__main__":
    success = test_ad_creation_endpoint()
    exit(0 if success else 1)
