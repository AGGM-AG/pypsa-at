# SPDX-FileCopyrightText: 2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""Tests for the KLIEN-scaled AT run-of-river corridor build script."""

import pandas as pd
import pytest
from build_klien_hydro_trajectory_at import (
    KLIEN_BASE_YEAR,
    KLIEN_LAST_YEAR,
    build_klien_ror_trajectory,
    klien_buildout_factors,
    resolve_climate_scenario,
)


@pytest.fixture
def klien() -> pd.DataFrame:
    """Two catchments: 100 MW today, 120 MW in 2040 and 150 MW in 2070 (medium/mocc)."""
    return pd.DataFrame(
        {
            "id": [1, 2],
            "C_current": [60.0, 40.0],
            "C_2040_medium_mocc": [70.0, 50.0],
            "C_2070_medium_mocc": [90.0, 60.0],
            "C_2040_high_stcc": [100.0, 100.0],
            "C_2070_high_stcc": [100.0, 100.0],
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
    assert factors.loc[2040] == pytest.approx(1.2)
    assert factors.loc[KLIEN_LAST_YEAR] == pytest.approx(1.5)


def test_factors_interpolate_linearly(klien):
    factors = klien_buildout_factors(klien, "medium", "mocc")
    # 2030 sits one third of the way from 2025 (1.0) to 2040 (1.2)
    assert factors.loc[2030] == pytest.approx(1.0 + 0.2 / 3)
    # 2055 sits halfway from 2040 (1.2) to 2070 (1.5)
    assert factors.loc[2055] == pytest.approx(1.35)


def test_factors_index_is_complete(klien):
    factors = klien_buildout_factors(klien, "medium", "mocc")
    assert factors.index.tolist() == list(range(KLIEN_BASE_YEAR, KLIEN_LAST_YEAR + 1))
    assert factors.notna().all()


def test_factors_use_ambition_and_climate(klien):
    factors = klien_buildout_factors(klien, "high", "stcc")
    assert factors.loc[2040] == pytest.approx(2.0)


def test_corridor_scales_brownfield(klien):
    out = build_klien_ror_trajectory(
        klien, 1000.0, [2025, 2030, 2040, 2050], "medium", "mocc"
    )
    assert out.index.name == "year"
    assert out.index.tolist() == [2025, 2030, 2040, 2050]
    assert list(out.columns) == ["factor", "brownfield_mw", "value"]
    assert (out["brownfield_mw"] == 1000.0).all()
    assert out.loc[2025, "value"] == pytest.approx(1000.0)
    assert out.loc[2040, "value"] == pytest.approx(1200.0)
    assert out.loc[2050, "value"] == pytest.approx(1300.0)


def test_corridor_clips_years_outside_study_range(klien):
    out = build_klien_ror_trajectory(klien, 1000.0, [2020, 2080], "medium", "mocc")
    assert out.loc[2020, "factor"] == 1.0
    assert out.loc[2080, "factor"] == pytest.approx(1.5)


def test_corridor_sorts_and_casts_years(klien):
    out = build_klien_ror_trajectory(klien, 1000.0, ["2040", "2030"], "medium", "mocc")
    assert out.index.tolist() == [2030, 2040]


def test_corridor_wocc_falls_back_to_mocc(klien):
    wocc = build_klien_ror_trajectory(klien, 1000.0, [2040], "medium", "wocc")
    mocc = build_klien_ror_trajectory(klien, 1000.0, [2040], "medium", "mocc")
    assert wocc.compare(mocc).empty
