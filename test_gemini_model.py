#!/usr/bin/env python3
"""
Test script to verify Gemini API and find correct model name for vision tasks.
"""
import os
import sys
import asyncio
import base64
from io import BytesIO
from PIL import Image, ImageDraw

# Add project to path
sys.path.insert(0, os.path.dirname(__file__))

async def test_gemini_models():
    """Test different Gemini model names to find which one works for vision."""
    import google.generativeai as genai

    # Get API key
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("ERROR: GEMINI_API_KEY environment variable not set!")
        return

    genai.configure(api_key=api_key)

    # Create a simple test image (red square with "TEST" text)
    print("\n=== Creating test image ===")
    img = Image.new('RGB', (200, 200), color='red')
    draw = ImageDraw.Draw(img)
    draw.text((70, 90), "TEST", fill='white')

    # Save to bytes
    img_buffer = BytesIO()
    img.save(img_buffer, format='PNG')
    img_buffer.seek(0)

    print("✅ Test image created (200x200 red square with 'TEST' text)\n")

    # List available models
    print("=== Available Gemini Models ===")
    try:
        models = genai.list_models()
        vision_models = []
        for model in models:
            # Check if model supports vision
            if 'generateContent' in model.supported_generation_methods:
                vision_models.append(model.name)
                print(f"  {model.name}")
                print(f"    Methods: {', '.join(model.supported_generation_methods)}")

        print(f"\n✅ Found {len(vision_models)} models with generateContent\n")
    except Exception as e:
        print(f"❌ Error listing models: {e}\n")
        vision_models = []

    # Test specific model names
    test_models = [
        "models/gemini-3-pro-image-preview",  # Current (likely wrong)
        "models/gemini-1.5-pro",               # Standard vision model
        "models/gemini-1.5-flash",             # Fast vision model
        "models/gemini-pro-vision",            # Legacy vision model
        "gemini-1.5-pro",                      # Without "models/" prefix
        "gemini-1.5-flash",                    # Without "models/" prefix
    ]

    # Add any found models to the test list
    for vm in vision_models[:3]:  # Just test first 3
        if vm not in test_models:
            test_models.append(vm)

    print("=== Testing Models with Vision Task ===")
    test_prompt = "What color is this image? Respond in JSON format: {\"color\": \"red\", \"text\": \"TEST\"}"

    successful_models = []

    for model_name in test_models:
        print(f"\nTesting: {model_name}")
        try:
            model = genai.GenerativeModel(model_name)

            # Rewind buffer for each test
            img_buffer.seek(0)
            test_image = Image.open(img_buffer)

            # Try to generate content
            response = model.generate_content([test_prompt, test_image])

            response_text = response.text if response.text else ""
            print(f"  ✅ SUCCESS!")
            print(f"  Response length: {len(response_text)} chars")
            print(f"  Response preview: {response_text[:100]}")
            successful_models.append(model_name)

        except Exception as e:
            error_msg = str(e)
            if "not found" in error_msg.lower() or "invalid" in error_msg.lower():
                print(f"  ❌ Model not found: {error_msg[:80]}")
            elif "quota" in error_msg.lower() or "rate" in error_msg.lower():
                print(f"  ⚠️  Rate limit/quota: {error_msg[:80]}")
            else:
                print(f"  ❌ Error: {error_msg[:80]}")

    # Summary
    print("\n" + "="*60)
    print("=== SUMMARY ===")
    if successful_models:
        print(f"\n✅ {len(successful_models)} model(s) working:")
        for model in successful_models:
            print(f"   - {model}")
        print(f"\n🎯 RECOMMENDED: Use '{successful_models[0]}' in dependencies.py")
    else:
        print("\n❌ No models worked! Check:")
        print("   1. GEMINI_API_KEY is valid")
        print("   2. Gemini API billing is enabled")
        print("   3. You have access to Gemini vision models")
    print("="*60)

if __name__ == "__main__":
    asyncio.run(test_gemini_models())
