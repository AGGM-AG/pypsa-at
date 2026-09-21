# SPDX-FileCopyrightText: 2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""Tests for the regional KLIEN run-of-river corridor build script."""

import pandas as pd
import pytest
from build_klien_hydro_trajectory_at import (
    COLUMNS,
    KLIEN_BASE_YEAR,
    KLIEN_LAST_YEAR,
    build_regional_ror_corridor,
    interpolate_catchment_pathway,
    klien_buildout_factors,
    locate_in_regions,
    marginal_full_load_hours,
    resolve_climate_scenario,
)


@pytest.fixture
def klien() -> pd.DataFrame:
    """
    Three catchments: 100 MW today, 130 MW in 2040 and 160 MW in 2070 (medium/mocc).

    Catchment 1 grows by 10 MW at 4,000 h, catchment 2 by 20 MW at 2,000 h,
    catchment 3 not at all.
    """
    return pd.DataFrame(
        {
            "C_current": [60.0, 30.0, 10.0],
            "E_current": [300.0, 100.0, 40.0],
            "C_2040_medium_mocc": [70.0, 50.0, 10.0],
            "E_2040_medium_mocc": [340.0, 140.0, 40.0],
            "C_2070_medium_mocc": [80.0, 70.0, 10.0],
            "E_2070_medium_mocc": [380.0, 180.0, 40.0],
            "C_2040_high_stcc": [100.0, 100.0, 10.0],
            "E_2040_high_stcc": [500.0, 300.0, 40.0],
            "C_2070_high_stcc": [100.0, 100.0, 10.0],
            "E_2070_high_stcc": [500.0, 300.0, 40.0],
        },
        index=pd.Index(["1", "2", "3"], name="id"),
    )


@pytest.fixture
def catchment_regions() -> pd.DataFrame:
    """Catchment 1 lies in AT121, catchment 2 straddles AT334 (3/4) and AT335 (1/4)."""
    return pd.DataFrame(
        {
            "section": ["1", "2", "2", "3"],
            "bus": ["AT121", "AT334", "AT335", "AT130"],
            "weight": [1.0, 0.75, 0.25, 1.0],
        }
    )


@pytest.mark.parametrize(
    ("configured", "expected"),
    [("wocc", "mocc"), ("mocc", "mocc"), ("stcc", "stcc")],
)
def test_resolve_climate_scenario(configured, expected):
    assert resolve_climate_scenario(configured) == expected


def test_factors_anchor_years(klien):
    factors = klien_buildout_factors(klien, "medium", "mocc")
    assert factors.loc[KLIEN_BASE_YEAR] == 1.0
    assert factors.loc[2040] == pytest.approx(1.3)
    assert factors.loc[KLIEN_LAST_YEAR] == pytest.approx(1.6)


def test_factors_interpolate_linearly(klien):
    factors = klien_buildout_factors(klien, "medium", "mocc")
    # 2030 sits one third of the way from 2025 (1.0) to 2040 (1.3)
    assert factors.loc[2030] == pytest.approx(1.0 + 0.3 / 3)
    # 2055 sits halfway from 2040 (1.3) to 2070 (1.6)
    assert factors.loc[2055] == pytest.approx(1.45)


def test_factors_index_is_complete(klien):
    factors = klien_buildout_factors(klien, "medium", "mocc")
    assert factors.index.tolist() == list(range(KLIEN_BASE_YEAR, KLIEN_LAST_YEAR + 1))
    assert factors.notna().all()


def test_pathway_interpolates_per_catchment(klien):
    out = interpolate_catchment_pathway(
        klien, [2020, 2030, 2040, 2055, 2080], "medium", "mocc"
    )

    assert out.columns.tolist() == [2020, 2030, 2040, 2055, 2080]
    # before the base year and after the last anchor the pathway is clipped
    assert out[2020].tolist() == pytest.approx([60.0, 30.0, 10.0])
    assert out[2080].tolist() == pytest.approx([80.0, 70.0, 10.0])
    # one third of the 2025-2040 step, halfway through the 2040-2070 step
    assert out[2030].tolist() == pytest.approx([60.0 + 10.0 / 3, 30.0 + 20.0 / 3, 10.0])
    assert out[2055].tolist() == pytest.approx([75.0, 60.0, 10.0])


def test_pathway_uses_ambition_and_climate_and_quantity(klien):
    capacity = interpolate_catchment_pathway(klien, [2040], "high", "stcc")
    energy = interpolate_catchment_pathway(klien, [2040], "high", "stcc", quantity="E")
    assert capacity[2040].tolist() == pytest.approx([100.0, 100.0, 10.0])
    assert energy[2040].tolist() == pytest.approx([500.0, 300.0, 40.0])


def test_locate_in_regions_splits_by_plant_capacity_weights(catchment_regions):
    per_catchment = pd.DataFrame(
        {2040: [10.0, 20.0, 0.0]}, index=pd.Index(["1", "2", "3"], name="id")
    )

    out = locate_in_regions(per_catchment, catchment_regions)

    assert out.index.name == "region"
    assert out[2040].to_dict() == pytest.approx(
        {"AT121": 10.0, "AT334": 15.0, "AT335": 5.0, "AT130": 0.0}
    )


