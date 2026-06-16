# SPDX-FileCopyrightText: 2023-2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""Integration tests for mods/network/gas.py — gas storage capacity overrides."""

import pandas as pd
import pytest

from evals.utils import filter_by
from mods.clustering.utils import _map_at_nuts3_to_nuts2, _map_de_nuts1_to_de5
from mods.network.gas import _TANAP_PIPELINE_CAPACITY
from test.conftest import require_config


def test_gas_storage_update(nc, project_root, is_testrun):
    """
    Verify input data values in solve networks.

    Parameters
    ----------
    nc
        The solved networks.
    """
    file_name = "gas_input_locations_s_AT35DE16_updated.csv"
    file_path = project_root / "data" / "pypsa-at" / file_name
    expected = pd.read_csv(file_path, index_col=0)["storage update (GWh)"]
    expected = expected.dropna().mul(1e3)
    expected = expected[expected > 0]
    # aggregate update values depending on custom clustering
    clustering = require_config(nc, "mods", "modify_nuts3_shapes")
    if clustering.startswith("AT10"):
        expected = expected.groupby(expected.index.map(_map_at_nuts3_to_nuts2)).sum()
    if clustering.endswith("DE5"):
        expected = expected.groupby(expected.index.map(_map_de_nuts1_to_de5)).sum()

    gas_storage_capacity = nc.statistics.optimal_capacity(
        groupby="location",
        components="Store",
        bus_carrier="gas",
    )

    # align indices for CI regions
    if is_testrun:
        model_locations = list(gas_storage_capacity.index.unique("location"))
        expected = filter_by(expected, Region=model_locations)

    expected_store_names = {f"{loc} gas Store" for loc in expected.index}

    for year, n in nc.networks.items():
        gas_stores = n.stores.query("carrier == 'gas'")
        # All gas stores are non-extendable
        assert not gas_stores["e_nom_extendable"].any()
        # Only the expected gas Stores exist
        assert set(gas_stores.index) == expected_store_names
        pd.testing.assert_series_equal(
            gas_storage_capacity[year], expected, rtol=1e-03, check_names=False
        )


@pytest.mark.parametrize("block_name", ["eastern_border_block", "turkstream_block"])
def test_block_russian_gas_imports(nc, block_name):
    """
    Verify blockade of Russian gas imports functionality for all years.
    Find country based generators that should be turned off, assert that they are.

    Parameters
    ----------
    nc
        The solved networks.
    block_name
        name of each corridor that can be blocked.
    """
    corridors = require_config(nc, "mods", "block_russian_gas_imports", enable=False)
    model_countries = require_config(nc, "countries")

    block_config = corridors[block_name]
    if block_config is None:
        pytest.skip(f"No block config for {block_name}, skipping")

    config_countries = block_config.get("countries", [])
    assert config_countries, "No countries in config."

    start_year = block_config["start_year"]
    end_year = block_config.get("end_year", float("inf"))
    countries = [c for c in config_countries if c in model_countries]

    if not countries:
        pytest.skip(
            f"No countries from {block_name} blockade in modeled scope, skipping test."
        )

    for year, n in nc.networks.items():
        pyear = int(year)
        is_active = pyear >= start_year and pyear <= end_year
        if not is_active:
            continue

        for cc in countries:
            generator_name = f"{cc} gas pipeline import"
            if generator_name not in n.generators.index:
                continue
            expected_p_nom = _TANAP_PIPELINE_CAPACITY if cc == "BG" else 0
            assert n.generators.loc[generator_name, "p_nom"] == expected_p_nom, (
                f"{generator_name} p_nom expected {expected_p_nom} in {year} ({block_name})."
            )
            assert not n.generators.loc[generator_name, "p_nom_extendable"], (
                f"{generator_name} is extendable in {year} ({block_name}), despite blockade of Russian gas imports."
            )

    pipeline_supply = nc.statistics.supply(
        groupby=["network", "country", "carrier"],
        components="Generator",
        carrier="pipeline gas",
    ).pipe(filter_by, country=countries)

    for year in nc.networks:
        pyear = int(year)
        is_active = pyear >= start_year and pyear <= end_year
        if not is_active:
            continue
        supply_annual = pipeline_supply.xs(year, level="network")
        for cc in countries:
            if cc == "BG":
                # supply has no fixed value for BG, since TANAP capacity is available
                continue
            assert (supply_annual == 0).all()(
                f"Expected zero pipeline gas supply in {cc} for {year}, is {supply_annual}."
            )
