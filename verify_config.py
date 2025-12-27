
import os
from viraltracker.core.config import Config

def test_config_logic():
    print("--- Initial State ---")
    print(f"Orchestrator: {Config.get_model('orchestrator')}")
    print(f"Default:      {Config.get_model('default')}")
    print(f"Complex:      {Config.get_model('complex')}")
    
    print("\n--- Testing Override ---")
    os.environ["ORCHESTRATOR_MODEL"] = "test-override-model"
    # Re-initialization isn't needed for Config.get_model as it checks env var every time
    print(f"Orchestrator (expect 'test-override-model'): {Config.get_model('orchestrator')}")
    
    print("\n--- Testing Case Insensitivity ---")
    print(f"ORCHESTRATOR (upper): {Config.get_model('ORCHESTRATOR')}")
    
    print("\n--- Testing Fallback ---")
    print(f"NonExistent (expect default): {Config.get_model('non_existent_component')}")

if __name__ == "__main__":
    test_config_logic()
