"""Quick script to verify social proof in latest ad run."""
import os
import sys
from supabase import create_client

# Get Supabase credentials from environment
url = os.environ.get('SUPABASE_URL')
key = os.environ.get('SUPABASE_KEY')

if not url or not key:
    print("ERROR: SUPABASE_URL and SUPABASE_KEY must be set")
    sys.exit(1)

supabase = create_client(url, key)

# Get the latest ad run
ad_run_id = "78600e8b-6314-49e3-b916-aa406a27aec5"

# Fetch generated ads
response = supabase.table('generated_ads').select('*').eq('ad_run_id', ad_run_id).execute()

print(f"\n{'='*80}")
print(f"AD RUN: {ad_run_id}")
print(f"Total Ads: {len(response.data)}")
print(f"{'='*80}\n")

# Check each ad for social proof
for i, ad in enumerate(response.data, 1):
    headline = ad.get('headline', '')
    body = ad.get('body_copy', '')

    has_social_proof = '100,000' in headline or '100,000' in body

    print(f"Ad {i}: {'✅ HAS SOCIAL PROOF' if has_social_proof else '❌ NO SOCIAL PROOF'}")
    print(f"  Headline: {headline}")
    print(f"  Body (first 100 chars): {body[:100]}...")
    print()
