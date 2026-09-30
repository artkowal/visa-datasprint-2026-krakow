"""Widok dopasowania gmin z profilami kategorii i wizualizacją uzupełnienia/wzmocnienia."""

import streamlit as st
import plotly.graph_objects as go
from pathlib import Path

from app.map_builder import load_gminy_data
from app.matching_map import build_matching_map
from app.categories import GROUP_ICONS, GROUP_ORDER

_REAL_DATA_PATH = Path("dataset/json/by_category.json")
_VIEW_EXCLUDED = {"Handel internetowy", "Inne", "Żywność", "Zdrowie i apteki", "Dyskonty i domy towarowe"}
CATEGORIES = [g for g in GROUP_ORDER if g not in _VIEW_EXCLUDED]


def _get_rank_fn():
    if _REAL_DATA_PATH.exists():
        from app.matching_real import rank_matches
        return rank_matches, True
    from app.matching_demo import rank_matches
    return rank_matches, False


@st.cache_resource(show_spinner=False)
def _cached_profiles() -> dict[str, dict[str, float]]:
    from app.matching_real import load_display_profiles
    return load_display_profiles(matching_only=True)


@st.cache_resource(show_spinner=False)
def _cached_norm_profiles() -> dict[str, dict[str, float]]:
    from app.matching_real import load_normalized_profiles
    return load_normalized_profiles()


@st.cache_resource(show_spinner="Przygotowuję mapę gmin…")
def load_matching_map():
    geojson, _, centroids = load_gminy_data("geojson/postcodes_poland.geojson")
    return geojson, centroids


def _profile_fig(
    profile: dict[str, float],
    mode: str,
    anchor: dict[str, float] | None = None,
    height_per_row: int = 26,
    anchor_name: str = "Kotwica",
    match_name: str = "Dopasowanie",
) -> go.Figure:
    """Horizontal bar chart of category shares.

    Standalone (anchor=None): strong/neutral/weak coloring.
    Comparison (anchor provided): highlights complementary or reinforcing pairs.
    """
    sorted_cats = sorted(profile.items(), key=lambda x: x[1], reverse=True)
    names = [c for c, _ in sorted_cats]
    vals = [v * 100 for _, v in sorted_cats]
    labels = [f"{GROUP_ICONS.get(c, '')} {c}" for c in names]

    if anchor is None:
        # Standalone profile: top-3 teal, bottom-3 red, rest slate
        colors = []
        n = len(vals)
        for i in range(n):
            if i < 3:
                colors.append("#2dd4bf")
            elif i >= n - 3:
                colors.append("#f87171")
            else:
                colors.append("#475569")
    else:
        colors = []
        for cat, val in sorted_cats:
            a = anchor.get(cat, 0.0)
            m = val / 100
            if mode == "Wzmocnienie":
                # Both strong → teal
                if a >= 0.08 and m >= 0.08:
                    colors.append("#2dd4bf")
                # Both weak/neutral → slate
                else:
                    colors.append("#475569")
            else:  # Uzupełnienie
                # Match strong, anchor weak → gold (match fills the gap)
                if m >= 0.08 and a < 0.04:
                    colors.append("#fbbf24")
                # Anchor strong, match weak → violet (anchor fills the gap)
                elif a >= 0.08 and m < 0.04:
                    colors.append("#a78bfa")
                else:
                    colors.append("#475569")

    text = [f"{v:.1f}%" if v >= 1.0 else "" for v in vals]

    # tryb bez kotwicy — samodzielny profil
    if anchor is None:
        fig = go.Figure(go.Bar(
            x=vals, y=labels, orientation="h",
            marker_color=colors,
            text=text, textposition="outside", cliponaxis=False,
            hovertemplate="%{y}: %{x:.1f}%<extra></extra>",
        ))
        max_val = max(vals) if vals else 1
        fig.update_layout(
            height=max(180, len(names) * height_per_row),
            margin={"l": 0, "r": 50, "t": 4, "b": 4},
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            font={"color": "#cdd6f4", "size": 11},
            xaxis=dict(showgrid=False, zeroline=False, visible=False, range=[0, max_val * 1.35]),
            yaxis=dict(showgrid=False, zeroline=False, tickfont={"size": 11}, autorange="reversed"),
            showlegend=False,
        )
        return fig

    # tryb porównania — dwa słupki obok siebie
    anchor_vals = [anchor.get(c, 0) * 100 for c, _ in sorted_cats]

    def _bar_color_pair(cat, match_val, anchor_val, mode):
        m, a = match_val / 100, anchor_val / 100
        if mode == "Wzmocnienie":
            if a >= 0.08 and m >= 0.08:
                return "#2dd4bf", "#2dd4bf"   # obie mocne — teal
            return "#475569", "#374151"
        else:
            if m >= 0.08 and a < 0.04:
                return "#fbbf24", "#374151"    # match uzupełnia
            if a >= 0.08 and m < 0.04:
                return "#374151", "#a78bfa"    # anchor uzupełnia
            return "#475569", "#374151"

    match_colors, anchor_colors = zip(*[_bar_color_pair(c, v, anchor.get(c, 0) * 100, mode)
                                        for c, v in sorted_cats])

    anchor_text = [f"{v:.1f}%" if v >= 1.0 else "" for v in anchor_vals]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        name=anchor_name,
        x=anchor_vals, y=labels, orientation="h",
        marker_color=list(anchor_colors),
        opacity=0.70,
        text=anchor_text,
        textposition="outside",
        textfont=dict(size=13, color="#94a3b8"),
        cliponaxis=False,
        hovertemplate=f"<b>%{{y}}</b><br>{anchor_name}: %{{x:.1f}}%<extra></extra>",
    ))
    fig.add_trace(go.Bar(
        name=match_name,
        x=vals, y=labels, orientation="h",
        marker_color=list(match_colors),
        text=[f"{v:.1f}%" if v >= 1.0 else "" for v in vals],
        textposition="outside",
        textfont=dict(size=13, color="#cdd6f4"),
        cliponaxis=False,
        hovertemplate=f"<b>%{{y}}</b><br>{match_name}: %{{x:.1f}}%<extra></extra>",
    ))

    max_val = max(max(vals), max(anchor_vals)) if vals else 1

    fig.update_layout(
        barmode="group",
        bargap=0.25,
        bargroupgap=0.08,
        height=max(220, len(names) * height_per_row),
        margin={"l": 0, "r": 65, "t": 4, "b": 4},
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font={"color": "#cdd6f4", "size": 13},
        xaxis=dict(showgrid=False, zeroline=False, visible=False, range=[0, max_val * 1.4]),
        yaxis=dict(showgrid=False, zeroline=False, tickfont={"size": 13}, autorange="reversed"),
        legend=dict(orientation="h", yanchor="bottom", y=1.01, xanchor="right", x=1,
                    font=dict(size=11), bgcolor="rgba(0,0,0,0)"),
        showlegend=True,
    )
    return fig


