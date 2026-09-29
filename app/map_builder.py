import folium
import json
import geopandas as gpd
from folium.plugins import Search

_PALETTE = [
    "#e74c3c", "#3498db", "#2ecc71", "#f39c12", "#9b59b6",
    "#1abc9c", "#e67e22", "#e91e63", "#00bcd4", "#8bc34a",
    "#ff5722", "#607d8b", "#795548", "#ff9800", "#673ab7",
]


def _gmina_color(name: str) -> str:
    return _PALETTE[hash(name) % len(_PALETTE)]


def load_gminy_data(
    geojson_path: str,
) -> tuple[dict, dict[str, list[str]], dict[str, tuple[float, float]]]:
    """
    Wczytuje GeoJSON kodów pocztowych i scala poligony po gminie.
    Zwraca: (geojson_dict_gminy, {gmina: [kody_pocztowe]}, {gmina: (lat, lon)})
    """
    gdf = gpd.read_file(geojson_path)
    gdf["geometry"] = gdf["geometry"].make_valid()

    mapping: dict[str, list[str]] = gdf.groupby("Gmina")["Name"].apply(list).to_dict()

    dissolved = gdf.dissolve(by="Gmina").reset_index()[["Gmina", "geometry"]]
    dissolved["geometry"] = dissolved["geometry"].make_valid()
    dissolved = dissolved[
        dissolved["geometry"].notna() &
        dissolved["geometry"].geom_type.isin(["Polygon", "MultiPolygon"])
    ]
    dissolved["n_kodow"] = dissolved["Gmina"].map(lambda g: len(mapping[g]))

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
) -> folium.Map:
    """
    Mapa z poligonami gmin.
    selected — zbiór nazw gmin (uppercase) aktualnie zaznaczonych.
    Kliknięcie zwraca nazwę gminy przez tooltip.
    """
    m = folium.Map(
        location=list(center),
        zoom_start=zoom,
        tiles="OpenStreetMap",
    )

    geojson = gminy_geojson
    if geojson is None:
        with open(geojson_path, encoding="utf-8") as f:
            geojson = json.load(f)

    def _style(feature):
        name = str(feature["properties"].get("Gmina", ""))
        if name in selected:
            return {
                "fillColor": "#a78bfa",
                "color": "#a78bfa",
                "weight": 2.5,
                "fillOpacity": 0.65,
            }
        color = _gmina_color(name)
        return {
            "fillColor": color,
            "color": color,
            "weight": 1.0,
            "fillOpacity": 0.25,
        }

    def _highlight(feature):
        return {
            "fillColor": "#f97316",
            "color": "#f97316",
            "weight": 2.5,
            "fillOpacity": 0.65,
        }

    geojson_layer = folium.GeoJson(
        geojson,
        name="gminy",
        style_function=_style,
        highlight_function=_highlight,
        tooltip=folium.GeoJsonTooltip(
            fields=["Gmina", "n_kodow"],
            aliases=["Gmina:", "Kodów pocztowych:"],
            style="background:#1e1e2e;color:#cdd6f4;border:none;font-size:13px",
        ),
    ).add_to(m)

    Search(
        layer=geojson_layer,
        geom_type="Polygon",
        placeholder="Szukaj gminy…",
        collapsed=False,
        search_label="Gmina",
        zoom=11,
    ).add_to(m)

    # Informacja na mapie
    info_html = """
    <div style="position:fixed;top:12px;right:12px;z-index:1000;
                background:#1e1e2e;color:#cdd6f4;padding:10px 14px;
                border-radius:8px;font-size:12px;border:1px solid #a78bfa;
                max-width:200px">
        <b style="color:#a78bfa">Jak używać</b><br>
        Kliknij gminę aby ją zaznaczyć.<br>
        Możesz wybrać wiele gmin.<br><br>
        <span style="color:#a78bfa">■</span> zaznaczona<br>
        <span style="color:#3b82f6">■</span> dostępna
    </div>
    """
    m.get_root().html.add_child(folium.Element(info_html))

    return m
