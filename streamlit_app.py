import math
import streamlit as st
from app.map_builder import build_map, load_gminy_data
from app.analytics import run_residents_analysis
from app.marts import get_gmina, ensure_topic
from app.matching_view import render_matching

GEOJSON_PATH = "geojson/postcodes_poland.geojson"
MAP_HEIGHT = 500


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a))


def find_neighbors(center: str, centroids: dict, radius_km: float) -> set[str]:
    """Zwraca zbiór gmin (łącznie z center) w promieniu radius_km od centroidu center."""
    if center not in centroids:
        return {center}
    lat1, lon1 = centroids[center]
    return {g for g, (lat2, lon2) in centroids.items()
            if _haversine(lat1, lon1, lat2, lon2) <= radius_km}

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
    div[data-testid="stMetric"] { background: #2a2a3e; border-radius: 8px; padding: 10px; }
    /* mniejsza przezroczystość podczas rerunu fragmentu */
    [data-stale="true"] { opacity: 0.75 !important; transition: opacity 0.15s; }
</style>
""", unsafe_allow_html=True)

st.title("Visa — Porównanie gmin")
map_view = st.radio(
    "Widok mapy",
    ["Statystyki gmin", "Wzmocnienie", "Uzupełnienie"],
    horizontal=True,
    index=0,
    key="main_map_view",
)
if map_view != "Statystyki gmin":
    render_matching(map_view)
    st.stop()

# ── Dane gmin ─────────────────────────────────────────────────────────────────
@st.cache_resource(show_spinner="Scalanie kodów pocztowych w gminy…")
def load_gminy():
    return load_gminy_data(GEOJSON_PATH)

gminy_geojson, gmina_to_postcodes, centroids = load_gminy()

# mapowanie kod → gmina (odwrócone)
code_to_gmina = {code: gmina for gmina, codes in gmina_to_postcodes.items() for code in codes}

# ── Session state ─────────────────────────────────────────────────────────────
if "selected" not in st.session_state:
    st.session_state["selected"] = set()
if "map_center" not in st.session_state:
    st.session_state["map_center"] = [52.0, 19.5]
if "map_zoom" not in st.session_state:
    st.session_state["map_zoom"] = 6
if "_last_click" not in st.session_state:
    st.session_state["_last_click"] = None
if "mode" not in st.session_state:
    st.session_state["mode"] = "standard"
if "radius_km" not in st.session_state:
    st.session_state["radius_km"] = 10
if "center_gmina" not in st.session_state:
    st.session_state["center_gmina"] = None

selected: set[str] = st.session_state["selected"]

# ── Ustawienia w popover ──────────────────────────────────────────────────────
with st.popover("⚙️ Ustawienia"):
    st.radio(
        "Tryb analizy",
        options=["standard", "wspolpraca"],
        format_func=lambda x: "🖱️ Standard — kliknij gminę aby ją zaznaczyć"
                               if x == "standard"
                               else "🤝 Współpraca graniczna — zaznacza sąsiednie gminy",
        key="mode",
    )
    if st.session_state["mode"] == "wspolpraca":
        st.slider(
            "Promień (km)", min_value=5, max_value=150,
            value=st.session_state["radius_km"], step=5,
            key="radius_km",
        )

# ── Mapa w @st.fragment ───────────────────────────────────────────────────────
@st.fragment
def map_fragment():
    sel = st.session_state["selected"]
    with st.spinner("Ładuję mapę…"):
        fig = build_map(
            GEOJSON_PATH, sel,
            gminy_geojson=gminy_geojson,
            center=tuple(st.session_state["map_center"]),
            zoom=st.session_state["map_zoom"],
            center_gmina=st.session_state.get("center_gmina"),
            centroids=centroids,
        )
    # on_select="rerun" → Streamlit rerenderuje tylko fragment przy kliknięciu
    # uirevision w fig → Plotly zachowuje viewport (pan/zoom) między rerenderami
    event = st.plotly_chart(fig, key="main_map", on_select="rerun", use_container_width=True)

    pts = (event.selection.points if event and event.selection else [])
    if pts:
        gmina = pts[0].get("location", "")
        if gmina and gmina != st.session_state["_last_click"]:
            st.session_state["_last_click"] = gmina

            if st.session_state["mode"] == "wspolpraca":
                neighbors = find_neighbors(gmina, centroids, st.session_state["radius_km"])
                sel.clear()
                sel.update(neighbors)
                st.session_state["center_gmina"] = gmina
                st.toast(f"Obszar: {gmina} + {len(neighbors)-1} sąsiednich gmin", icon="🤝")
            else:
                st.session_state["center_gmina"] = None
                if gmina in sel:
                    sel.discard(gmina)
                    st.toast(f"Odznaczono: {gmina}", icon="🔲")
                else:
                    sel.add(gmina)
                    st.toast(f"Zaznaczono: {gmina}", icon="📍")

            st.session_state["selected"] = sel
            st.rerun(scope="app")

map_fragment()

# ── Pasek wybranych + wyczyść ─────────────────────────────────────────────────
if selected:
    cols_top = st.columns([6, 1])
    with cols_top[0]:
        st.markdown("**Wybrane:** " + " · ".join(f"`{g}`" for g in sorted(selected)))
    with cols_top[1]:
        if st.button("✕ Wyczyść"):
            st.session_state["selected"] = set()
            st.session_state["_last_click"] = None
else:
    st.info("Kliknij gminę na mapie aby ją zaznaczyć. Możesz wybrać kilka do porównania.", icon="👆")
    st.stop()

# ── Wczytaj marty raz przy starcie ────────────────────────────────────────────
@st.cache_resource(show_spinner="Ładuję dane analityczne…")
def load_marts():
    return {
        topic: ensure_topic(topic)
        for topic in ["summary", "by_country", "by_month", "by_hour", "by_card", "by_channel"]
    }

marts = load_marts()

st.markdown("---")

gminy_list = sorted(selected)
cols = st.columns(len(gminy_list))

# Pierwsza gmina = referencja dla delta
ref_summary = marts["summary"].get(gminy_list[0], {}) if gminy_list else {}

def _delta(current, ref, key, pct=False, inverse=False):
    """Zwraca (delta_str, delta_color) względem referencji lub (None, 'off') dla ref."""
    if not ref or current is ref_summary:
        return None, "off"
    d = current.get(key, 0) - ref.get(key, 0)
    if d == 0:
        return None, "off"
    sign = "+" if d > 0 else ""
    s = f"{sign}{d:.1f}%" if pct else f"{sign}{d:,}"
    color = ("inverse" if inverse else "normal")
    return s, color

for col, gmina in zip(cols, gminy_list):
    postal_codes = tuple(sorted(gmina_to_postcodes.get(gmina, [])))
    is_ref = (gmina == gminy_list[0])

    with col:
        st.markdown(f"## 🏘️ {gmina}")
        if is_ref and len(gminy_list) > 1:
            st.caption(f"{len(postal_codes)} kodów pocztowych · **baza referencyjna**")
        else:
            st.caption(f"{len(postal_codes)} kodów pocztowych")

        summary    = marts["summary"].get(gmina, {})
        countries  = marts["by_country"].get(gmina, [])
        months     = marts["by_month"].get(gmina, [])
        hours      = marts["by_hour"].get(gmina, [])
        cards      = marts["by_card"].get(gmina, [])
        channels   = marts["by_channel"].get(gmina, [])

        if not summary:
            st.warning("Brak danych dla tej gminy.")
            continue

        # ── A. Turyści ────────────────────────────────────────────────────────
        st.markdown("### 🌍 Turyści")
        m1, m2, m3 = st.columns(3)

        d_total, dc_total   = _delta(summary, ref_summary, "n_total")
        d_foreign, dc_for   = _delta(summary, ref_summary, "n_foreign")
        d_pct, dc_pct       = _delta(summary, ref_summary, "pct_foreign", pct=True)

        m1.metric("Transakcje łącznie", f"{summary['n_total']:,}",
                  delta=d_total, delta_color=dc_total)
        m2.metric("Turyści zagraniczni", f"{summary['n_foreign']:,}",
                  delta=d_foreign, delta_color=dc_for)
        m3.metric("% zagranicznych", f"{summary['pct_foreign']}%",
                  delta=d_pct, delta_color=dc_pct,
                  help="Udział transakcji kartami zagranicznymi (issr_jurn ≠ Domestic) wśród wszystkich transakcji w gminie")

        if countries:
            import pandas as pd
            st.markdown("**Top kraje gości:**")
            df = pd.DataFrame(countries)[["country", "n", "pct"]]
            df.columns = ["Kraj", "Transakcje", "%"]
            st.dataframe(df, hide_index=True, width='stretch')

        if months:
            import pandas as pd
            st.markdown("**Goście per miesiąc:**")
            df = pd.DataFrame(months).set_index("month")[["n_foreign"]]
            df.columns = ["Turyści"]
            st.bar_chart(df, width='stretch')

        if cards:
            import pandas as pd
            st.markdown("**Typ karty gości:**")
            df = pd.DataFrame(cards)[["type", "n", "pct"]]
            df.columns = ["Karta", "Transakcje", "%"]
            st.dataframe(df, hide_index=True, width='stretch')

        # ── C. Czas ───────────────────────────────────────────────────────────
        st.markdown("### 🕐 Rytm dnia")

        if months:
            import pandas as pd
            st.markdown("**Trend miesięczny:**")
            df = pd.DataFrame(months).set_index("month")[["n", "pct_foreign"]]
            df.columns = ["Transakcje", "% zagranicznych"]
            st.line_chart(df, width='stretch')

        if hours:
            import pandas as pd
            st.markdown("**% turystów per godzina:**")
            df = pd.DataFrame(hours).set_index("hour")[["pct_foreign"]]
            df.columns = ["% zagranicznych"]
            st.area_chart(df, width='stretch')

        # ── D. Wartość i płatności ────────────────────────────────────────────
        st.markdown("### 💳 Płatności")

        if channels:
            import pandas as pd
            st.markdown("**Kanały płatności:**")
            df = pd.DataFrame(channels)[["channel", "n", "pct"]].head(6)
            df.columns = ["Kanał", "Transakcje", "%"]
            st.dataframe(df, hide_index=True, width='stretch')

        # ── B + E — mieszkańcy (wolne, na żądanie) ────────────────────────────
        st.markdown("### 🏠 Mieszkańcy i powiązania")

        btn_key = f"btn_residents_{gmina}"
        res_key = f"residents_{gmina}"

        if res_key not in st.session_state:
            if st.button("Analizuj mieszkańców", key=btn_key):
                with st.spinner("Liczę card_home i przepływy… (może zająć chwilę)"):
                    st.session_state[res_key] = run_residents_analysis(
                        list(postal_codes), code_to_gmina
                    )
                st.rerun()

        if res_key in st.session_state:
            r = st.session_state[res_key]

            st.caption(f"Karty z przypisanym domem w gminie: {r.get('n_resident_cards', 0):,}")

            # E — wskaźniki syntetyczne
            st.markdown("#### 📊 Wskaźniki syntetyczne")
            e1, e2, e3 = st.columns(3)
            e1.metric("Samowystarczalność",
                      f"{r.get('E1_self_sufficiency', 0):.1f}%",
                      help="% zakupów codziennych robionych lokalnie")
            e2.metric("Atrakcyjność",
                      f"{r.get('E2_attractiveness', 0):.1f}%",
                      help="napływ / (napływ + odpływ)")
            e3.metric("Zależność od gości",
                      f"{r.get('E3_tourism_dependency', 0):.1f}%",
                      help="% transakcji w obszarze od osób spoza gminy")

            # E5 — siła powiązania
            if "E5_connections" in r:
                st.markdown("#### 🔗 Powiązania z innymi gminami")
                conn = r["E5_connections"][["gmina", "kierunek", "n_out", "n_in", "flow_total"]]
                conn.columns = ["Gmina", "↔", "Odpływ →", "Napływ ←", "Łącznie"]
                st.dataframe(conn, hide_index=True, width='stretch')

            # B2 — odpływ
            if "B2_outflow" in r and len(r["B2_outflow"]):
                st.markdown("#### 🚗 Dokąd wyjeżdżają mieszkańcy")
                df = r["B2_outflow"][["area_gmina", "n"]].rename(
                    columns={"area_gmina": "Gmina", "n": "Transakcje"})
                st.bar_chart(df.set_index("Gmina"), width='stretch')

            # B3 — napływ
            if "B3_inflow" in r and len(r["B3_inflow"]):
                st.markdown("#### 🏙️ Skąd przyjeżdżają do gminy")
                df = r["B3_inflow"][["home_gmina", "n"]].rename(
                    columns={"home_gmina": "Gmina", "n": "Transakcje"})
                st.bar_chart(df.set_index("Gmina"), width='stretch')

            # B4 — odpływ wg kategorii
            if "B4_outflow_cat" in r and len(r["B4_outflow_cat"]):
                st.markdown("#### 🛒 Czego szukają poza gminą (top kategorie)")
                df = r["B4_outflow_cat"].rename(
                    columns={"mrch_catg_nm": "Kategoria", "n": "Transakcje"})
                st.dataframe(df, hide_index=True, width='stretch')
