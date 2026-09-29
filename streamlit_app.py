import streamlit as st
from streamlit_folium import st_folium
from app.map_builder import build_map, load_gminy_data
from app.queries import get_stats_gmina

GEOJSON_PATH = "geojson/postcodes_poland.geojson"

st.set_page_config(
    page_title="Visa City Analytics",
    page_icon="",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
    .stApp { background: #1e1e2e; color: #cdd6f4; }
    h1, h2, h3 { color: #a78bfa !important; }
</style>
""", unsafe_allow_html=True)

st.title("Visa")

# ── Dane gmin (dissolve kodów pocztowych) — ładowane raz ─────────────────────
@st.cache_resource(show_spinner="Scalanie kodów pocztowych w gminy…")
def load_gminy():
    return load_gminy_data(GEOJSON_PATH)

gminy_geojson, gmina_to_postcodes, _ = load_gminy()

# ── Session state ─────────────────────────────────────────────────────────────
if "selected" not in st.session_state:
    st.session_state["selected"] = set()

selected: set[str] = st.session_state["selected"]

# ── Mapa ──────────────────────────────────────────────────────────────────────
m = build_map(GEOJSON_PATH, selected, gminy_geojson=gminy_geojson)

map_data = st_folium(m, width=None, height=580,
                     returned_objects=["last_object_clicked_tooltip"])

# Toggle kliknięcia — tooltip format: "Gmina:\n<nazwa>\nKodów pocztowych:\n<n>"
clicked = map_data.get("last_object_clicked_tooltip")
if clicked:
    lines = [l.strip() for l in clicked.strip().splitlines() if l.strip()]
    gmina = ""
    for i, line in enumerate(lines):
        if line.lower().startswith("gmina"):
            gmina = lines[i + 1] if i + 1 < len(lines) else ""
            break
    if gmina:
        if gmina in selected:
            selected.discard(gmina)
        else:
            selected.add(gmina)
        st.session_state["selected"] = selected
        st.rerun()

# ── Wyniki ────────────────────────────────────────────────────────────────────
if not selected:
    st.info("Kliknij gminę na mapie.", icon="👆")
else:
    cols_top = st.columns([6, 1])
    with cols_top[0]:
        st.markdown("**Wybrane:** " + " · ".join(f"`{g}`" for g in sorted(selected)))
    with cols_top[1]:
        if st.button("✕ Wyczyść"):
            st.session_state["selected"] = set()
            st.rerun()

    st.markdown("---")

    @st.cache_data(show_spinner=False)
    def load(codes: tuple[str, ...]) -> dict:
        return get_stats_gmina(list(codes))

    cols = st.columns(len(selected))
    for col, gmina in zip(cols, sorted(selected)):
        with col:
            postal_codes = tuple(sorted(gmina_to_postcodes.get(gmina, [])))
            with st.spinner(f"Ładuję {gmina}…"):
                d = load(postal_codes)
            st.markdown(f"### 🏘️ {gmina}")
            st.caption(f"{len(postal_codes)} kodów pocztowych")
            st.metric("Wszystkie transakcje",     f"{int(d['n_total']):,}")
            st.metric("Unikalne karty",           f"{int(d['n_kart_total']):,}")
            st.markdown("---")
            st.metric("Turyści (karty spoza PL)", f"{int(d['n_turysci']):,}")
            st.metric("Unikalne karty turystów",  f"{int(d['n_kart_turysci']):,}")
            st.metric("Lokalni",                  f"{int(d['n_lokalni']):,}")
