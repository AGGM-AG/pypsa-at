# SPDX-FileCopyrightText: 2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""Integration test for recalibrated heat demand loads."""

import pandas as pd
import pytest

from test.conftest import require_config


def test_heat_loads_match_recalibrated_input(nc):
    apply_at_demand = require_config(nc, "demand", "heat", "apply_at_demand")
    if not apply_at_demand:
        pytest.skip("No at heat demand applied.")
    for year, network in nc.networks.items():
        demand = pd.DataFrame.from_dict(network.meta["resources"]["heat_demand_nea_at"])
        expected = (
            demand[demand["year"].eq(int(year))]
            .groupby(["region", "carrier"])["value"]
            .sum()
        )

        regions = network.loads.bus.map(network.buses.location).fillna(
            network.loads.bus
        )
        weights = network.snapshot_weightings["generators"]
        actual = network.loads.p_set * weights.sum()
        dynamic = network.loads_t.p_set.mul(weights, axis=0).sum()
        actual.loc[dynamic.index] = dynamic
        actual = actual.groupby([regions, network.loads.carrier]).sum()
        actual = actual.reindex(expected.index).fillna(0)

        pd.testing.assert_series_equal(
            actual,
            expected,
            check_names=False,
            check_exact=False,
            rtol=1e-6,
            atol=1e-6,
        )
