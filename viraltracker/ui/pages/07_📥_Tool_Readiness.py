import streamlit as st

st.set_page_config(page_title="Tool Readiness", page_icon="📥", layout="wide")

from viraltracker.ui.auth import require_auth  # noqa: E402
require_auth()

from viraltracker.ui.utils import require_feature, render_brand_selector  # noqa: E402
require_feature("tool_readiness", "Tool Readiness")

from viraltracker.services.models import ReadinessStatus, ToolReadinessReport  # noqa: E402


# ---- Helper functions ----

def _time_ago(dt) -> str:
    """Format a datetime as a human-readable relative time."""
    from datetime import datetime, timezone
    if isinstance(dt, str):
        dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)
    if not dt.tzinfo:
        dt = dt.replace(tzinfo=timezone.utc)
    diff = now - dt
    if diff.total_seconds() < 0:
        return "just now"
    if diff.days >= 1:
        return f"{diff.days}d ago"
    hours = diff.seconds // 3600
    if hours >= 1:
        return f"{hours}h ago"
    minutes = diff.seconds // 60
    return f"{minutes}m ago" if minutes > 0 else "just now"


def _render_tool(tool):
    """Render a single tool readiness card."""
    col_info, col_action = st.columns([10, 4])

    with col_info:
        st.markdown(f"### {tool.icon} {tool.tool_label}")
        if tool.summary and tool.status != ReadinessStatus.READY:
            st.caption(tool.summary)

        all_unmet = [
            r for r in tool.hard_results + tool.soft_results + tool.freshness_results
            if not r.met
        ]
        for req in all_unmet:
            badge = "🔴" if req.requirement_type.value == "hard" else "🟡"
            line = f"{badge} **{req.label}** — {req.detail}"
            if req.fix_action:
                line += f" → _{req.fix_action}_"
            st.markdown(line)

            if req.fix_page_link:
                try:
                    fix_label = req.fix_action.split(" in ")[-1] if " in " in (req.fix_action or "") else "fix"
                    st.page_link(req.fix_page_link, label=f"Go to {fix_label}")
                except Exception:
                    pass

    with col_action:
        try:
            if tool.status == ReadinessStatus.READY:
                st.page_link(tool.page_link, label=f"Open {tool.tool_label} →")
            elif tool.status == ReadinessStatus.PARTIAL:
                st.page_link(tool.page_link, label="Open (limited) →")
        except Exception:
            st.caption(tool.tool_label)


# ---- Main page ----

brand_id = render_brand_selector(key="tool_readiness_brand")
if not brand_id:
    st.stop()

cache_key = f"tool_readiness_{brand_id}"

if cache_key not in st.session_state:
    from viraltracker.services.tool_readiness_service import ToolReadinessService
    service = ToolReadinessService()
    try:
        with st.spinner("Checking tool readiness..."):
            report = service.get_readiness_report(brand_id)
        st.session_state[cache_key] = report.model_dump(mode="json")
    except Exception as e:
        st.error(f"Failed to check readiness: {e}")
        st.stop()

report = ToolReadinessReport(**st.session_state[cache_key])

st.title("📥 Tool Readiness")

col1, col2 = st.columns([8, 2])
with col1:
    st.caption(f"Last checked: {_time_ago(report.generated_at)}")
with col2:
    if st.button("🔄 Refresh"):
        st.session_state.pop(cache_key, None)
        st.rerun()

total = len(report.ready) + len(report.partial) + len(report.blocked)
if total > 0:
    st.progress(report.overall_pct, text=f"{len(report.ready)}/{total} tools ready")

if not report.ready and not report.partial:
    st.info(
        "**Getting Started**\n\n"
        "No tools are ready yet. Recommended first steps:\n"
        "1. Add products in **Brand Manager**\n"
        "2. Set the **Ad Library URL** for your brand\n"
        "3. Add competitors (optional)\n"
        "4. Run **Brand Research** to scrape ads"
    )

STATUS_CONFIG = {
    ReadinessStatus.READY: {"emoji": "✅", "header": "Ready to Use"},
    ReadinessStatus.PARTIAL: {"emoji": "⚠️", "header": "Partially Ready"},
    ReadinessStatus.BLOCKED: {"emoji": "❌", "header": "Blocked"},
}

for status, config in STATUS_CONFIG.items():
    tools = getattr(report, status.value, [])
    if not tools:
        continue

    st.subheader(f"{config['emoji']} {config['header']} ({len(tools)})")

    for tool in tools:
        with st.container(border=True):
            _render_tool(tool)

if report.not_applicable:
    with st.expander(f"ℹ️ Not Applicable ({len(report.not_applicable)})", expanded=False):
        for tool in report.not_applicable:
            st.markdown(f"**{tool.icon} {tool.tool_label}** — {tool.summary}")
