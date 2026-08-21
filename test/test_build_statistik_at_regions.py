import importlib

import geopandas as gpd
import pandas as pd
from shapely.geometry import Polygon

regions = importlib.import_module("scripts.pypsa-at.build_statistik_at_regions")


def test_build_statistik_at_regions(tmp_path):
    source = tmp_path / "RegGemVz2025.ods"
    table = pd.DataFrame(
        [
            {
                "Bundeslandkennziffer": 1,
                "Bundesland": "Burgenland",
                "NUTS3-Code": "AT111",
                "NUTS3": "Mittelburgenland",
                "Kennziffer Bezirk": 108,
                "Name Bezirk": "Oberpullendorf",
                "Gemeinde kennziffer": 10801,
                "Gemeindename": "Oberpullendorf",
                "PLZ Gemeindeamt": 7350,
                "Bevölkerungszahl 01.01.2025": 3_000,
            }
        ]
    )
    with pd.ExcelWriter(source, engine="odf") as writer:
        table.to_excel(writer, sheet_name="Gemeinden", index=False)

    shapes = tmp_path / "nuts3_shapes.geojson"
    gpd.GeoDataFrame(
        {"level3": ["AT111"], "level2": ["AT11"]},
        geometry=[Polygon([(0, 0), (1, 0), (1, 1), (0, 0)])],
        crs="EPSG:4326",
    ).to_file(shapes, driver="GeoJSON")

    result = regions.add_nuts2_code(regions.read_municipalities(source), shapes)

    assert result[regions.OUTPUT_COLUMNS].to_dict("records") == [
        {
            "federal_state_code": "1",
            "federal_state": "Burgenland",
            "nuts2_code": "AT11",
            "nuts3_code": "AT111",
            "nuts3_name": "Mittelburgenland",
            "district_code": "108",
            "district_name": "Oberpullendorf",
            "municipality_code": "10801",
            "municipality_name": "Oberpullendorf",
            "postal_code": "7350",
            "population": 3000,
        }
    ]


def test_read_municipalities_ignores_submunicipality_rows(tmp_path):
    source = tmp_path / "RegGemVz2025.ods"
    table = pd.DataFrame(
        [
            {
                "Bundeslandkennziffer": 4,
                "Bundesland": "Oberösterreich",
                "NUTS3-Code": "AT312",
                "NUTS3": "Linz-Wels",
                "Kennziffer Bezirk": 401,
                "Name Bezirk": "Stadt Linz",
                "Gemeinde kennziffer": 40101,
                "Gemeindename": "Linz",
                "PLZ Gemeindeamt": 4020,
                "Bevölkerungszahl 01.01.2025": 213557,
            },
            {
                "Bundeslandkennziffer": None,
                "Bundesland": None,
                "NUTS3-Code": None,
                "NUTS3": None,
                "Kennziffer Bezirk": None,
                "Name Bezirk": None,
                "Gemeinde kennziffer": 40101,
                "Gemeindename": "Linz",
                "PLZ Gemeindeamt": None,
                "Bevölkerungszahl 01.01.2025": 165755,
            },
        ]
    )
    with pd.ExcelWriter(source, engine="odf") as writer:
        table.to_excel(writer, sheet_name="Gemeinden", index=False)

    result = regions.read_municipalities(source)

    assert len(result) == 1
    assert result.iloc[0]["population"] == 213557
