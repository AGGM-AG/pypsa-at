# SPDX-FileCopyrightText: 2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""Integration tests for the Austrian road transport demand override."""

import pandas as pd
import pytest

from test.conftest import require_config


def test_bev_charger_capacity_follows_regional_car_stock(nc):
    """BEV charger capacity must be proportional to the regional car stock."""
    use_nea_demand = require_config(nc, "demand", "transport", "use_nea_demand")
    if not use_nea_demand:
        pytest.skip("Austrian road transport demand override disabled.")
    energy_totals_year = require_config(nc, "energy", "energy_totals_year")

    checked = False
    for year, network in nc.networks.items():
        transport_data = pd.DataFrame.from_dict(
            network.meta["resources"]["transport_data_at"]
        )
        cars = transport_data[
            transport_data["year"].eq(energy_totals_year)
            & transport_data["country"].str.startswith("AT")
        ].set_index("country")["number cars"]
        assert not cars.empty, "No Austrian regional car stock attached to meta."

        chargers = network.links[network.links.carrier.eq("BEV charger")]
        locations = chargers.bus0.map(network.buses.location)
        p_nom = chargers.p_nom.groupby(locations).sum()
        p_nom = p_nom[p_nom.index.str.startswith("AT")]
        if p_nom.empty or p_nom.sum() == 0:
            continue  # no electrified road transport in this horizon

        expected = cars.reindex(p_nom.index)
        assert not expected.isna().any(), (
            f"Charger nodes without car stock in {year}: "
            f"{sorted(p_nom.index[expected.isna()])}"
        )

        pd.testing.assert_series_equal(
            p_nom / p_nom.sum(),
            expected / expected.sum(),
            check_names=False,
            check_exact=False,
            rtol=1e-6,
            atol=1e-9,
        )
        checked = True

    assert checked, "No network with BEV chargers found."
