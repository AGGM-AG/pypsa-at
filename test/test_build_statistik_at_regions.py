import importlib
from types import SimpleNamespace

import geopandas as gpd
import pandas as pd
import pytest

regions = importlib.import_module("scripts.pypsa-at.build_statistik_at_regions")


@pytest.fixture
def municipality_input():
    return pd.DataFrame(
        {
            "Bundeslandkennziffer": [9.0, None, 6.0, 1.0, 2.0],
            "Bundesland": [
                "Wien",
                None,
                "Steiermark",
                "Burgenland",
                "Kärnten",
            ],
            "NUTS3-Code": [
                "AT130",
                None,
                "AT221",
                "AT111",
                "AT211",
            ],
            "NUTS3": [
                "Wien",
                None,
                "Graz",
                "Mittelburgenland",
                "Klagenfurt",
            ],
            "Kennziffer Bezirk": [900.0, None, 601.0, 101.0, 201.0],
            "Name Bezirk": [
                "Wien",
                None,
                "Graz",
                "Eisenstadt",
                "Klagenfurt",
            ],
            "Gerichtsbezirks kennziffer": [
                "9001",
                "9001",
                "6011",
                None,
                "2011, 2012",
            ],
            "Gerichtsbezirksname": [
                "Wien",
                None,
                "Graz",
                "Eisenstadt",
                "Klagenfurt",
            ],
            "Gemeinde kennziffer": [
                90001,
                90002,
                60101,
                10101,
                20101,
            ],
            "Gemeindename": [
                "Gemeinde A",
                "Gemeinde B",
                "Gemeinde C",
                "Excluded A",
                "Excluded B",
            ],
            "PLZ Gemeindeamt": [1010, 1020, 8010, 7000, 9000],
            "Bevölkerungszahl 01.01.2025": [
                "100",
                "200",
                "300",
                "400",
                "500",
            ],
        }
    )


@pytest.fixture
def expected_municipalities():
    return pd.DataFrame(
        {
            "federal_state_code": [9.0, 9.0, 6.0],
            "federal_state": ["Wien", "Wien", "Steiermark"],
            "nuts3_code": ["AT130", "AT130", "AT221"],
            "nuts3_name": ["Wien", "Wien", "Graz"],
            "district_code": [900.0, 900.0, 601.0],
            "district_name": ["Wien", "Wien", "Graz"],
            "Gerichtsbezirks kennziffer": [
                "9001",
                "9001",
                "6011",
            ],
            "district_name_judicial": ["Wien", "Wien", "Graz"],
            "municipality_code": [90001, 90002, 60101],
            "municipality_name": [
                "Gemeinde A",
                "Gemeinde B",
                "Gemeinde C",
            ],
            "postal_code": [1010, 1020, 8010],
            "population": [100, 200, 300],
        }
    )


@pytest.fixture
def municipality_file(tmp_path, municipality_input):
    path = tmp_path / "municipalities.ods"

    with pd.ExcelWriter(path, engine="odf") as writer:
        municipality_input.to_excel(
            writer,
            sheet_name="Gemeinden",
            index=False,
        )

    return path


@pytest.fixture
def municipalities(municipality_file):
    return regions.read_municipalities(municipality_file)


def test_main_rejects_unsupported_base_year():
    snakemake = SimpleNamespace(
        params=SimpleNamespace(planning_horizons=[2030]),
    )

    with pytest.raises(NotImplementedError, match="2030"):
        regions.main(snakemake)


def test_read_municipalities(
    municipalities,
    expected_municipalities,
):
    pd.testing.assert_frame_equal(
        municipalities,
        expected_municipalities,
    )


def test_add_nuts2_code(
    tmp_path,
    municipalities,
    expected_municipalities,
):
    shapes_input = gpd.GeoDataFrame(
        {
            "level3": ["AT130", "AT130", "AT221"],
            "level2": ["AT13", "AT13", "AT22"],
        },
        geometry=gpd.points_from_xy(
            [16.37, 16.38, 15.44],
            [48.20, 48.21, 47.07],
        ),
        crs="EPSG:4326",
    )
    shapes_file = tmp_path / "nuts3_shapes.geojson"
    shapes_input.to_file(shapes_file, driver="GeoJSON")

    expected = expected_municipalities.assign(
        nuts2_code=["AT13", "AT13", "AT22"],
    )

    result = regions.add_nuts2_code(
        municipalities,
        shapes_file,
    )

    pd.testing.assert_frame_equal(result, expected)
