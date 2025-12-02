"""
Upload Savage product images to Supabase storage and link to product.

Run with:
    python upload_savage_images.py
"""
import os
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

SUPABASE_URL = os.environ.get('SUPABASE_URL')
SUPABASE_KEY = os.environ.get('SUPABASE_SERVICE_KEY')

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set")

db = create_client(SUPABASE_URL, SUPABASE_KEY)

# Savage product ID
PRODUCT_ID = "3c85266c-cc62-4c95-9383-a6b7e7b6155e"

# Storage bucket
BUCKET = "product-images"

# Images to upload with metadata
# Format: (filepath, display_name, is_main, sort_order, notes)
IMAGE_FILES = [
    ("test_images/savage/savagefront.jpeg", "Package Front", True, 1, "Front of product pouch - main product shot"),
    ("test_images/savage/WhatsApp Image 2025-11-13 at 14.40.23 (1).jpeg", "Package Back", False, 2, "Back of product pouch with supplement facts and tagline 'Because Testosterone is a Feature Not a Flaw'"),
    ("test_images/savage/WhatsApp Image 2025-11-13 at 14.40.23 (2).jpeg", "Package Front+Back", False, 3, "Both front and back of product pouch visible in single image"),
    ("test_images/savage/SAVAGE_Logo-Black.png", "Logo Black", False, 10, "Black bull skull logo with SAVAGE text"),
    ("test_images/savage/SAVAGE_Logo-BlackRed.png", "Logo Black/Red", False, 11, "Bull skull with Blood Red SAVAGE text"),
    ("test_images/savage/SAVAGE_LogoTagline-Black.png", "Logo with Tagline", False, 12, "Logo with 'Primal Fuel For Men' tagline"),
    ("test_images/savage/SAVAGE_Wordmark-Black.png", "Wordmark", False, 13, "SAVAGE wordmark only in brush font, no skull"),
]


def get_content_type(filename):
    """Get MIME type for file"""
    ext = filename.lower().split('.')[-1]
    return {
        'jpg': 'image/jpeg',
        'jpeg': 'image/jpeg',
        'png': 'image/png',
        'gif': 'image/gif',
        'webp': 'image/webp',
    }.get(ext, 'application/octet-stream')


def upload_product_images():
    """Upload product images to storage and create product_images records"""

    print(f"Uploading {len(IMAGE_FILES)} images for Savage product...")
    print(f"Product ID: {PRODUCT_ID}")
    print()

    # Verify product exists
    product_check = db.table("products").select("name").eq("id", PRODUCT_ID).execute()
    if not product_check.data:
        print(f"Product {PRODUCT_ID} not found!")
        return

    print(f"Product: {product_check.data[0]['name']}")
    print()

    uploaded = 0
    for filepath, display_name, is_main, sort_order, notes in IMAGE_FILES:
        file_path = Path(filepath)

        if not file_path.exists():
            print(f"  Skipping {display_name} - file not found: {filepath}")
            continue

        # Read file
        with open(file_path, "rb") as f:
            file_data = f.read()

        # Generate storage path
        safe_filename = file_path.name.replace(' ', '_').replace('(', '').replace(')', '')
        storage_path = f"{PRODUCT_ID}/{safe_filename}"
        full_storage_path = f"{BUCKET}/{storage_path}"

        print(f"Uploading: {display_name}")
        print(f"  File: {file_path.name} ({len(file_data) / 1024:.1f} KB)")
        print(f"  Storage: {full_storage_path}")

        try:
            # Upload to Supabase storage
            content_type = get_content_type(file_path.name)
            db.storage.from_(BUCKET).upload(
                storage_path,
                file_data,
                {"content-type": content_type, "upsert": "true"}
            )

            # Create product_images record
            image_record = {
                "product_id": PRODUCT_ID,
                "storage_path": full_storage_path,
                "filename": display_name,
                "is_main": is_main,
                "sort_order": sort_order,
                "notes": notes
            }

            # Check if record already exists
            existing = db.table("product_images").select("id").eq(
                "product_id", PRODUCT_ID
            ).eq("storage_path", full_storage_path).execute()

            if existing.data:
                # Update existing
                db.table("product_images").update(image_record).eq("id", existing.data[0]['id']).execute()
                print(f"  Updated existing record")
            else:
                # Insert new
                db.table("product_images").insert(image_record).execute()
                print(f"  Created new record")

            uploaded += 1

        except Exception as e:
            print(f"  Error: {e}")

        print()

    print("=" * 50)
    print(f"UPLOAD COMPLETE: {uploaded}/{len(IMAGE_FILES)} images")
    print("=" * 50)
    print()
    print("Next steps:")
    print("1. View in Brand Manager UI")
    print("2. Run image analysis on product images")
    print("3. Create hooks for the product")


if __name__ == "__main__":
    upload_product_images()
