"""Admin Page - Manage organizations, users, features, and usage limits."""

import streamlit as st

st.set_page_config(page_title="Admin", page_icon="🔧", layout="wide")

from viraltracker.ui.auth import require_auth, get_current_user_id
require_auth()

from viraltracker.core.database import get_supabase_client
from viraltracker.services.organization_service import OrganizationService
from viraltracker.services.feature_service import FeatureService, FeatureKey
from viraltracker.services.usage_limit_service import UsageLimitService, LimitType
from viraltracker.ui.utils import (
    render_organization_selector,
    get_current_organization_id,
    is_superuser,
)
import pandas as pd


# ============================================================================
# Services
# ============================================================================

def _get_org_service():
    return OrganizationService(get_supabase_client())

def _get_feature_service():
    return FeatureService(get_supabase_client())

def _get_limit_service():
    return UsageLimitService(get_supabase_client())


# ============================================================================
# Access control
# ============================================================================

user_id = get_current_user_id()
if not user_id:
    st.error("Not authenticated.")
    st.stop()

user_is_superuser = is_superuser(user_id)

# Organization selector
org_id = render_organization_selector(key="admin_org_selector")
if not org_id:
    st.stop()

# Check permissions: must be owner, admin, or superuser
if org_id != "all":
    org_service = _get_org_service()
    user_role = org_service.get_user_role(user_id, org_id)
    if not user_is_superuser and user_role not in ("owner", "admin"):
        st.error("You must be an organization owner or admin to access this page.")
        st.stop()
else:
    user_role = "superuser"


# ============================================================================
# Helpers
# ============================================================================

def _pick_org_for_tab(tab_key: str):
    """When sidebar shows 'All Organizations', render an in-tab org picker.

    Returns a specific org_id (never 'all') or None.
    """
    if org_id != "all":
        return org_id

    org_service = _get_org_service()
    orgs = org_service.get_all_organizations()
    if not orgs:
        st.info("No organizations found.")
        return None

    options = {o["name"]: o["id"] for o in orgs}
    selected_name = st.selectbox(
        "Select Organization",
        list(options.keys()),
        key=f"admin_tab_org_{tab_key}",
    )
    return options[selected_name]


# ============================================================================
# Main page
# ============================================================================

st.title("🔧 Admin")

tab_orgs, tab_users, tab_features, tab_limits = st.tabs(
    ["Organizations", "Users", "Features", "Usage Limits"]
)


# ============================================================================
# Tab: Organizations
# ============================================================================

with tab_orgs:
    org_service = _get_org_service()

    if user_is_superuser:
        st.subheader("All Organizations")
        orgs = org_service.get_all_organizations()
        if orgs:
            rows = []
            for o in orgs:
                member_count = org_service.get_member_count(o["id"])
                rows.append({
                    "Name": o["name"],
                    "Slug": o.get("slug") or "",
                    "Owner": (o.get("owner_user_id") or "")[:8] + "...",
                    "Members": member_count,
                    "Created": str(o.get("created_at", ""))[:10],
                })
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

            # Edit organizations
            st.divider()
            st.subheader("Edit Organization")
            edit_options = {o["name"]: o for o in orgs}
            edit_name = st.selectbox(
                "Select Organization to Edit",
                list(edit_options.keys()),
                key="admin_edit_org_select",
            )
            edit_org = edit_options[edit_name]

            with st.form("edit_org_form"):
                new_name = st.text_input("Name", value=edit_org["name"])
                new_slug = st.text_input("Slug", value=edit_org.get("slug") or "")
                new_owner = st.text_input(
                    "Owner User ID",
                    value=edit_org.get("owner_user_id") or "",
                )
                if st.form_submit_button("Save Changes"):
                    try:
                        updates = {}
                        if new_name != edit_org["name"]:
                            updates["name"] = new_name
                        if new_slug != (edit_org.get("slug") or ""):
                            updates["slug"] = new_slug
                        if new_owner != (edit_org.get("owner_user_id") or ""):
                            updates["owner_user_id"] = new_owner or None
                        if updates:
                            get_supabase_client().table("organizations").update(
                                updates
                            ).eq("id", edit_org["id"]).execute()
                            st.success(f"Updated {new_name}.")
                            st.rerun()
                        else:
                            st.info("No changes detected.")
                    except Exception as e:
                        st.error(f"Failed to update: {e}")
        else:
            st.info("No organizations found.")

        st.divider()
        st.subheader("Create Organization")
        with st.form("create_org_form"):
            new_org_name = st.text_input("Organization Name")
            new_org_owner = st.text_input("Owner User ID")
            submitted = st.form_submit_button("Create")
            if submitted and new_org_name and new_org_owner:
                try:
                    org = org_service.create_organization(new_org_name, new_org_owner)
                    st.success(f"Created organization: {org['name']}")
                    st.rerun()
                except Exception as e:
                    st.error(f"Failed to create organization: {e}")
    else:
        # Non-superuser: show own org info
        if org_id and org_id != "all":
            org_info = org_service.get_organization(org_id)
            if org_info:
                st.subheader(f"Organization: {org_info['name']}")
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("Slug", org_info.get("slug", "N/A"))
                with col2:
                    member_count = org_service.get_member_count(org_id)
                    st.metric("Members", member_count)
                with col3:
                    st.metric("Created", str(org_info.get("created_at", ""))[:10])


