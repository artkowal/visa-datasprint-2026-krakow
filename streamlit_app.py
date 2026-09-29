from pathlib import Path

import plotly.io as pio
import streamlit as st
from app.map_builder import build_map, load_gminy_data
from app.analytics import run_residents_analysis
from app.marts import get_gmina, ensure_topic
from app import queries as q

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
    /* zmniejszone paddingi boczne */
    .block-container { padding-left: 1.5rem !important; padding-right: 1.5rem !important; max-width: 100% !important; }
</style>
""", unsafe_allow_html=True)

logo_col, note_col = st.columns([3, 2], gap="large", vertical_alignment="center")
with logo_col:
    st.image(str(Path(__file__).resolve().parent / "assets" / "megapolis-visa.svg"), width="stretch")
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

@st.cache_resource(show_spinner=False)
def load_cat_profiles() -> dict:
    try:
        from app.matching_real import load_display_profiles
        return load_display_profiles()
    except Exception:
        return {}

cat_profiles = load_cat_profiles()

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
if "_ref_gmina" not in st.session_state:
    st.session_state["_ref_gmina"] = None
selected: set[str] = st.session_state["selected"]

# ── Pasek sterowania ──────────────────────────────────────────────────────────
map_view = st.radio(
    "Widok mapy",
    ["Statystyki gmin", "Dominujące kategorie"],
    horizontal=True,
    index=0,
    key="main_map_view",
)

# ── Cache figur mapy ──────────────────────────────────────────────────────────
_FIGURE_CACHE: dict = {}
_FIGURE_CACHE_MAX = 40

def _get_figure(sel: set, view_mode: str, center=(52.0, 19.5), zoom=6):
    key = (frozenset(sel), view_mode, center, zoom)
    if key not in _FIGURE_CACHE:
        if len(_FIGURE_CACHE) >= _FIGURE_CACHE_MAX:
            _FIGURE_CACHE.pop(next(iter(_FIGURE_CACHE)))
        # uirevision encodes the center — gdy search zmienia center, Plotly używa nowych
        # wartości z figury zamiast zachowywać stary viewport klienta
        uirev = f"{center[0]:.4f}_{center[1]:.4f}_{zoom}"
        _FIGURE_CACHE[key] = build_map(
            GEOJSON_PATH, sel,
            gminy_geojson=gminy_geojson,
            center=center,
            zoom=zoom,
            centroids=centroids,
            dominant=dominant_data if view_mode == "Dominujące kategorie" else None,
            uirevision=uirev,
        )
    return _FIGURE_CACHE[key]

# ── Mapa w @st.fragment ───────────────────────────────────────────────────────
@st.fragment
def map_fragment():
    sel = st.session_state["selected"]

    # Wyszukiwarka — fly-to animuje mapę, nie dodaje gminy do zaznaczonych
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

    if search:
        lat, lon = centroids[search]
        st.session_state["map_center"] = [lat, lon]
        st.session_state["map_zoom"] = 9
        del st.session_state["gmina_search"]
        st.rerun(scope="app")

    center = tuple(st.session_state["map_center"])
    zoom = st.session_state["map_zoom"]
    fig = _get_figure(sel, map_view, center=center, zoom=zoom)
    event = st.plotly_chart(fig, key="main_map", on_select="rerun", width="stretch")

    pts = (event.selection.points if event and event.selection else [])
    if pts:
        gmina = pts[0].get("location", "")
        if gmina and gmina != st.session_state["_last_click"]:
            st.session_state["_last_click"] = gmina
            if gmina in sel:
                sel.discard(gmina)
                st.toast(f"Odznaczono: {gmina}", icon="🔲")
                # jeśli odznaczono miasto referencyjne, ustaw nowe ref jako pierwsze z pozostałych
                if st.session_state["_ref_gmina"] == gmina:
                    st.session_state["_ref_gmina"] = next(iter(sel), None)
            else:
                if not sel:
                    st.session_state["_ref_gmina"] = gmina
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
            st.session_state["_ref_gmina"] = None
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

_ref = st.session_state.get("_ref_gmina")
if _ref and _ref in selected:
    gminy_list = [_ref] + sorted(selected - {_ref})
else:
    gminy_list = sorted(selected)


def _comparison_chart(
    gminy: list[str], profiles: dict, dominant: dict, diff_mode: bool = False
) -> "go.Figure":
    import plotly.graph_objects as go
    from app.categories import GROUP_ICONS, GROUP_ORDER

    CATS = [g for g in GROUP_ORDER if g not in {"Handel internetowy", "Inne"}]
    ref_prof = profiles.get(gminy[0], {})
    GMINA_COLORS = ["#6366f1", "#2dd4bf", "#fb923c", "#60a5fa"]

    # Sortowanie wg wariancji między gminami — kategorie gdzie są różnice idą na lewo
    if len(gminy) > 1:
        def _var(c):
            vals = [profiles.get(g, {}).get(c, 0) for g in gminy]
            m = sum(vals) / len(vals)
            return sum((v - m) ** 2 for v in vals)
        sorted_cats = sorted(CATS, key=_var, reverse=True)
    else:
        sorted_cats = sorted(CATS, key=lambda c: ref_prof.get(c, 0), reverse=True)

    x_labels = [f"{GROUP_ICONS.get(c, '')} {c}" for c in sorted_cats]

    fig = go.Figure()

    for idx, gmina in enumerate(gminy):
        prof = profiles.get(gmina, {})
        dom_group = dominant.get(gmina, {}).get("grupa")
        is_ref = (idx == 0)

        color = GMINA_COLORS[idx % len(GMINA_COLORS)]

        if diff_mode:
            vals = [(prof.get(c, 0) - ref_prof.get(c, 0)) * 100 for c in sorted_cats]
            if is_ref:
                continue  # ref = linia zerowa, nie rysujemy
            text_vals = [f"+{v:.1f}pp" if v >= 0.5 else (f"{v:.1f}pp" if v <= -0.5 else "") for v in vals]
        else:
            vals = [prof.get(c, 0) * 100 for c in sorted_cats]
            text_vals = [f"{v:.0f}%" if v >= 1 else "" for v in vals]

        bar_colors = color

        hover_name = gmina + (" (ref)" if is_ref else "")
        hover_tmpl = (
            f"<b>{gmina}</b><br>%{{x}}: %{{y:+.1f}} pp od ref<extra></extra>"
            if diff_mode else
            f"<b>{gmina}</b><br>%{{x}}: %{{y:.1f}}%<extra></extra>"
        )

        fig.add_trace(go.Bar(
            name=hover_name,
            x=x_labels,
            y=vals,
            marker_color=bar_colors,
            text=text_vals,
            textposition="outside",
            cliponaxis=False,
            hovertemplate=hover_tmpl,
        ))

    y_title = "odchylenie od ref (pp)" if diff_mode else "udział transakcji (%)"
    fig.update_layout(
        barmode="group",
        height=420,
        margin={"l": 0, "r": 10, "t": 30, "b": 10},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"color": "#cdd6f4", "size": 11},
        xaxis=dict(tickangle=-38, showgrid=False, zeroline=False, tickfont={"size": 10}),
        yaxis=dict(
            showgrid=True,
            gridcolor="#2a2a3e",
            zeroline=diff_mode,
            zerolinecolor="#6366f1",
            zerolinewidth=1.5,
            ticksuffix="pp" if diff_mode else "%",
            title=dict(text=y_title, font={"size": 11}),
        ),
        legend=dict(orientation="h", yanchor="bottom", y=1.01, xanchor="left", x=0),
        bargap=0.18,
        bargroupgap=0.04,
        hoverlabel=dict(bgcolor="#2a2a3e", font_color="#cdd6f4"),
    )
    return fig


# Pierwsza gmina = referencja dla delta
ref_summary = marts["summary"].get(gminy_list[0], {}) if gminy_list else {}

# ── Pętla 1: nagłówki — nazwa + dominująca kategoria ─────────────────────────
hdr_cols = st.columns(len(gminy_list))
for col, gmina in zip(hdr_cols, gminy_list):
    is_ref = (gmina == gminy_list[0])
    with col:
        dom = dominant_data.get(gmina)
        if is_ref and len(gminy_list) > 1:
            st.markdown(
                f"## 🏘️ {gmina} "
                f'<span style="font-size:0.55em;background:#6366f1;color:#fff;'
                f'padding:2px 8px;border-radius:999px;vertical-align:middle">REF</span>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(f"## 🏘️ {gmina}")
        if dom:
            from app.categories import GROUP_ICONS
            icon = GROUP_ICONS.get(dom["grupa"], "🏷️")
            st.markdown(f"{icon} **{dom['grupa']}** · {dom['pct']}% transakcji · śr. {dom['avg_amt']} zł")

# ── Wykres profilu kategorii (full-width, już po nagłówkach) ──────────────────
st.markdown("### 📊 Profil kategorii")
if any(g in cat_profiles for g in gminy_list):
    _chart_cols2 = st.columns([3, 2])
    with _chart_cols2[0]:
        _diff_mode2 = st.toggle(
            "Różnice od ref (odchylenie pp)",
            value=False,
            key="cat_diff_toggle",
            disabled=len(gminy_list) == 1,
            help="Zamiast wartości bezwzględnych pokazuje o ile pp dana gmina różni się od pierwszej wybranej.",
        )
    with _chart_cols2[1]:
        if _diff_mode2:
            st.caption("Oś X sortowana wg rozrzutu — największe różnice z lewej.")
    st.plotly_chart(
        _comparison_chart(gminy_list, cat_profiles, dominant_data, diff_mode=_diff_mode2),
        key="cat_comparison2",
        width="stretch",
    )
else:
    st.info("Brak danych profilu kategorii. Wygeneruj `by_category.json`.")

st.markdown("---")

# ── Pętla 2: szczegółowe statystyki (każda sekcja = własny st.columns) ────────
import pandas as pd


def _delta(current, ref, key, pct=False, inverse=False):
    if not ref or current is ref_summary:
        return "—", "off"
    d = current.get(key, 0) - ref.get(key, 0)
    if d == 0:
        return "—", "off"
    sign = "+" if d > 0 else ""
    s = f"{sign}{d:.1f}%" if pct else f"{sign}{d:,}"
    color = ("inverse" if inverse else "normal")
    return s, color


# Zbierz dane wszystkich gmin z góry
_city = {
    g: {
        "summary":   marts["summary"].get(g, {}),
        "countries": marts["by_country"].get(g, []),
        "months":    marts["by_month"].get(g, []),
        "hours":     marts["by_hour"].get(g, []),
        "cards":     marts["by_card"].get(g, []),
        "channels":  marts["by_channel"].get(g, []),
        "residents": marts["residents"].get(g, {}),
    }
    for g in gminy_list
}

# ── Sekcja A: Turyści ─────────────────────────────────────────────────────────
st.markdown("### 🌍 Turyści")
for col, gmina in zip(st.columns(len(gminy_list)), gminy_list):
    summary = _city[gmina]["summary"]
    with col:
        if not summary:
            st.warning("Brak danych dla tej gminy.")
            continue
        m1, m2, m3 = st.columns(3)
        d_total,   dc_total = _delta(summary, ref_summary, "n_total")
        d_foreign, dc_for   = _delta(summary, ref_summary, "n_foreign")
        d_pct,     dc_pct   = _delta(summary, ref_summary, "pct_foreign", pct=True)
        m1.metric("Transakcje łącznie",  f"{summary['n_total']:,}",    delta=d_total,   delta_color=dc_total)
        m2.metric("Turyści zagraniczni", f"{summary['n_foreign']:,}",  delta=d_foreign, delta_color=dc_for)
        m3.metric("% zagranicznych",     f"{summary['pct_foreign']}%", delta=d_pct,     delta_color=dc_pct,
                  help="Udział transakcji kartami zagranicznymi wśród wszystkich transakcji w gminie")

        if _city[gmina]["countries"]:
            st.markdown("**Top kraje gości:**")
            df = pd.DataFrame(_city[gmina]["countries"])[["country", "n", "pct"]]
            df.columns = ["Kraj", "Transakcje", "%"]
            st.dataframe(df, hide_index=True, width='stretch')

        if _city[gmina]["months"]:
            st.markdown("**Goście per miesiąc:**")
            df = pd.DataFrame(_city[gmina]["months"]).set_index("month")[["n_foreign"]]
            df.columns = ["Turyści"]
            st.bar_chart(df, width='stretch')

        if _city[gmina]["cards"]:
            st.markdown("**Typ karty gości:**")
            df = pd.DataFrame(_city[gmina]["cards"])[["type", "n", "pct"]]
            df.columns = ["Karta", "Transakcje", "%"]
            st.dataframe(df, hide_index=True, width='stretch')

# ── Sekcja B: Rytm dnia ───────────────────────────────────────────────────────
st.markdown("---")
st.markdown("### 🕐 Rytm dnia")
for col, gmina in zip(st.columns(len(gminy_list)), gminy_list):
    with col:
        if _city[gmina]["months"]:
            st.markdown("**Trend miesięczny:**")
            df = pd.DataFrame(_city[gmina]["months"]).set_index("month")[["n", "pct_foreign"]]
            df.columns = ["Transakcje", "% zagranicznych"]
            st.line_chart(df, width='stretch')

        if _city[gmina]["hours"]:
            st.markdown("**% turystów per godzina:**")
            df = pd.DataFrame(_city[gmina]["hours"]).set_index("hour")[["pct_foreign"]]
            df.columns = ["% zagranicznych"]
            st.area_chart(df, width='stretch')

# ── Sekcja C: Płatności ───────────────────────────────────────────────────────
st.markdown("---")
st.markdown("### 💳 Płatności")
for col, gmina in zip(st.columns(len(gminy_list)), gminy_list):
    with col:
        if _city[gmina]["channels"]:
            st.markdown("**Kanały płatności:**")
            df = pd.DataFrame(_city[gmina]["channels"])[["channel", "n", "pct"]].head(6)
            df.columns = ["Kanał", "Transakcje", "%"]
            st.dataframe(df, hide_index=True, width='stretch')
        else:
            st.caption("Brak danych o kanałach płatności.")

# ── Sekcja D: Mieszkańcy i powiązania ────────────────────────────────────────
st.markdown("---")
st.markdown("### 🏠 Mieszkańcy i powiązania")
for col, gmina in zip(st.columns(len(gminy_list)), gminy_list):
    r = _city[gmina]["residents"]
    with col:
        if not r:
            st.caption("Brak danych o mieszkańcach dla tej gminy.")
            continue

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
