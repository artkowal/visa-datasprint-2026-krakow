import json
import geopandas as gpd
import plotly.graph_objects as go

_PALETTE = [
    "#e74c3c", "#3498db", "#2ecc71", "#f39c12", "#9b59b6",
    "#1abc9c", "#e67e22", "#e91e63", "#00bcd4", "#8bc34a",
    "#ff5722", "#607d8b", "#795548", "#ff9800", "#673ab7",
]
_SELECTED_COLOR = "#a78bfa"
_N = len(_PALETTE)

# Discrete colorscale: każdy kolor zajmuje równy przedział [i/N, (i+1)/N]
_COLORSCALE = []
for _i, _c in enumerate(_PALETTE):
    _COLORSCALE.append([_i / _N, _c])
    _COLORSCALE.append([(_i + 1) / _N, _c])


def load_gminy_data(
    geojson_path: str,
) -> tuple[dict, dict[str, list[str]], dict[str, tuple[float, float]]]:
    gdf = gpd.read_file(geojson_path)
    gdf["geometry"] = gdf["geometry"].make_valid()

    mapping: dict[str, list[str]] = gdf.groupby("Gmina")["Name"].apply(list).to_dict()

    dissolved = gdf.dissolve(by="Gmina").reset_index()[["Gmina", "geometry"]]
    dissolved["geometry"] = dissolved["geometry"].make_valid()
    dissolved = dissolved[
        dissolved["geometry"].notna() &
        dissolved["geometry"].geom_type.isin(["Polygon", "MultiPolygon"])
    ]
    dissolved["n_kodow"] = dissolved["Gmina"].map(lambda g: len(mapping.get(g, [])))

    centroids: dict[str, tuple[float, float]] = {
        row["Gmina"]: (row.geometry.centroid.y, row.geometry.centroid.x)
        for _, row in dissolved.iterrows()
    }

    geojson = json.loads(dissolved.to_json())
    return geojson, mapping, centroids


def build_map(
    geojson_path: str,
    selected: set[str],
    gminy_geojson: dict | None = None,
    center: tuple[float, float] = (52.0, 19.5),
    zoom: int = 6,
) -> go.Figure:
    geojson = gminy_geojson
    if geojson is None:
        with open(geojson_path, encoding="utf-8") as f:
            geojson = json.load(f)

    features = geojson["features"]
    all_names = [f["properties"]["Gmina"] for f in features]

    unsel_names = [g for g in all_names if g not in selected]
    sel_names   = [g for g in all_names if g in selected]

    unsel_geojson = {
        "type": "FeatureCollection",
        "features": [f for f in features if f["properties"]["Gmina"] not in selected],
    }
    sel_geojson = {
        "type": "FeatureCollection",
        "features": [f for f in features if f["properties"]["Gmina"] in selected],
    }

    fig = go.Figure()

    # ── warstwa bazowa: losowe kolory ─────────────────────────────────────────
    if unsel_names:
        z_vals = [hash(g) % _N for g in unsel_names]
        fig.add_trace(go.Choroplethmap(
            geojson=unsel_geojson,
            locations=unsel_names,
            z=z_vals,
            featureidkey="properties.Gmina",
            colorscale=_COLORSCALE,
            zmin=0,
            zmax=_N - 1,
            showscale=False,
            marker_opacity=0.45,
            marker_line_width=0.4,
            marker_line_color="#1e1e2e",
            hovertemplate="<b>%{location}</b><extra></extra>",
            name="gminy",
        ))

    # ── warstwa zaznaczonych: fioletowa ──────────────────────────────────────
    if sel_names:
        fig.add_trace(go.Choroplethmap(
            geojson=sel_geojson,
            locations=sel_names,
            z=[1] * len(sel_names),
            featureidkey="properties.Gmina",
            colorscale=[[0, _SELECTED_COLOR], [1, _SELECTED_COLOR]],
            zmin=0,
            zmax=1,
            showscale=False,
            marker_opacity=0.75,
            marker_line_width=2.5,
            marker_line_color="#ffffff",
            hovertemplate="<b>%{location}</b> ✓<extra></extra>",
            name="zaznaczone",
        ))

    # Plotly zoom ~= folium zoom - 1
    plotly_zoom = max(3, zoom - 1)

    fig.update_layout(
        map_style="open-street-map",
        map_zoom=plotly_zoom,
        map_center={"lat": center[0], "lon": center[1]},
        margin={"r": 0, "t": 0, "l": 0, "b": 0},
        height=520,
        paper_bgcolor="#1e1e2e",
        plot_bgcolor="#1e1e2e",
        hoverlabel=dict(bgcolor="#2a2a3e", font_color="#cdd6f4", font_size=13),
        showlegend=False,
        # uirevision = stała wartość → Plotly zachowuje viewport (zoom/center) między rerenderami
        uirevision="poland_map",
    )

    return fig
