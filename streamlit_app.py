import streamlit as st
from app.sidebar import render_sidebar_logo

st.set_page_config(
    page_title="Megapolis VISA",
    page_icon="🗺️",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
    .stApp { background: #1e1e2e; color: #cdd6f4; }
    h1, h2, h3 { color: #a78bfa !important; }
    div[data-testid="stMetric"] { background: #2a2a3e; border-radius: 8px; padding: 10px; }
    /* mniejsza przezroczystość podczas rerunu fragmentu */
    [data-stale="true"] { opacity: 0.75 !important; transition: opacity 0.15s; }
    /* zmniejszone paddingi boczne */
    .block-container { padding-left: 1.5rem !important; padding-right: 1.5rem !important; max-width: 100% !important; }

    /* sidebar zawsze widoczny na desktopie: ukryj przyciski zwijania i rozwijania.
       Na wąskich ekranach (< 768 px) sidebar jest nakładką, więc tam przyciski zostają. */
    @media (min-width: 768px) {
        [data-testid="stSidebarCollapseButton"],
        [data-testid="stSidebarCollapsedControl"],
        [data-testid="collapsedControl"] { display: none !important; }
    }

    /* ukryj wbudowany spacer/header sidebara — daje pusty odstęp nad logo */
    section[data-testid="stSidebar"] [data-testid="stLogoSpacer"],
    section[data-testid="stSidebar"] [data-testid="stSidebarHeader"],
    section[data-testid="stSidebar"] .e16xr0mu4 { display: none !important; }

    /* logo Megapolis VISA w sidebarze — pełna szerokość */
    .megapolis-logo-wrap { padding-top: 30px; padding-bottom: 4px; margin-left: -0.5rem; margin-right: -0.5rem; width: calc(100% + 1rem); }
    .megapolis-logo-wrap img { width: 100%; height: auto; display: block; }
</style>
""", unsafe_allow_html=True)

# Definicja stron — jeden obiekt używany i do routingu i do linków
page_mapa = st.Page("pages/1_Mapa.py", title="Mapa", icon="🗺️")
page_dopasowania = st.Page("pages/2_Dopasowania_Gmin.py", title="Dopasowania gmin", icon="🧩")

# 1. Logo u góry sidebara
render_sidebar_logo()

# 2. Ręczne linki nawigacyjne — pod logo
with st.sidebar:
    st.caption("Menu")
    st.page_link(page_mapa, label="Mapa", icon="🗺️")
    st.page_link(page_dopasowania, label="Dopasowania gmin", icon="🧩")

# 3. Routing bez automatycznego renderowania nav
pg = st.navigation([page_mapa, page_dopasowania], position="hidden")
pg.run()