def _key_pairs(
    anchor_name: str,
    match_name: str,
    norm_profiles: dict[str, dict[str, float]],
    mode: str,
) -> list[tuple]:
    """
    Wzmocnienie → list of (cat, None, desc)
    Uzupełnienie → list of (anchor_cat_or_None, match_cat_or_None, score)
    """
    an = norm_profiles.get(anchor_name, {})
    mn = norm_profiles.get(match_name, {})

    if mode == "Wzmocnienie":
        shared = [(c, min(an.get(c, 0), mn.get(c, 0))) for c in CATEGORIES]
        shared = [(c, v) for c, v in shared if v > 0.005]
        shared.sort(key=lambda x: -x[1])
        return [(c, None, f"obie +{v*100:.0f}pp ponad śred.") for c, v in shared[:3]]
    else:
        # pary wymiany: anchor silny tam gdzie match słaby i vice versa
        a_gives = sorted(
            [(c, an.get(c, 0)) for c in CATEGORIES if an.get(c, 0) > 0.005 and mn.get(c, 0) < 0],
            key=lambda x: -x[1],
        )
        m_gives = sorted(
            [(c, mn.get(c, 0)) for c in CATEGORIES if mn.get(c, 0) > 0.005 and an.get(c, 0) < 0],
            key=lambda x: -x[1],
        )
        n = min(3, max(len(a_gives), len(m_gives)))
        return [
            (a_gives[i] if i < len(a_gives) else None,
             m_gives[i] if i < len(m_gives) else None)
            for i in range(n)
        ]


