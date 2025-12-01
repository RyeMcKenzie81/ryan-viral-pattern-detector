"""
Migration script to fix reference_ad_storage_path in ad_runs table.

The workflow was storing "temp" instead of the actual path.
This script finds the correct path from storage and updates the database.
"""

import sys
sys.path.insert(0, '/Users/ryemckenzie/projects/viraltracker')

from viraltracker.core.database import get_supabase_client


def fix_reference_ad_paths():
    db = get_supabase_client()

    # Get all ad runs with "temp" as reference path
    runs = db.table('ad_runs').select('id').eq('reference_ad_storage_path', 'temp').execute()
    print(f"Found {len(runs.data)} ad runs with 'temp' reference path")

    if not runs.data:
        print("Nothing to fix!")
        return

    # Get all files in reference-ads bucket
    files = db.storage.from_('reference-ads').list()
    file_names = [f.get('name') for f in files if f.get('name')]
    print(f"Found {len(file_names)} files in reference-ads bucket")

    fixed = 0
    not_found = 0

    for run in runs.data:
        run_id = run['id']

        # Find matching file (starts with ad_run_id)
        matching_files = [f for f in file_names if f.startswith(run_id)]

        if matching_files:
            # Use the first match (should only be one)
            correct_path = f"reference-ads/{matching_files[0]}"

            db.table('ad_runs').update({
                'reference_ad_storage_path': correct_path
            }).eq('id', run_id).execute()

            print(f"  ✓ Fixed {run_id[:8]}... -> {matching_files[0]}")
            fixed += 1
        else:
            print(f"  ✗ No file found for {run_id[:8]}...")
            not_found += 1

    print()
    print(f"Migration complete!")
    print(f"  Fixed: {fixed}")
    print(f"  Not found: {not_found}")


if __name__ == '__main__':
    print("=" * 60)
    print("Fix Reference Ad Paths Migration")
    print("=" * 60)
    print()
    fix_reference_ad_paths()
