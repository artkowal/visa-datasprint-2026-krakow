"""Widok dopasowania gmin z profilami kategorii i wizualizacją uzupełnienia/wzmocnienia."""

import streamlit as st
import plotly.graph_objects as go
from pathlib import Path

from app.map_builder import load_gminy_data
from app.matching_map import build_matching_map
from app.categories import GROUP_ICONS, GROUP_ORDER

_REAL_DATA_PATH = Path("dataset/json/by_category.json")
CATEGORIES = [g for g in GROUP_ORDER if g not in {"Handel internetowy", "Inne"}]


def _get_rank_fn():
    if _REAL_DATA_PATH.exists():
        from app.matching_real import rank_matches
        return rank_matches, True
    from app.matching_demo import rank_matches
    return rank_matches, False


@st.cache_resource(show_spinner=False)
def _cached_profiles() -> dict[str, dict[str, float]]:
    from app.matching_real import load_display_profiles
    return load_display_profiles()


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

    fig = go.Figure(go.Bar(
        x=vals,
        y=labels,
        orientation="h",
        marker_color=colors,
        marker_line=dict(
            color=["#2dd4bf" if c == "#2dd4bf" else "rgba(0,0,0,0)" for c in colors],
            width=2,
        ),
        text=text,
        textposition="outside",
        cliponaxis=False,
        hovertemplate="%{y}: %{x:.1f}%<extra></extra>",
        name="Dopasowanie",
    ))

    # warstwa referencyjna — wartości kotwicy jako złote markery
    if anchor is not None:
        anchor_vals = [anchor.get(c, 0) * 100 for c, _ in sorted_cats]
        shared_cats = {c for c, v in sorted_cats if anchor.get(c, 0) >= 0.08 and v >= 0.08} if mode == "Wzmocnienie" else set()
        fig.add_trace(go.Scatter(
            x=anchor_vals,
            y=labels,
            mode="markers",
            marker=dict(
                symbol="line-ns-open",
                size=14,
                color="#f7bb42",
                line=dict(width=2.5, color="#f7bb42"),
            ),
            name="Kotwica",
            hovertemplate="%{y} (kotwica): %{x:.1f}%<extra></extra>",
        ))

    max_val = max(vals) if vals else 1
    if anchor is not None:
        anchor_max = max((anchor.get(c, 0) * 100 for c, _ in sorted_cats), default=0)
        max_val = max(max_val, anchor_max)

    # tytuł z wspólnymi mocnymi kategoriami (tylko Wzmocnienie)
    shared_label = ""
    if anchor is not None and mode == "Wzmocnienie":
        shared = [f"{GROUP_ICONS.get(c,'')} {c}" for c, v in sorted_cats if anchor.get(c, 0) >= 0.08 and v >= 0.08]
        if shared:
            shared_label = "🤝 " + " · ".join(shared)

    fig.update_layout(
        height=max(180, len(names) * height_per_row),
        margin={"l": 0, "r": 50, "t": 28 if shared_label else 4, "b": 4},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"color": "#cdd6f4", "size": 11},
        title=dict(text=shared_label, font=dict(size=11, color="#2dd4bf"), x=0, xanchor="left") if shared_label else {},
        xaxis=dict(
            showgrid=False, zeroline=False, visible=False,
            range=[0, max_val * 1.35],
        ),
        yaxis=dict(showgrid=False, zeroline=False, tickfont={"size": 11}),
        legend=dict(orientation="h", yanchor="bottom", y=1.01, xanchor="right", x=1,
                    font=dict(size=10)) if anchor is not None else {},
        showlegend=anchor is not None,
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
            value=150,
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
        match_cols = st.columns(len(matches), gap="small")
        for col, match in zip(match_cols, matches):
            match_profile = all_profiles.get(match.gmina, {})
            with col:
                with st.container(border=True):
                    st.markdown(f"**{match.gmina}**")
                    st.metric("Wynik", f"{match.score}/100", delta=f"{match.distance_km:g} km", delta_color="off")

                    pairs = _key_pairs(anchor, match.gmina, norm_profiles, mode)
                    if pairs:
                        if mode == "Wzmocnienie":
                            for cat, _, desc in pairs:
                                icon = GROUP_ICONS.get(cat, "")
                                st.caption(f"{icon} **{cat}** — {desc}")
                        else:
                            for row in pairs:
                                ag, mg = row
                                a_str = (f"{GROUP_ICONS.get(ag[0],'')} **{ag[0]}** +{ag[1]*100:.0f}pp"
                                         if ag else "—")
                                m_str = (f"{GROUP_ICONS.get(mg[0],'')} **{mg[0]}** +{mg[1]*100:.0f}pp"
                                         if mg else "—")
                                st.caption(f"{a_str} ↔ {m_str}")

                    with st.expander("Pełny profil kategorii"):
                        if match_profile:
                            st.plotly_chart(
                                _profile_fig(match_profile, mode, anchor=anchor_profile, height_per_row=22),
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
