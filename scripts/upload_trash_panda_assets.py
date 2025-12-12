#!/usr/bin/env python3
"""
Upload Trash Panda assets to Supabase.

Uploads all assets from /Downloads/assets-2/ with proper categorization.
Excludes candlestick charts (too complex for beginner audience).
"""

import os
import asyncio
from pathlib import Path
from uuid import UUID

# Add both project paths
import sys
# Main viraltracker (for core.database)
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
# Planning subfolder (for content_pipeline services)
sys.path.insert(0, str(Path(__file__).parent.parent))

from viraltracker.core.database import get_supabase_client
from viraltracker.services.content_pipeline.services.asset_service import AssetManagementService

# Configuration
ASSETS_DIR = Path("/Users/ryemckenzie/Downloads/assets-2")
BRAND_NAME = "Trash Panda Economics"

# Files to exclude (by full path to be specific)
EXCLUDE_FILES = {
    "Green Candle (Price Up).png",
    "Red Candle (Price Down).png",
}

# Root-level files to skip (duplicates)
SKIP_ROOT_FILES = {
    "Core-assets.png",  # Duplicate - use the one in characters/ instead
}

# Folder to asset type mapping
FOLDER_TYPE_MAP = {
    "characters": "character",
    "backgrounds": "background",
    "Props": "prop",
    "Commodities": "prop",
    "Currency": "prop",
    "The Tech": "prop",
    "charts & UI": "prop",
}

# Core assets (main characters that should be marked as core)
CORE_ASSET_NAMES = {
    "core-assets",  # The expression sheet
    "whale",
    "boomer-facing-right",
    "thechad",
    "the-gov-fed",
    "bull",
    "bear",
    "the-bag-holder",
    "degenerate",
    "mini-raccoon-thief",
}

# Tags based on folder
FOLDER_TAGS = {
    "characters": ["character", "main-cast"],
    "backgrounds": ["background", "scene"],
    "Props": ["prop", "item"],
    "Commodities": ["prop", "food", "commodity"],
    "Currency": ["prop", "money", "currency"],
    "The Tech": ["prop", "tech", "device"],
    "charts & UI": ["prop", "chart", "ui"],
}


def get_brand_id(supabase) -> str:
    """Get the brand ID for Trash Panda Economics."""
    result = supabase.table("brands").select("id").eq("name", BRAND_NAME).execute()
    if not result.data:
        raise ValueError(f"Brand '{BRAND_NAME}' not found")
    return result.data[0]["id"]


def normalize_name(filename: str) -> str:
    """Convert filename to normalized asset name."""
    # Remove extension
    name = Path(filename).stem
    # Replace special characters
    name = name.replace("_", "-").replace(" ", "-").replace("(", "").replace(")", "")
    # Remove quotes
    name = name.replace("'", "").replace('"', "")
    # Lowercase
    name = name.lower()
    # Remove double dashes
    while "--" in name:
        name = name.replace("--", "-")
    # Strip leading/trailing dashes
    name = name.strip("-")
    return name


def get_content_type(filename: str) -> str:
    """Get MIME type from filename."""
    ext = Path(filename).suffix.lower()
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }.get(ext, "image/png")


def collect_assets() -> list[dict]:
    """Collect all assets to upload."""
    assets = []

    for folder_name, asset_type in FOLDER_TYPE_MAP.items():
        folder_path = ASSETS_DIR / folder_name
        if not folder_path.exists():
            print(f"Warning: Folder not found: {folder_path}")
            continue

        for file_path in folder_path.iterdir():
            if file_path.is_file() and file_path.suffix.lower() in [".png", ".jpg", ".jpeg", ".webp"]:
                filename = file_path.name

                # Skip excluded files
                if filename in EXCLUDE_FILES:
                    print(f"Skipping excluded: {filename}")
                    continue

                name = normalize_name(filename)
                is_core = name in CORE_ASSET_NAMES
                tags = FOLDER_TAGS.get(folder_name, ["imported"])

                assets.append({
                    "path": file_path,
                    "name": name,
                    "type": asset_type,
                    "tags": tags,
                    "is_core": is_core,
                    "folder": folder_name,
                })

    return assets


async def upload_assets():
    """Upload all assets to Supabase."""
    print("=" * 60)
    print("Trash Panda Assets Uploader")
    print("=" * 60)

    # Initialize
    supabase = get_supabase_client()
    brand_id = get_brand_id(supabase)
    print(f"Brand ID: {brand_id}")

    service = AssetManagementService(supabase_client=supabase)

    # Collect assets
    assets = collect_assets()
    print(f"\nFound {len(assets)} assets to upload")
    print("-" * 60)

    # Group by type for display
    by_type = {}
    for asset in assets:
        t = asset["type"]
        if t not in by_type:
            by_type[t] = []
        by_type[t].append(asset["name"])

    for t, names in by_type.items():
        print(f"\n{t.upper()} ({len(names)}):")
        for name in sorted(names):
            core_marker = " [CORE]" if name in CORE_ASSET_NAMES else ""
            print(f"  - {name}{core_marker}")

    print("\n" + "-" * 60)
    input("Press Enter to start upload (Ctrl+C to cancel)...")
    print()

    # Upload each asset
    successful = 0
    failed = 0

    for i, asset in enumerate(assets, 1):
        try:
            print(f"[{i}/{len(assets)}] Uploading {asset['name']}...", end=" ")

            # Read file
            with open(asset["path"], "rb") as f:
                file_data = f.read()

            content_type = get_content_type(asset["path"].name)

            # Upload
            asset_id = await service.upload_asset_with_file(
                brand_id=UUID(brand_id),
                name=asset["name"],
                asset_type=asset["type"],
                file_data=file_data,
                filename=asset["path"].name,
                content_type=content_type,
                tags=asset["tags"],
                is_core_asset=asset["is_core"],
            )

            print(f"OK (id={asset_id})")
            successful += 1

        except Exception as e:
            print(f"FAILED: {e}")
            failed += 1

    print("\n" + "=" * 60)
    print(f"Upload complete: {successful} successful, {failed} failed")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(upload_assets())
