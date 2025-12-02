"""
Streamlit Authentication Module

Provides password protection for Streamlit pages with persistent cookie sessions.

Usage:
    from viraltracker.ui.auth import require_auth

    # At the top of any protected page (after st.set_page_config):
    require_auth()

    # Rest of your page code...

To make a page PUBLIC (no auth required):
    1. Add the page filename to PUBLIC_PAGES list below
    2. Or use: require_auth(public=True) to skip auth for that page

Environment Variables:
    STREAMLIT_PASSWORD: Required. The password users must enter.
    STREAMLIT_COOKIE_KEY: Optional. Secret key for signing cookies (auto-generated if not set).
    STREAMLIT_COOKIE_EXPIRY_DAYS: Optional. How long sessions last (default: 30 days).
"""

import os
import streamlit as st
import hashlib
import hmac
import time
import base64
import json
from typing import Optional

# ============================================================================
# Configuration
# ============================================================================

# Pages that don't require authentication (add filenames here)
# Example: ["Client_Gallery.py", "Public_Report.py"]
PUBLIC_PAGES = []

# Cookie settings
COOKIE_NAME = "viraltracker_auth"
COOKIE_EXPIRY_DAYS = int(os.getenv("STREAMLIT_COOKIE_EXPIRY_DAYS", "90"))

def _get_cookie_key() -> str:
    """Get or generate the cookie signing key."""
    key = os.getenv("STREAMLIT_COOKIE_KEY")
    if not key:
        # Generate a key from the password (stable across restarts)
        password = os.getenv("STREAMLIT_PASSWORD", "")
        key = hashlib.sha256(f"viraltracker_cookie_{password}".encode()).hexdigest()
    return key


def _get_password() -> Optional[str]:
    """Get the configured password."""
    return os.getenv("STREAMLIT_PASSWORD")


# ============================================================================
# Cookie Management (using query params as fallback, localStorage preferred)
# ============================================================================

def _sign_token(data: dict) -> str:
    """Create a signed token from data."""
    payload = json.dumps(data, sort_keys=True)
    signature = hmac.new(
        _get_cookie_key().encode(),
        payload.encode(),
        hashlib.sha256
    ).hexdigest()

    token_data = {"payload": payload, "sig": signature}
    return base64.urlsafe_b64encode(json.dumps(token_data).encode()).decode()


