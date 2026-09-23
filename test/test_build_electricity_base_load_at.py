# SPDX-FileCopyrightText: 2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""Tests for the Austrian base electricity load build script."""

import importlib

import pandas as pd
import pytest

bbl = importlib.import_module("scripts.pypsa-at.build_electricity_base_load_at")


@pytest.fixture
def population() -> pd.Series:
    return pd.Series(
        [0.2, 0.3, 0.5], index=["AT111", "AT112", "AT333"], name="population"
    )


@pytest.fixture
def energiemosaik() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "electricity for residential": [100.0, 300.0, 50.0],
            "electricity for services": [200.0, 100.0, 50.0],
            "agriculture electricity": [10.0, 30.0, 5.0],
        },
        index=["AT111", "AT112", "AT333"],
    )


def test_population_keys_for_every_carrier(population):
    keys = bbl.build_distribution_keys(population, None)
    assert set(keys.columns) == set(bbl.NEA_BASE_LOAD_SECTORS)
    for carrier in keys.columns:
        pd.testing.assert_series_equal(keys[carrier], population, check_names=False)


def test_energiemosaik_keys_override_population_except_rail(population, energiemosaik):
    keys = bbl.build_distribution_keys(population, energiemosaik)
    pd.testing.assert_frame_equal(keys[energiemosaik.columns], energiemosaik)
    pd.testing.assert_series_equal(
        keys["electricity for rail"], population, check_names=False
    )


def test_energiemosaik_keys_raise_for_missing_region(population, energiemosaik):
    with pytest.raises(ValueError, match="AT333"):
        bbl.build_distribution_keys(population, energiemosaik.drop(index="AT333"))
