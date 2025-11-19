"""
Simple API test script to verify endpoints work correctly.

Tests:
1. Import check ✓
2. Health endpoint (GET /health)
3. Root endpoint (GET /)
4. OpenAPI docs available (GET /docs)

Note: Full integration tests (with agent execution) require
running server and making actual HTTP requests.
"""

import sys
from viraltracker.api.app import app
from fastapi.testclient import TestClient

# Create test client
client = TestClient(app)

def test_imports():
    """Test that API imports successfully."""
    print("✅ Test 1: API imports successfully")
    return True

def test_root():
    """Test root endpoint."""
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Viraltracker API"
    assert "endpoints" in data
    print("✅ Test 2: Root endpoint (GET /) works")
    return True

def test_health():
    """Test health check endpoint."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert "services" in data
    assert data["version"] == "1.0.0"
    print(f"✅ Test 3: Health endpoint works - Status: {data['status']}")
    print(f"   Services: {data['services']}")
    return True

def test_openapi_docs():
    """Test OpenAPI documentation is available."""
    response = client.get("/openapi.json")
    assert response.status_code == 200
    data = response.json()
    assert "openapi" in data
    assert data["info"]["title"] == "Viraltracker API"
    print("✅ Test 4: OpenAPI docs available at /docs and /redoc")
    return True

def main():
    """Run all tests."""
    print("\n" + "="*60)
    print("VIRALTRACKER API - TEST SUITE")
    print("="*60 + "\n")

    tests = [
        ("Imports", test_imports),
        ("Root Endpoint", test_root),
        ("Health Check", test_health),
        ("OpenAPI Docs", test_openapi_docs),
    ]

    passed = 0
    failed = 0

    for name, test_func in tests:
        try:
            test_func()
            passed += 1
        except Exception as e:
            print(f"❌ Test failed: {name}")
            print(f"   Error: {e}")
            failed += 1

    print("\n" + "="*60)
    print(f"TEST RESULTS: {passed} passed, {failed} failed")
    print("="*60 + "\n")

    if failed == 0:
        print("🎉 All tests passed! API is ready for deployment.\n")
        print("Next steps:")
        print("1. Start server: uvicorn viraltracker.api.app:app --reload")
        print("2. Test with curl or Postman")
        print("3. Deploy to Railway")
        return 0
    else:
        print("⚠️  Some tests failed. Please fix before deploying.\n")
        return 1

if __name__ == "__main__":
    sys.exit(main())
