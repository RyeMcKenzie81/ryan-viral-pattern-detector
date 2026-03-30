"""
Content Policies Page — per-brand automation configuration for SEO content.

Configure:
- Image evaluation rules (AI-checked brand-specific visual criteria)
- Publish cadence (times per day, window, timezone, days of week)
- Auto-interlinking modes
- Warning tolerance for auto-publishing
"""

import json
import logging
import streamlit as st
from viraltracker.ui.auth import require_auth

st.set_page_config(page_title="Content Policies", page_icon="📋", layout="wide")
require_auth()

logger = logging.getLogger(__name__)


# =============================================================================
# HELPERS
# =============================================================================

def get_db():
    from viraltracker.core.database import get_supabase_client
    return get_supabase_client()


def _load_policy(brand_id: str):
    """Load content policy for a brand, or return defaults."""
    db = get_db()
    result = (
        db.table("brand_content_policies")
        .select("*")
        .eq("brand_id", brand_id)
        .limit(1)
        .execute()
    )
    if result.data:
        return result.data[0]
    return None


def _save_policy(brand_id: str, organization_id: str, policy_data: dict):
    """Create or update a brand content policy."""
    db = get_db()
    existing = (
        db.table("brand_content_policies")
        .select("id")
        .eq("brand_id", brand_id)
        .limit(1)
        .execute()
    )

    policy_data["brand_id"] = brand_id
    policy_data["organization_id"] = organization_id

    if existing.data:
        db.table("brand_content_policies").update(
            policy_data
        ).eq("id", existing.data[0]["id"]).execute()
    else:
        db.table("brand_content_policies").insert(policy_data).execute()


TIMEZONES = [
    "America/New_York",
    "America/Chicago",
    "America/Denver",
    "America/Los_Angeles",
    "America/Phoenix",
    "America/Anchorage",
    "Pacific/Honolulu",
    "Europe/London",
    "Europe/Berlin",
    "Europe/Paris",
    "Asia/Tokyo",
    "Asia/Shanghai",
    "Australia/Sydney",
    "UTC",
]

DAY_NAMES = {1: "Monday", 2: "Tuesday", 3: "Wednesday", 4: "Thursday",
             5: "Friday", 6: "Saturday", 7: "Sunday"}


# =============================================================================
# MAIN PAGE
# =============================================================================

st.title("📋 Content Policies")
st.caption("Configure automated content evaluation, publishing, and interlinking per brand.")

# Brand selector
from viraltracker.ui.utils import render_brand_selector
brand_id = render_brand_selector(key="content_policies_brand")
if not brand_id:
    st.stop()

# Get organization_id from brand
from viraltracker.ui.utils import get_current_organization_id
organization_id = get_current_organization_id()

# Load existing policy
policy = _load_policy(brand_id)
has_policy = policy is not None
if not has_policy:
    policy = {}

st.divider()

# =============================================================================
# IMAGE EVALUATION RULES
# =============================================================================

st.subheader("🖼️ Image Evaluation Rules")
st.caption(
    "Define brand-specific rules that Claude vision checks against every generated image. "
    "Rules with severity 'error' block auto-publishing. 'Warning' rules are counted against the warning tolerance."
)

image_eval_enabled = st.toggle(
    "Enable image evaluation",
    value=policy.get("image_eval_enabled", True),
    key="cp_image_eval_enabled",
)

existing_rules = policy.get("image_eval_rules", [])
if isinstance(existing_rules, str):
    try:
        existing_rules = json.loads(existing_rules)
    except (json.JSONDecodeError, TypeError):
        existing_rules = []

# Initialize session state for rules
if "cp_image_rules" not in st.session_state:
    st.session_state.cp_image_rules = existing_rules.copy() if existing_rules else []

# Display existing rules
if st.session_state.cp_image_rules:
    for i, rule in enumerate(st.session_state.cp_image_rules):
        col1, col2, col3 = st.columns([5, 1, 1])
        with col1:
            st.text(f"{i+1}. [{rule.get('severity', 'error').upper()}] {rule.get('rule', '')}")
        with col2:
            severity_badge = "🔴" if rule.get("severity") == "error" else "🟡"
            st.text(severity_badge)
        with col3:
            if st.button("Remove", key=f"cp_remove_rule_{i}"):
                st.session_state.cp_image_rules.pop(i)
                st.rerun()
else:
    st.info("No image evaluation rules configured. Add rules below.")

# Add new rule
with st.expander("Add new rule", expanded=not st.session_state.cp_image_rules):
    new_rule_text = st.text_input(
        "Rule description",
        placeholder="e.g., Characters must be facing the viewer/camera",
        key="cp_new_rule_text",
    )
    new_rule_severity = st.selectbox(
        "Severity",
        options=["error", "warning"],
        help="Error = blocks auto-publish. Warning = counted against tolerance.",
        key="cp_new_rule_severity",
    )
    if st.button("Add Rule", key="cp_add_rule"):
        if new_rule_text.strip():
            st.session_state.cp_image_rules.append({
                "rule": new_rule_text.strip(),
                "severity": new_rule_severity,
            })
            st.rerun()

min_confidence = st.slider(
    "Minimum confidence threshold",
    min_value=0.5,
    max_value=1.0,
    value=float(policy.get("image_eval_min_confidence", 0.8)),
    step=0.05,
    help="Rules failing below this confidence are flagged for human review instead of auto-failing.",
    key="cp_min_confidence",
)

st.divider()

