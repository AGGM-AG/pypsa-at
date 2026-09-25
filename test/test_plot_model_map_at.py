# SPDX-FileCopyrightText: 2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""Unit tests for the pure helpers of scripts/pypsa-at/plot_model_map_at.py."""

import numpy as np
import pandas as pd
import pytest
from plot_model_map_at import (
    NUCLEAR_COLOR,
    aggregate_colocated_plants,
    filter_powerplants,
    fueltype_colors,
    parse_wkt_points,
    pipeline_capacity,
    scale,
    select_reported_sites,
)
from shapely.geometry import Point

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
