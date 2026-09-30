import base64
from pathlib import Path

import streamlit as st

_LOGO_PATH = Path(__file__).resolve().parent.parent / "assets" / "megapolis-visa.svg"


@st.cache_resource(show_spinner=False)
def _logo_data_uri() -> str:
    svg = _LOGO_PATH.read_bytes()
    return "data:image/svg+xml;base64," + base64.b64encode(svg).decode()


def render_sidebar_logo() -> None:
    with st.sidebar:
        st.markdown(
            f'<div class="megapolis-logo-wrap">'
            f'<img src="{_logo_data_uri()}" alt="Megapolis VISA">'
            f'</div>',
            unsafe_allow_html=True,
        )
