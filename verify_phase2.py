
import os
from viraltracker.core.config import Config

def test_phase2_config():
    agents = [
        "twitter", "tiktok", "youtube", "facebook", "analysis", "audio_production"
    ]
    
    print("--- Initial State (Should be Default) ---")
    for agent in agents:
        model = Config.get_model(agent)
        print(f"{agent}: {model}")
        if model != Config.DEFAULT_MODEL:
            print(f"ERROR: {agent} should match DEFAULT_MODEL ({Config.DEFAULT_MODEL})")
            
    print("\n--- Testing Overrides ---")
    # Set overrides
    for agent in agents:
        os.environ[f"{agent.upper()}_MODEL"] = f"custom-{agent}-model"
        
    # Verify overrides
    for agent in agents:
        model = Config.get_model(agent)
        print(f"{agent}: {model}")
        expected = f"custom-{agent}-model"
        if model != expected:
            print(f"ERROR: {agent} should be {expected}, got {model}")
            
    print("\n--- Phase 2 Verification Complete ---")

if __name__ == "__main__":
    test_phase2_config()