# ============================================================================
# Tab: Users
# ============================================================================

with tab_users:
    tab_org = _pick_org_for_tab("users")
    if not tab_org:
        st.stop()

    org_service = _get_org_service()
    st.subheader("Organization Members")

    members = org_service.get_org_members(tab_org)
    if members:
        member_rows = []
        for m in members:
            member_rows.append({
                "Display Name": m.get("display_name") or m["user_id"][:8] + "...",
                "Role": m["role"].title(),
                "Joined": str(m.get("created_at", ""))[:10],
                "User ID": m["user_id"],
            })
        st.dataframe(pd.DataFrame(member_rows), use_container_width=True, hide_index=True)

        # Per-member management
        st.divider()
        st.subheader("Manage Member")

        member_options = {
            f"{m.get('display_name') or m['user_id'][:8]} ({m['role']})": m
            for m in members
        }
        selected_label = st.selectbox(
            "Select Member",
            list(member_options.keys()),
            key="admin_member_select",
        )
        selected_member = member_options[selected_label]

        col_role, col_remove = st.columns(2)

        with col_role:
            can_change = True
            if selected_member["user_id"] == user_id:
                can_change = False
                st.caption("Cannot change your own role.")
            elif selected_member["role"] == "owner" and not user_is_superuser:
                can_change = False
                st.caption("Only superusers can modify owner roles.")

            role_options = ["owner", "admin", "member", "viewer"]
            current_idx = role_options.index(selected_member["role"]) if selected_member["role"] in role_options else 2
            new_role = st.selectbox(
                "Change Role",
                role_options,
                index=current_idx,
                disabled=not can_change,
                key="admin_role_change",
            )
            if st.button("Update Role", disabled=not can_change, key="admin_update_role"):
                if new_role != selected_member["role"]:
                    try:
                        org_service.update_member_role(tab_org, selected_member["user_id"], new_role)
                        st.success(f"Role updated to {new_role}.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Failed to update role: {e}")

        with col_remove:
            can_remove = selected_member["user_id"] != user_id and (
                user_is_superuser or selected_member["role"] != "owner"
            )
            if not can_remove:
                st.caption("Cannot remove yourself or the owner.")
            if st.button(
                "Remove Member",
                disabled=not can_remove,
                type="primary",
                key="admin_remove_member",
            ):
                try:
                    org_service.remove_member(tab_org, selected_member["user_id"])
                    st.success("Member removed.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Failed to remove member: {e}")

    else:
        st.info("No members found.")

    # Add member form
    st.divider()
    st.subheader("Add Member")
    with st.form("add_member_form"):
        new_user_id = st.text_input("User ID", help="The user must already have an account.")
        new_role = st.selectbox("Role", ["member", "admin", "viewer"], key="add_member_role")
        add_submitted = st.form_submit_button("Add Member")
        if add_submitted and new_user_id:
            try:
                org_service.add_member(tab_org, new_user_id, new_role)
                st.success(f"Added user as {new_role}.")
                st.rerun()
            except Exception as e:
                st.error(f"Failed to add member: {e}")


# ============================================================================
# Tab: Features
# ============================================================================