# =============================================================================
# PUBLISH CADENCE
# =============================================================================

st.subheader("📅 Publish Cadence")
st.caption(
    "Configure how articles are staggered when publishing to Shopify. "
    "Articles that pass all checks are queued and published at configured intervals."
)

publish_enabled = st.toggle(
    "Enable automatic publishing",
    value=policy.get("publish_enabled", False),
    key="cp_publish_enabled",
)

if publish_enabled:
    col1, col2 = st.columns(2)
    with col1:
        times_per_day = st.number_input(
            "Publications per day",
            min_value=1,
            max_value=10,
            value=policy.get("publish_times_per_day", 2),
            key="cp_times_per_day",
        )
    with col2:
        tz_default = policy.get("publish_timezone", "America/New_York")
        tz_index = TIMEZONES.index(tz_default) if tz_default in TIMEZONES else 0
        timezone = st.selectbox(
            "Timezone",
            options=TIMEZONES,
            index=tz_index,
            key="cp_timezone",
        )

    col1, col2 = st.columns(2)
    with col1:
        window_start_str = policy.get("publish_window_start", "09:00")
        h_s, m_s = map(int, str(window_start_str).split(":"))
        from datetime import time as dt_time
        window_start = st.time_input(
            "Window start",
            value=dt_time(h_s, m_s),
            key="cp_window_start",
        )
    with col2:
        window_end_str = policy.get("publish_window_end", "17:00")
        h_e, m_e = map(int, str(window_end_str).split(":"))
        window_end = st.time_input(
            "Window end",
            value=dt_time(h_e, m_e),
            key="cp_window_end",
        )

    existing_days = policy.get("publish_days_of_week", [1, 2, 3, 4, 5])
    if isinstance(existing_days, str):
        try:
            existing_days = json.loads(existing_days)
        except (json.JSONDecodeError, TypeError):
            existing_days = [1, 2, 3, 4, 5]

    selected_days = st.multiselect(
        "Publish days",
        options=list(DAY_NAMES.keys()),
        default=existing_days,
        format_func=lambda x: DAY_NAMES[x],
        key="cp_days_of_week",
    )
else:
    times_per_day = policy.get("publish_times_per_day", 2)
    timezone = policy.get("publish_timezone", "America/New_York")
    window_start = None
    window_end = None
    selected_days = policy.get("publish_days_of_week", [1, 2, 3, 4, 5])

st.divider()

# =============================================================================
# AUTO-INTERLINKING
# =============================================================================

st.subheader("🔗 Auto-Interlinking")
st.caption(
    "After an article publishes to Shopify, automatically create internal links "
    "between related articles in the same cluster."
)

interlink_enabled = st.toggle(
    "Enable auto-interlinking after publish",
    value=policy.get("interlink_enabled", True),
    key="cp_interlink_enabled",
)

existing_modes = policy.get("interlink_modes", ["auto_link", "bidirectional"])
if isinstance(existing_modes, str):
    try:
        existing_modes = json.loads(existing_modes)
    except (json.JSONDecodeError, TypeError):
        existing_modes = ["auto_link", "bidirectional"]

MODE_LABELS = {
    "suggest": "Suggest links (store suggestions only)",
    "auto_link": "Auto-link (insert <a> tags into article HTML)",
    "bidirectional": "Bidirectional (add Related Articles section)",
}

if interlink_enabled:
    selected_modes = st.multiselect(
        "Interlinking modes",
        options=list(MODE_LABELS.keys()),
        default=existing_modes,
        format_func=lambda x: MODE_LABELS.get(x, x),
        key="cp_interlink_modes",
    )
else:
    selected_modes = existing_modes

st.divider()

# =============================================================================
# WARNING TOLERANCE
# =============================================================================

st.subheader("⚙️ Evaluation Settings")

max_warnings = st.number_input(
    "Max warnings for auto-publish",
    min_value=0,
    max_value=20,
    value=policy.get("max_warnings_for_auto_publish", 0),
    help="0 = zero tolerance (all checks must pass). Higher values allow articles with N warnings to auto-publish.",
    key="cp_max_warnings",
)

st.divider()

# =============================================================================
# SAVE
# =============================================================================

if st.button("💾 Save Content Policy", type="primary", key="cp_save"):
    policy_data = {
        "image_eval_enabled": image_eval_enabled,
        "image_eval_rules": st.session_state.cp_image_rules,
        "image_eval_min_confidence": min_confidence,
        "publish_enabled": publish_enabled,
        "publish_times_per_day": times_per_day,
        "publish_window_start": window_start.strftime("%H:%M") if window_start else "09:00",
        "publish_window_end": window_end.strftime("%H:%M") if window_end else "17:00",
        "publish_timezone": timezone if publish_enabled else policy.get("publish_timezone", "America/New_York"),
        "publish_days_of_week": selected_days if publish_enabled else policy.get("publish_days_of_week", [1, 2, 3, 4, 5]),
        "interlink_enabled": interlink_enabled,
        "interlink_modes": selected_modes,
        "max_warnings_for_auto_publish": max_warnings,
    }

    try:
        _save_policy(brand_id, organization_id, policy_data)
        st.success("Content policy saved!")
        # Clear cached rules so they reload from DB
        if "cp_image_rules" in st.session_state:
            del st.session_state.cp_image_rules
        st.rerun()
    except Exception as e:
        st.error(f"Failed to save: {e}")
        logger.error(f"Failed to save content policy: {e}")