def render_matching(mode: str) -> None:
    geojson, centroids = load_matching_map()
    names = sorted(centroids)
    if "matching_anchor" not in st.session_state:
        st.session_state["matching_anchor"] = "KRAKOW" if "KRAKOW" in centroids else names[0]
    if "matching_last_map_click" not in st.session_state:
        st.session_state["matching_last_map_click"] = None

    ctrl_a, ctrl_b = st.columns([3, 1])
    with ctrl_a:
        anchor = st.selectbox("Gmina bazowa", names, key="matching_anchor")
    with ctrl_b:
        radius = st.select_slider(
            "Zasięg",
            options=[30, 50, 80, 120, 150, 200, 300],
            value=50,
            format_func=lambda x: f"{x} km",
        )

    if mode == "Wzmocnienie":
        st.info("**💪 Wzmocnienie** — szuka gmin z podobnymi mocnymi kategoriami. Teal = wspólna mocna kategoria.")
    else:
        st.info("**🔄 Uzupełnienie** — szuka gmin, które wypełniają luki. Złoty = gmina uzupełnia Ciebie · Fiolet = Ty uzupełniasz gminę.")

    rank_fn, is_real = _get_rank_fn()
    matches = rank_fn(anchor, centroids, mode, max_distance_km=radius)
    all_profiles = _cached_profiles()
    norm_profiles = _cached_norm_profiles()
    anchor_profile = all_profiles.get(anchor, {})

    # ── Mapa (lewa) + Profil kotwy (prawa) ───────────────────────────────────
    map_col, profile_col = st.columns([3, 2], gap="large")

    with map_col:
        event = st.plotly_chart(
            build_matching_map(geojson, anchor, matches, mode, centroids[anchor], radius),
            key="matching_map_chart",
            on_select="rerun",
            width="stretch",
            height=600,
        )
        points = event.selection.points if event and event.selection else []
        if points:
            clicked = points[0].get("location")
            if clicked and clicked != st.session_state["matching_last_map_click"]:
                st.session_state["matching_last_map_click"] = clicked
                if clicked != anchor:
                    st.session_state["matching_anchor"] = clicked
                    st.rerun()

    with profile_col:
        st.markdown(f"#### Profil: **{anchor}**")
        if anchor_profile:
            st.caption("🟢 mocna &nbsp;·&nbsp; ⚫ neutralna &nbsp;·&nbsp; 🔴 słaba")
            st.plotly_chart(
                _profile_fig(anchor_profile, mode),
                key=f"anchor_chart_{anchor}",
                width="stretch",
            )
        else:
            st.info("Brak danych profilu dla tej gminy.")

    # ── Dopasowania ───────────────────────────────────────────────────────────
    st.markdown("---")
    st.subheader(f"Najlepsze dopasowania · zasięg {radius} km")

    if not matches:
        st.warning("W tym zasięgu nie znaleziono innych gmin. Zwiększ zasięg.")
    else:
        for row_start in range(0, len(matches), 2):
            row_matches = matches[row_start:row_start + 2]
            cols = st.columns(2, gap="large")
            for col, match in zip(cols, row_matches):
                match_profile = all_profiles.get(match.gmina, {})
                with col:
                    with st.container(border=True):
                        st.markdown(f"**{match.gmina}**")
                        st.metric("Wynik", f"{match.score}/100", delta=f"{match.distance_km:g} km", delta_color="off")

                        # ── kolorowe chipy kategorii ──────────────────────
                        if match_profile and anchor_profile:
                            chips = []
                            for cat in CATEGORIES:
                                m_val = match_profile.get(cat, 0)
                                a_val = anchor_profile.get(cat, 0)
                                if mode == "Wzmocnienie":
                                    if a_val >= 0.08 and m_val >= 0.08:
                                        bg, fg = "#2dd4bf", "#0f172a"
                                    elif m_val >= 0.05:
                                        bg, fg = "#334155", "#cdd6f4"
                                    else:
                                        continue
                                else:
                                    if m_val >= 0.08 and a_val < 0.04:
                                        bg, fg = "#f7bb42", "#0f172a"
                                    elif a_val >= 0.08 and m_val < 0.04:
                                        bg, fg = "#a78bfa", "#0f172a"
                                    elif m_val >= 0.05:
                                        bg, fg = "#334155", "#cdd6f4"
                                    else:
                                        continue
                                icon = GROUP_ICONS.get(cat, "")
                                chips.append(
                                    f'<span style="display:inline-block;background:{bg};color:{fg};'
                                    f'padding:3px 8px;border-radius:999px;font-size:0.75em;'
                                    f'margin:2px 2px 2px 0;white-space:nowrap">{icon} {cat}</span>'
                                )
                            if chips:
                                st.markdown(
                                    f'<p style="margin:6px 0 2px;font-size:0.78em;color:#94a3b8;">'
                                    f'Najbardziej dominujące w {match.gmina}:</p>'
                                    + "".join(chips),
                                    unsafe_allow_html=True,
                                )

                        # ── wykres porównawczy — zawsze widoczny ──────────
                        if match_profile:
                            st.plotly_chart(
                                _profile_fig(match_profile, mode, anchor=anchor_profile,
                                             height_per_row=44, anchor_name=anchor, match_name=match.gmina),
                                key=f"match_chart_{match.gmina}",
                                width="stretch",
                            )
                        else:
                            st.caption("Brak danych profilu.")

    # wyrównaj wysokości kart — components.html gwarantuje wykonanie JS
    import streamlit.components.v1 as components
    components.html("""
    <script>
    const run = () => {
        const doc = window.parent.document;
        const rows = doc.querySelectorAll('[data-testid="stHorizontalBlock"]');
        rows.forEach(row => {
            const cols = [...row.querySelectorAll('[data-testid="column"]')];
            if (cols.length < 2) return;
            cols.forEach(c => c.style.height = 'auto');
            const maxH = Math.max(...cols.map(c => c.getBoundingClientRect().height));
            cols.forEach(c => {
                c.style.height = maxH + 'px';
                const card = c.querySelector('[data-testid="stVerticalBlockBorderWrapper"]');
                if (card) card.style.height = '100%';
            });
        });
    };
    [200, 600, 1200].forEach(t => setTimeout(run, t));
    </script>
    """, height=0)

    if not is_real:
        st.warning(
            "**Dane demonstracyjne:** profile kategorii są syntetyczne. "
            "Wygeneruj `by_category.json` aby zobaczyć ranking oparty na transakcjach Visa."
        )
