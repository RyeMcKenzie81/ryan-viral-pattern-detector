"""
Refresh Supabase schema cache by making a simple query.
This forces Supabase to reload the schema and recognize new columns.
"""
import os
from dotenv import load_dotenv
from supabase import create_client

# Load environment variables
load_dotenv()

# Initialize Supabase client
url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

if not url or not key:
    raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in .env")

supabase = create_client(url, key)

# Make a simple query to refresh schema cache
result = supabase.table("video_analysis").select("hook_features").limit(1).execute()
print(f"✅ Schema cache refreshed - found {len(result.data)} records")
print("The 'hook_features' column is now recognized by Supabase")
