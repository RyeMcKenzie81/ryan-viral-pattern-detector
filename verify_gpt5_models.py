
import os
from pydantic_ai import Agent
from viraltracker.core.config import Config

# Mock API keys
os.environ["OPENAI_API_KEY"] = "mock_key"
os.environ["GEMINI_API_KEY"] = "mock_key"

def test_models():
    models_to_test = [
        "openai:gpt-5.2-2025-12-11",
        "openai:gpt-5-mini-2025-08-07",
        "openai:gpt-5-nano-2025-08-07",
        Config.VISION_BACKUP_MODEL
    ]
    
    print("Testing GPT-5 model initialization...")
    for model_str in models_to_test:
        try:
            print(f"Trying: {model_str}")
            # Pydantic AI checks model string validity immediately
            agent = Agent(model=model_str)
            print(f"✅ Success with: {model_str}")
        except Exception as e:
            print(f"❌ Failed: {e}")

if __name__ == "__main__":
    test_models()
