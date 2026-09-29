"""Osobna strona dopasowań; te same tryby są też na ekranie głównym."""

from pathlib import Path

import streamlit as st

from app.matching_view import render_matching


st.set_page_config(page_title="Megapolis VISA | Dopasowania", page_icon="🧩", layout="wide")
st.markdown("""
<style>
    .stApp { background: #1e1e2e; color: #cdd6f4; }
    h1, h2, h3 { color: #a78bfa !important; }
</style>
""", unsafe_allow_html=True)
logo_col, note_col = st.columns([3, 2], gap="large", vertical_alignment="center")
with logo_col:
    st.image(str(Path(__file__).resolve().parents[1] / "assets" / "megapolis-visa.svg"), use_container_width=True)
with note_col:
    st.markdown(
        '<div style="padding:16px 20px;border-left:3px solid #f7bb42;'
        'border-radius:8px;background:#282c44;color:#cdd6f4;line-height:1.45">'
        'Zobacz, gdzie gminy współpracują i jakie funkcje mogą rozwijać razem.'
        '</div>',
        unsafe_allow_html=True,
    )
st.header("Dopasowania gmin")
mode = st.radio("Tryb dopasowania", ["Wzmocnienie", "Uzupełnienie"], horizontal=True)
render_matching(mode)
