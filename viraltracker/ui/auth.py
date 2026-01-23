"""
Streamlit Authentication Module - Supabase Auth

Provides Supabase-based authentication for Streamlit pages with persistent cookie sessions.

Usage:
    from viraltracker.ui.auth import require_auth

    # At the top of any protected page (after st.set_page_config):
    require_auth()

    # Rest of your page code...

To make a page PUBLIC (no auth required):
    1. Add the page filename to PUBLIC_PAGES list below
    2. Or use: require_auth(public=True) to skip auth for that page

Environment Variables:
    SUPABASE_URL: Required. Supabase project URL.
    SUPABASE_ANON_KEY: Required. Supabase anon key (for RLS-enforced auth).
"""

import os
import streamlit as st
import time
import json
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

# ============================================================================
# Configuration
# ============================================================================

# Pages that don't require authentication (add filenames here)
# Example: ["Client_Gallery.py", "Public_Report.py"]
PUBLIC_PAGES = ["66_🌐_Public_Gallery.py"]

# Cookie settings
COOKIE_NAME = "viraltracker_session"
COOKIE_EXPIRY_DAYS = 30

# Session state keys
USER_KEY = "_supabase_user"
SESSION_KEY = "_supabase_session"
AUTHENTICATED_KEY = "_authenticated"


# ============================================================================
# Supabase Client
# ============================================================================

def _get_auth_client():
    """Get Supabase client configured for auth (uses anon key)."""
    from viraltracker.core.database import get_anon_client
    return get_anon_client()


# ============================================================================
# Cookie Management
# ============================================================================

def _get_cookie_controller():
    """Get the cookie controller instance."""
    from streamlit_cookies_controller import CookieController
    return CookieController()


def _save_session_to_cookie(session_data: Dict[str, Any]) -> None:
    """
    Save Supabase session data to browser cookie.

    Args:
        session_data: Dict containing access_token, refresh_token, expires_at
    """
    try:
        controller = _get_cookie_controller()
        cookie_value = json.dumps({
            "access_token": session_data.get("access_token"),
            "refresh_token": session_data.get("refresh_token"),
            "expires_at": session_data.get("expires_at"),
        })
        controller.set(
            COOKIE_NAME,
            cookie_value,
            max_age=COOKIE_EXPIRY_DAYS * 24 * 60 * 60
        )
        logger.debug("Session saved to cookie")
    except Exception as e:
        logger.warning(f"Failed to save session cookie: {e}")


def _get_session_from_cookie() -> Optional[Dict[str, Any]]:
    """
    Get session data from browser cookie.

    Returns:
        Session data dict or None if not found/invalid
    """
    try:
        controller = _get_cookie_controller()
        cookie_value = controller.get(COOKIE_NAME)
        if not cookie_value:
            return None

        # Parse the cookie value
        if isinstance(cookie_value, str):
            return json.loads(cookie_value)
        return cookie_value
    except Exception as e:
        logger.debug(f"Failed to get session from cookie: {e}")
        return None


def _clear_session_cookie() -> None:
    """Clear the session cookie."""
    try:
        controller = _get_cookie_controller()
        controller.remove(COOKIE_NAME)
        logger.debug("Session cookie cleared")
    except Exception as e:
        logger.warning(f"Failed to clear session cookie: {e}")


# ============================================================================
# Session Management
# ============================================================================

def _init_session_state() -> None:
    """Initialize auth-related session state."""
    if USER_KEY not in st.session_state:
        st.session_state[USER_KEY] = None
    if SESSION_KEY not in st.session_state:
        st.session_state[SESSION_KEY] = None
    if AUTHENTICATED_KEY not in st.session_state:
        st.session_state[AUTHENTICATED_KEY] = False


