
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
tab_core, tab_agents, tab_services, tab_pipelines, tab_angle, tab_calibration, tab_interactions, tab_exemplars, tab_weights, tab_experiments, tab_vclusters = st.tabs([
    "Core Capabilities",
    "Social Agents",
    "Backend Services",
    "Content Pipelines",
    "Angle Pipeline",
    "Calibration",
    "Interactions",
    "Exemplar Library",
    "Scorer Weights",
    "Gen Experiments",
    "Visual Clusters",
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

# ============================================================================
# Phase 8A: Calibration Proposals Tab
# ============================================================================
with tab_calibration:
    st.markdown("### Quality Calibration Proposals")
    st.info(
        "Weekly analysis of human overrides proposes threshold adjustments. "
        "Review proposals below and Activate or Dismiss them."
    )

    try:
        import asyncio
        from viraltracker.services.quality_calibration_service import QualityCalibrationService
        from viraltracker.ui.auth import get_current_user_id

        cal_svc = QualityCalibrationService()
        cal_user_id = get_current_user_id()

        loop = asyncio.new_event_loop()
        pending = loop.run_until_complete(cal_svc.get_pending_proposals())

        if pending:
            st.markdown(f"**{len(pending)} pending proposal(s)**")
            for proposal in pending:
                with st.expander(
                    f"Proposal {proposal['id'][:8]}... — "
                    f"Threshold: {proposal.get('proposed_pass_threshold')} | "
                    f"FP Rate: {proposal.get('false_positive_rate', 'N/A')} | "
                    f"FN Rate: {proposal.get('false_negative_rate', 'N/A')}",
                    expanded=True,
                ):
                    col1, col2 = st.columns(2)
                    with col1:
                        st.markdown("**Current Config**")
                        st.json({
                            "pass_threshold": float(proposal.get("current_config_id", "N/A") or "N/A"),
                        } if proposal.get("current_config_id") else {"status": "using defaults"})

                    with col2:
                        st.markdown("**Proposed Changes**")
                        st.json({
                            "pass_threshold": float(proposal["proposed_pass_threshold"]),
                            "borderline_range": proposal["proposed_borderline_range"],
                        })

                    st.markdown(f"**Analysis Window**: {proposal.get('analysis_window_start')} to {proposal.get('analysis_window_end')}")
                    st.markdown(f"**Overrides Analyzed**: {proposal.get('total_overrides_analyzed', 0)}")
                    st.markdown(f"**Safety**: min_sample={proposal.get('meets_min_sample_size')}, within_delta={proposal.get('within_delta_bounds')}")

                    acol1, acol2 = st.columns(2)
                    with acol1:
                        if st.button("Activate", key=f"cal_activate_{proposal['id']}", type="primary"):
                            try:
                                from uuid import UUID
                                result = loop.run_until_complete(
                                    cal_svc.activate_proposal(
                                        UUID(proposal["id"]),
                                        UUID(cal_user_id) if cal_user_id else UUID("00000000-0000-0000-0000-000000000000"),
                                    )
                                )
                                st.success(f"Activated! New config version: {result.get('version')}")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Activation failed: {e}")
                    with acol2:
                        dismiss_reason = st.text_input(
                            "Dismiss reason",
                            key=f"cal_dismiss_reason_{proposal['id']}",
                            placeholder="Why dismiss?",
                        )
                        if st.button("Dismiss", key=f"cal_dismiss_{proposal['id']}"):
                            try:
                                from uuid import UUID
                                loop.run_until_complete(
                                    cal_svc.dismiss_proposal(
                                        UUID(proposal["id"]),
                                        UUID(cal_user_id) if cal_user_id else UUID("00000000-0000-0000-0000-000000000000"),
                                        dismiss_reason or "No reason provided",
                                    )
                                )
                                st.success("Proposal dismissed.")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Dismiss failed: {e}")
        else:
            st.info("No pending calibration proposals.")

        # History
        st.markdown("---")
        st.markdown("### Proposal History")
        history = loop.run_until_complete(cal_svc.get_proposal_history())
        loop.close()

        if history:
            for h in history[:10]:
                status_icon = {"activated": "✅", "dismissed": "❌", "proposed": "⏳", "insufficient_evidence": "⚠️"}.get(h["status"], "❓")
                st.markdown(
                    f"{status_icon} **{h['id'][:8]}** — {h['status']} | "
                    f"Threshold: {h.get('proposed_pass_threshold')} | "
                    f"Overrides: {h.get('total_overrides_analyzed', 0)} | "
                    f"Date: {h.get('proposed_at', 'N/A')[:10]}"
                )
        else:
            st.caption("No proposal history yet.")

    except Exception as e:
        st.warning(f"Could not load calibration data: {e}")


# ============================================================================
# Phase 8A: Interaction Effects Tab
# ============================================================================
with tab_interactions:
    st.markdown("### Element Interaction Effects")
    st.info(
        "Top pairwise element interactions detected from creative performance data. "
        "Synergies boost performance when combined; conflicts reduce it."
    )

    try:
        import asyncio
        from viraltracker.services.interaction_detector_service import InteractionDetectorService
        from viraltracker.ui.utils import render_brand_selector

        int_brand_id = render_brand_selector(key="interactions_brand_selector")
        if int_brand_id:
            from uuid import UUID
            detector = InteractionDetectorService()
            loop = asyncio.new_event_loop()
            interactions = loop.run_until_complete(
                detector.get_top_interactions(UUID(int_brand_id))
            )
            loop.close()

            if interactions:
                import pandas as pd
                df = pd.DataFrame([{
                    "Rank": i.get("effect_rank", ""),
                    "Element A": f"{i['element_a_name']}={i['element_a_value']}",
                    "Element B": f"{i['element_b_name']}={i['element_b_value']}",
                    "Effect": f"{i['interaction_effect']:+.4f}",
                    "Direction": i["effect_direction"],
                    "CI": f"[{i.get('confidence_interval_low', 0):.3f}, {i.get('confidence_interval_high', 0):.3f}]",
                    "N": i["sample_size"],
                    "p-value": f"{i.get('p_value', 1.0):.3f}",
                } for i in interactions])

                st.dataframe(df, use_container_width=True, hide_index=True)

                st.markdown("---")
                advisory = detector.format_advisory_context(interactions)
                if advisory:
                    st.markdown("**Advisory Summary:**")
                    st.markdown(advisory)
            else:
                st.info("No interaction data yet. Run Genome Validation to detect interactions.")
    except Exception as e:
        st.warning(f"Could not load interaction data: {e}")


# ============================================================================
# Phase 8A: Exemplar Library Tab
# ============================================================================
with tab_exemplars:
    st.markdown("### Exemplar Library")
    st.info(
        "Curated calibration ads used as few-shot examples in review prompts. "
        "Gold approve/reject exemplars teach the AI your brand's quality bar."
    )

    try:
        import asyncio
        from viraltracker.pipelines.ad_creation_v2.services.exemplar_service import ExemplarService
        from viraltracker.ui.utils import render_brand_selector

        ex_brand_id = render_brand_selector(key="exemplar_brand_selector")
        if ex_brand_id:
            from uuid import UUID
            ex_svc = ExemplarService()
            loop = asyncio.new_event_loop()

            # Stats
            stats = loop.run_until_complete(ex_svc.get_exemplar_stats(UUID(ex_brand_id)))
            scol1, scol2, scol3, scol4 = st.columns(4)
            with scol1:
                st.metric("Gold Approve", stats.get("gold_approve", 0))
            with scol2:
                st.metric("Gold Reject", stats.get("gold_reject", 0))
            with scol3:
                st.metric("Edge Case", stats.get("edge_case", 0))
            with scol4:
                st.metric("Total", stats.get("total", 0))

            # Auto-seed button
            if st.button("Auto-Seed from Overrides", key="exemplar_auto_seed"):
                try:
                    seed_result = loop.run_until_complete(
                        ex_svc.auto_seed_exemplars(UUID(ex_brand_id))
                    )
                    st.success(
                        f"Seeded {seed_result['seeded']} exemplars: "
                        f"{seed_result.get('gold_approve', 0)} approve, "
                        f"{seed_result.get('gold_reject', 0)} reject, "
                        f"{seed_result.get('edge_case', 0)} edge"
                    )
                    st.rerun()
                except Exception as e:
                    st.error(f"Auto-seed failed: {e}")

            st.divider()

            # List exemplars
            exemplars = loop.run_until_complete(
                ex_svc.get_exemplars(UUID(ex_brand_id))
            )
            loop.close()

            if exemplars:
                for ex in exemplars:
                    ad_data = ex.get("generated_ads", {})
                    cat_icon = {
                        "gold_approve": "✅",
                        "gold_reject": "❌",
                        "edge_case": "⚠️",
                    }.get(ex["category"], "❓")

                    col1, col2, col3 = st.columns([1, 3, 1])
                    with col1:
                        st.markdown(f"{cat_icon} **{ex['category']}**")
                    with col2:
                        hook = ad_data.get("hook_text", "N/A")
                        st.markdown(f"\"{hook[:80]}\"")
                        st.caption(
                            f"Source: {ex.get('source', 'N/A')} | "
                            f"Template: {ex.get('template_category', 'N/A')} | "
                            f"Canvas: {ex.get('canvas_size', 'N/A')} | "
                            f"Color: {ex.get('color_mode', 'N/A')}"
                        )
                    with col3:
                        if st.button("Remove", key=f"remove_exemplar_{ex['id']}"):
                            try:
                                loop2 = asyncio.new_event_loop()
                                loop2.run_until_complete(
                                    ex_svc.remove_exemplar(UUID(ex["id"]), "Removed via Settings UI")
                                )
                                loop2.close()
                                st.success("Exemplar removed.")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Remove failed: {e}")
                    st.divider()
            else:
                st.info("No exemplars yet. Use Auto-Seed or mark ads as exemplars in the Results Dashboard.")
    except Exception as e:
        st.warning(f"Could not load exemplar data: {e}")


# ============================================================================
# Phase 8B: Scorer Weight Learning Tab
# ============================================================================
with tab_weights:
    st.markdown("### Scorer Weight Learning Status")
    st.info(
        "Scorer weights evolve from static presets to learned values via Thompson Sampling. "
        "cold → warm → hot as observations accumulate."
    )

    try:
        from viraltracker.ui.utils import render_brand_selector

        wt_brand_id = render_brand_selector(key="scorer_weights_brand_selector")
        if wt_brand_id:
            from uuid import UUID
            from viraltracker.services.scorer_weight_learning_service import ScorerWeightLearningService

            wt_svc = ScorerWeightLearningService()
            weight_status = wt_svc.get_weight_status(UUID(wt_brand_id))

            if weight_status:
                import pandas as pd
                df = pd.DataFrame([{
                    "Scorer": s["scorer_name"],
                    "Phase": s["learning_phase"],
                    "Observations": s["total_observations"],
                    "Static Weight": s["static_weight"],
                    "Learned Mean": s["learned_mean"] or "—",
                    "Effective Weight": s["effective_weight"],
                    "α": s["alpha"],
                    "β": s["beta"],
                } for s in weight_status])

                st.dataframe(df, use_container_width=True, hide_index=True)

                # Phase summary
                phases = [s["learning_phase"] for s in weight_status]
                cold_count = phases.count("cold")
                warm_count = phases.count("warm")
                hot_count = phases.count("hot")

                pcol1, pcol2, pcol3 = st.columns(3)
                with pcol1:
                    st.metric("Cold Scorers", cold_count)
                with pcol2:
                    st.metric("Warm Scorers", warm_count)
                with pcol3:
                    st.metric("Hot Scorers", hot_count)
            else:
                st.info("No scorer weight data yet. Posteriors initialize after first template selection.")
    except Exception as e:
        st.warning(f"Could not load scorer weight data: {e}")


# ============================================================================
# Phase 8B: Generation Experiments Tab
# ============================================================================
with tab_experiments:
    st.markdown("### Generation Experiments")
    st.info(
        "A/B test different prompt versions, pipeline configs, or element strategies. "
        "Max 1 active experiment per brand."
    )

    try:
        from viraltracker.ui.utils import render_brand_selector

        exp_brand_id = render_brand_selector(key="gen_exp_brand_selector")
        if exp_brand_id:
            from uuid import UUID
            from viraltracker.services.generation_experiment_service import GenerationExperimentService

            exp_svc = GenerationExperimentService()
            experiments = exp_svc.list_experiments(UUID(exp_brand_id))

            if experiments:
                for exp in experiments:
                    status_icon = {
                        "draft": "📝", "active": "🔬",
                        "completed": "✅", "cancelled": "❌"
                    }.get(exp["status"], "❓")

                    with st.expander(
                        f"{status_icon} {exp['name']} — {exp['status']} "
                        f"({exp.get('experiment_type', 'N/A')})",
                        expanded=(exp["status"] == "active"),
                    ):
                        col1, col2 = st.columns(2)
                        with col1:
                            st.markdown(f"**Hypothesis:** {exp.get('hypothesis', 'N/A')}")
                            st.markdown(f"**Split:** {float(exp.get('split_ratio', 0.5)):.0%} variant")
                            st.markdown(f"**Min Sample:** {exp.get('min_sample_size', 20)} ads/arm")

                        with col2:
                            ctrl = exp.get("control_metrics") or {}
                            var = exp.get("variant_metrics") or {}
                            st.markdown(f"**Control:** {ctrl.get('ads_approved', 0)}/{ctrl.get('ads_generated', 0)} approved")
                            st.markdown(f"**Variant:** {var.get('ads_approved', 0)}/{var.get('ads_generated', 0)} approved")
                            if exp.get("winner"):
                                st.markdown(f"**Winner:** {exp['winner']} (p={exp.get('confidence', 'N/A')})")

                        # Action buttons
                        if exp["status"] == "draft":
                            if st.button("Activate", key=f"activate_exp_{exp['id']}", type="primary"):
                                try:
                                    exp_svc.activate_experiment(exp["id"])
                                    st.success("Experiment activated!")
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Activation failed: {e}")

                        if exp["status"] == "active":
                            if st.button("Run Analysis", key=f"analyze_exp_{exp['id']}"):
                                try:
                                    analysis = exp_svc.run_analysis(exp["id"])
                                    st.json(analysis)
                                except Exception as e:
                                    st.error(f"Analysis failed: {e}")

                            if st.button("Conclude", key=f"conclude_exp_{exp['id']}"):
                                try:
                                    exp_svc.conclude_experiment(exp["id"])
                                    st.success("Experiment concluded!")
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Conclude failed: {e}")
            else:
                st.info("No experiments yet for this brand.")

            # Create new experiment form
            st.markdown("---")
            st.markdown("#### Create New Experiment")

            with st.form("create_experiment_form"):
                exp_name = st.text_input("Experiment Name", placeholder="e.g. Prompt v2 vs v1")
                exp_hypothesis = st.text_area(
                    "Hypothesis",
                    placeholder="e.g. Shorter prompts will increase approval rate",
                    height=80,
                )
                exp_type = st.selectbox(
                    "Experiment Type",
                    ["prompt_version", "pipeline_config", "review_rubric", "element_strategy"],
                )
                exp_col1, exp_col2 = st.columns(2)
                with exp_col1:
                    exp_split = st.slider("Variant Traffic %", 10, 90, 50, 5) / 100.0
                with exp_col2:
                    exp_min_sample = st.number_input("Min Sample Size (per arm)", 5, 200, 20, 5)

                exp_control = st.text_area(
                    "Control Config (JSON)",
                    value='{"version": "current"}',
                    height=80,
                )
                exp_variant = st.text_area(
                    "Variant Config (JSON)",
                    value='{"version": "new"}',
                    height=80,
                )

                submitted = st.form_submit_button("Create Experiment", type="primary")
                if submitted:
                    try:
                        import json as _json
                        ctrl_cfg = _json.loads(exp_control)
                        var_cfg = _json.loads(exp_variant)
                        new_exp = exp_svc.create_experiment(
                            brand_id=UUID(exp_brand_id),
                            name=exp_name,
                            experiment_type=exp_type,
                            control_config=ctrl_cfg,
                            variant_config=var_cfg,
                            split_ratio=exp_split,
                            min_sample_size=exp_min_sample,
                            hypothesis=exp_hypothesis or None,
                        )
                        st.success(f"Experiment created: {new_exp.get('name', exp_name)}")
                        st.rerun()
                    except _json.JSONDecodeError as je:
                        st.error(f"Invalid JSON in config: {je}")
                    except Exception as e:
                        st.error(f"Failed to create experiment: {e}")

    except Exception as e:
        st.warning(f"Could not load experiment data: {e}")


# ============================================================================
# Phase 8B: Visual Style Clusters Tab
# ============================================================================
with tab_vclusters:
    st.markdown("### Visual Style Clusters")
    st.info(
        "DBSCAN clustering of ad visual embeddings, correlated with performance. "
        "Identifies which visual styles perform best."
    )

    try:
        from viraltracker.ui.utils import render_brand_selector

        vc_brand_id = render_brand_selector(key="visual_clusters_brand_selector")
        if vc_brand_id:
            from uuid import UUID
            from viraltracker.pipelines.ad_creation_v2.services.visual_clustering_service import VisualClusteringService

            vc_svc = VisualClusteringService()
            clusters = vc_svc.get_cluster_summary(UUID(vc_brand_id))

            if clusters:
                import pandas as pd
                df = pd.DataFrame([{
                    "Cluster": c["cluster_label"],
                    "Size": c["cluster_size"],
                    "Avg Reward": round(c.get("avg_reward_score") or 0, 3),
                    "Top Descriptors": str(c.get("top_descriptors", {}))[:100],
                    "Computed": c.get("computed_at", "N/A")[:10],
                } for c in clusters])

                st.dataframe(df, use_container_width=True, hide_index=True)

                # Best/worst cluster highlight
                if len(clusters) >= 2:
                    best = clusters[0]
                    bcol1, bcol2 = st.columns(2)
                    with bcol1:
                        st.success(
                            f"Best cluster: #{best['cluster_label']} "
                            f"(reward: {best.get('avg_reward_score', 0):.3f}, "
                            f"size: {best['cluster_size']})"
                        )
                    with bcol2:
                        worst = clusters[-1]
                        st.error(
                            f"Worst cluster: #{worst['cluster_label']} "
                            f"(reward: {worst.get('avg_reward_score', 0):.3f}, "
                            f"size: {worst['cluster_size']})"
                        )
            else:
                st.info("No visual clusters yet. Run Genome Validation to trigger clustering.")
    except Exception as e:
        st.warning(f"Could not load visual cluster data: {e}")


# Display current configuration summary
st.markdown("---")
st.subheader("Current LLM Configuration Snapshot")
st.code(f"""
ORCHESTRATOR_MODEL = {Config.get_model("orchestrator")}
DEFAULT_MODEL      = {Config.get_model("default")}
COMPLEX_MODEL      = {Config.get_model("complex")}
BASIC_MODEL        = {Config.get_model("basic")}
""", language="properties")