with tab_features:
    tab_org = _pick_org_for_tab("features")
    if not tab_org:
        st.stop()

    feature_service = _get_feature_service()
    st.subheader("Feature Flags")

    st.caption(
        "**Section toggle** → controls base pages only. "
        "**Opt-in pages** → controlled by their own toggle, independent of section state."
    )

    # Get current feature states from DB
    current_features = feature_service.get_org_features(tab_org)
    feature_states = {f["feature_key"]: f.get("enabled", False) for f in current_features}

    # Section → pages mapping (mirrors nav.py exactly)
    SECTIONS = [
        {
            "key": FeatureKey.SECTION_BRANDS,
            "label": "Brands",
            "base_pages": ["Brand Manager", "Personas", "URL Mapping", "Client Onboarding"],
            "opt_in": [
                (FeatureKey.BRAND_RESEARCH, "Brand Research"),
            ],
        },
        {
            "key": FeatureKey.SECTION_COMPETITORS,
            "label": "Competitors",
            "base_pages": ["Competitors", "Competitive Analysis"],
            "opt_in": [
                (FeatureKey.COMPETITOR_RESEARCH, "Competitor Research"),
                (FeatureKey.REDDIT_RESEARCH, "Reddit Research"),
            ],
        },
        {
            "key": FeatureKey.SECTION_ADS,
            "label": "Ads",
            "base_pages": [
                "Ad Gallery", "Plan List", "Plan Executor",
                "Template Queue", "Template Evaluation", "Template Recommendations",
            ],
            "opt_in": [
                (FeatureKey.AD_CREATOR, "Ad Creator"),
                (FeatureKey.AD_LIBRARY, "Ad History & Ad Performance"),
                (FeatureKey.AD_SCHEDULER, "Ad Scheduler"),
                (FeatureKey.AD_PLANNING, "Ad Planning"),
                (FeatureKey.BELIEF_CANVAS, "Belief Canvas"),
                (FeatureKey.RESEARCH_INSIGHTS, "Research Insights"),
            ],
        },
        {
            "key": FeatureKey.SECTION_CONTENT,
            "label": "Content",
            "base_pages": [
                "Comic Video", "Comic JSON Generator", "Editor Handoff",
                "Audio Production", "Knowledge Base",
            ],
            "opt_in": [
                (FeatureKey.CONTENT_PIPELINE, "Content Pipeline"),
                (FeatureKey.VEO_AVATARS, "Veo Avatars"),
            ],
        },
        {
            "key": FeatureKey.SECTION_SYSTEM,
            "label": "System",
            "base_pages": [
                "Agent Catalog", "Scheduled Tasks", "Tools Catalog",
                "Services Catalog", "Database Browser", "Platform Settings",
                "History", "Public Gallery", "Pipeline Visualizer",
                "Usage Dashboard", "Admin", "Sora MVP",
            ],
            "opt_in": [],
        },
    ]

    # Build flat list of all feature keys for bulk actions
    all_feature_keys = [s["key"] for s in SECTIONS]
    for s in SECTIONS:
        all_feature_keys.extend(pk for pk, _ in s["opt_in"])

    # Bulk actions
    col_enable, col_disable = st.columns(2)
    with col_enable:
        if st.button("Enable All", key="admin_enable_all_features"):
            feature_service.enable_all_features(tab_org)
            try:
                from viraltracker.ui.nav import _get_org_features_cached
                _get_org_features_cached.clear()
            except Exception:
                pass
            st.success("All features enabled.")
            st.rerun()
    with col_disable:
        if st.button("Disable All", key="admin_disable_all_features"):
            for fk in all_feature_keys:
                feature_service.disable_feature(tab_org, fk)
            try:
                from viraltracker.ui.nav import _get_org_features_cached
                _get_org_features_cached.clear()
            except Exception:
                pass
            st.success("All features disabled.")
            st.rerun()

    st.divider()

    # Always-visible pages
    st.caption("**Always visible:** Agent Chat (default page)")

    # Collect changes across all sections
    all_changes = {}

    for section in SECTIONS:
        sk = section["key"]
        section_enabled = feature_states.get(sk, True)  # Sections default ON
        icon = "✅" if section_enabled else "❌"

        with st.expander(f"{icon} {section['label']}", expanded=True):
            # Section master toggle
            new_section = st.checkbox(
                f"Show {section['label']} section",
                value=section_enabled,
                key=f"admin_section_{sk}",
            )
            if new_section != section_enabled:
                all_changes[sk] = new_section

            # Base pages (follow section toggle, not individually controllable)
            if section["base_pages"]:
                status = "**visible**" if new_section else "~~hidden~~"
                pages_list = ", ".join(section["base_pages"])
                st.caption(f"Base pages ({status}): {pages_list}")

            # Opt-in pages (individually toggleable)
            if section["opt_in"]:
                for pk, label in section["opt_in"]:
                    page_enabled = feature_states.get(pk, False)  # Pages default OFF

                    new_page = st.checkbox(
                        label,
                        value=page_enabled,
                        key=f"admin_page_{pk}",
                    )
                    if new_page != page_enabled:
                        all_changes[pk] = new_page

                    # No hint needed — opt-in pages are independent of section

    if all_changes:
        if st.button("Save Feature Changes", type="primary", key="admin_save_features"):
            for fk, enabled in all_changes.items():
                feature_service.set_feature(tab_org, fk, enabled)
            # Clear nav cache so sidebar updates immediately
            try:
                from viraltracker.ui.nav import _get_org_features_cached
                _get_org_features_cached.clear()
            except Exception:
                pass
            st.success(f"Updated {len(all_changes)} feature(s).")
            st.rerun()
    else:
        st.info("No changes to save.")


