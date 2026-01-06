
import streamlit as st
import os
import dotenv
from typing import Any
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
tab_core, tab_agents, tab_services, tab_pipelines, tab_angle = st.tabs([
    "Core Capabilities",
    "Social Agents",
    "Backend Services",
    "Content Pipelines",
    "Angle Pipeline"
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

with tab_angle:
    st.markdown("### Angle Pipeline Settings")
    st.markdown("Configure thresholds and limits for the angle candidate pipeline.")

    # Helper to get/set system settings
    def get_system_setting(key: str, default: Any) -> Any:
        """Get a system setting from the database."""
        try:
            from viraltracker.core.database import get_supabase_client
            db = get_supabase_client()
            result = db.table("system_settings").select("value").eq("key", key).execute()
            if result.data:
                return result.data[0]["value"]
            return default
        except Exception:
            return default

    def set_system_setting(key: str, value: Any) -> bool:
        """Set a system setting in the database."""
        try:
            from viraltracker.core.database import get_supabase_client
            db = get_supabase_client()
            db.table("system_settings").upsert({
                "key": key,
                "value": value
            }, on_conflict="key").execute()
            return True
        except Exception as e:
            st.error(f"Failed to save setting: {e}")
            return False

    st.markdown("#### Candidate Management")

    col1, col2 = st.columns(2)

    with col1:
        # Stale threshold
        current_stale = int(get_system_setting("angle_pipeline.stale_threshold_days", 30))
        new_stale = st.number_input(
            "Stale Threshold (days)",
            min_value=7,
            max_value=365,
            value=current_stale,
            help="Candidates without new evidence for this many days are considered stale"
        )
        if new_stale != current_stale:
            if st.button("Save Stale Threshold"):
                if set_system_setting("angle_pipeline.stale_threshold_days", new_stale):
                    st.success("Saved!")
                    st.rerun()

        # Evidence decay half-life
        current_decay = int(get_system_setting("angle_pipeline.evidence_decay_halflife_days", 60))
        new_decay = st.number_input(
            "Evidence Decay Half-Life (days)",
            min_value=14,
            max_value=365,
            value=current_decay,
            help="How quickly evidence weight decays over time (for frequency scoring)"
        )
        if new_decay != current_decay:
            if st.button("Save Evidence Decay"):
                if set_system_setting("angle_pipeline.evidence_decay_halflife_days", new_decay):
                    st.success("Saved!")
                    st.rerun()

    with col2:
        # Min candidates for pattern discovery
        current_min = int(get_system_setting("angle_pipeline.min_candidates_pattern_discovery", 10))
        new_min = st.number_input(
            "Min Candidates for Pattern Discovery",
            min_value=5,
            max_value=100,
            value=current_min,
            help="Minimum candidates needed before pattern discovery can run"
        )
        if new_min != current_min:
            if st.button("Save Min Candidates"):
                if set_system_setting("angle_pipeline.min_candidates_pattern_discovery", new_min):
                    st.success("Saved!")
                    st.rerun()

        # Max ads per scheduled run
        current_max_ads = int(get_system_setting("angle_pipeline.max_ads_per_scheduled_run", 50))
        new_max_ads = st.number_input(
            "Max Ads Per Scheduled Run",
            min_value=10,
            max_value=200,
            value=current_max_ads,
            help="Maximum ads generated in a single scheduled job run"
        )
        if new_max_ads != current_max_ads:
            if st.button("Save Max Ads"):
                if set_system_setting("angle_pipeline.max_ads_per_scheduled_run", new_max_ads):
                    st.success("Saved!")
                    st.rerun()

    st.markdown("#### Pattern Discovery")

    col3, col4 = st.columns(2)

    with col3:
        # DBSCAN epsilon
        current_eps = float(get_system_setting("angle_pipeline.cluster_eps", 0.3))
        new_eps = st.slider(
            "Clustering Sensitivity (epsilon)",
            min_value=0.1,
            max_value=0.8,
            value=current_eps,
            step=0.05,
            help="Lower = tighter clusters (more patterns), Higher = looser clusters (fewer patterns)"
        )
        if abs(new_eps - current_eps) > 0.01:
            if st.button("Save Cluster Sensitivity"):
                if set_system_setting("angle_pipeline.cluster_eps", new_eps):
                    st.success("Saved!")
                    st.rerun()

    with col4:
        # Min cluster size
        current_min_cluster = int(get_system_setting("angle_pipeline.cluster_min_samples", 2))
        new_min_cluster = st.number_input(
            "Min Cluster Size",
            min_value=2,
            max_value=10,
            value=current_min_cluster,
            help="Minimum candidates needed to form a pattern cluster"
        )
        if new_min_cluster != current_min_cluster:
            if st.button("Save Min Cluster Size"):
                if set_system_setting("angle_pipeline.cluster_min_samples", new_min_cluster):
                    st.success("Saved!")
                    st.rerun()

    st.markdown("#### Current Settings Summary")
    st.code(f"""
angle_pipeline.stale_threshold_days = {get_system_setting("angle_pipeline.stale_threshold_days", 30)}
angle_pipeline.evidence_decay_halflife_days = {get_system_setting("angle_pipeline.evidence_decay_halflife_days", 60)}
angle_pipeline.min_candidates_pattern_discovery = {get_system_setting("angle_pipeline.min_candidates_pattern_discovery", 10)}
angle_pipeline.max_ads_per_scheduled_run = {get_system_setting("angle_pipeline.max_ads_per_scheduled_run", 50)}
angle_pipeline.cluster_eps = {get_system_setting("angle_pipeline.cluster_eps", 0.3)}
angle_pipeline.cluster_min_samples = {get_system_setting("angle_pipeline.cluster_min_samples", 2)}
""", language="properties")

# Display current configuration summary
st.markdown("---")
st.subheader("Current LLM Configuration Snapshot")
st.code(f"""
ORCHESTRATOR_MODEL = {Config.get_model("orchestrator")}
DEFAULT_MODEL      = {Config.get_model("default")}
COMPLEX_MODEL      = {Config.get_model("complex")}
BASIC_MODEL        = {Config.get_model("basic")}
""", language="properties")
