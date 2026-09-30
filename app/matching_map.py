"""Mapa gmin dla demonstracyjnego rankingu partnerów."""

import plotly.graph_objects as go

from app.matching_demo import Match


def build_matching_map(
    geojson: dict,
    anchor: str,
    matches: list[Match],
    mode: str,
    center: tuple[float, float],
    radius_km: int,
) -> go.Figure:
    features = geojson["features"]
    match_by_name = {match.gmina: match for match in matches}

    def layer(names: set[str]) -> dict:
        return {
            "type": "FeatureCollection",
            "features": [f for f in features if f["properties"]["Gmina"] in names],
        }

    all_names = {f["properties"]["Gmina"] for f in features}
    neutral_names = sorted(all_names - {anchor} - match_by_name.keys())
    ranked_names = [match.gmina for match in matches]
    color = "#2dd4bf" if mode == "Wzmocnienie" else "#fbbf24"

    fig = go.Figure()
    fig.add_trace(go.Choroplethmap(
        geojson=layer(set(neutral_names)),
        locations=neutral_names,
        z=[1] * len(neutral_names),
        featureidkey="properties.Gmina",
        colorscale=[[0, "#64748b"], [1, "#64748b"]],
        showscale=False,
        marker_opacity=0.28,
        marker_line_width=0.3,
        marker_line_color="#172033",
        hovertemplate="<b>%{location}</b><br>Kliknij, aby wybrać gminę<extra></extra>",
        name="Pozostałe gminy",
    ))
    if ranked_names:
        fig.add_trace(go.Choroplethmap(
            geojson=layer(set(ranked_names)),
            locations=ranked_names,
            z=[match_by_name[name].score for name in ranked_names],
            customdata=[
                [i, match_by_name[name].distance_km, match_by_name[name].category]
                for i, name in enumerate(ranked_names, 1)
            ],
            featureidkey="properties.Gmina",
            colorscale=[[0, color], [1, color]],
            zmin=0,
            zmax=100,
            showscale=False,
            marker_opacity=0.82,
            marker_line_width=1.6,
            marker_line_color="#ffffff",
            hovertemplate=(
                "<b>%{location}</b><br>#%{customdata[0]} · wynik: %{z}/100"
                "<br>%{customdata[1]} km · %{customdata[2]}<extra></extra>"
            ),
            name="Dopasowania",
        ))
    fig.add_trace(go.Choroplethmap(
        geojson=layer({anchor}),
        locations=[anchor],
        z=[1],
        featureidkey="properties.Gmina",
        colorscale=[[0, "#a78bfa"], [1, "#a78bfa"]],
        showscale=False,
        marker_opacity=0.95,
        marker_line_width=2.5,
        marker_line_color="#ffffff",
        hovertemplate="<b>%{location}</b><br>Wybrana gmina<extra></extra>",
        name="Wybrana gmina",
    ))
    fig.update_layout(
        map_style="open-street-map",
        map_zoom=9 if radius_km <= 30 else 8 if radius_km <= 80 else 7 if radius_km <= 150 else 6,
        map_center={"lat": center[0], "lon": center[1]},
        height=600,
        margin={"r": 0, "t": 0, "l": 0, "b": 0},
        paper_bgcolor="#1e1e2e",
        hoverlabel=dict(bgcolor="#2a2a3e", font_color="#cdd6f4", font_size=13),
        showlegend=False,
        clickmode="event+select",
        uirevision=f"matching_map_{anchor}",
    )
    return fig
