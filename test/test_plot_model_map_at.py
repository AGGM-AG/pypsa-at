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
    aggm_corridor_capacity,
    apply_aggm_capacities,
    assign_corridors,
    corridor_key,
    fill_hotmaps_emissions,
    filter_powerplants,
    fueltype_colors,
    parse_wkt_points,
    scale,
)
from shapely.geometry import Point, box


@pytest.fixture
def bus_regions() -> gpd.GeoDataFrame:
    """Three unit squares side by side: AT1 | AT2 | DE."""
    return gpd.GeoDataFrame(
        {"name": ["AT1", "AT2", "DE"]},
        geometry=[box(0, 0, 1, 1), box(1, 0, 2, 1), box(2, 0, 3, 1)],
        crs="EPSG:4326",
    ).set_index("name")


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


# --- corridor matching -------------------------------------------------------


def test_corridor_key_ignores_direction():
    assert corridor_key("DE", "AT1") == corridor_key("AT1", "DE") == "AT1 <-> DE"


def test_assign_corridors_locates_both_ends(bus_regions):
    pipes = pd.DataFrame({"point0": ["POINT (0.5 0.5)"], "point1": ["POINT (2.5 0.5)"]})
    out = assign_corridors(pipes, bus_regions)
    assert out.loc[0, ["bus0", "bus1"]].tolist() == ["AT1", "DE"]
    assert out.loc[0, "corridor"] == "AT1 <-> DE"


def test_assign_corridors_leaves_outside_points_unassigned(bus_regions):
    pipes = pd.DataFrame({"point0": ["POINT (0.5 0.5)"], "point1": ["POINT (9 9)"]})
    out = assign_corridors(pipes, bus_regions)
    assert pd.isna(out.loc[0, "bus1"])
    assert pd.isna(out.loc[0, "corridor"])


def test_assign_corridors_marks_intra_region_pipes_without_corridor(bus_regions):
    pipes = pd.DataFrame({"point0": ["POINT (0.2 0.5)"], "point1": ["POINT (0.8 0.5)"]})
    out = assign_corridors(pipes, bus_regions)
    assert pd.isna(out.loc[0, "corridor"])


# --- AGGM capacities ---------------------------------------------------------


def make_aggm(rows) -> pd.DataFrame:
    return pd.DataFrame(
        rows, columns=["bus0", "bus1", "p_nom", "p_nom_reverse", "p_min_pu"]
    )


def test_aggm_capacity_one_way_corridor():
    aggm = make_aggm([["DE", "AT1", 100.0, np.nan, 0]])
    assert aggm_corridor_capacity(aggm).to_dict() == {"AT1 <-> DE": 100.0}


def test_aggm_capacity_bidirectional_uses_p_min_pu():
    aggm = make_aggm([["AT1", "AT2", 100.0, np.nan, -1]])
    assert aggm_corridor_capacity(aggm).to_dict() == {"AT1 <-> AT2": 100.0}


def test_aggm_capacity_takes_stronger_direction_of_summed_strands():
    aggm = make_aggm(
        [
            ["DE", "AT1", 100.0, 30.0, 0],  # forward 100, reverse 30
            ["AT1", "DE", 50.0, np.nan, 0],  # reverse direction strand: 50
        ]
    )
    # DE->AT1: 100, AT1->DE: 30 + 50 = 80
    assert aggm_corridor_capacity(aggm).to_dict() == {"AT1 <-> DE": 100.0}


def test_aggm_capacity_reverse_can_dominate():
    aggm = make_aggm([["DE", "AT1", 10.0, 30.0, 0], ["AT1", "DE", 50.0, np.nan, 0]])
    assert aggm_corridor_capacity(aggm).to_dict() == {"AT1 <-> DE": 80.0}


def make_pipes(rows) -> pd.DataFrame:
    return pd.DataFrame(
        rows, columns=["bus0", "bus1", "corridor", "p_nom", "p_nom_diameter"]
    )


def test_apply_aggm_splits_in_proportion_to_upstream_capacity():
    pipes = make_pipes(
        [
            ["AT1", "DE", "AT1 <-> DE", 100.0, 1.0],
            ["DE", "AT1", "AT1 <-> DE", 300.0, 1.0],
        ]
    )
    out, _ = apply_aggm_capacities(pipes, pd.Series({"AT1 <-> DE": 800.0}))
    assert out["p_nom_map"].tolist() == [200.0, 600.0]
    assert (out["status"] == "aggm").all()


def test_apply_aggm_fills_missing_upstream_with_diameter_capacity():
    pipes = make_pipes([["AT1", "DE", "AT1 <-> DE", np.nan, 50.0]])
    out, _ = apply_aggm_capacities(pipes, pd.Series(dtype=float))
    assert out.loc[0, "p_nom_map"] == 50.0


def test_apply_aggm_splits_equally_without_upstream_capacity():
    pipes = make_pipes(
        [
            ["AT1", "DE", "AT1 <-> DE", np.nan, np.nan],
            ["AT1", "DE", "AT1 <-> DE", np.nan, np.nan],
        ]
    )
    out, _ = apply_aggm_capacities(pipes, pd.Series({"AT1 <-> DE": 800.0}))
    assert out["p_nom_map"].tolist() == [400.0, 400.0]


def test_apply_aggm_flags_at_corridor_without_aggm_value():
    pipes = make_pipes([["AT1", "AT2", "AT1 <-> AT2", 70.0, 1.0]])
    out, _ = apply_aggm_capacities(pipes, pd.Series({"AT1 <-> DE": 800.0}))
    assert out.loc[0, "status"] == "not_in_model"
    assert out.loc[0, "p_nom_map"] == 70.0


def test_apply_aggm_keeps_foreign_and_intra_region_pipes_upstream():
    pipes = make_pipes(
        [
            ["DE", "CH", "CH <-> DE", 70.0, 1.0],
            ["AT1", "AT1", np.nan, 20.0, 1.0],
        ]
    )
    out, _ = apply_aggm_capacities(pipes, pd.Series({"AT1 <-> DE": 800.0}))
    assert out["status"].tolist() == ["upstream", "upstream"]
    assert out["p_nom_map"].tolist() == [70.0, 20.0]


def test_apply_aggm_returns_corridors_without_geometry():
    pipes = make_pipes([["AT1", "DE", "AT1 <-> DE", 10.0, 1.0]])
    aggm = pd.Series({"AT1 <-> DE": 800.0, "AT1 <-> AT2": 50.0})
    _, missing = apply_aggm_capacities(pipes, aggm)
    assert missing.to_dict() == {"AT1 <-> AT2": 50.0}


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
