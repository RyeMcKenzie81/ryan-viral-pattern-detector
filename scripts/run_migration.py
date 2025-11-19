#!/usr/bin/env python3
"""
Run SQL Migration Script

Usage:
    python scripts/run_migration.py migrations/2025-10-31_add_generated_content.sql
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from viraltracker.core.database import get_supabase_client


def run_migration(sql_file: str):
    """Run a SQL migration file"""

    print(f"Running migration: {sql_file}")

    # Read SQL file
    try:
        with open(sql_file, 'r') as f:
            sql = f.read()
    except FileNotFoundError:
        print(f"Error: File not found: {sql_file}")
        sys.exit(1)

    # Get Supabase client
    try:
        db = get_supabase_client()
        print("✓ Connected to database")
    except Exception as e:
        print(f"Error connecting to database: {e}")
        sys.exit(1)

    # Run migration using RPC call to execute SQL
    try:
        # Supabase Python client doesn't support raw SQL execution
        # We need to use the underlying PostgREST connection
        # For now, print instructions for manual execution

        print("\n" + "="*60)
        print("MIGRATION SQL")
        print("="*60)
        print(sql)
        print("="*60)
        print("\nIMPORTANT: The Supabase Python client doesn't support raw SQL execution.")
        print("Please run this migration manually using one of these methods:")
        print("\n1. Supabase Dashboard:")
        print("   - Go to your Supabase project dashboard")
        print("   - Navigate to SQL Editor")
        print("   - Paste and run the SQL above")
        print("\n2. PostgreSQL CLI (psql):")
        print(f"   psql <connection_string> -f {sql_file}")
        print("\n3. Database GUI tool (pgAdmin, TablePlus, etc.)")
        print("   - Connect to your Supabase database")
        print(f"   - Run the SQL from: {sql_file}")

    except Exception as e:
        print(f"Error running migration: {e}")
        sys.exit(1)


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print("Usage: python scripts/run_migration.py <sql_file>")
        sys.exit(1)

    sql_file = sys.argv[1]
    run_migration(sql_file)
