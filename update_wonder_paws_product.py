"""
Update Wonder Paws Collagen product with Phase 6 constraint fields.

This script populates the new product constraint fields with refined data:
- Simplified current_offer (no subscription details)
- Brand voice (warm and pet-friendly)
- Unique selling points from PDP and hooks
- NO prohibited_claims or required_disclaimers for this brand
"""
import os
from supabase import create_client, Client

# Initialize Supabase client
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("SUPABASE_URL and SUPABASE_KEY environment variables must be set")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Wonder Paws product ID
PRODUCT_ID = "83166c93-632f-47ef-a929-922230e05f82"

# Updated product constraints
product_update = {
    "current_offer": "Up to 35% off",
    "brand_voice_notes": "Warm, caring, and pet-owner friendly",
    "unique_selling_points": [
        "Three types of grass-fed collagen (Types I, II, III)",
        "Enhanced with hyaluronic acid for joint lubrication",
        "Easy-to-use liquid drops - no pills",
        "Supports joints, coat, skin, and nails all in one",
        "Made with natural ingredients",
        "Fast-acting formula - see results in weeks"
    ],
    # Explicitly setting these to NULL (they're not needed for this brand)
    "prohibited_claims": None,
    "required_disclaimers": None
}

print("Updating Wonder Paws Collagen product with Phase 6 constraints...")
print(f"Product ID: {PRODUCT_ID}")
print("\nNew data:")
print(f"  current_offer: {product_update['current_offer']}")
print(f"  brand_voice_notes: {product_update['brand_voice_notes']}")
print(f"  unique_selling_points: {len(product_update['unique_selling_points'])} USPs")
for usp in product_update['unique_selling_points']:
    print(f"    - {usp}")
print(f"  prohibited_claims: {product_update['prohibited_claims']}")
print(f"  required_disclaimers: {product_update['required_disclaimers']}")

# Update the product
response = supabase.table("products").update(product_update).eq("id", PRODUCT_ID).execute()

if response.data:
    print("\n✅ Product updated successfully!")
    print(f"   Updated {len(response.data)} row(s)")
else:
    print("\n❌ Update failed!")
    print(f"   Response: {response}")
