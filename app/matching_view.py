"""Wspólny widok dwóch demonstracyjnych trybów dopasowania gmin."""

import streamlit as st

from app.map_builder import load_gminy_data
from app.matching_demo import rank_matches
from app.matching_map import build_matching_map


@st.cache_resource(show_spinner="Przygotowuję mapę gmin…")
def load_matching_map():
    geojson, _, centroids = load_gminy_data("geojson/postcodes_poland.geojson")
    return geojson, centroids


def render_matching(mode: str) -> None:
    st.caption("Wybierz gminę. Kliknięcie innej gminy na mapie zmienia punkt wyjścia.")

    geojson, centroids = load_matching_map()
    names = sorted(centroids)
    if "matching_anchor" not in st.session_state:
        st.session_state["matching_anchor"] = "KRAKOW" if "KRAKOW" in centroids else names[0]
    if "matching_last_map_click" not in st.session_state:
        st.session_state["matching_last_map_click"] = None

    control_a, control_b = st.columns([3, 1])
    with control_a:
        anchor = st.selectbox("Gmina bazowa", names, key="matching_anchor")
    with control_b:
        radius = st.select_slider(
            "Zasięg",
            options=[30, 50, 80, 120, 150, 200, 300],
            value=150,
            format_func=lambda x: f"{x} km",
        )

    if mode == "Wzmocnienie":
        st.info("**Wzmocnienie** szuka pobliskich gmin z podobnymi mocnymi kategoriami. Razem mogą rozwijać istniejącą specjalizację.")
    else:
        st.info("**Uzupełnienie** szuka gmin mocniejszych tam, gdzie wybrana gmina jest słabsza. Pokazuje możliwy podział funkcji.")

    matches = rank_matches(anchor, centroids, mode, max_distance_km=radius)
    map_col, results_col = st.columns([3, 2], gap="large")
    with map_col:
        match_color = "turkusowe" if mode == "Wzmocnienie" else "złote"
        st.markdown(f"**Fioletowa:** {anchor} · **{match_color.capitalize()}:** 5 najlepszych dopasowań")
        event = st.plotly_chart(
            build_matching_map(geojson, anchor, matches, mode, centroids[anchor], radius),
            key="matching_map_chart",
            on_select="rerun",
            use_container_width=True,
        )
        points = event.selection.points if event and event.selection else []
        if points:
            clicked = points[0].get("location")
            if clicked and clicked != st.session_state["matching_last_map_click"]:
                st.session_state["matching_last_map_click"] = clicked
                if clicked != anchor:
                    st.session_state["matching_anchor"] = clicked
                    st.rerun()

    with results_col:
        st.subheader("Najlepsze dopasowania")
        st.caption(f"Tryb: {mode.lower()} · zasięg: {radius} km")
        if not matches:
            st.warning("W tym zasięgu nie znaleziono innych gmin. Zwiększ zasięg.")
        for i, match in enumerate(matches, 1):
            st.markdown(f"**{i}. {match.gmina}** · {match.score}/100")
            st.progress(match.score / 100)
            reason = "Wspólna mocna kategoria" if mode == "Wzmocnienie" else "Kategoria uzupełniająca"
            st.caption(f"{reason}: {match.category} · {match.distance_km:g} km")

    st.warning(
        "**Dane demonstracyjne:** oceny kategorii i wyniki dopasowania są syntetyczne, "
        "wyliczone stabilnie z nazw gmin. Tylko położenie gmin pochodzi z GeoJSON. "
        "Ranking nie jest rekomendacją opartą na transakcjach Visa."
    )
