from pathlib import Path

import plotly.io as pio
import streamlit as st
from app.map_builder import build_map, load_gminy_data
from app.analytics import run_residents_analysis
from app.marts import get_gmina, ensure_topic
from app import queries as q

# Faster Plotly JSON serialization (requires orjson)
try:
    pio.json.config.default_engine = "orjson"
except Exception:
    pass

GEOJSON_PATH = "geojson/postcodes_poland.geojson"
MAP_HEIGHT = 500

st.set_page_config(
    page_title="Megapolis VISA",
    page_icon="🗺️",
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

logo_col, note_col = st.columns([3, 2], gap="large", vertical_alignment="center")
with logo_col:
    st.image(str(Path(__file__).resolve().parent / "assets" / "megapolis-visa.svg"), use_container_width=True)
with note_col:
    st.markdown(
        '<div style="padding:16px 20px;border-left:3px solid #f7bb42;'
        'border-radius:8px;background:#282c44;color:#cdd6f4;line-height:1.45">'
        'Zobacz, gdzie gminy współpracują i jakie funkcje mogą rozwijać razem.'
        '</div>',
        unsafe_allow_html=True,
    )

# ── Dane gmin ─────────────────────────────────────────────────────────────────
@st.cache_resource(show_spinner="Scalanie kodów pocztowych w gminy…")
def load_gminy():
    return load_gminy_data(GEOJSON_PATH)

gminy_geojson, gmina_to_postcodes, centroids = load_gminy()

@st.cache_resource(show_spinner=False)
def load_dominant() -> dict:
    try:
        return q.get_dominant_categories()
    except Exception:
        return {}

dominant_data = load_dominant()

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
selected: set[str] = st.session_state["selected"]

# ── Pasek sterowania ──────────────────────────────────────────────────────────
map_view = st.radio(
    "Widok mapy",
    ["Statystyki gmin", "Dominujące kategorie"],
    horizontal=True,
    index=0,
    key="main_map_view",
)

_render_dominant_map = (map_view == "Dominujące kategorie")

# ── Pamięć podręczna figur ────────────────────────────────────────────────────
# Klucz: (frozenset(selected), view_mode) → go.Figure
# Unikamy przebudowy identycznej figury przy każdym renderze fragmentu.
_FIGURE_CACHE: dict = {}
_FIGURE_CACHE_MAX = 40

def _get_figure(sel: set, view_mode: str) -> "go.Figure":
    key = (frozenset(sel), view_mode)
    if key not in _FIGURE_CACHE:
        if len(_FIGURE_CACHE) >= _FIGURE_CACHE_MAX:
            _FIGURE_CACHE.pop(next(iter(_FIGURE_CACHE)))
        _FIGURE_CACHE[key] = build_map(
            GEOJSON_PATH, sel,
            gminy_geojson=gminy_geojson,
            center=(52.0, 19.5),
            zoom=6,
            centroids=centroids,
            dominant=dominant_data if view_mode == "Dominujące kategorie" else None,
        )
    return _FIGURE_CACHE[key]

# ── Mapa w @st.fragment ───────────────────────────────────────────────────────
@st.fragment
def map_fragment():
    sel = st.session_state["selected"]

    # ── Search nad mapą ───────────────────────────────────────────────────
    _sc, _ = st.columns([3, 7])
    with _sc:
        search = st.selectbox(
            "Szukaj gminy",
            [None] + sorted(centroids.keys()),
            key="gmina_search",
            label_visibility="collapsed",
            placeholder="🔍 Szukaj gminy…",
            index=0,
        )

    fig = _get_figure(sel, map_view)
    event = st.plotly_chart(fig, key="main_map", on_select="rerun", width="stretch")

    # Animuj centrum JS — bez przebudowy mapy
    fly_to = st.session_state.pop("_fly_to", None)
    if fly_to:
        lat, lon, zoom = fly_to
        st.components.v1.html(f"""
        <script>
        (function() {{
            var tries = 0;
            function fly() {{
                var plots = window.parent.document.querySelectorAll('.js-plotly-plot');
                if (plots.length && window.parent.Plotly) {{
                    window.parent.Plotly.relayout(plots[0], {{
                        'map.center': {{lat: {lat}, lon: {lon}}},
                        'map.zoom': {zoom}
                    }});
                }} else if (tries++ < 20) {{
                    setTimeout(fly, 100);
                }}
            }}
            fly();
        }})();
        </script>
        """, height=0)

    if search:
        lat, lon = centroids[search]
        st.session_state["_fly_to"] = (lat, lon, 9)
        del st.session_state["gmina_search"]
        st.rerun(scope="fragment")

    # ── Kliknięcie w mapę ─────────────────────────────────────────────────
    pts = (event.selection.points if event and event.selection else [])
    if pts:
        gmina = pts[0].get("location", "")
        if gmina and gmina != st.session_state["_last_click"]:
            st.session_state["_last_click"] = gmina
            if gmina in sel:
                sel.discard(gmina)
                st.toast(f"Odznaczono: {gmina}", icon="🔲")
            else:
                sel.add(gmina)
                st.toast(f"Zaznaczono: {gmina}", icon="📍")
            st.session_state["selected"] = sel
            st.rerun(scope="app")

map_fragment()

# Jeśli search zrobił scope="fragment", selected mogło się zmienić — odśwież stronę
selected = st.session_state["selected"]

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
        for topic in ["summary", "by_country", "by_month", "by_hour", "by_card", "by_channel", "residents", "t_dominant"]
    }

