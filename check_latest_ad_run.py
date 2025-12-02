"""
Check the latest ad run and its generated ads in Supabase.
"""
import os
from supabase import create_client

# Initialize Supabase client
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("SUPABASE_URL and SUPABASE_KEY environment variables must be set")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

print("=" * 80)
print("LATEST AD RUN CHECK")
print("=" * 80)

# Get the most recent ad run
response = supabase.table("ad_runs").select("*").order("created_at", desc=True).limit(1).execute()

if not response.data:
    print("\n❌ No ad runs found in database")
    exit(1)

ad_run = response.data[0]
print(f"\n📋 Latest Ad Run:")
print(f"   ID: {ad_run['id']}")
print(f"   Product ID: {ad_run['product_id']}")
print(f"   Status: {ad_run['status']}")
print(f"   Created: {ad_run['created_at']}")
print(f"   Reference Ad: {ad_run.get('reference_ad_storage_path', 'N/A')}")

# Get generated ads for this run
gen_ads_response = supabase.table("generated_ads").select("*").eq("ad_run_id", ad_run['id']).execute()

print(f"\n🎨 Generated Ads: {len(gen_ads_response.data)} ads")

if gen_ads_response.data:
    for ad in gen_ads_response.data:
        print(f"\n   Ad #{ad['prompt_index']}:")
        print(f"      Storage Path: {ad['storage_path']}")
        print(f"      Final Status: {ad['final_status']}")
        print(f"      Hook: {ad.get('hook_text', 'N/A')[:60]}...")
else:
    print("\n   ❌ No generated ads found for this run")

# Check Supabase Storage
print(f"\n📦 Checking Storage Buckets...")
try:
    buckets = supabase.storage.list_buckets()
    print(f"   Available buckets: {[b['name'] for b in buckets]}")

    # Try to list files in generated-ads bucket
    for bucket_name in ['generated-ads', 'generated_ads', 'ads']:
        try:
            files = supabase.storage.from_(bucket_name).list()
            print(f"\n   Bucket '{bucket_name}' contents: {len(files)} items")
            if files:
                for f in files[:5]:  # Show first 5
                    print(f"      - {f['name']}")
        except Exception as e:
            print(f"   Bucket '{bucket_name}': {str(e)}")

except Exception as e:
    print(f"   ❌ Storage check failed: {str(e)}")

print("\n" + "=" * 80)
