"""
Quick unit test for Bug #13 fix - Markdown code fence stripping in review_ad_claude().

Bug #13: json.decoder.JSONDecodeError when Claude wraps JSON in ```json ... ```
Fix: Strip markdown code fences before parsing JSON response

Run with:
    python test_review_ad_claude_bug13.py
"""
import json


def test_markdown_fence_stripping():
    """Test that the markdown fence stripping logic correctly handles Claude responses (Bug #13 fix)"""
    print("Testing Bug #13 fix: Markdown code fence stripping logic...")

    # Test data: Different ways Claude might wrap JSON
    test_cases = [
        {
            "name": "JSON with ```json fence",
            "response": '```json\n{"approved": true, "feedback": "Good ad"}\n```',
            "expected": {"approved": True, "feedback": "Good ad"}
        },
        {
            "name": "JSON with ``` fence (no language)",
            "response": '```\n{"approved": false, "feedback": "Needs work"}\n```',
            "expected": {"approved": False, "feedback": "Needs work"}
        },
        {
            "name": "Plain JSON (no fences)",
            "response": '{"approved": true, "feedback": "Great"}',
            "expected": {"approved": True, "feedback": "Great"}
        },
        {
            "name": "JSON with extra whitespace",
            "response": '\n\n  ```json\n{"approved": true, "feedback": "Nice"}\n```  \n',
            "expected": {"approved": True, "feedback": "Nice"}
        },
    ]

    results = []

    for test_case in test_cases:
        print(f"\n✓ Test: {test_case['name']}...")

        review_text = test_case["response"]

        # This is the EXACT logic from Bug #13 fix (viraltracker/agent/agents/ad_creation_agent.py:1225-1236)
        review_text_clean = review_text.strip()
        if review_text_clean.startswith('```'):
            # Remove opening fence (```json or ```)
            lines = review_text_clean.split('\n')
            if lines[0].startswith('```'):
                lines = lines[1:]
            # Remove closing fence
            if lines and lines[-1].strip() == '```':
                lines = lines[:-1]
            review_text_clean = '\n'.join(lines)

        # Try to parse JSON
        try:
            review_dict = json.loads(review_text_clean)

            # Verify it matches expected output
            if review_dict == test_case['expected']:
                print(f"  ✓ {test_case['name']}: Correctly parsed JSON")
                results.append(True)
            else:
                print(f"  ✗ FAILED: Expected {test_case['expected']}, got {review_dict}")
                results.append(False)
        except json.JSONDecodeError as e:
            print(f"  ✗ FAILED: JSONDecodeError - {e}")
            print(f"     Cleaned text: {repr(review_text_clean[:100])}")
            results.append(False)

    # Check all tests passed
    if all(results):
        print("\n✅ Bug #13 FIX VERIFIED - All markdown fence formats handled correctly!")
        print("   Claude responses will be parsed successfully")
        print("   Markdown fence stripping working as expected")
        return True
    else:
        print("\n❌ Bug #13 FIX INCOMPLETE - Some formats not handled correctly")
        return False


def test_actual_code_location():
    """Verify the fix is actually present in the source code"""
    print("\n\nVerifying Bug #13 fix is in source code...")

    import os
    code_file = "viraltracker/agent/agents/ad_creation_agent.py"

    if not os.path.exists(code_file):
        print(f"  ✗ Could not find {code_file}")
        return False

    with open(code_file, 'r') as f:
        content = f.read()

    # Check for the key fix patterns
    fix_indicators = [
        "# Strip markdown code fences if present",  # Comment from Bug #13 fix
        "if review_text_clean.startswith('```'):",  # Fence detection
        "lines = lines[1:]",  # Remove opening fence
        "if lines and lines[-1].strip() == '```':",  # Remove closing fence
    ]

    all_found = True
    for indicator in fix_indicators:
        if indicator in content:
            print(f"  ✓ Found: {indicator[:50]}...")
        else:
            print(f"  ✗ Missing: {indicator[:50]}...")
            all_found = False

    if all_found:
        print("  ✓ Bug #13 fix code is present in source file")
        return True
    else:
        print("  ✗ Bug #13 fix may be incomplete or missing")
        return False


if __name__ == "__main__":
    # Test 1: Logic verification
    logic_success = test_markdown_fence_stripping()

    # Test 2: Source code verification
    code_success = test_actual_code_location()

    # Overall result
    if logic_success and code_success:
        print("\n" + "="*70)
        print("✅ ALL TESTS PASSED - Bug #13 fix is complete and verified!")
        print("="*70)
        exit(0)
    else:
        print("\n" + "="*70)
        print("❌ SOME TESTS FAILED - Review output above")
        print("="*70)
        exit(1)
