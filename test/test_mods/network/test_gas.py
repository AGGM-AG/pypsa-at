# SPDX-FileCopyrightText: 2023-2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""Integration tests for mods/network/gas.py — gas storage capacity overrides."""

import pandas as pd

from evals.utils import filter_by
from mods.clustering.utils import _map_at_nuts3_to_nuts2, _map_de_nuts1_to_de5
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
