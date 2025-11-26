"""
Debug Supabase storage download issue for Phase 5
"""
import os
import asyncio
from viraltracker.core.database import get_supabase_client

async def debug_storage():
    """Diagnose storage bucket access issues"""

    # Get Supabase client
    supabase = get_supabase_client()

    # The path from the error
    storage_path = "reference-ads/e467a89b-0686-47ae-8a79-82541c6be077_test_reference.png"

    # Parse bucket and file path
    parts = storage_path.split("/", 1)
    bucket = parts[0]
    file_path = parts[1] if len(parts) > 1 else storage_path

    print(f"=== SUPABASE STORAGE DEBUG ===")
    print(f"Bucket: {bucket}")
    print(f"File path: {file_path}")
    print(f"SUPABASE_URL: {os.getenv('SUPABASE_URL')}")
    print()

    # Step 1: List all buckets
    print("STEP 1: Listing all buckets...")
    try:
        buckets = supabase.storage.list_buckets()
        print(f"✅ Found {len(buckets)} buckets:")
        for b in buckets:
            # Handle both dict and object responses
            if isinstance(b, dict):
                print(f"  - {b.get('name')} (id: {b.get('id')}, public: {b.get('public')})")
            else:
                print(f"  - {b.name} (id: {b.id}, public: {b.public})")

        # Check if our bucket exists
        if isinstance(buckets[0], dict):
            bucket_names = [b.get('name') for b in buckets]
        else:
            bucket_names = [b.name for b in buckets]

        if bucket in bucket_names:
            print(f"✅ Bucket '{bucket}' exists")
        else:
            print(f"❌ Bucket '{bucket}' NOT FOUND!")
            print(f"   Available buckets: {bucket_names}")
            return
    except Exception as e:
        print(f"❌ Error listing buckets: {str(e)}")
        import traceback
        traceback.print_exc()
        return

    print()

    # Step 2: List files in the bucket
    print(f"STEP 2: Listing files in bucket '{bucket}'...")
    try:
        files = supabase.storage.from_(bucket).list()
        print(f"✅ Found {len(files)} files:")
        for f in files:
            print(f"  - {f.get('name')} (size: {f.get('metadata', {}).get('size')} bytes)")

        # Check if our file exists
        file_names = [f.get('name') for f in files]
        if file_path in file_names:
            print(f"✅ File '{file_path}' exists")
        else:
            print(f"❌ File '{file_path}' NOT FOUND!")
            print(f"   Available files: {file_names}")
    except Exception as e:
        print(f"❌ Error listing files: {str(e)}")

    print()

    # Step 3: Try to get public URL
    print(f"STEP 3: Getting public URL...")
    try:
        public_url = supabase.storage.from_(bucket).get_public_url(file_path)
        print(f"✅ Public URL: {public_url}")
    except Exception as e:
        print(f"❌ Error getting public URL: {str(e)}")

    print()

    # Step 4: Try to download the file
    print(f"STEP 4: Attempting to download file...")
    try:
        data = supabase.storage.from_(bucket).download(file_path)
        print(f"✅ Download successful!")
        print(f"   Data type: {type(data)}")
        print(f"   Data length: {len(data)} bytes")

        # Check if it's HTML (error page)
        if isinstance(data, bytes):
            preview = data[:200].decode('utf-8', errors='ignore')
            if preview.startswith('<!DOCTYPE') or preview.startswith('<html'):
                print(f"❌ WARNING: Downloaded data is HTML, not image!")
                print(f"   Preview: {preview}")
            else:
                print(f"✅ Data appears to be binary (image)")
        else:
            print(f"❌ WARNING: Data is not bytes, it's {type(data)}")
            print(f"   Content: {str(data)[:200]}")
    except Exception as e:
        print(f"❌ Error downloading file: {str(e)}")
        import traceback
        traceback.print_exc()

    print()
    print("=== DEBUG COMPLETE ===")

if __name__ == "__main__":
    asyncio.run(debug_storage())
