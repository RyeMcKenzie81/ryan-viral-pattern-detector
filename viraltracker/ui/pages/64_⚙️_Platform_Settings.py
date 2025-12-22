
import streamlit as st
import os
import dotenv
from viraltracker.core.config import Config
from viraltracker.ui.auth import require_auth

# Page config
st.set_page_config(page_title="Platform Settings", page_icon="⚙️", layout="wide")

# Authentication
require_auth()

st.title("⚙️ Platform Settings")

# ============================================================================
# LLM Configuration
# ============================================================================

st.subheader("🤖 LLM Model Configuration")
st.info("Manage which AI models power different parts of the platform.")

# Define available models
AVAILABLE_MODELS = [
    "claude-sonnet-4-5-20250929",
    "claude-opus-4-5-20251101",
    "claude-sonnet-4-20250514",
    "openai:gpt-4o",
    "openai:gpt-4-turbo",
    "models/gemini-2.5-pro"
]

# Helper to update .env file
def update_env_file(key: str, value: str):
    env_path = ".env"
    dotenv.set_key(env_path, key, value)
    st.session_state[f"saved_{key}"] = True
    # Reload env vars in process
    os.environ[key] = value

# Orchestrator Config
st.markdown("### Orchestrator Agent")
st.markdown("The main routing agent that directs user requests.")

current_orchestrator = os.getenv("ORCHESTRATOR_MODEL", "openai:gpt-4o")
# Check if current value is in list, if not add it (handling custom models)
if current_orchestrator not in AVAILABLE_MODELS:
    AVAILABLE_MODELS.append(current_orchestrator)

selected_orchestrator = st.selectbox(
    "Orchestrator Model",
    options=AVAILABLE_MODELS,
    index=AVAILABLE_MODELS.index(current_orchestrator)
)

if selected_orchestrator != current_orchestrator:
    if st.button("Save Orchestrator Model"):
        update_env_file("ORCHESTRATOR_MODEL", selected_orchestrator)
        st.success(f"Updated ORCHESTRATOR_MODEL to {selected_orchestrator}")
        st.rerun()

# Default Model Config
st.markdown("### Default Fallback Model")
st.markdown("Used by agents when no specific model is configured.")

current_default = os.getenv("DEFAULT_MODEL", Config.DEFAULT_MODEL)
if current_default not in AVAILABLE_MODELS:
    AVAILABLE_MODELS.append(current_default)

selected_default = st.selectbox(
    "Default Model",
    options=AVAILABLE_MODELS,
    index=AVAILABLE_MODELS.index(current_default)
)

if selected_default != current_default:
    if st.button("Save Default Model"):
        update_env_file("DEFAULT_MODEL", selected_default)
        st.success(f"Updated DEFAULT_MODEL to {selected_default}")
        st.rerun()

# Specialist Agent Overrides
st.markdown("### Specialist Agent Overrides")
st.markdown("Override the default model for specific agents.")

agents = {
    "TWITTER": "Twitter Agent",
    "TIKTOK": "TikTok Agent",
    "YOUTUBE": "YouTube Agent",
    "FACEBOOK": "Facebook Agent",
    "ANALYSIS": "Analysis Agent",
    "AUDIO_PRODUCTION": "Audio Production Agent"
}

for key, label in agents.items():
    col1, col2 = st.columns([3, 1])
    
    with col1:
        current_model = os.getenv(f"{key}_MODEL", "Default (Inherit)")
        
        # Add "Default (Inherit)" option if not present
        options = ["Default (Inherit)"] + [m for m in AVAILABLE_MODELS if m != "Default (Inherit)"]
        
        # If current model is a real model string, ensure it's selected
        index = 0
        if current_model in options:
            index = options.index(current_model)
        elif current_model != "Default (Inherit)":
            options.append(current_model)
            index = options.index(current_model)
            
        selected = st.selectbox(
            f"{label}",
            options=options,
            index=index,
            key=f"select_{key}"
        )

    with col2:
        st.write("") # Spacer
        st.write("") # Spacer
        if selected != current_model:
            if st.button(f"Save {key}", key=f"btn_{key}"):
                if selected == "Default (Inherit)":
                    # Remove from .env to fallback to default
                    dotenv.unset_key(".env", f"{key}_MODEL")
                    del os.environ[f"{key}_MODEL"]
                    st.success(f"Reset {key} to Default")
                else:
                    update_env_file(f"{key}_MODEL", selected)
                    st.success(f"Updated {key} to {selected}")
                st.rerun()

# Display current configuration summary
st.markdown("---")
st.subheader("Current Configuration Snapshot")
st.code(f"""
ORCHESTRATOR_MODEL = {Config.get_model("orchestrator")}
DEFAULT_MODEL      = {Config.get_model("default")}
COMPLEX_MODEL      = {Config.get_model("complex")}
FAST_MODEL         = {Config.get_model("fast")}
""", language="properties")