def _restore_session() -> bool:
    """
    Try to restore session from cookie.

    Returns:
        True if session was restored successfully, False otherwise
    """
    session_data = _get_session_from_cookie()
    if not session_data:
        return False

    access_token = session_data.get("access_token")
    refresh_token = session_data.get("refresh_token")
    expires_at = session_data.get("expires_at", 0)

    if not access_token or not refresh_token:
        return False

    # Check if token is expired (with 5 min buffer)
    current_time = time.time()
    if expires_at and expires_at < current_time + 300:
        # Token is expired or about to expire, try to refresh
        return _refresh_session(refresh_token)

    # Token is still valid, try to get user
    try:
        client = _get_auth_client()
        # Set the session on the client
        response = client.auth.set_session(access_token, refresh_token)

        if response and response.user:
            st.session_state[USER_KEY] = response.user
            st.session_state[SESSION_KEY] = response.session
            st.session_state[AUTHENTICATED_KEY] = True
            logger.debug(f"Session restored for user: {response.user.email}")
            return True
    except Exception as e:
        logger.debug(f"Failed to restore session: {e}")
        # Try to refresh the session
        return _refresh_session(refresh_token)

    return False


def _refresh_session(refresh_token: str) -> bool:
    """
    Refresh the session using the refresh token.

    Args:
        refresh_token: The refresh token

    Returns:
        True if refresh successful, False otherwise
    """
    try:
        client = _get_auth_client()
        response = client.auth.refresh_session(refresh_token)

        if response and response.session:
            session = response.session
            st.session_state[USER_KEY] = response.user
            st.session_state[SESSION_KEY] = session
            st.session_state[AUTHENTICATED_KEY] = True

            # Save new tokens to cookie
            _save_session_to_cookie({
                "access_token": session.access_token,
                "refresh_token": session.refresh_token,
                "expires_at": session.expires_at,
            })
            logger.debug("Session refreshed successfully")
            return True
    except Exception as e:
        logger.debug(f"Failed to refresh session: {e}")

    return False


# ============================================================================
# Authentication Operations
# ============================================================================

def sign_in(email: str, password: str) -> tuple[bool, Optional[str]]:
    """
    Sign in with email and password.

    Args:
        email: User email
        password: User password

    Returns:
        Tuple of (success, error_message)
    """
    try:
        client = _get_auth_client()
        response = client.auth.sign_in_with_password({
            "email": email,
            "password": password
        })

        if response and response.session:
            session = response.session
            st.session_state[USER_KEY] = response.user
            st.session_state[SESSION_KEY] = session
            st.session_state[AUTHENTICATED_KEY] = True

            # Save to cookie
            _save_session_to_cookie({
                "access_token": session.access_token,
                "refresh_token": session.refresh_token,
                "expires_at": session.expires_at,
            })
            logger.info(f"User signed in: {response.user.email}")
            return True, None
    except Exception as e:
        error_msg = str(e)
        # Parse common error messages
        if "Invalid login credentials" in error_msg:
            return False, "Invalid email or password"
        if "Email not confirmed" in error_msg:
            return False, "Please check your email to confirm your account"
        logger.warning(f"Sign in failed: {e}")
        return False, f"Sign in failed: {error_msg}"

    return False, "Sign in failed"


def sign_up(email: str, password: str) -> tuple[bool, Optional[str]]:
    """
    Sign up with email and password.

    Args:
        email: User email
        password: User password

    Returns:
        Tuple of (success, error_message)
    """
    try:
        client = _get_auth_client()
        response = client.auth.sign_up({
            "email": email,
            "password": password
        })

        if response and response.user:
            # Check if email confirmation is required
            if response.session:
                # Auto-confirmed, sign them in
                session = response.session
                st.session_state[USER_KEY] = response.user
                st.session_state[SESSION_KEY] = session
                st.session_state[AUTHENTICATED_KEY] = True

                _save_session_to_cookie({
                    "access_token": session.access_token,
                    "refresh_token": session.refresh_token,
                    "expires_at": session.expires_at,
                })
                logger.info(f"User signed up and auto-confirmed: {response.user.email}")
                return True, None
            else:
                # Email confirmation required
                logger.info(f"User signed up, awaiting confirmation: {response.user.email}")
                return True, "Please check your email to confirm your account"
    except Exception as e:
        error_msg = str(e)
        if "already registered" in error_msg.lower():
            return False, "This email is already registered. Try signing in instead."
        if "password" in error_msg.lower() and "6" in error_msg:
            return False, "Password must be at least 6 characters"
        logger.warning(f"Sign up failed: {e}")
        return False, f"Sign up failed: {error_msg}"

    return False, "Sign up failed"


