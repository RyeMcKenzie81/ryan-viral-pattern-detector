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
    from viraltracker.ui.utils import render_organization_selector, get_current_organization_id

    # Org selector in sidebar — drives which features (and pages) are visible
    render_organization_selector(key="nav_org_selector")

    from viraltracker.ui.nav import build_navigation_pages, _get_org_features

    # Debug: show active org + features in sidebar (remove after validation)
    _debug_org = get_current_organization_id()
    _debug_features = _get_org_features(_debug_org) if _debug_org else set()
    with st.sidebar:
        with st.expander("🐛 Nav Debug", expanded=False):
            st.caption(f"**org_id:** `{_debug_org}`")
            st.caption(f"**features ({len(_debug_features)}):** {sorted(_debug_features) if _debug_features else 'none'}")

    pages = build_navigation_pages()
else:
    pages = [
        st.Page("pages/login.py", title="Sign In", icon="🔐", default=True),
        st.Page("pages/66_🌐_Public_Gallery.py", title="Public Gallery", icon="🌐"),
    ]

pg = st.navigation(pages)
pg.run()
