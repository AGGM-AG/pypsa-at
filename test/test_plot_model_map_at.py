# SPDX-FileCopyrightText: 2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""Unit tests for the pure helpers of scripts/pypsa-at/plot_model_map_at.py."""

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from plot_model_map_at import (
    NUCLEAR_COLOR,
    aggregate_colocated_plants,
    aggregate_corridors,
    assign_to_regions,
    corridor_lines,
    filter_powerplants,
    fueltype_colors,
    parse_wkt_points,
    pie_angles,
    pipeline_capacity,
    scale,
    select_reported_sites,
    sum_by_region,
)
from shapely.geometry import LineString, Point, box

# --- geometry parsing --------------------------------------------------------


def test_parse_wkt_points_strips_srid_prefix():
    points = parse_wkt_points(pd.Series(["SRID=4326;POINT(15.1 47.2)"]))
    assert points.iloc[0].equals(Point(15.1, 47.2))


def test_parse_wkt_points_accepts_plain_wkt():
    points = parse_wkt_points(pd.Series(["POINT (1 2)"]))
    assert points.iloc[0].equals(Point(1, 2))


def test_parse_wkt_points_keeps_missing_as_none():
    points = parse_wkt_points(pd.Series(["POINT (1 2)", np.nan]))
    assert points.iloc[1] is None


# --- Hotmaps emissions -------------------------------------------------------


def make_hotmaps(rows) -> pd.DataFrame:
    return pd.DataFrame(
        rows, columns=["Subsector", "Emissions_ETS_2014", "Emissions_EPRTR_2014"]
    )


def test_reported_sites_prefer_ets():
    sites, _ = select_reported_sites(make_hotmaps([["Cement", 10.0, 99.0]]))
    assert sites["emissions"].tolist() == [10.0]


def test_reported_sites_fall_back_to_eprtr():
    sites, _ = select_reported_sites(make_hotmaps([["Cement", np.nan, 99.0]]))
    assert sites["emissions"].tolist() == [99.0]


def test_reported_sites_drop_sites_without_emissions():
    hotmaps = make_hotmaps([["Cement", 10.0, np.nan], ["Glass", np.nan, np.nan]])
    sites, _ = select_reported_sites(hotmaps)
    assert sites["Subsector"].tolist() == ["Cement"]


def test_reported_sites_count_dropped_sites_per_subsector():
    hotmaps = make_hotmaps(
        [
            ["Cement", np.nan, np.nan],
            ["Cement", np.nan, np.nan],
            ["Glass", np.nan, np.nan],
            ["Glass", 5.0, np.nan],
        ]
    )
    _, dropped = select_reported_sites(hotmaps)
    assert dropped.to_dict() == {"Cement": 2, "Glass": 1}


# --- scaling, colours, filters -----------------------------------------------


def test_scale_is_linear_to_reference():
    assert scale(pd.Series([0.0, 50.0, 100.0]), 100.0, 4.0).tolist() == [0, 2, 4]


def test_scale_caps_at_maximum():
    out = scale(pd.Series([5.0, 10.0, 40.0]), 10.0, 1.0, cap=2.0)
    assert out.tolist() == [0.5, 1.0, 2.0]


def test_pipeline_capacity_keeps_reported_p_nom():
    pipes = pd.DataFrame({"p_nom": [1500.0], "p_nom_diameter": [9999.0]})
    assert pipeline_capacity(pipes).tolist() == [1500.0]


def test_pipeline_capacity_fills_missing_with_diameter_estimate():
    pipes = pd.DataFrame({"p_nom": [np.nan], "p_nom_diameter": [700.0]})
    assert pipeline_capacity(pipes).tolist() == [700.0]


def test_fueltype_colors_maps_ppm_fueltypes_to_tech_colors():
    tech_colors = {"solar": "#f9d002", "onwind": "#235ebc", "gas": "#e05b09"}
    colors = fueltype_colors(["Solar", "Wind", "Natural Gas"], tech_colors)
    assert colors == {"Solar": "#f9d002", "Wind": "#235ebc", "Natural Gas": "#e05b09"}


def test_fueltype_colors_overrides_nuclear():
    colors = fueltype_colors(["Nuclear"], {"nuclear": "#ff8c00"})
    assert colors == {"Nuclear": NUCLEAR_COLOR}


def test_aggregate_colocated_plants_sums_same_fueltype_at_one_site():
    ppl = pd.DataFrame(
        {
            "lon": [5.2706, 5.2706, 5.2706],
            "lat": [45.7973, 45.7973, 45.7973],
            "Fueltype": ["Nuclear", "Nuclear", "Hydro"],
            "Capacity": [945.0, 917.0, 30.0],
        }
    )
    out = aggregate_colocated_plants(ppl).set_index("Fueltype")["Capacity"]
    assert out.to_dict() == {"Hydro": 30.0, "Nuclear": 1862.0}


