from importlib import import_module
from types import SimpleNamespace

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box

build_heat_demand_at = import_module("scripts.pypsa-at.build_heat_demand_at")


@pytest.fixture
def heat_demand_inputs(tmp_path):
    polygons = gpd.GeoDataFrame(
        {
            "country": ["AT", "AT", "DE"],
            "level2": ["AT10", "AT10", "DE11"],
            "level3": ["AT111", "AT112", "DE111"],
            "geometry": [
                box(0, 0, 1000, 1000),
                box(1000, 0, 2000, 1000),
                box(0, 1000, 1000, 2000),
            ],
        },
        crs="EPSG:3857",
    )
    shapes = tmp_path / "shapes.geojson"
    polygons.to_file(shapes, driver="GeoJSON")

    heatmaps = []
    for year, values in {
        2021: [[0.0, 0.0], [0.1, 0.2]],
        2030: [[0.0, 0.0], [0.2, 0.4]],
        2050: [[0.0, 0.0], [0.4, 0.8]],
    }.items():
        path = tmp_path / f"heatmap_{year}.tif"
        with rasterio.open(
            path,
            "w",
            driver="GTiff",
            height=2,
            width=2,
            count=1,
            dtype="float32",
            crs="EPSG:3857",
            transform=from_origin(0, 2000, 1000, 1000),
            nodata=-9999,
        ) as raster:
            raster.write(np.array(values, dtype="float32"), 1)
        heatmaps.append(str(path))

    return shapes, heatmaps


@pytest.fixture(params=["AT10DE5", "AT35DE5"], ids=["level2", "level3"])
def snakemake(tmp_path, heat_demand_inputs, request):
    shapes, heatmaps = heat_demand_inputs
    return SimpleNamespace(
        input=SimpleNamespace(nuts3_shapes=shapes, heatmaps=heatmaps),
        params=SimpleNamespace(
            clustering=request.param,
            planning_horizons=[2025, 2030, 2040, 2050],
        ),
        output=SimpleNamespace(heat_demand=tmp_path / "heat_demand.csv"),
    )


@pytest.fixture
def expected_heat_demand(snakemake):
    if snakemake.params.clustering.startswith("AT10"):
        return pd.DataFrame(
            {
                "region": ["AT10"] * 4,
                "year": [2025, 2030, 2040, 2050],
                "value": [130 / 3, 60.0, 90.0, 120.0],
            }
        )

    return pd.DataFrame(
        {
            "region": ["AT111"] * 4 + ["AT112"] * 4,
            "year": [2025, 2030, 2040, 2050] * 2,
            "value": [130 / 9, 20.0, 30.0, 40.0, 260 / 9, 40.0, 60.0, 80.0],
        }
    )


def test_main_builds_heat_demand(snakemake, expected_heat_demand):
    build_heat_demand_at.main(snakemake)

    result = pd.read_csv(snakemake.output.heat_demand)

    pd.testing.assert_frame_equal(result, expected_heat_demand)
