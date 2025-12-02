"""Section divider - Content & Knowledge"""
import streamlit as st

st.set_page_config(page_title="Content", page_icon="━", layout="wide")

from viraltracker.ui.auth import require_auth
require_auth()

st.title("Content & Knowledge")
st.markdown("Tools for managing content and knowledge assets.")

col1, col2 = st.columns(2)
with col1:
    st.page_link("pages/07_📚_Knowledge_Base.py", label="📚 Knowledge Base", icon="📚")
with col2:
    st.page_link("pages/08_🎙️_Audio_Production.py", label="🎙️ Audio Production", icon="🎙️")