def sign_out() -> None:
    """Sign out the current user."""
    try:
        client = _get_auth_client()
        client.auth.sign_out()
    except Exception as e:
        logger.debug(f"Sign out API call failed (may be expected): {e}")

    # Clear session state
    st.session_state[USER_KEY] = None
    st.session_state[SESSION_KEY] = None
    st.session_state[AUTHENTICATED_KEY] = False

    # Clear cookie
    _clear_session_cookie()
    logger.info("User signed out")


# ============================================================================
# UI Components
# ============================================================================

def _show_login_form() -> None:
    """Display the login/signup form."""
    st.markdown("### Welcome to ViralTracker")
    st.markdown("Sign in to access your dashboard.")

    # Tabs for login and signup
    tab_login, tab_signup = st.tabs(["Sign In", "Sign Up"])

    with tab_login:
        with st.form("login_form", clear_on_submit=False):
            email = st.text_input("Email", key="login_email")
            password = st.text_input("Password", type="password", key="login_password")
            remember = st.checkbox("Remember me", value=True, key="login_remember")
            submitted = st.form_submit_button("Sign In", type="primary", use_container_width=True)

            if submitted:
                if not email or not password:
                    st.error("Please enter both email and password")
                else:
                    with st.spinner("Signing in..."):
                        success, error = sign_in(email, password)
                    if success:
                        st.success("Signed in successfully!")
                        st.rerun()
                    else:
                        st.error(error or "Sign in failed")

    with tab_signup:
        with st.form("signup_form", clear_on_submit=False):
            email = st.text_input("Email", key="signup_email")
            password = st.text_input("Password", type="password", key="signup_password")
            password_confirm = st.text_input("Confirm Password", type="password", key="signup_password_confirm")
            submitted = st.form_submit_button("Create Account", type="primary", use_container_width=True)

            if submitted:
                if not email or not password:
                    st.error("Please enter both email and password")
                elif password != password_confirm:
                    st.error("Passwords do not match")
                elif len(password) < 6:
                    st.error("Password must be at least 6 characters")
                else:
                    with st.spinner("Creating account..."):
                        success, message = sign_up(email, password)
                    if success:
                        if message:
                            st.info(message)
                        else:
                            st.success("Account created!")
                            st.rerun()
                    else:
                        st.error(message or "Sign up failed")

    # Stop execution - don't render rest of page
    st.stop()


def _add_logout_button() -> None:
    """Add logout button and user info to sidebar."""
    user = st.session_state.get(USER_KEY)
    with st.sidebar:
        if user:
            st.markdown(f"**{user.email}**")
        if st.button("Sign Out", key="_logout_btn"):
            sign_out()
            st.rerun()


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

    # Initialize session state
    _init_session_state()

    # Check if already authenticated in session
    if st.session_state.get(AUTHENTICATED_KEY):
        _add_logout_button()
        return True

    # Try to restore session from cookie
    if _restore_session():
        _add_logout_button()
        return True

    # Show login form
    _show_login_form()
    return False


def is_authenticated() -> bool:
    """
    Check if current session is authenticated without showing login form.

    Useful for conditionally showing content based on auth status.

    Returns:
        True if authenticated, False otherwise.
    """
    _init_session_state()

    if st.session_state.get(AUTHENTICATED_KEY):
        return True

    # Try to restore from cookie (silent)
    return _restore_session()


def get_current_user():
    """
    Get the currently authenticated user.

    Returns:
        User object or None if not authenticated
    """
    return st.session_state.get(USER_KEY)


def get_current_user_id() -> Optional[str]:
    """
    Get the currently authenticated user's ID.

    Returns:
        User ID string or None if not authenticated
    """
    user = get_current_user()
    if user:
        return user.id
    return None
