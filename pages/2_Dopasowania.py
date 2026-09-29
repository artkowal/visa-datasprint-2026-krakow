"""Osobna strona dopasowań; te same tryby są też na ekranie głównym."""

import streamlit as st

from app.matching_view import render_matching


st.set_page_config(page_title="Dopasowania gmin", page_icon="🧩", layout="wide")
st.markdown("""
<style>
    .stApp { background: #1e1e2e; color: #cdd6f4; }
    h1, h2, h3 { color: #a78bfa !important; }
</style>
""", unsafe_allow_html=True)
st.title("🧩 Dopasowania gmin")
mode = st.radio("Tryb dopasowania", ["Wzmocnienie", "Uzupełnienie"], horizontal=True)
render_matching(mode)
