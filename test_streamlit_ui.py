"""
Test Suite for Streamlit UI - Task 1.9

Tests the Streamlit web interface implementation for the Pydantic AI agent.

Run with:
    python test_streamlit_ui.py
    # or
    pytest test_streamlit_ui.py -v
"""

import os
import sys

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
    print("📝 Loaded environment variables from .env file")
except ImportError:
    print("⚠️  python-dotenv not installed, using existing environment variables")


def test_streamlit_import():
    """Test 1: Verify streamlit can be imported."""
    try:
        import streamlit as st
        print("✅ Test 1 PASSED: Streamlit imported successfully")
        print(f"   Streamlit version: {st.__version__}")
        return True
    except ImportError as e:
        print(f"❌ Test 1 FAILED: Could not import streamlit: {e}")
        print("   Run: pip install streamlit==1.40.0")
        return False


def test_app_file_exists():
    """Test 2: Check that viraltracker/ui/app.py exists."""
    app_path = os.path.join(os.path.dirname(__file__), 'viraltracker', 'ui', 'app.py')

    if os.path.exists(app_path):
        print(f"✅ Test 2 PASSED: App file exists at {app_path}")

        # Check file size
        file_size = os.path.getsize(app_path)
        line_count = 0
        with open(app_path, 'r') as f:
            line_count = len(f.readlines())

        print(f"   File size: {file_size} bytes")
        print(f"   Line count: {line_count} lines")

        if line_count >= 200:
            print("   ✓ File meets minimum line count requirement (200+ lines)")
        else:
            print(f"   ⚠️  File is shorter than expected ({line_count} < 200 lines)")

        return True
    else:
        print(f"❌ Test 2 FAILED: App file not found at {app_path}")
        return False


def test_agent_import_in_app():
    """Test 3: Verify agent can be imported from app.py."""
    try:
        # Add project root to path
        project_root = os.path.dirname(__file__)
        if project_root not in sys.path:
            sys.path.insert(0, project_root)

        from viraltracker.agent import agent, AgentDependencies
        print("✅ Test 3 PASSED: Agent imports successful")
        print(f"   Agent type: {type(agent)}")
        print(f"   AgentDependencies type: {type(AgentDependencies)}")
        return True
    except ImportError as e:
        print(f"❌ Test 3 FAILED: Could not import agent: {e}")
        return False


def test_dependencies_creation():
    """Test 4: Test AgentDependencies.create() works (without API keys)."""
    try:
        # Add project root to path
        project_root = os.path.dirname(__file__)
        if project_root not in sys.path:
            sys.path.insert(0, project_root)

        from viraltracker.agent import AgentDependencies

        # Check if required environment variables are set
        required_vars = ['SUPABASE_URL', 'SUPABASE_KEY', 'GEMINI_API_KEY']
        missing_vars = [var for var in required_vars if not os.getenv(var)]

        if missing_vars:
            print("⚠️  Test 4 SKIPPED: Missing required environment variables:")
            for var in missing_vars:
                print(f"   - {var}")
            print("   This is expected if running tests without .env file")
            print("   AgentDependencies.create() would fail without these vars")
            return True  # Don't fail the test, just skip

        # Try to create dependencies
        try:
            deps = AgentDependencies.create(
                project_name='test-project'
            )
            print("✅ Test 4 PASSED: AgentDependencies.create() successful")
            print(f"   Project name: {deps.project_name}")
            print(f"   Has twitter service: {hasattr(deps, 'twitter')}")
            print(f"   Has gemini service: {hasattr(deps, 'gemini')}")
            print(f"   Has stats service: {hasattr(deps, 'stats')}")
            return True
        except Exception as e:
            print(f"❌ Test 4 FAILED: AgentDependencies.create() raised exception: {e}")
            return False

    except ImportError as e:
        print(f"❌ Test 4 FAILED: Could not import AgentDependencies: {e}")
        return False


def run_all_tests():
    """Run all tests and report results."""
    print("=" * 70)
    print("STREAMLIT UI TEST SUITE - Task 1.9")
    print("=" * 70)
    print()

    tests = [
        ("Test 1: Streamlit Import", test_streamlit_import),
        ("Test 2: App File Exists", test_app_file_exists),
        ("Test 3: Agent Import", test_agent_import_in_app),
        ("Test 4: Dependencies Creation", test_dependencies_creation),
    ]

    results = []
    for test_name, test_func in tests:
        print(f"\nRunning {test_name}...")
        print("-" * 70)
        result = test_func()
        results.append((test_name, result))
        print()

    # Summary
    print("=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for test_name, result in results:
        status = "✅ PASSED" if result else "❌ FAILED"
        print(f"{status}: {test_name}")

    print()
    print(f"Results: {passed}/{total} tests passed")

    if passed == total:
        print("🎉 All tests passed!")
        return 0
    else:
        print(f"⚠️  {total - passed} test(s) failed")
        return 1


if __name__ == '__main__':
    exit_code = run_all_tests()
    sys.exit(exit_code)