def _verify_token(token: str) -> Optional[dict]:
    """Verify and decode a signed token."""
    try:
        token_data = json.loads(base64.urlsafe_b64decode(token.encode()).decode())
        payload = token_data["payload"]
        signature = token_data["sig"]

        expected_sig = hmac.new(
            _get_cookie_key().encode(),
            payload.encode(),
            hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(signature, expected_sig):
            return None

        data = json.loads(payload)

        # Check expiry
        if data.get("exp", 0) < time.time():
            return None

        return data
    except Exception:
        return None


def _create_auth_token() -> str:
    """Create a new auth token."""
    expiry = time.time() + (COOKIE_EXPIRY_DAYS * 24 * 60 * 60)
    return _sign_token({"auth": True, "exp": expiry})


def _get_stored_token() -> Optional[str]:
    """Get token from session state (set by JavaScript from localStorage)."""
    return st.session_state.get("_auth_token_from_storage")


def _inject_cookie_scripts(token: Optional[str] = None):
    """Inject JavaScript to handle localStorage for persistent auth."""

    if token:
        # Set token in localStorage
        js = f"""
        <script>
            localStorage.setItem('{COOKIE_NAME}', '{token}');
        </script>
        """
        st.markdown(js, unsafe_allow_html=True)

    # Always inject script to read token and send to Streamlit
    # This uses a hidden form to communicate back
    js_read = f"""
    <script>
        (function() {{
            const token = localStorage.getItem('{COOKIE_NAME}');
            if (token && !window._authTokenSent) {{
                window._authTokenSent = true;
                // Store in a way Streamlit can access
                const event = new CustomEvent('streamlit:setComponentValue', {{
                    detail: {{ value: token }}
                }});

                // Use query params as a fallback mechanism
                const url = new URL(window.location.href);
                if (!url.searchParams.has('_auth')) {{
                    url.searchParams.set('_auth', token);
                    // Only redirect if we have a token and it's not already in URL
                    if (token && window.location.search.indexOf('_auth=') === -1) {{
                        window.location.href = url.toString();
                    }}
                }}
            }}
        }})();
    </script>
    """
    st.markdown(js_read, unsafe_allow_html=True)


def _clear_auth():
    """Clear authentication."""
    js = f"""
    <script>
        localStorage.removeItem('{COOKIE_NAME}');
        const url = new URL(window.location.href);
        url.searchParams.delete('_auth');
        window.location.href = url.toString();
    </script>
    """
    st.markdown(js, unsafe_allow_html=True)
    st.session_state["_authenticated"] = False


# ============================================================================
# Main Authentication Function
# ============================================================================

def require_auth(public: bool = False) -> bool:
    """
    Require authentication for the current page.

    Call this at the top of each Streamlit page (after set_page_config).

    Args:
        public: If True, skip authentication for this page.

    Returns:
        True if authenticated, False otherwise.

    Usage:
        # Protected page (default):
        require_auth()

        # Public page:
        require_auth(public=True)
    """
    # Skip auth if page is public
    if public:
        return True

    # Check if page is in public pages list
    try:
        import inspect
        frame = inspect.currentframe()
        if frame and frame.f_back:
            filename = os.path.basename(frame.f_back.f_code.co_filename)
            if filename in PUBLIC_PAGES:
                return True
    except Exception:
        pass

    # Check if auth is disabled (no password set)
    password = _get_password()
    if not password:
        # No password configured - allow access but show warning
        st.sidebar.warning("Auth disabled (STREAMLIT_PASSWORD not set)")
        return True

    # Check session state first (fastest)
    if st.session_state.get("_authenticated"):
        _add_logout_button()
        return True

    # Check for token in query params (from localStorage redirect)
    query_params = st.query_params
    token = query_params.get("_auth")

    if token:
        token_data = _verify_token(token)
        if token_data and token_data.get("auth"):
            st.session_state["_authenticated"] = True
            _add_logout_button()
            return True

    # Inject script to check localStorage and redirect if token exists
    _inject_cookie_scripts()

    # Show login form
    _show_login_form(password)
    return False


def _show_login_form(correct_password: str):
    """Display the login form."""
    st.markdown("### Login Required")
    st.markdown("Enter the password to access this application.")

    with st.form("login_form"):
        password_input = st.text_input("Password", type="password")
        remember = st.checkbox("Remember me for 90 days", value=True)
        submitted = st.form_submit_button("Login", type="primary")

        if submitted:
            if password_input == correct_password:
                st.session_state["_authenticated"] = True

                if remember:
                    # Create token and store in localStorage
                    token = _create_auth_token()
                    _inject_cookie_scripts(token)

                    # Also add to URL for immediate access
                    st.query_params["_auth"] = token

                st.rerun()
            else:
                st.error("Incorrect password")

    # Stop execution - don't render rest of page
    st.stop()


def _add_logout_button():
    """Add logout button to sidebar."""
    with st.sidebar:
        if st.button("Logout", key="_logout_btn"):
            _clear_auth()
            st.session_state["_authenticated"] = False
            st.query_params.clear()
            st.rerun()


def is_authenticated() -> bool:
    """
    Check if current session is authenticated without showing login form.

    Useful for conditionally showing content based on auth status.

    Returns:
        True if authenticated, False otherwise.
    """
    if st.session_state.get("_authenticated"):
        return True

    password = _get_password()
    if not password:
        return True  # No auth configured

    token = st.query_params.get("_auth")
    if token:
        token_data = _verify_token(token)
        if token_data and token_data.get("auth"):
            return True

    return False
