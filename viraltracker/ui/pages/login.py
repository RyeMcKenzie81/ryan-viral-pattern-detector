"""
Login page for unauthenticated users.

Shown as the default page when user is not signed in.
Calls st.rerun() on successful sign-in so the navigation rebuilds
with the authenticated page list.
"""

import streamlit as st

st.header("Welcome to ViralTracker")
st.markdown("Sign in to access your dashboard.")

with st.form("login_form", clear_on_submit=False):
    email = st.text_input("Email")
    password = st.text_input("Password", type="password")
    submitted = st.form_submit_button("Sign In", type="primary", use_container_width=True)

    if submitted:
        if not email or not password:
            st.error("Please enter both email and password")
        else:
            from viraltracker.ui.auth import sign_in

            with st.spinner("Signing in..."):
                success, error = sign_in(email, password)
            if success:
                st.success("Signed in successfully!")
                st.rerun()
            else:
                st.error(error or "Sign in failed")
