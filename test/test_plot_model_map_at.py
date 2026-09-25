# SPDX-FileCopyrightText: 2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""Unit tests for the pure helpers of scripts/pypsa-at/plot_model_map_at.py."""

import numpy as np
import pandas as pd
import pytest
from plot_model_map_at import (
    fill_hotmaps_emissions,
    filter_powerplants,
    fueltype_colors,
    parse_wkt_points,
    pipeline_capacity,
    scale,
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
        rows,
        columns=["country", "Subsector", "Emissions_ETS_2014", "Emissions_EPRTR_2014"],
    )


def test_fill_emissions_prefers_ets():
    out = fill_hotmaps_emissions(make_hotmaps([["AT", "Cement", 10.0, 99.0]]))
    assert out.loc[0, "emissions"] == 10.0
    assert not out.loc[0, "filled"]


def test_fill_emissions_falls_back_to_eprtr():
    out = fill_hotmaps_emissions(make_hotmaps([["AT", "Cement", np.nan, 99.0]]))
    assert out.loc[0, "emissions"] == 99.0
    assert not out.loc[0, "filled"]


def test_fill_emissions_uses_country_subsector_quantile():
    hotmaps = make_hotmaps(
        [
            ["AT", "Cement", 0.0, np.nan],
            ["AT", "Cement", 100.0, np.nan],
            ["AT", "Cement", np.nan, np.nan],
            ["DE", "Cement", 1e6, np.nan],  # other country must not count
            ["AT", "Glass", 1e6, np.nan],  # other subsector must not count
        ]
    )
    out = fill_hotmaps_emissions(hotmaps)
    assert out.loc[2, "emissions"] == pytest.approx(20.0)
    assert out["filled"].tolist() == [False, False, True, False, False]


def test_fill_emissions_group_without_data_stays_nan_and_filled():
    out = fill_hotmaps_emissions(make_hotmaps([["AT", "Glass", np.nan, np.nan]]))
    assert np.isnan(out.loc[0, "emissions"])
    assert out.loc[0, "filled"]


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
