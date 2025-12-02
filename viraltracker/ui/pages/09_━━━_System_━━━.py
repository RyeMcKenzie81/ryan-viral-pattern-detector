"""Section divider - System Tools"""
import streamlit as st

st.set_page_config(page_title="System", page_icon="━", layout="wide")

from viraltracker.ui.auth import require_auth
require_auth()

st.title("System Tools")
st.markdown("Developer tools for exploring agents, services, and data.")

col1, col2 = st.columns(2)
with col1:
    st.page_link("pages/10_🤖_Agent_Catalog.py", label="🤖 Agent Catalog", icon="🤖")
    st.page_link("pages/11_📚_Tools_Catalog.py", label="📚 Tools Catalog", icon="📚")
    st.page_link("pages/12_⚙️_Services_Catalog.py", label="⚙️ Services Catalog", icon="⚙️")
with col2:
    st.page_link("pages/13_🗄️_Database_Browser.py", label="🗄️ Database Browser", icon="🗄️")
    st.page_link("pages/14_📜_History.py", label="📜 History", icon="📜")
