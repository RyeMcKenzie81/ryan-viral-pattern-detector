"""
Upload Wonder Paws product images to Supabase storage and link to test product.

Run with:
    python upload_wonder_paws_images.py
"""
import asyncio
from pathlib import Path
from uuid import UUID
from viraltracker.core.database import get_supabase_client

# Test product ID
PRODUCT_ID = "83166c93-632f-47ef-a929-922230e05f82"

# Image files in test_images/wonder_paws/
IMAGE_FILES = [
    "test_images/wonder_paws/Collagen (1).jpg",
    "test_images/wonder_paws/hi_res-1d-Pollyana Abdalla_r1_01I_0576-Collagen.jpg",
    "test_images/wonder_paws/hi_res-1e-Pollyana Abdalla_r1_01E_2058-Collagen.jpg",
    "test_images/wonder_paws/hi_res-5b-Pollyana Abdalla_r1_01I_0890-Collagen.jpg",
]

# Storage bucket for product images
BUCKET = "product-images"


async def upload_product_images():
    """Upload product images to storage and update product record"""
    supabase = get_supabase_client()

    print(f"Uploading {len(IMAGE_FILES)} product images to Supabase storage...")

    # First, verify product exists
    product_check = supabase.table("products").select("*").eq("id", PRODUCT_ID).execute()
    if not product_check.data:
        print(f"❌ Product {PRODUCT_ID} not found in database!")
        return

    print(f"✅ Product found: {product_check.data[0].get('name')}")

    # Upload each image and collect storage paths
    storage_paths = []

    for i, image_path in enumerate(IMAGE_FILES):
        file_path = Path(image_path)

        if not file_path.exists():
            print(f"⚠️  Skipping {file_path.name} - file not found")
            continue

        # Read image data
        with open(file_path, "rb") as f:
            image_data = f.read()

        # Generate storage path: product_id/image_index.jpg
        storage_path = f"{PRODUCT_ID}/product_{i}.jpg"

        try:
            # Upload to Supabase storage (sync API)
            print(f"Uploading {file_path.name} ({len(image_data) / 1024 / 1024:.2f} MB)...")

            # Use upsert to overwrite if already exists
            supabase.storage.from_(BUCKET).upload(
                storage_path,
                image_data,
                {"content-type": "image/jpeg", "upsert": "true"}
            )

            full_storage_path = f"{BUCKET}/{storage_path}"
            storage_paths.append(full_storage_path)
            print(f"✅ Uploaded: {full_storage_path}")

        except Exception as e:
            error_str = str(e)
            if "already exists" in error_str.lower():
                # If file already exists, add to paths anyway
                full_storage_path = f"{BUCKET}/{storage_path}"
                storage_paths.append(full_storage_path)
                print(f"ℹ️  Already exists: {full_storage_path}")
            else:
                print(f"❌ Failed to upload {file_path.name}: {e}")

    if not storage_paths:
        print("❌ No images uploaded successfully!")
        return

    print(f"\n✅ Successfully uploaded {len(storage_paths)} images")

    # Update product with image paths
    # First image becomes main_image_storage_path
    # Remaining images go into reference_image_storage_paths array
    main_image = storage_paths[0]
    reference_images = storage_paths[1:] if len(storage_paths) > 1 else []

    print(f"\nUpdating product record...")
    print(f"  main_image_storage_path: {main_image}")
    print(f"  reference_image_storage_paths: {reference_images}")

    try:
        update_result = supabase.table("products").update({
            "main_image_storage_path": main_image,
            "reference_image_storage_paths": reference_images
        }).eq("id", PRODUCT_ID).execute()

        print(f"\n✅ Product updated successfully!")
        print(f"   Main image: {main_image}")
        print(f"   Reference images: {len(reference_images)}")

    except Exception as e:
        print(f"❌ Failed to update product: {e}")
        return

    print(f"\n🎯 Ready for testing!")
    print(f"   Product {PRODUCT_ID} now has {len(storage_paths)} images")
    print(f"   Run integration test to verify Stage 7 passes")


if __name__ == "__main__":
    asyncio.run(upload_product_images())