marts = load_marts()

st.markdown("---")

gminy_list = sorted(selected)
cols = st.columns(len(gminy_list))

# Pierwsza gmina = referencja dla delta
ref_summary = marts["summary"].get(gminy_list[0], {}) if gminy_list else {}

def _fmt_month(m) -> str:
    s = str(int(m))
    return f"{s[:4]}-{s[4:]}"

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

        # ── Dominująca kategoria ─────────────────────────────────────────────
        dom = dominant_data.get(gmina)
        if dom:
            from app.categories import GROUP_ICONS
            icon = GROUP_ICONS.get(dom["grupa"], "🏷️")
            st.markdown(
                f"**Dominująca kategoria:** {icon} **{dom['grupa']}** "
                f"— {dom['pct']}% transakcji · śr. {dom['avg_amt']} zł"
            )

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
            df.index = df.index.map(_fmt_month)
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
            df.index = df.index.map(_fmt_month)
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

        # ── B + E — mieszkańcy (z martu JSON) ────────────────────────────────
        st.markdown("### 🏠 Mieszkańcy i powiązania")
        import pandas as pd
        r = marts["residents"].get(gmina, {})

        if not r:
            st.caption("Brak danych o mieszkańcach dla tej gminy.")
        else:
            st.caption(f"Karty z przypisanym domem w gminie: {r.get('n_resident_cards', 0):,}")

            st.markdown("#### 📊 Wskaźniki syntetyczne")
            e1, e2, e3 = st.columns(3)
            e1.metric("Samowystarczalność", f"{r.get('E1_self_sufficiency', 0):.1f}%",
                      help="% zakupów codziennych robionych lokalnie")
            e2.metric("Atrakcyjność", f"{r.get('E2_attractiveness', 0):.1f}%",
                      help="napływ / (napływ + odpływ)")
            e3.metric("Zależność od gości", f"{r.get('E3_tourism_dependency', 0):.1f}%",
                      help="% transakcji w obszarze od osób spoza gminy")

            if r.get("E5_connections"):
                st.markdown("#### 🔗 Powiązania z innymi gminami")
                st.dataframe(
                    pd.DataFrame(r["E5_connections"])
                      .rename(columns={"gmina":"Gmina","kierunek":"↔","n_out":"Odpływ →","n_in":"Napływ ←","flow_total":"Łącznie"}),
                    hide_index=True, width='stretch')

            if r.get("B2_outflow"):
                st.markdown("#### 🚗 Dokąd wyjeżdżają mieszkańcy")
                df = pd.DataFrame(r["B2_outflow"]).rename(columns={"area_gmina":"Gmina","n":"Transakcje"})
                st.bar_chart(df.set_index("Gmina"), width='stretch')

            if r.get("B3_inflow"):
                st.markdown("#### 🏙️ Skąd przyjeżdżają do gminy")
                df = pd.DataFrame(r["B3_inflow"]).rename(columns={"home_gmina":"Gmina","n":"Transakcje"})
                st.bar_chart(df.set_index("Gmina"), width='stretch')

            if r.get("B4_outflow_cat"):
                st.markdown("#### 🛒 Czego szukają poza gminą")
                df = pd.DataFrame(r["B4_outflow_cat"])
                total = df["n"].sum()
                df["%"] = (df["n"] / total * 100).round(1).astype(str) + "%"
                df = df.rename(columns={"mrch_catg_nm": "Kategoria", "n": "Transakcje"})
                st.dataframe(df[["Kategoria", "Transakcje", "%"]], hide_index=True, width='stretch')
