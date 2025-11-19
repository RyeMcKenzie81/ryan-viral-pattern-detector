#!/usr/bin/env python3
"""Test that the --product flag works correctly."""

import sys
import subprocess

def test_help():
    """Test that --product appears in help text."""
    result = subprocess.run(
        ["python", "-m", "viraltracker.cli.main", "tiktok", "analyze-url", "--help"],
        capture_output=True,
        text=True,
        timeout=5
    )

    if "--product" in result.stdout:
        print("✅ analyze-url has --product flag")
    else:
        print("❌ analyze-url missing --product flag")
        print(result.stdout)
        sys.exit(1)

    result = subprocess.run(
        ["python", "-m", "viraltracker.cli.main", "tiktok", "analyze-urls", "--help"],
        capture_output=True,
        text=True,
        timeout=5
    )

    if "--product" in result.stdout:
        print("✅ analyze-urls has --product flag")
    else:
        print("❌ analyze-urls missing --product flag")
        sys.exit(1)

    print("\n✅ All tests passed!")

if __name__ == "__main__":
    test_help()
