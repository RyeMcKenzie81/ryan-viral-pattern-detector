
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
    "claude-3-5-sonnet-20241022",
    "claude-3-5-haiku-20241022",
    "claude-3-opus-20240229",
    "openai:gpt-4o",
    "openai:gpt-4o-mini",
    "openai:o1-preview",
    "openai:o1-mini",
    "openai:gpt-5.2-2025-12-11",
    "openai:gpt-5-mini-2025-08-07",
    "openai:gpt-5-nano-2025-08-07",
    "google-gla:models/gemini-3-pro-preview",
    "google-gla:models/gemini-3-pro-image-preview",
    "google-gla:models/gemini-3-flash-preview",
]

# Helper to update .env file
def update_env_file(key: str, value: str):
    env_path = ".env"
    dotenv.set_key(env_path, key, value)
    st.session_state[f"saved_{key}"] = True
    # Reload env vars in process
    os.environ[key] = value

def render_model_selector(key: str, label: str):
    """Render a selectbox for a model configuration."""
    col1, col2 = st.columns([3, 1])
    
    with col1:
        current_model = os.getenv(f"{key}_MODEL", "Default (Inherit)")
        
        # Add "Default (Inherit)" - logic to determine what it inherits from
        options = ["Default (Inherit)"] + [m for m in AVAILABLE_MODELS if m != "Default (Inherit)"]
        
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
        st.write("") 
        st.write("") 
        if selected != current_model:
            if st.button(f"Save {key}", key=f"btn_{key}"):
                if selected == "Default (Inherit)":
                    dotenv.unset_key(".env", f"{key}_MODEL")
                    del os.environ[f"{key}_MODEL"]
                    st.success(f"Reset {key} to Default")
                else:
                    update_env_file(f"{key}_MODEL", selected)
                    st.success(f"Updated {key} to {selected}")
                st.rerun()

# Create Tabs
tab_core, tab_agents, tab_services, tab_pipelines = st.tabs([
    "Core Capabilities", 
    "Social Agents", 
    "Backend Services", 
    "Content Pipelines"
])

with tab_core:
    st.markdown("### Core Capabilities")
    st.markdown("These settings define the default behavior for broad categories of tasks.")
    
    # Orchestrator Config (Special handling as it's not a capability override per se)
    st.markdown("#### Orchestrator")
    current_orch = os.getenv("ORCHESTRATOR_MODEL", "openai:gpt-4o")
    orch_opts = AVAILABLE_MODELS if current_orch in AVAILABLE_MODELS else AVAILABLE_MODELS + [current_orch]
    selected_orch = st.selectbox("Orchestrator Model", orch_opts, index=orch_opts.index(current_orch))
    if selected_orch != current_orch:
        if st.button("Save Orchestrator"):
            update_env_file("ORCHESTRATOR_MODEL", selected_orch)
            st.rerun()
            
    st.markdown("#### Default Fallback")
    current_def = os.getenv("DEFAULT_MODEL", Config.DEFAULT_MODEL)
    def_opts = AVAILABLE_MODELS if current_def in AVAILABLE_MODELS else AVAILABLE_MODELS + [current_def]
    selected_def = st.selectbox("Default Model", def_opts, index=def_opts.index(current_def))
    if selected_def != current_def:
        if st.button("Save Default"):
            update_env_file("DEFAULT_MODEL", selected_def)
            st.rerun()

    st.markdown("#### Capability Overrides")
    capabilities = {
        "CREATIVE": "Creative (Writing, Hooks)",
        "VISION": "Vision (Analysis, Review)",
        "VISION_BACKUP": "Vision Backup",
        "BASIC": "Basic Logic",
        "COMPLEX": "Complex Reasoning"
    }
    for key, label in capabilities.items():
        render_model_selector(key, label)

with tab_agents:
    st.markdown("### Social & Specialized Agents")
    st.markdown("Override defaults for specific highly-specialized agents.")
    
    agents = {
        "TWITTER": "Twitter Agent",
        "TIKTOK": "TikTok Agent",
        "YOUTUBE": "YouTube Agent",
        "FACEBOOK": "Facebook Agent",
        "AD_CREATION": "Ad Creation Agent",
        "ANALYSIS": "Analysis Agent",
        "AUDIO_PRODUCTION": "Audio Production Agent"
    }
    for key, label in agents.items():
        render_model_selector(key, label)

with tab_services:
    st.markdown("### Backend Services")
    st.markdown("Control the intelligence behind core backend logic.")
    
    services = {
        "COMPETITOR": "Competitor Analysis Service",
        "BRAND_RESEARCH": "Brand Research Service",
        "AMAZON_REVIEW": "Amazon Review Service",
        "PERSONA": "Persona Service",
        "REDDIT": "Reddit Sentiment Service",
        "PLANNING": "Planning Service"
    }
    for key, label in services.items():
        render_model_selector(key, label)

with tab_pipelines:
    st.markdown("### Content Pipelines")
    st.markdown("Models used for specific content generation workflows.")
    
    pipelines = {
        "COMIC": "Comic Generation Pipeline",
        "SCRIPT": "Video Script Pipeline",
        "COPY_SCAFFOLD": "Copy Scaffold Service"
    }
    for key, label in pipelines.items():
        render_model_selector(key, label)

# Display current configuration summary
st.markdown("---")
st.subheader("Current Configuration Snapshot")
st.code(f"""
ORCHESTRATOR_MODEL = {Config.get_model("orchestrator")}
DEFAULT_MODEL      = {Config.get_model("default")}
COMPLEX_MODEL      = {Config.get_model("complex")}
BASIC_MODEL        = {Config.get_model("basic")}
""", language="properties")
