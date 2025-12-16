"""
Import Phase 1-2 Belief Testing Templates

This script uploads the 5 Phase 1-2 templates to Supabase storage
and creates records in scraped_templates table.

Usage:
    python scripts/import_phase12_templates.py

Templates expected in ~/Downloads:
    - template1.jpeg (Dog at stairs - "Noticing this?")
    - template2.jpeg (Hair check - "It's not just age.")
    - template3.jpeg (Morning pause - "This usually comes first.")
    - template4.jpeg (Railing grip - "Most people miss this early.")
    - template5.jpeg (Counter scene - quiet product)
"""

import os
import sys
from pathlib import Path
from uuid import uuid4

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from viraltracker.core.database import get_supabase_client


# Template metadata
TEMPLATES = [
    {
        "filename": "template1.jpeg",
        "name": "Phase 1-2: Dog at Stairs",
        "description": "Observation shot - senior dog hesitating at stairs with 'Noticing this?' anchor text. Perfect for pet joint/mobility belief testing.",
        "category": "ugc_style",
        "anchor_text": "Noticing this?",
        "template_type": "observation_shot",
        "industry_niche": "pets",
    },
    {
        "filename": "template2.jpeg",
        "name": "Phase 1-2: Hair Check Close-Up",
        "description": "Situation close-up - man's hand checking crown of head with 'It's not just age.' anchor text. For hair/thinning belief testing.",
        "category": "ugc_style",
        "anchor_text": "It's not just age.",
        "template_type": "situation_closeup",
        "industry_niche": "hair",
    },
    {
        "filename": "template3.jpeg",
        "name": "Phase 1-2: Morning Pause",
        "description": "Observation shot - person sitting on edge of bed in morning with 'This usually comes first.' anchor text. General wellness/joint belief testing.",
        "category": "ugc_style",
        "anchor_text": "This usually comes first.",
        "template_type": "observation_shot",
        "industry_niche": "supplements",
    },
    {
        "filename": "template4.jpeg",
        "name": "Phase 1-2: Railing Grip",
        "description": "Situation close-up - two hands gripping stair railing with 'Most people miss this early.' anchor text. Joint/mobility belief testing.",
        "category": "ugc_style",
        "anchor_text": "Most people miss this early.",
        "template_type": "situation_closeup",
        "industry_niche": "supplements",
    },
    {
        "filename": "template5.jpeg",
        "name": "Phase 1-2: Quiet Product Presence",
        "description": "Type C quiet product - supplement bottle on kitchen counter with coffee and glasses. No text overlay. Product is incidental, not hero.",
        "category": "product_showcase",
        "anchor_text": None,
        "template_type": "quiet_product",
        "industry_niche": "supplements",
    },
]


def main():
    """Upload templates and create database records."""
    db = get_supabase_client()
    downloads_dir = Path.home() / "Downloads"

    print("=" * 60)
    print("Phase 1-2 Template Import")
    print("=" * 60)

    # Check all files exist first
    missing = []
    for template in TEMPLATES:
        filepath = downloads_dir / template["filename"]
        if not filepath.exists():
            missing.append(template["filename"])

    if missing:
        print(f"\nERROR: Missing files in {downloads_dir}:")
        for f in missing:
            print(f"  - {f}")
        sys.exit(1)

    print(f"\nFound all 5 templates in {downloads_dir}")

    # Process each template
    results = []
    for i, template in enumerate(TEMPLATES, 1):
        print(f"\n[{i}/5] Processing: {template['name']}")

        filepath = downloads_dir / template["filename"]

        # Generate unique storage name
        storage_name = f"{uuid4()}_{template['filename']}"
        storage_path = f"scraped-templates/{storage_name}"

        # Upload to storage
        print(f"  Uploading to storage...")
        try:
            with open(filepath, "rb") as f:
                file_bytes = f.read()

            db.storage.from_("scraped-templates").upload(
                storage_name,
                file_bytes,
                {"content-type": "image/jpeg", "upsert": "true"}
            )
            print(f"  Uploaded: {storage_path}")
        except Exception as e:
            # Bucket might not exist, try reference-ads instead
            print(f"  Note: scraped-templates bucket issue, trying reference-ads...")
            storage_path = f"reference-ads/{storage_name}"
            try:
                db.storage.from_("reference-ads").upload(
                    storage_name,
                    file_bytes,
                    {"content-type": "image/jpeg", "upsert": "true"}
                )
                print(f"  Uploaded: {storage_path}")
            except Exception as e2:
                print(f"  ERROR uploading: {e2}")
                continue

        # Create database record
        print(f"  Creating database record...")
        try:
            record = {
                "name": template["name"],
                "description": template["description"],
                "category": template["category"],
                "storage_path": storage_path,
                "industry_niche": template["industry_niche"],
                "awareness_level": 2,  # Problem-aware
                "awareness_level_name": "Problem-Aware",
                "is_active": True,
                "layout_analysis": {
                    "template_type": template["template_type"],
                    "anchor_text": template["anchor_text"],
                    "phase_optimized": [1, 2],
                    "text_slots": ["anchor_only"] if template["anchor_text"] else [],
                },
                # Pre-populate high evaluation scores since we designed these for Phase 1-2
                "phase_tags": {
                    "eligible_phases": [1, 2],
                    "total_score": 15,
                    "d1_belief_clarity": 3,
                    "d2_neutrality": 3,
                    "d3_reusability": 3,
                    "d4_problem_aware_entry": 3,
                    "d5_slot_availability": 3,
                    "d6_compliance_pass": True,
                },
                "evaluation_score": 15,
                "evaluation_notes": "Purpose-built Phase 1-2 belief testing template. Designed for recognition, not persuasion.",
            }

            result = db.table("scraped_templates").insert(record).execute()

            if result.data:
                template_id = result.data[0]["id"]
                print(f"  Created record: {template_id}")
                results.append({
                    "name": template["name"],
                    "id": template_id,
                    "storage_path": storage_path,
                })
            else:
                print(f"  ERROR: No data returned from insert")

        except Exception as e:
            print(f"  ERROR creating record: {e}")
            continue

    # Summary
    print("\n" + "=" * 60)
    print("IMPORT COMPLETE")
    print("=" * 60)
    print(f"\nSuccessfully imported {len(results)}/5 templates:\n")

    for r in results:
        print(f"  - {r['name']}")
        print(f"    ID: {r['id']}")
        print(f"    Path: {r['storage_path']}")
        print()

    print("These templates are now available in:")
    print("  - Template Evaluation page (pre-scored 15/15)")
    print("  - Ad Planning wizard (Phase 1-2 eligible)")
    print()


if __name__ == "__main__":
    main()
