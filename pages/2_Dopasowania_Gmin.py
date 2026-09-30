"""Osobna strona dopasowań; te same tryby są też na ekranie głównym."""

import streamlit as st

from app.matching_view import render_matching

mode = st.radio("Tryb dopasowania", ["Wzmocnienie", "Uzupełnienie"], horizontal=True)
render_matching(mode)
