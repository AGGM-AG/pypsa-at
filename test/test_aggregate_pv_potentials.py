# SPDX-FileCopyrightText: 2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""Unit tests for scripts/pypsa-at/aggregate_pv_potentials.py."""

import sys

sys.path.insert(0, "./scripts/pypsa-at")

import geopandas as gpd
import pytest
from aggregate_pv_potentials import assign_nuts_regions, process_pv_file
from shapely.geometry import box


def _make_nuts3_shapes(level2, level3, geometries, crs="EPSG:4326"):
    """Build a minimal NUTS3 shapes GeoDataFrame for test fixtures."""
    return gpd.GeoDataFrame(
        {"level2": level2, "level3": level3, "geometry": geometries},
        crs=crs,
    )


def test_assign_nuts_regions_basic():
    """Municipalities inside known NUTS3 polygons receive correct nuts3/at10 labels."""
    nuts3_shapes = _make_nuts3_shapes(
        level2=["AT11", "AT12"],
        level3=["AT111", "AT121"],
        geometries=[box(0, 0, 1, 1), box(1, 0, 2, 1)],
    )
    muni_gdf = gpd.GeoDataFrame(
        {
            "C_energy": [100.0, 200.0],
            "geometry": [box(0.1, 0.1, 0.9, 0.9), box(1.1, 0.1, 1.9, 0.9)],
        },
        crs="EPSG:4326",
    )

    result = assign_nuts_regions(muni_gdf, nuts3_shapes)

    assert result["nuts3"].tolist() == ["AT111", "AT121"]
    assert result["at10"].tolist() == ["AT11", "AT12"]


def test_assign_nuts_regions_fallback():
    """A municipality outside all NUTS3 shapes raises a ValueError."""
    nuts3_shapes = _make_nuts3_shapes(
        level2=["AT11", "AT12"],
        level3=["AT111", "AT121"],
        geometries=[box(0, 0, 1, 1), box(1, 0, 2, 1)],
    )
    # Municipality far outside the single shape; sjoin predicate="within" will yield NaN.
    muni_gdf = gpd.GeoDataFrame(
        {
            "C_energy": [75.0],
            "name": "Municipality 1",
            "geometry": [box(10, 10, 11, 11)],
        },
        crs="EPSG:4326",
    )

    with pytest.raises(ValueError):
        assign_nuts_regions(muni_gdf, nuts3_shapes)


def test_process_pv_file_writes_csvs(tmp_path):
    """process_pv_file creates correct DataFrames with expected aggregated values."""
    nuts3_shapes = _make_nuts3_shapes(
        level2=["AT11", "AT12"],
        level3=["AT111", "AT121"],
        geometries=[box(0, 0, 1, 1), box(1, 0, 2, 1)],
    )
    muni_gdf = gpd.GeoDataFrame(
        {
            "C_energy": [100.0, 200.0, 300.0],
            "geometry": [
                box(0.1, 0.1, 0.9, 0.9),
                box(1.1, 0.1, 1.4, 0.9),
                box(1.5, 0.1, 1.9, 0.9),
            ],
        },
        crs="EPSG:4326",
    )
    pv_path = tmp_path / "muni.geojson"
    muni_gdf.to_file(pv_path, driver="GeoJSON")

    nuts3_df, at10_df = process_pv_file(str(pv_path), nuts3_shapes)

    assert nuts3_df.index.name == "nuts3"
    assert at10_df.index.name == "at10"
    assert nuts3_df.loc["AT111", "C_energy"] == pytest.approx(100.0)
    assert nuts3_df.loc["AT121", "C_energy"] == pytest.approx(500.0)
    assert at10_df.loc["AT11", "C_energy"] == pytest.approx(100.0)
    assert at10_df.loc["AT12", "C_energy"] == pytest.approx(500.0)
