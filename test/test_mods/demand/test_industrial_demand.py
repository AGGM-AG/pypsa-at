# SPDX-FileCopyrightText: 2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""End-to-end test for industrial demand profiles in solved networks."""

import pandas as pd

from test.conftest import require_config


def test_industrial_loads_match_profiles(nc):
    """Compare normalized solved industry Loads with the stored resource."""
    config = require_config(nc, "industry", "demand_profiles", enable=False)
    load_carriers = set(config["carrier_mapping"].values())

    for year, network in nc.networks.items():
        profiles = pd.DataFrame.from_dict(
            network.meta["resources"]["industrial_demand_profiles"]
        )
        profiles = profiles[profiles["year"].astype(str) == str(year)]
        expected = profiles.pivot(index="snapshot", columns="region", values="value")
        expected.index = pd.to_datetime(expected.index)
        expected = expected.div(expected.sum(), axis=1)

        loads = network.loads[network.loads.carrier.isin(load_carriers)]
        idx = loads[
            loads.index.map(lambda x: x.split(" ")[0]).isin(expected.columns)
        ].index
        actual = network.loads_t.p_set[idx]
        actual = actual.div(actual.sum(), axis=1)
        actual.columns = expected.columns

        pd.testing.assert_frame_equal(
            actual, expected, check_exact=False, atol=1e-9, check_names=False
        )
