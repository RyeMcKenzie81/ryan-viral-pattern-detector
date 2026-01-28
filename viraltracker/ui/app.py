"""
Viraltracker UI — entry point with dynamic sidebar navigation.

Uses st.navigation() to build the sidebar from feature-gated page lists.
Unauthenticated users see only the Sign In and Public Gallery pages.
Authenticated users see pages filtered by their organization's enabled features.

Run with:
    streamlit run viraltracker/ui/app_v2.py [--server.port 8502]

This entry point coexists with the original app.py.
Once validated, swap app_v2.py -> app.py.
"""

import os
import sys
import logging

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

from viraltracker.ui.auth import is_authenticated, _add_logout_button

if is_authenticated():
    _add_logout_button()

    from viraltracker.ui.nav import build_navigation_pages

    pages = build_navigation_pages()
else:
    pages = [
        st.Page("pages/login.py", title="Sign In", icon="🔐", default=True),
        st.Page("pages/66_🌐_Public_Gallery.py", title="Public Gallery", icon="🌐"),
    ]

pg = st.navigation(pages)
pg.run()
