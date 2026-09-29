import math
import altair as alt
import pandas as pd
import streamlit as st
from app.map_builder import build_map, load_gminy_data
from app.analytics import run_residents_analysis
from app.marts import get_gmina, ensure_topic
from app.panels import render_gmina
from app.queries import get_gmina_group_table, get_marts_meta, marts_ready
from app.trade import build_reference

GEOJSON_PATH = "geojson/postcodes_poland.geojson"

CHANNEL_META: dict[str, tuple[str, str, str]] = {
    # channel_flg -> (ikona, etykieta, kolor-badge)
    "mobile":             ("📱", "Mobilnie",         "violet"),
    "cp_contactless":     ("📶", "Zbliżeniowo",       "blue"),
    "eci":                ("🛒", "Internet",           "orange"),
    "cp_non_contactless": ("💳", "Karta włożona",      "green"),
    "recur":              ("🔁", "Cykliczne",          "gray"),
    "moto":               ("☎️", "Tel./poczta",        "gray"),
    "cash":               ("💵", "Gotówka",            "gray"),
    "other":              ("❔", "Inne",               "gray"),
}

CARD_ICONS = {
    "CLASSIC": "💳", "BUSINESS": "🏢", "PLATINUM": "💎",
    "INFINITE": "♾️", "PREMIER": "⭐", "VISA SIGNATURE CARD": "✍️", "VPAY": "🔵",
}

_CLR_FOREIGN  = "#f97316"
_CLR_DOMESTIC = "#6366f1"


