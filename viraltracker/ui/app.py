"""
Viraltracker UI — entry point with dynamic sidebar navigation.

Uses st.navigation() to build the sidebar from feature-gated page lists.
Unauthenticated users see only the Sign In and Public Gallery pages.
Authenticated users see pages filtered by their organization's enabled features.

Run with:
    streamlit run viraltracker/ui/app.py
"""

import asyncio
import os
import sys
import logging

# Force standard asyncio event loop so nest_asyncio can patch it.
# uvloop (pulled in by uvicorn[standard]) cannot be patched, which
# causes ValueError in every page that calls nest_asyncio.apply().
asyncio.set_event_loop_policy(asyncio.DefaultEventLoopPolicy())
_loop = asyncio.new_event_loop()
asyncio.set_event_loop(_loop)

import nest_asyncio
nest_asyncio.apply()

import streamlit as st

st.set_page_config(
    page_title="Viraltracker",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ============================================================================
# Observability — same init as app.py, cached per process
# ============================================================================


@st.cache_resource
def init_observability():
    """Initialize Logfire at runtime, once per process."""
    print("LOGFIRE INIT STARTING", file=sys.stderr, flush=True)

    token = os.environ.get("LOGFIRE_TOKEN")
    if not token:
        print("LOGFIRE SKIPPED: No token", file=sys.stderr, flush=True)
        return {"status": "skipped", "reason": "LOGFIRE_TOKEN not set"}

    try:
        import logfire

        print(f"LOGFIRE: Token found (len={len(token)})", file=sys.stderr, flush=True)

        env = os.environ.get("LOGFIRE_ENVIRONMENT", "production")
        logfire.configure(
            token=token,
            service_name="viraltracker",
            environment=env,
            send_to_logfire=True,
            console=False,
        )
        print("LOGFIRE: Configured", file=sys.stderr, flush=True)

        logging.basicConfig(
            level=logging.INFO,
            handlers=[
                logfire.LogfireLoggingHandler(),
                logging.StreamHandler(sys.stderr),
            ],
            force=True,
        )
        print("LOGFIRE: Logging configured", file=sys.stderr, flush=True)

        logfire.instrument_pydantic()
        logfire.info("Logfire observability initialized")
        print("LOGFIRE INIT SUCCESS", file=sys.stderr, flush=True)
        return {"status": "success", "environment": env}

    except Exception as e:
        print(f"LOGFIRE INIT ERROR: {e}", file=sys.stderr, flush=True)
        return {"status": "error", "reason": str(e)}


_logfire_status = init_observability()
print(f"LOGFIRE STATUS: {_logfire_status}", file=sys.stderr, flush=True)


# ============================================================================
# Navigation
# ============================================================================

from viraltracker.ui.auth import is_authenticated

if is_authenticated():
    from viraltracker.ui.utils import render_organization_selector
    from viraltracker.ui.nav import build_navigation_pages

    pages = build_navigation_pages()

    # Hide the default navigation so we can build a custom sidebar
    # with the org selector above the page links.
    pg = st.navigation(pages, position="hidden")

    with st.sidebar:
        # Reduce top padding and spacing around the workspace selector
        st.markdown(
            """<style>
            [data-testid="stSidebar"] [data-testid="stSidebarContent"] { padding-top: 1rem; }
            [data-testid="stSidebar"] hr { margin-top: 0.5rem; margin-bottom: 0.5rem; }
            </style>""",
            unsafe_allow_html=True,
        )
        # Org selector first — drives which features (and pages) are visible
        render_organization_selector()
        st.divider()

        # Render page links grouped by section
        for section, page_list in pages.items():
            if section:
                st.header(section)
            for page in page_list:
                st.page_link(page, icon=page.icon)

        # Logfire observability status
        st.divider()
        if _logfire_status["status"] == "success":
            st.caption(f"✅ Logfire: {_logfire_status['environment']}")
        elif _logfire_status["status"] == "skipped":
            st.caption("⚠️ Logfire: off")
        else:
            st.caption("❌ Logfire: error")

    pg.run()
else:
    pages = [
        st.Page("pages/login.py", title="Sign In", icon="🔐", default=True),
        st.Page("pages/66_🌐_Public_Gallery.py", title="Public Gallery", icon="🌐"),
    ]
    pg = st.navigation(pages)
    pg.run()
