"""
Populate Wonder Paws Collagen 3X product in Supabase database.

This script:
1. Checks the current database record
2. Updates missing fields with scraped product information
3. Displays the final record
"""

import os
from viraltracker.core.database import get_supabase_client

# Product ID
PRODUCT_ID = "83166c93-632f-47ef-a929-922230e05f82"

# Scraped product data - only fields that match Product model schema
PRODUCT_DATA = {
    "product_url": "https://www.mywonderpaws.com/products/wonder-paws-collagen-3x-for-dogs-ultimate-skin-joint-support",
    "price_range": "$30-43",
    "description": "Triple-action collagen drops for dog joint health and mobility. One-time pricing: 1 bottle $42.85, 2 bottles $34.28/ea, 3 bottles $32.14/ea. Subscription pricing: 1 bottle $34.28, 2 bottles $32.14/ea, 3 bottles $30/ea (20-30% savings).",
    "key_benefits": [
        "Supports hip & joint mobility and flexibility",
        "Promotes shiny, bright and soft coat",
        "Helps reduce allergies and itching",
        "Promotes stronger nails"
    ],
    "key_problems_solved": [
        "Joint mobility issues",
        "Dull coat",
        "Allergies and itching",
        "Weak nails"
    ],
    "features": [
        "Grass-fed collagen peptides (Types I, II, III)",
        "Hyaluronic acid",
        "Liquid tincture formula for easy administration",
        "Triple-action collagen formula",
        "Volume discounts available (up to 25% off)",
        "Subscription option (20-30% savings)"
    ],
}


def main():
    """Check and update the product record."""
    print("=" * 80)
    print("Wonder Paws Collagen 3X - Database Population")
    print("=" * 80)
    print()

    # Initialize Supabase client
    supabase = get_supabase_client()

    # Check current record
    print(f"Checking product record: {PRODUCT_ID}")
    print()

    try:
        response = supabase.table("products").select("*").eq("id", PRODUCT_ID).execute()

        if not response.data:
            print("❌ Product not found in database!")
            print()
            print("Creating new product record...")

            # Insert new product
            insert_data = PRODUCT_DATA.copy()
            insert_data["id"] = PRODUCT_ID

            response = supabase.table("products").insert(insert_data).execute()
            print("✅ Product created successfully!")
        else:
            current_data = response.data[0]
            print("✅ Product found in database!")
            print()
            print("Current record:")
            print("-" * 80)
            for key, value in current_data.items():
                if key not in ["created_at", "updated_at"]:
                    print(f"  {key}: {value}")
            print()

            # Check which fields need updating (force update for description, price_range, features)
            needs_update = False
            update_data = {}
            force_update_fields = ["description", "price_range", "features"]

            for key, value in PRODUCT_DATA.items():
                current_value = current_data.get(key)
                # Force update certain fields, otherwise only update if empty
                if key in force_update_fields or not current_value or current_value == "":
                    if current_value != value:  # Only update if value is different
                        update_data[key] = value
                        needs_update = True

            if needs_update:
                print("Updating fields:")
                print("-" * 80)
                for key, value in update_data.items():
                    print(f"  {key}: {value}")
                print()

                # Update the record
                response = supabase.table("products").update(update_data).eq("id", PRODUCT_ID).execute()
                print("✅ Product updated successfully!")
            else:
                print("✅ All fields already populated - no update needed!")

        # Display final record
        print()
        print("=" * 80)
        print("Final Product Record")
        print("=" * 80)

        response = supabase.table("products").select("*").eq("id", PRODUCT_ID).execute()
        final_data = response.data[0]

        for key, value in final_data.items():
            if key not in ["created_at", "updated_at"]:
                # Truncate long values for display
                if isinstance(value, str) and len(value) > 100:
                    display_value = value[:97] + "..."
                else:
                    display_value = value
                print(f"  {key}: {display_value}")

        print()
        print("=" * 80)
        print("✅ Setup Complete!")
        print("=" * 80)
        print()
        print("Next steps:")
        print("  1. Set the environment variable:")
        print(f'     export TEST_PRODUCT_ID="{PRODUCT_ID}"')
        print()
        print("  2. Run the integration tests:")
        print("     pytest tests/test_ad_creation_integration.py -v")
        print()

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