# ============================================================================
# Tab: Usage Limits
# ============================================================================

with tab_limits:
    tab_org = _pick_org_for_tab("limits")
    if not tab_org:
        st.stop()

    limit_service = _get_limit_service()
    st.subheader("Usage Limits")

    limit_types = [
        {"type": LimitType.MONTHLY_COST, "label": "Monthly Cost (USD)", "period": "monthly", "help": "Maximum monthly spend in USD"},
        {"type": LimitType.MONTHLY_TOKENS, "label": "Monthly Tokens", "period": "monthly", "help": "Maximum total tokens per month"},
        {"type": LimitType.DAILY_REQUESTS, "label": "Daily API Requests", "period": "daily", "help": "Maximum API requests per day"},
        {"type": LimitType.DAILY_ADS, "label": "Daily Ad Generations", "period": "daily", "help": "Maximum ad generations per day"},
    ]

    current_limits = limit_service.get_limits(tab_org)
    limit_map = {l["limit_type"]: l for l in current_limits}

    for lt_info in limit_types:
        lt = lt_info["type"]
        existing = limit_map.get(lt)

        st.markdown(f"**{lt_info['label']}**")
        col_val, col_thresh, col_enabled = st.columns([2, 1, 1])

        with col_val:
            current_val = float(existing["limit_value"]) if existing else 0.0
            if "cost" in lt:
                new_val = st.number_input(
                    "Limit Value", min_value=0.0, value=current_val, step=10.0,
                    help=lt_info["help"], key=f"admin_limit_val_{lt}", label_visibility="collapsed",
                )
            else:
                new_val = st.number_input(
                    "Limit Value", min_value=0, value=int(current_val), step=100,
                    help=lt_info["help"], key=f"admin_limit_val_{lt}", label_visibility="collapsed",
                )

        with col_thresh:
            current_thresh = float(existing.get("alert_threshold", 0.8)) if existing else 0.8
            new_thresh = st.slider(
                "Alert %", min_value=0.0, max_value=1.0, value=current_thresh,
                step=0.05, key=f"admin_limit_thresh_{lt}",
            )

        with col_enabled:
            current_enabled = existing.get("enabled", True) if existing else True
            new_enabled = st.checkbox("Enabled", value=current_enabled, key=f"admin_limit_enabled_{lt}")

        try:
            status = limit_service.get_current_period_usage(tab_org, lt)
            usage = status["current_usage"]
            if "cost" in lt:
                st.caption(f"Current usage: ${usage:.2f}")
            elif "tokens" in lt:
                st.caption(f"Current usage: {int(usage):,} tokens")
            else:
                st.caption(f"Current usage: {int(usage):,}")
        except Exception:
            pass

        col_save, col_delete = st.columns(2)
        with col_save:
            if st.button("Save", key=f"admin_limit_save_{lt}"):
                if new_val > 0:
                    limit_service.set_limit(tab_org, lt, float(new_val), lt_info["period"], new_thresh, new_enabled)
                    st.success(f"Saved {lt_info['label']} limit.")
                    st.rerun()
                else:
                    st.warning("Limit value must be greater than 0.")
        with col_delete:
            if existing:
                if st.button("Remove", key=f"admin_limit_del_{lt}"):
                    limit_service.delete_limit(tab_org, lt)
                    st.success(f"Removed {lt_info['label']} limit.")
                    st.rerun()

        st.divider()
