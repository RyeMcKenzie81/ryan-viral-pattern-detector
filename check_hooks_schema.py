"""
Check the hooks table schema to understand the constraints
"""
from viraltracker.core.database import get_supabase_client

supabase = get_supabase_client()

# Test with emotional_score = 0
print("Testing with emotional_score = 0...")
for impact in [0, 1, 5, 10]:
    test_hook = {
        "product_id": "83166c93-632f-47ef-a929-922230e05f82",
        "text": f"Test hook impact={impact} emotional=0",
        "category": "test",
        "framework": "Test",
        "impact_score": impact,
        "emotional_score": 0,
        "active": True
    }

    try:
        result = supabase.table("hooks").insert(test_hook).execute()
        print(f"✅ Success with impact={impact}, emotional=0")
        # Delete the test hook
        hook_id = result.data[0]["id"]
        supabase.table("hooks").delete().eq("id", hook_id).execute()
    except Exception as e:
        error_msg = str(e)
        if "emotional_score" in error_msg:
            print(f"❌ Failed with impact={impact}, emotional=0: EMOTIONAL_SCORE constraint")
        elif "impact_score" in error_msg:
            print(f"❌ Failed with impact={impact}, emotional=0: IMPACT_SCORE constraint")
        else:
            print(f"❌ Failed with impact={impact}, emotional=0: {error_msg[:150]}")

# Maybe emotional_score shouldn't be included at all?
print("\nTesting WITHOUT emotional_score field...")
test_hook = {
    "product_id": "83166c93-632f-47ef-a929-922230e05f82",
    "text": "Test hook without emotional_score",
    "category": "test",
    "framework": "Test",
    "impact_score": 5,
    "active": True
}

try:
    result = supabase.table("hooks").insert(test_hook).execute()
    print("✅ Success without emotional_score field!")
    print(f"   Inserted hook: {result.data[0]}")
    # Delete the test hook
    hook_id = result.data[0]["id"]
    supabase.table("hooks").delete().eq("id", hook_id).execute()
except Exception as e:
    print(f"❌ Failed: {str(e)[:200]}")
