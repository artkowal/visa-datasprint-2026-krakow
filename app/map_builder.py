import folium
import json
import geopandas as gpd


def load_gminy_data(geojson_path: str) -> tuple[dict, dict[str, list[str]]]:
    """
    Wczytuje GeoJSON kodów pocztowych i scala poligony po gminie.
    Zwraca: (geojson_dict_gminy, {gmina: [kody_pocztowe]})
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

    geojson = json.loads(dissolved.to_json())
    return geojson, mapping


def build_map(geojson_path: str, selected: set[str], gminy_geojson: dict | None = None) -> folium.Map:
    """
    Mapa z poligonami gmin.
    selected — zbiór nazw gmin (uppercase) aktualnie zaznaczonych.
    Kliknięcie zwraca nazwę gminy przez tooltip.
    """
    m = folium.Map(
        location=[52.0, 19.5],
        zoom_start=6,
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
                "fillOpacity": 0.55,
            }
        return {
            "fillColor": "#3b82f6",
            "color": "#3b82f6",
            "weight": 1.2,
            "fillOpacity": 0.20,
        }

    def _highlight(feature):
        return {
            "fillColor": "#f97316",
            "color": "#f97316",
            "weight": 2.5,
            "fillOpacity": 0.65,
        }

    folium.GeoJson(
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
