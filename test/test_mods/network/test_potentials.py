# SPDX-FileCopyrightText: 2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""Unit tests for mods/network/potentials.py — PEMMDB trajectory aggregation and KLIEN regional mapping."""

import re
import sys

import pandas as pd
import pytest

from mods.network.potentials import aggregate_by_cluster_and_country

sys.path.insert(0, "./scripts/pypsa-at")

import geopandas as gpd  # noqa: E402
from build_klien_potentials import (  # noqa: E402
    map_to_nuts3_weighted,
    process_potential_file,
)
from shapely.geometry import box  # noqa: E402

# ---------------------------------------------------------------------------
# PEMMDB trajectory aggregation
# ---------------------------------------------------------------------------


def _make_trajectories(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(
        rows, columns=["bus", "pypsa_eur_carrier", "p_nom_min", "p_nom_max"]
    )


def test_basic_aggregation():
    df = _make_trajectories(
        [
            {
                "bus": "BE00",
                "pypsa_eur_carrier": "onwind",
                "p_nom_min": 10.0,
                "p_nom_max": 50.0,
            },
        ]
    )
    result = aggregate_by_cluster_and_country(df)
    assert ("BE", "onwind") in result.index
    assert result.loc[("BE", "onwind"), "p_nom_min"] == 10.0
    assert result.loc[("BE", "onwind"), "p_nom_max"] == 50.0


def test_multiple_tyndp_buses_sum_to_location():
    # NO has three TYNDP nodes: NOS0, NOM1, NON1 → all map to "NO"
    df = _make_trajectories(
        [
            {
                "bus": "NOS0",
                "pypsa_eur_carrier": "onwind",
                "p_nom_min": 100.0,
                "p_nom_max": 200.0,
            },
            {
                "bus": "NOM1",
                "pypsa_eur_carrier": "onwind",
                "p_nom_min": 50.0,
                "p_nom_max": 100.0,
            },
            {
                "bus": "NON1",
                "pypsa_eur_carrier": "onwind",
                "p_nom_min": 30.0,
                "p_nom_max": 60.0,
            },
        ]
    )
    result = aggregate_by_cluster_and_country(df)
    assert result.loc[("NO", "onwind"), "p_nom_min"] == 180.0
    assert result.loc[("NO", "onwind"), "p_nom_max"] == 360.0


def test_sub_national_location_and_country_both_present():
    # DK has DKW1 → DK0 and DKE1 → DK1; country-level DK should be their sum
    df = _make_trajectories(
        [
            {
                "bus": "DKW1",
                "pypsa_eur_carrier": "onwind",
                "p_nom_min": 40.0,
                "p_nom_max": 80.0,
            },
            {
                "bus": "DKE1",
                "pypsa_eur_carrier": "onwind",
                "p_nom_min": 20.0,
                "p_nom_max": 40.0,
            },
        ]
    )
    result = aggregate_by_cluster_and_country(df)
    assert ("DK0", "onwind") in result.index
    assert ("DK1", "onwind") in result.index
    assert ("DK", "onwind") in result.index
    assert result.loc[("DK", "onwind"), "p_nom_min"] == 60.0
    assert result.loc[("DK", "onwind"), "p_nom_max"] == 120.0


def test_skip_countries_filters_locations():
    df = _make_trajectories(
        [
            {
                "bus": "BE00",
                "pypsa_eur_carrier": "onwind",
                "p_nom_min": 10.0,
                "p_nom_max": 50.0,
            },
            {
                "bus": "FR00",
                "pypsa_eur_carrier": "onwind",
                "p_nom_min": 20.0,
                "p_nom_max": 80.0,
            },
        ]
    )
    result = aggregate_by_cluster_and_country(df, skip_countries=["FR"])
    assert ("BE", "onwind") in result.index
    assert ("FR", "onwind") not in result.index


def test_unmapped_bus_raises():
    df = _make_trajectories(
        [
            {
                "bus": "XX99",
                "pypsa_eur_carrier": "onwind",
                "p_nom_min": 0.0,
                "p_nom_max": 0.0,
            },
        ]
    )
    with pytest.raises(ValueError, match="TYNDP bus codes not in"):
        aggregate_by_cluster_and_country(df)


def test_multiple_carriers():
    df = _make_trajectories(
        [
            {
                "bus": "PL00",
                "pypsa_eur_carrier": "onwind",
                "p_nom_min": 10.0,
                "p_nom_max": 50.0,
            },
            {
                "bus": "PL00",
                "pypsa_eur_carrier": "solar rooftop",
                "p_nom_min": 5.0,
                "p_nom_max": 20.0,
            },
        ]
    )
    result = aggregate_by_cluster_and_country(df)
    assert ("PL", "onwind") in result.index
    assert ("PL", "solar rooftop") in result.index


def test_result_index_names():
    df = _make_trajectories(
        [
            {
                "bus": "CH00",
                "pypsa_eur_carrier": "onwind",
                "p_nom_min": 1.0,
                "p_nom_max": 5.0,
            },
        ]
    )
    result = aggregate_by_cluster_and_country(df)
    assert result.index.names == ["location", "pypsa_eur_carrier"]


# ---------------------------------------------------------------------------
# KLIEN regional potential mapping (scripts/pypsa-at/build_klien_potentials.py)
# ---------------------------------------------------------------------------


def _make_nuts3_shapes(level2, level3, geometries, crs="EPSG:4326"):
    """Build a minimal NUTS3 shapes GeoDataFrame for test fixtures."""
    return gpd.GeoDataFrame(
        {"level2": level2, "level3": level3, "geometry": geometries},
        crs=crs,
    )


def test_map_to_nuts3_weighted_basic():
    """Municipalities fully inside known NUTS3 polygons receive correct nuts3 labels."""
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

    result = map_to_nuts3_weighted(muni_gdf, nuts3_shapes)

    # After weighting and grouping, each municipality should map to its NUTS3 region.
    nuts3_agg = result.groupby("nuts3")["C_energy"].sum()

    assert set(nuts3_agg.index) == {"AT111", "AT121"}


@pytest.mark.parametrize(
    "geometry",
    [box(10, 10, 11, 11), box(0.5, 0.5, 10, 10)],
    ids=["zero_overlap", "partial_overlap_below_threshold"],
)
def test_map_to_nuts3_weighted_raises_value_error_for_insufficient_coverage(geometry):
    """map_to_nuts3_weighted raises ValueError when a municipality has insufficient overlap with any NUTS3 shape."""
    nuts3_shapes = _make_nuts3_shapes(
        level2=["AT11"], level3=["AT111"], geometries=[box(0, 0, 1, 1)]
    )
    muni_gdf = gpd.GeoDataFrame(
        {"C_energy": [75.0], "geometry": [geometry]}, crs="EPSG:4326"
    )
    # No match= because the error message differs between cases (missing overlap vs threshold).
    with pytest.raises(ValueError):
        map_to_nuts3_weighted(muni_gdf, nuts3_shapes)


def test_map_to_nuts3_weighted_single_region():
    """A polygon fully inside one NUTS3 region receives a weight of 1.0 (capacity unchanged)."""
    nuts3_shapes = _make_nuts3_shapes(
        level2=["AT11", "AT12"],
        level3=["AT111", "AT121"],
        geometries=[box(0, 0, 2, 2), box(2, 0, 4, 2)],
    )
    muni_gdf = gpd.GeoDataFrame(
        {
            "C_energy": [300.0],
            "geometry": [box(0.5, 0.5, 1.5, 1.5)],
        },
        crs="EPSG:4326",
    )

    result = map_to_nuts3_weighted(muni_gdf, nuts3_shapes)
    nuts3_agg = result.groupby("nuts3")["C_energy"].sum()

    assert nuts3_agg["AT111"] == pytest.approx(300.0, rel=0.01)
    assert "AT121" not in nuts3_agg or nuts3_agg.get("AT121", 0.0) == pytest.approx(
        0.0, abs=1e-6
    )


def test_map_to_nuts3_weighted_equal_split():
    """A polygon straddling two NUTS3 regions 50/50 splits capacity exactly in half."""
    nuts3_shapes = _make_nuts3_shapes(
        level2=["AT11", "AT12"],
        level3=["AT111", "AT121"],
        geometries=[box(0, 0, 1, 2), box(1, 0, 2, 2)],
    )
    muni_gdf = gpd.GeoDataFrame(
        {
            "C_energy": [200.0],
            "geometry": [box(0, 0, 2, 2)],
        },
        crs="EPSG:4326",
    )

    result = map_to_nuts3_weighted(muni_gdf, nuts3_shapes)
    nuts3_agg = result.groupby("nuts3")["C_energy"].sum()

    assert nuts3_agg["AT111"] == pytest.approx(100.0, rel=0.01)
    assert nuts3_agg["AT121"] == pytest.approx(100.0, rel=0.01)


def test_map_to_nuts3_weighted_unequal_split():
    """A polygon covering 1/1.3 of AT111 and 0.3/1.3 of AT121 splits proportionally."""
    nuts3_shapes = _make_nuts3_shapes(
        level2=["AT11", "AT12"],
        level3=["AT111", "AT121"],
        geometries=[box(0, 0, 1, 2), box(1, 0, 2, 2)],
    )
    muni_gdf = gpd.GeoDataFrame(
        {
            "C_energy": [100.0],
            "geometry": [box(0, 0, 1.3, 2)],
        },
        crs="EPSG:4326",
    )

    result = map_to_nuts3_weighted(muni_gdf, nuts3_shapes)
    nuts3_agg = result.groupby("nuts3")["C_energy"].sum()

    assert nuts3_agg["AT111"] == pytest.approx(100 * 1.0 / 1.3, rel=0.02)
    assert nuts3_agg["AT121"] == pytest.approx(100 * 0.3 / 1.3, rel=0.02)


def test_map_to_nuts3_weighted_almost_entirely_inside_does_not_raise():
    """A municipality whose overlapping area covers ≥ the minimum weight threshold must not raise — polygon just inside a single NUTS3 shape."""
    nuts3_shapes = _make_nuts3_shapes(
        level2=["AT11"],
        level3=["AT111"],
        geometries=[box(0, 0, 1, 1)],
    )
    muni_gdf = gpd.GeoDataFrame(
        {
            "C_energy": [42.0],
            "geometry": [box(0.01, 0.01, 0.99, 0.99)],
        },
        crs="EPSG:4326",
    )

    # Should not raise; polygon is strictly inside the single NUTS3 shape.
    result = map_to_nuts3_weighted(muni_gdf, nuts3_shapes)
    nuts3_agg = result.groupby("nuts3")["C_energy"].sum()
    assert nuts3_agg["AT111"] == pytest.approx(42.0, rel=0.01)


def test_process_potential_file_aggregates_multiple_municipalities_into_nuts3(
    tmp_path,
):
    """process_potential_file sums multiple municipalities within the same NUTS3 region."""
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
    potential_path = tmp_path / "muni.geojson"
    muni_gdf.to_file(potential_path, driver="GeoJSON")

    nuts3_df = process_potential_file(str(potential_path), nuts3_shapes)

    assert nuts3_df.index.name == "nuts3"
    assert nuts3_df.loc["AT111", "C_energy"] == pytest.approx(100.0, rel=0.01)
    assert nuts3_df.loc["AT121", "C_energy"] == pytest.approx(500.0, rel=0.01)


def test_map_to_nuts3_weighted_non_at_fragment_redirected():
    """
    Non-AT overlay fragments are redirected to the nearest AT NUTS3 region — full input capacity is conserved.

    A municipality straddling an AT/non-AT boundary (50 % in each) must have its
    non-AT fragment reassigned to the nearest AT region so that:
    - No non-AT code appears in the result.
    - The full input capacity is conserved in AT111.
    """
    nuts3_shapes = _make_nuts3_shapes(
        level2=["AT11", "DE12"],
        level3=["AT111", "DE123"],
        geometries=[box(0, 0, 2, 2), box(2, 0, 4, 2)],
    )
    # Polygon spans x=[1,3], crossing the AT/DE boundary at x=2; 50 % in each region.
    muni_gdf = gpd.GeoDataFrame(
        {
            "C_energy": [200.0],
            "geometry": [box(1, 0, 3, 2)],
        },
        crs="EPSG:4326",
    )

    result = map_to_nuts3_weighted(muni_gdf, nuts3_shapes)
    nuts3_agg = result.groupby("nuts3")["C_energy"].sum()

    # The non-AT fragment must have been redirected; DE123 must not appear.
    assert "DE123" not in nuts3_agg.index
    # All capacity (both the native AT fragment and the redirected DE fragment) ends up in AT111.
    assert nuts3_agg["AT111"] == pytest.approx(200.0, rel=0.01)


def test_map_to_nuts3_weighted_non_at_fragment_redirected_to_nearest():
    """
    A non-AT fragment is redirected to the geometrically nearest AT NUTS3 region using nearest-neighbour selection.

    Two AT regions exist at different distances from the non-AT fragment centroid.
    The redirect must choose AT121 (adjacent, boundary at x=2) over AT111 (farther,
    boundary at x=1) — confirming nearest-neighbour logic, not arbitrary assignment.
    """
    nuts3_shapes = _make_nuts3_shapes(
        level2=["AT11", "AT12", "DE12"],
        level3=["AT111", "AT121", "DE123"],
        geometries=[box(0, 0, 1, 2), box(1, 0, 2, 2), box(2, 0, 4, 2)],
    )
    # Polygon lies entirely inside DE123; weight sum ≈ 1.0 so the sanity check passes,
    # then the single fragment (level3="DE123") is redirected to the nearest AT region.
    # Fragment centroid x≈2.5; AT121 boundary at x=2 (distance ≈0.5) vs AT111 at x=1 (≈1.5).
    muni_gdf = gpd.GeoDataFrame(
        {
            "C_energy": [100.0],
            "geometry": [box(2, 0, 3, 2)],
        },
        crs="EPSG:4326",
    )

    result = map_to_nuts3_weighted(muni_gdf, nuts3_shapes)
    nuts3_agg = result.groupby("nuts3")["C_energy"].sum()

    assert "DE123" not in nuts3_agg.index
    assert "AT111" not in nuts3_agg.index
    assert nuts3_agg["AT121"] == pytest.approx(100.0, rel=0.01)


def test_process_potential_file_raises_when_no_c_prefix_columns(tmp_path):
    """process_potential_file raises ValueError naming the file path when no C_ columns exist."""
    nuts3_shapes = _make_nuts3_shapes(
        level2=["AT11", "AT12"],
        level3=["AT111", "AT121"],
        geometries=[box(0, 0, 1, 1), box(1, 0, 2, 1)],
    )
    muni_gdf = gpd.GeoDataFrame(
        {
            "name": ["Muni A", "Muni B"],
            "geometry": [box(0.1, 0.1, 0.9, 0.9), box(1.1, 0.1, 1.9, 0.9)],
        },
        crs="EPSG:4326",
    )
    potential_path = tmp_path / "no_c_cols.geojson"
    muni_gdf.to_file(potential_path, driver="GeoJSON")

    with pytest.raises(ValueError, match=re.escape(str(potential_path))):
        process_potential_file(str(potential_path), nuts3_shapes)


def test_map_to_nuts3_weighted_multiple_c_columns():
    """map_to_nuts3_weighted distributes all C_ columns independently by area weight."""
    nuts3_shapes = _make_nuts3_shapes(
        level2=["AT11", "AT12"],
        level3=["AT111", "AT121"],
        geometries=[box(0, 0, 1, 1), box(1, 0, 2, 1)],
    )
    muni_gdf = gpd.GeoDataFrame(
        {
            "C_2030_low_wocc": [100.0, 300.0],
            "C_2040_high_stcc": [200.0, 400.0],
            "geometry": [box(0.1, 0.1, 0.9, 0.9), box(1.1, 0.1, 1.9, 0.9)],
        },
        crs="EPSG:4326",
    )

    result = map_to_nuts3_weighted(muni_gdf, nuts3_shapes)

    nuts3_agg = result.groupby("nuts3")[["C_2030_low_wocc", "C_2040_high_stcc"]].sum()

    assert nuts3_agg.loc["AT111", "C_2030_low_wocc"] == pytest.approx(100.0, rel=0.01)
    assert nuts3_agg.loc["AT111", "C_2040_high_stcc"] == pytest.approx(200.0, rel=0.01)
    assert nuts3_agg.loc["AT121", "C_2030_low_wocc"] == pytest.approx(300.0, rel=0.01)
    assert nuts3_agg.loc["AT121", "C_2040_high_stcc"] == pytest.approx(400.0, rel=0.01)


def test_map_to_nuts3_weighted_error_names_offending_index():
    """ValueError message contains the offending original index when weight sum < threshold."""
    nuts3_shapes = _make_nuts3_shapes(
        level2=["AT11"],
        level3=["AT111"],
        geometries=[box(0, 0, 1, 1)],
    )
    # Polygon entirely outside the single NUTS3 shape → weight sum = 0.
    muni_gdf = gpd.GeoDataFrame(
        {
            "C_energy": [50.0],
            "geometry": [box(10, 10, 11, 11)],
        },
        crs="EPSG:4326",
    )

    with pytest.raises(ValueError, match=r"municipality index.*\[0\]"):
        map_to_nuts3_weighted(muni_gdf, nuts3_shapes)