def _haversine(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat, dlon = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    return R * 2 * math.asin(math.sqrt(a))


def find_neighbors(center, centroids, radius_km):
    if center not in centroids:
        return {center}
    lat1, lon1 = centroids[center]
    return {g for g, (lat2, lon2) in centroids.items() if _haversine(lat1, lon1, lat2, lon2) <= radius_km}


st.set_page_config(page_title="Visa City Analytics", page_icon="", layout="wide",
                   initial_sidebar_state="collapsed")

st.markdown("""
<style>
    .stApp { background: #1e1e2e; color: #cdd6f4; }
    h1, h2, h3 { color: #a78bfa !important; }
    div[data-testid="stMetric"] { background: #2a2a3e; border-radius: 8px; padding: 10px; }
    [data-stale="true"] { opacity: 0.75 !important; transition: opacity 0.15s; }
</style>
""", unsafe_allow_html=True)

st.title("Visa — Porównanie gmin")

@st.cache_resource(show_spinner="Scalanie kodów pocztowych w gminy…")
def load_gminy():
    return load_gminy_data(GEOJSON_PATH)

gminy_geojson, gmina_to_postcodes, centroids = load_gminy()
code_to_gmina = {c: g for g, cs in gmina_to_postcodes.items() for c in cs}

for _k, _v in [("selected", set()), ("map_center", [52.0, 19.5]), ("map_zoom", 6),
               ("_last_click", None), ("mode", "standard"), ("radius_km", 10),
               ("center_gmina", None)]:
    if _k not in st.session_state:
        st.session_state[_k] = _v

selected: set[str] = st.session_state["selected"]

with st.popover("⚙️ Ustawienia"):
    st.radio("Tryb analizy", ["standard", "wspolpraca"],
             format_func=lambda x: ("🖱️ Standard — kliknij gminę" if x == "standard"
                                    else "🤝 Współpraca graniczna — zaznacza sąsiednie"),
             key="mode")
    if st.session_state["mode"] == "wspolpraca":
        st.slider("Promień (km)", 5, 150, st.session_state["radius_km"], 5, key="radius_km")

@st.fragment
def map_fragment():
    sel = st.session_state["selected"]
    with st.spinner("Ładuję mapę…"):
        fig = build_map(GEOJSON_PATH, sel, gminy_geojson=gminy_geojson,
                        center=tuple(st.session_state["map_center"]),
                        zoom=st.session_state["map_zoom"],
                        center_gmina=st.session_state.get("center_gmina"),
                        centroids=centroids)
    event = st.plotly_chart(fig, key="main_map", on_select="rerun", use_container_width=True)
    pts = event.selection.points if event and event.selection else []
    if pts:
        gmina = pts[0].get("location", "")
        if gmina and gmina != st.session_state["_last_click"]:
            st.session_state["_last_click"] = gmina
            if st.session_state["mode"] == "wspolpraca":
                nb = find_neighbors(gmina, centroids, st.session_state["radius_km"])
                sel.clear(); sel.update(nb)
                st.session_state["center_gmina"] = gmina
                st.toast(f"Obszar: {gmina} + {len(nb)-1} gmin", icon="🤝")
            else:
                st.session_state["center_gmina"] = None
                if gmina in sel:
                    sel.discard(gmina); st.toast(f"Odznaczono: {gmina}", icon="🔲")
                else:
                    sel.add(gmina); st.toast(f"Zaznaczono: {gmina}", icon="📍")
            st.session_state["selected"] = sel
            st.rerun(scope="app")

map_fragment()

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

@st.cache_resource(show_spinner="Ładuję dane analityczne…")
def load_marts():
    return {t: ensure_topic(t) for t in ["summary", "by_country", "by_month", "by_hour", "by_card", "by_channel"]}

marts = load_marts()

st.markdown("---")
gminy_list  = sorted(selected)
cols        = st.columns(len(gminy_list))
ref_summary = marts["summary"].get(gminy_list[0], {}) if gminy_list else {}


def _delta(cur, ref, key, pct=False, inverse=False):
    if not ref or cur is ref_summary:
        return None, "off"
    d = cur.get(key, 0) - ref.get(key, 0)
    if d == 0:
        return None, "off"
    s = f"{'+' if d>0 else ''}{d:.1f}%" if pct else f"{'+' if d>0 else ''}{d:,}"
    return s, ("inverse" if inverse else "normal")


def _split_bar(pct_foreign: float, n_foreign: int, n_domestic: int) -> None:
    """Pasek postępu HTML + etykiety dla podziału turysta/lokalny."""
    pct_dom = round(100 - pct_foreign, 1)
    st.markdown(
        f'<div style="display:flex;height:10px;border-radius:5px;overflow:hidden;margin:6px 0 2px">'
        f'<div style="width:{pct_foreign}%;background:{_CLR_FOREIGN}"></div>'
        f'<div style="width:{pct_dom}%;background:{_CLR_DOMESTIC}"></div>'
        f'</div>'
        f'<div style="display:flex;justify-content:space-between;font-size:12px;margin-bottom:4px">'
        f'<span style="color:{_CLR_FOREIGN}">✈️ {pct_foreign}% &nbsp;({n_foreign:,})</span>'
        f'<span style="color:{_CLR_DOMESTIC}">🏠 {pct_dom}% &nbsp;({n_domestic:,})</span>'
        f'</div>',
        unsafe_allow_html=True,
    )


def _monthly_charts(months: list[dict]) -> tuple[alt.Chart, alt.Chart]:
    """
    Dwa mini-wykresy trendu:
      1. % turystów per miesiąc (linia) — porównywalny między gminami
      2. Wolumen transakcji per miesiąc (słupki) — kontekst sezonowości
    """
    df = pd.DataFrame(months)
    df["m"] = df["month"].astype(str).str[:4] + "-" + df["month"].astype(str).str[4:]
    avg_pct = df["pct_foreign"].mean()

    x_axis = alt.Axis(labelAngle=-50, labelFontSize=8, tickCount=6, labelOverlap=True)

    # ── 1. % turystów — linia z punktami i linią średniej ─────────────────
    base = alt.Chart(df)
    avg_rule = (
        alt.Chart(pd.DataFrame({"avg": [avg_pct]}))
        .mark_rule(strokeDash=[4, 3], color="#94a3b8", strokeWidth=1)
        .encode(y="avg:Q")
    )
    line = (
        base.mark_line(color=_CLR_FOREIGN, strokeWidth=2)
        .encode(
            x=alt.X("m:O", title=None, axis=x_axis),
            y=alt.Y("pct_foreign:Q", title=None,
                    axis=alt.Axis(format=".1f", labelFontSize=8, title="%"),
                    scale=alt.Scale(zero=False)),
            tooltip=["m", alt.Tooltip("pct_foreign:Q", format=".1f", title="% zagranicznych"),
                     alt.Tooltip("n:Q", format=",", title="Transakcje")],
        )
    )
    dots = base.mark_point(color=_CLR_FOREIGN, size=30, filled=True).encode(
        x="m:O", y="pct_foreign:Q"
    )
    pct_chart = (avg_rule + line + dots).properties(height=90)

    # ── 2. Wolumen — cienkie słupki z kolorem intensywności turystów ──────
    vol_chart = (
        base.mark_bar(cornerRadiusTopLeft=2, cornerRadiusTopRight=2)
        .encode(
            x=alt.X("m:O", title=None, axis=x_axis),
            y=alt.Y("n:Q", title=None,
                    axis=alt.Axis(format="~s", labelFontSize=8)),
            color=alt.Color("pct_foreign:Q",
                scale=alt.Scale(scheme="oranges", domain=[0, df["pct_foreign"].max()]),
                legend=None),
            tooltip=["m", alt.Tooltip("n:Q", format=",", title="Transakcje"),
                     alt.Tooltip("pct_foreign:Q", format=".1f", title="% zagranicznych")],
        )
        .properties(height=60)
    )

    return pct_chart, vol_chart


# ── Per-gmina ─────────────────────────────────────────────────────────────────
for col, gmina in zip(cols, gminy_list):
    postal_codes = tuple(sorted(gmina_to_postcodes.get(gmina, [])))
    is_ref = (gmina == gminy_list[0])

    with col:
        st.markdown(f"## 🏘️ {gmina}")
        lbl = f"{len(postal_codes)} kodów · **baza ref.**" if (is_ref and len(gminy_list) > 1) \
              else f"{len(postal_codes)} kodów pocztowych"
        st.caption(lbl)

        summary  = marts["summary"].get(gmina, {})
        countries = marts["by_country"].get(gmina, [])
        months   = marts["by_month"].get(gmina, [])
        channels = marts["by_channel"].get(gmina, [])
        cards    = marts["by_card"].get(gmina, [])
        hours    = marts["by_hour"].get(gmina, [])

        if not summary:
            st.warning("Brak danych dla tej gminy.")
            continue

        n_total    = summary["n_total"]
        n_foreign  = summary["n_foreign"]
        n_domestic = summary["n_domestic"]
        pct_for    = summary["pct_foreign"]

        # ── 3 metryki nagłówkowe ──────────────────────────────────────────
        d_tot, dc_tot = _delta(summary, ref_summary, "n_total")
        d_pct, dc_pct = _delta(summary, ref_summary, "pct_foreign", pct=True)
        m1, m2, m3 = st.columns(3)
        m1.metric("🧾 Transakcje", f"{n_total:,}", delta=d_tot, delta_color=dc_tot)
        m2.metric("✈️ Turyści", f"{pct_for}%", delta=d_pct, delta_color=dc_pct,
                  help="% transakcji kartami wydanymi poza Polską")
        m3.metric("💳 Karty", f"{summary['n_cards']:,}")

        st.divider()

        # ── Kto kupuje ────────────────────────────────────────────────────
        st.markdown("**👥 Kto kupuje?**")
        _split_bar(pct_for, n_foreign, n_domestic)

        if countries:
            top = countries[:5]
            badges = " ".join(
                f":orange-badge[{c['country']} {c['pct']:.0f}%]" for c in top
            )
            st.markdown(f"Goście: {badges}")

        st.divider()

        # ── Płatności ─────────────────────────────────────────────────────
        st.markdown("**💳 Jak płaci?**")

        if channels:
            total_ch  = sum(c["n"] for c in channels)
            on_site_n = sum(c["n"] for c in channels if c["channel"] in ("cp_contactless", "cp_non_contactless", "mobile"))
            online_n  = sum(c["n"] for c in channels if c["channel"] in ("eci", "recur", "moto"))
            on_pct    = round(on_site_n / total_ch * 100, 1) if total_ch else 0
            off_pct   = round(online_n  / total_ch * 100, 1) if total_ch else 0

            pa, pb = st.columns(2)
            pa.metric("🏪 Na miejscu", f"{on_pct}%", f"{on_site_n:,}", delta_color="off")
            pb.metric("🌐 Online",      f"{off_pct}%", f"{online_n:,}",  delta_color="off")

            # Kanały jako badges (tylko te z >= 1%)
            ch_badges = " ".join(
                f":{CHANNEL_META.get(c['channel'], ('❔','',  'gray'))[2]}-badge"
                f"[{CHANNEL_META.get(c['channel'], ('❔','',''))[0]} {c['pct']:.0f}%]"
                for c in sorted(channels, key=lambda x: -x["n"])
                if c["pct"] >= 1.0 and c["channel"] != "cash"
            )
            if ch_badges:
                st.markdown(ch_badges)

        # Typy kart — jedna linia
        if cards:
            top_k = [c for c in cards if c["pct"] >= 2.0][:4]
            if top_k:
                k_badges = " ".join(
                    f":violet-badge[{CARD_ICONS.get(c['type'],'💳')} {c['type']} {c['pct']:.0f}%]"
                    for c in top_k
                )
                st.markdown(k_badges)

        st.divider()

        # ── Trend miesięczny ─────────────────────────────────────────────
        if months:
            st.markdown("**📅 Trend miesięczny**")
            pct_chart, vol_chart = _monthly_charts(months)
            st.caption("% turystów zagranicznych (linia = średnia)")
            st.altair_chart(pct_chart, use_container_width=True)
            st.caption("Wolumen transakcji (kolor = intensywność turystów)")
            st.altair_chart(vol_chart, use_container_width=True)

        # ── Szczegóły w expanders ─────────────────────────────────────────
        if hours:
            with st.expander("🕐 Rytm dnia"):
                df_h = pd.DataFrame(hours)
                long_h = pd.concat([
                    df_h.assign(grp="🏠 Krajowi",    n=df_h["n"] - df_h["n_foreign"])[["hour","grp","n"]],
                    df_h.assign(grp="✈️ Zagraniczni", n=df_h["n_foreign"])[["hour","grp","n"]],
                ])
                h_chart = (
                    alt.Chart(long_h).mark_area(opacity=0.85)
                    .encode(
                        x=alt.X("hour:O", title="Godzina"),
                        y=alt.Y("n:Q", title=None, axis=alt.Axis(format="~s"), stack=True),
                        color=alt.Color("grp:N",
                            scale=alt.Scale(domain=["✈️ Zagraniczni","🏠 Krajowi"],
                                            range=[_CLR_FOREIGN, _CLR_DOMESTIC]),
                            legend=alt.Legend(orient="bottom", title=None)),
                        tooltip=["hour","grp", alt.Tooltip("n:Q", format=",")],
                    ).properties(height=130)
                )
                st.altair_chart(h_chart, use_container_width=True)

        with st.expander("🏠 Mieszkańcy i powiązania"):
            btn_key = f"btn_r_{gmina}"
            res_key = f"res_{gmina}"
            if res_key not in st.session_state:
                if st.button("Analizuj mieszkańców", key=btn_key):
                    with st.spinner("Liczę card_home i przepływy…"):
                        st.session_state[res_key] = run_residents_analysis(
                            list(postal_codes), code_to_gmina)
                    st.rerun()
            if res_key in st.session_state:
                r = st.session_state[res_key]
                st.caption(f"Karty z domem w gminie: {r.get('n_resident_cards', 0):,}")
                e1, e2, e3 = st.columns(3)
                e1.metric("Samowystarczalność", f"{r.get('E1_self_sufficiency', 0):.1f}%",
                          help="% zakupów codziennych lokalnie")
                e2.metric("Atrakcyjność",        f"{r.get('E2_attractiveness', 0):.1f}%",
                          help="napływ / (napływ + odpływ)")
                e3.metric("Zależność od gości",  f"{r.get('E3_tourism_dependency', 0):.1f}%",
                          help="% transakcji od gości spoza gminy")
                if "E5_connections" in r:
                    st.markdown("**Powiązania:**")
                    conn = r["E5_connections"][["gmina","kierunek","n_out","n_in","flow_total"]]
                    conn.columns = ["Gmina","↔","Odpływ →","Napływ ←","Łącznie"]
                    st.dataframe(conn, hide_index=True, use_container_width=True)
                if "B2_outflow" in r and len(r["B2_outflow"]):
                    st.markdown("**Dokąd wyjeżdżają:**")
                    st.bar_chart(r["B2_outflow"][["area_gmina","n"]].rename(
                        columns={"area_gmina":"Gmina","n":"Transakcje"}).set_index("Gmina"),
                        use_container_width=True)
                if "B3_inflow" in r and len(r["B3_inflow"]):
                    st.markdown("**Skąd przyjeżdżają:**")
                    st.bar_chart(r["B3_inflow"][["home_gmina","n"]].rename(
                        columns={"home_gmina":"Gmina","n":"Transakcje"}).set_index("Gmina"),
                        use_container_width=True)
                if "B4_outflow_cat" in r and len(r["B4_outflow_cat"]):
                    st.markdown("**Czego szukają poza gminą:**")
                    st.dataframe(r["B4_outflow_cat"].rename(
                        columns={"mrch_catg_nm":"Kategoria","n":"Transakcje"}),
                        hide_index=True, use_container_width=True)

# ── Szczegóły handlu (panels.py) ──────────────────────────────────────────────
st.markdown("---")
st.markdown("# 🛍️ Handel, kupujący i płatności — szczegóły")
if not marts_ready():
    st.warning("Brak danych handlu. Uruchom: `python build_marts.py`")
else:
    @st.cache_resource(show_spinner="Ładuję dane handlu…")
    def load_trade_reference():
        return build_reference(get_gmina_group_table())

    _meta      = get_marts_meta()
    _trade_ref = load_trade_reference()
    for _tab, _gmina in zip(st.tabs([f"🏙️ {g}" for g in sorted(selected)]), sorted(selected)):
        with _tab:
            render_gmina(_gmina, _trade_ref, _meta)
