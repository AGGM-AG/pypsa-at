# SPDX-FileCopyrightText: 2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
"""Unit tests for aggregate_by_cluster_and_country in mods/pemmdb_overwrites.py."""

import pandas as pd
import pytest

from mods.pemmdb_overwrites import aggregate_by_cluster_and_country


def _make_trajectories(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(
        rows, columns=["bus", "pypsa_eur_carrier", "p_nom_min", "p_nom_max"]
    )


@pytest.mark.unit
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


@pytest.mark.unit
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


@pytest.mark.unit
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


@pytest.mark.unit
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


@pytest.mark.unit
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


@pytest.mark.unit
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


@pytest.mark.unit
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
