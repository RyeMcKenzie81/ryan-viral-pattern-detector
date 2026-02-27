"""
Public Blueprint Preview

Client-facing preview of a landing page blueprint mockup — no authentication required.
Access via: /Public_Blueprint?token=<share_token>

Shows the blueprint mockup HTML (brand-customized version of the competitor page).
"""

import streamlit as st

# Page config (must be first)
st.set_page_config(
    page_title="Blueprint Preview",
    page_icon="🏗️",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# NO AUTHENTICATION - This is a public page
# Hide sidebar and Streamlit chrome for clean presentation
st.markdown("""
<style>
    [data-testid="stSidebar"] {display: none;}
    [data-testid="stSidebarNav"] {display: none;}
    .stDeployButton {display: none;}
    #MainMenu {display: none;}
    header {display: none;}
    footer {display: none;}
</style>
""", unsafe_allow_html=True)


def get_blueprint_service():
    from viraltracker.services.landing_page_analysis.blueprint_service import (
        ReconstructionBlueprintService,
    )
    return ReconstructionBlueprintService()


# Get token from query params
query_params = st.query_params
share_token = query_params.get("token", None)

if not share_token:
    st.error("Missing token parameter. Please use a valid share link.")
    st.stop()

# Validate token format (alphanumeric + dash + underscore, 8-32 chars)
import re
if not re.match(r"^[A-Za-z0-9_-]{8,32}$", share_token):
    st.error("Invalid share link.")
    st.stop()

# Look up blueprint
service = get_blueprint_service()
result = service.get_blueprint_by_share_token(share_token)

if not result:
    st.error("Blueprint not found or sharing has been disabled.")
    st.stop()

# Render the blueprint HTML
html = result["html"]
source_url = result.get("source_url", "")

# Show source URL as a subtle header
if source_url:
    st.caption(f"Blueprint based on: {source_url}")

# Render full HTML via components.html for proper iframe rendering
import streamlit.components.v1 as components
components.html(html, height=2000, scrolling=True)
