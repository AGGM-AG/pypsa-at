# SPDX-FileCopyrightText: 2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""Integration tests for annual demand overrides."""

import pandas as pd

from test.conftest import require_config


def test_annual_industry_loads_match_input(nc):
    """Compare annual network Load energy with the prepared override input."""
    override_config = require_config(
        nc, "industry", "annual_demand_overrides", enable=False
    )
    carrier_mapping = require_config(nc, "demand", "carrier_to_load_mapping")

    target_years = {str(year) for year in override_config["target_years"]}
    checked = False

    for year, network in nc.networks.items():
        if str(year) not in target_years:
            continue

        overrides = pd.DataFrame.from_dict(
            network.meta["resources"]["industrial_demand_overrides"]
        )
        overrides = overrides[overrides["year"].eq(int(year))].copy()
        overrides["load_carrier"] = [
            carrier_mapping[sector][carrier]
            for sector, carrier in zip(overrides["sector"], overrides["carrier"])
        ]
        expected = overrides.groupby(["region", "load_carrier"])["value_TWh"].sum()

        regions = network.loads.bus.map(network.buses.location).fillna(
            network.loads.bus
        )
        weights = network.snapshot_weightings["generators"]
        actual = network.loads.p_set * weights.sum()
        dynamic = network.loads_t.p_set.mul(weights, axis=0).sum()
        actual.loc[dynamic.index] = dynamic
        actual = actual.groupby([regions, network.loads.carrier]).sum() / 1e6

        pd.testing.assert_series_equal(
            actual.reindex(expected.index),
            expected,
            check_names=False,
            check_exact=False,
            rtol=1e-6,
            atol=1e-6,
        )
        checked = True

    assert checked, f"No network found for configured target years {target_years}."