def test_locate_in_regions_drops_negligible_unplaced_growth(catchment_regions, caplog):
    per_catchment = pd.DataFrame(
        {2040: [10.0, 20.0, 0.02]}, index=pd.Index(["1", "2", "9"], name="id")
    )

    out = locate_in_regions(per_catchment, catchment_regions)

    assert out[2040].sum() == pytest.approx(30.0)
    assert "Dropping the increment of 1 KLIEN catchments" in caplog.text


def test_locate_in_regions_raises_for_unplaced_growth(catchment_regions):
    per_catchment = pd.DataFrame(
        {2040: [10.0, 20.0, 5.0]}, index=pd.Index(["1", "2", "9"], name="id")
    )
    with pytest.raises(ValueError, match="hold no plant"):
        locate_in_regions(per_catchment, catchment_regions)


def test_marginal_full_load_hours_per_region(klien, catchment_regions):
    out = marginal_full_load_hours(klien, catchment_regions, "medium", "mocc")

    # catchment 1: 40 GWh / 10 MW = 4,000 h; catchment 2: 40 GWh / 20 MW = 2,000 h
    assert out["AT121"] == pytest.approx(4_000.0)
    assert out["AT334"] == pytest.approx(2_000.0)
    assert out["AT335"] == pytest.approx(2_000.0)
    assert "AT130" not in out.index


@pytest.fixture
def corridor(klien, catchment_regions) -> pd.DataFrame:
    existing = pd.Series(
        {"AT121": 500.0, "AT334": 300.0, "AT335": 200.0, "AT130": 180.0, "AT111": 1.0},
        name="existing_ror_mw",
    ).rename_axis("region")
    # existing hours: AT121 6,000 h, AT334 4,500 h, AT335 1,500 h, AT130 6,000 h
    existing_flh = pd.Series(
        {"AT121": 6_000.0, "AT334": 4_500.0, "AT335": 1_500.0, "AT130": 6_000.0}
    )
    return build_regional_ror_corridor(
        klien,
        catchment_regions,
        existing,
        existing_flh,
        1.1,
        [2025, 2030, 2040, 2050],
        "medium",
        "wocc",
    )


def test_corridor_has_one_row_per_horizon_and_region(corridor):
    assert corridor.columns.tolist() == COLUMNS
    assert corridor["year"].unique().tolist() == [2025, 2030, 2040, 2050]
    assert sorted(corridor["region"].unique()) == [
        "AT111",
        "AT121",
        "AT130",
        "AT334",
        "AT335",
    ]


def test_corridor_adds_the_located_increment_to_the_existing_capacity(corridor):
    c = corridor.set_index(["year", "region"])
    # no increment in the base year: the corridor is the fleet
    assert c.loc[(2025, "AT121"), "value"] == pytest.approx(500.0)
    assert c.loc[(2025, "AT121"), "delta_c_mw"] == 0.0
    # 2040: catchment 1 (+10 MW) in AT121, catchment 2 (+20 MW) split 3:1
    assert c.loc[(2040, "AT121"), "value"] == pytest.approx(510.0)
    assert c.loc[(2040, "AT334"), "value"] == pytest.approx(315.0)
    assert c.loc[(2040, "AT335"), "value"] == pytest.approx(205.0)
    # 2030 gets one third of the 2040 step, 2050 one third of the 2040-2070 step
    assert c.loc[(2030, "AT121"), "delta_c_mw"] == pytest.approx(10.0 / 3)
    assert c.loc[(2050, "AT334"), "delta_c_mw"] == pytest.approx(15.0 + 0.75 * 20.0 / 3)
    # a region without growth keeps exactly its capacity
    assert (c.xs("AT130", level="region")["value"] == 180.0).all()
    assert (c.xs("AT111", level="region")["value"] == 1.0).all()


def test_corridor_regions_sum_to_the_national_increment(corridor, klien):
    factors = klien_buildout_factors(klien, "medium", "mocc")
    by_year = corridor.groupby("year")["delta_c_mw"].sum()
    for year in [2030, 2040, 2050]:
        assert by_year[year] == pytest.approx(
            klien["C_current"].sum() * (factors.loc[year] - 1)
        )


def test_corridor_yield_factor_caps_the_marginal_hours_at_the_existing_ones(corridor):
    c = corridor[corridor["year"] == 2040].set_index("region")
    # marginal 4,000 h x 1.1 = 4,400 h against 6,000 existing hours
    assert c.loc["AT121", "marginal_flh"] == pytest.approx(4_400.0)
    assert c.loc["AT121", "yield_factor"] == pytest.approx(4_400.0 / 6_000.0)
    # 2,000 h x 1.1 = 2,200 h against 4,500 h
    assert c.loc["AT334", "yield_factor"] == pytest.approx(2_200.0 / 4_500.0)
    # more marginal hours than the fleet has: capped at one
    assert c.loc["AT335", "yield_factor"] == 1.0
    # regions without growth or without existing hours get one
    assert c.loc["AT130", "yield_factor"] == 1.0
    assert c.loc["AT111", "yield_factor"] == 1.0
    # the yield factor is the same in every horizon
    assert corridor.groupby("region")["yield_factor"].nunique().eq(1).all()


def test_corridor_sorts_and_casts_years(klien, catchment_regions):
    out = build_regional_ror_corridor(
        klien,
        catchment_regions,
        pd.Series({"AT121": 500.0}),
        pd.Series({"AT121": 6_000.0}),
        1.0,
        ["2040", "2030"],
        "medium",
        "mocc",
    )
    assert out["year"].unique().tolist() == [2030, 2040]
    assert out["year"].dtype.kind == "i"