def test_aggregate_colocated_plants_keeps_separate_sites():
    ppl = pd.DataFrame(
        {
            "lon": [10.0, 11.0],
            "lat": [47.0, 47.0],
            "Fueltype": ["Hydro", "Hydro"],
            "Capacity": [30.0, 40.0],
        }
    )
    assert len(aggregate_colocated_plants(ppl)) == 2


def test_fueltype_colors_unknown_fueltype_raises():
    with pytest.raises(KeyError, match="Unobtainium"):
        fueltype_colors(["Unobtainium"], {"solar": "#f9d002"})


def test_filter_powerplants_applies_extent_and_threshold():
    ppl = pd.DataFrame(
        {
            "lon": [10.0, 10.0, 40.0],
            "lat": [47.0, 47.0, 47.0],
            "Capacity": [30.0, 10.0, 500.0],  # last one outside extent
        }
    )
    out, share = filter_powerplants(ppl, (5, 20, 44, 52), threshold=20.0)
    assert out["Capacity"].tolist() == [30.0]
    assert share == pytest.approx(0.75)


# --- clustered maps ----------------------------------------------------------


@pytest.fixture
def regions() -> gpd.GeoDataFrame:
    """Two unit squares side by side: AT1 | DE."""
    return gpd.GeoDataFrame(
        {"name": ["AT1", "DE"]},
        geometry=[box(0, 0, 1, 1), box(1, 0, 2, 1)],
        crs="EPSG:4326",
    )


def test_assign_to_regions_finds_containing_region(regions):
    points = gpd.GeoSeries([Point(0.5, 0.5), Point(1.5, 0.5)], crs="EPSG:4326")
    assert assign_to_regions(points, regions).tolist() == ["AT1", "DE"]


def test_assign_to_regions_leaves_outside_points_missing(regions):
    points = gpd.GeoSeries([Point(5, 5)], index=[7], crs="EPSG:4326")
    out = assign_to_regions(points, regions)
    assert out.index.tolist() == [7]
    assert pd.isna(out.loc[7])


def test_sum_by_region_pivots_categories():
    df = pd.DataFrame(
        {
            "region": ["AT1", "AT1", "AT1", "DE"],
            "Fueltype": ["Hydro", "Hydro", "Wind", "Hydro"],
            "Capacity": [10.0, 5.0, 3.0, 7.0],
        }
    )
    out = sum_by_region(df, "region", "Fueltype", "Capacity")
    assert out.loc["AT1"].to_dict() == {"Hydro": 15.0, "Wind": 3.0}
    assert out.loc["DE"].to_dict() == {"Hydro": 7.0, "Wind": 0.0}


def test_sum_by_region_ignores_unassigned_rows():
    df = pd.DataFrame(
        {
            "region": ["AT1", np.nan],
            "Fueltype": ["Hydro", "Hydro"],
            "Capacity": [1.0, 9.0],
        }
    )
    out = sum_by_region(df, "region", "Fueltype", "Capacity")
    assert out.index.tolist() == ["AT1"]


def test_aggregate_corridors_sums_parallel_and_reversed_strands():
    df = pd.DataFrame(
        {
            "bus0": ["AT1", "DE", "AT1"],
            "bus1": ["DE", "AT1", "DE"],
            "p_nom": [1.0, 2.0, 4.0],
        }
    )
    out = aggregate_corridors(df, "p_nom")
    assert out.to_dict("records") == [{"bus0": "AT1", "bus1": "DE", "p_nom": 7.0}]


def test_aggregate_corridors_drops_zero_capacity():
    df = pd.DataFrame(
        {"bus0": ["AT1", "CH"], "bus1": ["DE", "DE"], "p_nom": [0.0, 5.0]}
    )
    assert aggregate_corridors(df, "p_nom")["bus0"].tolist() == ["CH"]


def test_corridor_lines_connect_bus_coordinates():
    corridors = pd.DataFrame({"bus0": ["AT1"], "bus1": ["DE"], "p_nom": [5.0]})
    buses = pd.DataFrame({"x": [0.5, 1.5], "y": [0.5, 0.5]}, index=["AT1", "DE"])
    out = corridor_lines(corridors, buses)
    assert out.geometry.iloc[0].equals(LineString([(0.5, 0.5), (1.5, 0.5)]))
    assert out["p_nom"].tolist() == [5.0]


def test_pie_angles_split_full_circle_by_share():
    angles = pie_angles(pd.Series([1.0, 3.0]))
    assert angles == [(90.0, 180.0), (180.0, 450.0)]


def test_pie_angles_skip_zero_slices():
    assert pie_angles(pd.Series([0.0, 2.0])) == [(90.0, 450.0)]
