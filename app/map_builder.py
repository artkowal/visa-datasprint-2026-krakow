import json

import geopandas as gpd
import plotly.graph_objects as go
from shapely.geometry import MultiPolygon, Polygon

_PALETTE = [
    "#e74c3c", "#3498db", "#2ecc71", "#f39c12", "#9b59b6",
    "#1abc9c", "#e67e22", "#e91e63", "#00bcd4", "#8bc34a",
    "#ff5722", "#607d8b", "#795548", "#ff9800", "#673ab7",
]
_SELECTED_COLOR = "#a78bfa"
_N = len(_PALETTE)

_PL_PROJECTED_CRS = "EPSG:2180"
_GAP_CLOSE_METERS = 30  # smallest distance that fully closes gmina boundaries into one polygon

_MIN_HOLE_AREA_M2 = 500_000  # 0.5 km^2


def _fill_small_holes(geom, min_hole_area: float):
    if geom is None or geom.is_empty:
        return geom
    if geom.geom_type == "Polygon":
        kept = [ring for ring in geom.interiors if Polygon(ring).area >= min_hole_area]
        return Polygon(geom.exterior, kept)
    if geom.geom_type == "MultiPolygon":
        return MultiPolygon([_fill_small_holes(p, min_hole_area) for p in geom.geoms])
    return geom

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
    dissolved = dissolved.set_crs(gdf.crs).to_crs(_PL_PROJECTED_CRS)
    dissolved["geometry"] = dissolved["geometry"].buffer(_GAP_CLOSE_METERS).buffer(-_GAP_CLOSE_METERS)
    dissolved["geometry"] = dissolved["geometry"].apply(lambda g: _fill_small_holes(g, _MIN_HOLE_AREA_M2))
    dissolved = dissolved.to_crs(gdf.crs)
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
    center_gmina: str | None = None,
    centroids: dict | None = None,
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

    # ── linie od centrum do sąsiadów (tryb współpraca graniczna) ─────────────
    if center_gmina and centroids and center_gmina in centroids:
        c_lat, c_lon = centroids[center_gmina]
        neighbors_to_draw = [g for g in sel_names if g != center_gmina and g in centroids]

        # linie: centrum → każdy sąsiad (None przerywa segment)
        line_lats, line_lons = [], []
        for g in neighbors_to_draw:
            n_lat, n_lon = centroids[g]
            line_lats += [c_lat, n_lat, None]
            line_lons += [c_lon, n_lon, None]

        if line_lats:
            fig.add_trace(go.Scattermap(
                lat=line_lats,
                lon=line_lons,
                mode="lines",
                line=dict(color="#e2d0ff", width=1.2),
                hoverinfo="skip",
                showlegend=False,
                name="powiązania",
            ))

        # punkt centrum — wyróżniony
        fig.add_trace(go.Scattermap(
            lat=[c_lat],
            lon=[c_lon],
            mode="markers",
            marker=dict(size=12, color="#ffffff", opacity=0.95),
            hovertemplate=f"<b>{center_gmina}</b><br>centrum obszaru<extra></extra>",
            showlegend=False,
            name="centrum",
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
