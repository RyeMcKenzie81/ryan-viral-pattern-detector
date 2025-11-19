#!/usr/bin/env python3
"""Minimal test of Gemini API to isolate ragStoreName issue."""

import os
from dotenv import load_dotenv
import google.generativeai as genai

# Load .env file
load_dotenv()

# Configure API
api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    print("ERROR: GEMINI_API_KEY not set")
    exit(1)

genai.configure(api_key=api_key)

print("Testing Gemini API with minimal prompt...")
print(f"SDK version: {genai.__version__}")
print()

# Test 1: Simple text prompt
print("Test 1: Simple text generation")
try:
    model = genai.GenerativeModel("models/gemini-2.5-pro")
    response = model.generate_content("Say hello")
    print(f"✅ SUCCESS: {response.text}")
except Exception as e:
    print(f"❌ FAILED: {e}")

print()

# Test 2: File upload (if we have a test video)
test_video = "/Users/ryemckenzie/projects/viraltracker/test_video.mp4"
if os.path.exists(test_video):
    print("Test 2: Video file upload + analysis")
    try:
        video_file = genai.upload_file(test_video)
        print(f"  Uploaded: {video_file.uri}")

        response = model.generate_content([video_file, "Describe this video in one sentence."])
        print(f"✅ SUCCESS: {response.text}")

        genai.delete_file(video_file.name)
        print(f"  Cleaned up file")
    except Exception as e:
        print(f"❌ FAILED: {e}")
else:
    print("Test 2: SKIPPED (no test video found)")

print()
print("Test complete!")
