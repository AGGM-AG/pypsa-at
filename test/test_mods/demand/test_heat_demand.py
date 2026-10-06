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


def _heat_network():
    """Two-snapshot network with a dynamic, an all-zero and a static heat load."""
    import pypsa

    n = pypsa.Network()
    n.set_snapshots(pd.date_range("2030-01-01", periods=2, freq="h"))
    n.snapshot_weightings.loc[:, :] = 2.0
    for carrier in ("urban central heat", "urban decentral heat", "rural heat"):
        bus = f"AT211 {carrier}"
        n.add("Bus", bus, location="AT211", carrier=carrier)
        n.add("Load", bus, bus=bus, carrier=carrier)
    n.loads_t.p_set = pd.DataFrame(
        {
            "AT211 urban central heat": [1.0, 3.0],
            "AT211 urban decentral heat": [0.0, 0.0],
        },
        index=n.snapshots,
    )
    return n


def test_apply_heat_demand_scales_profiles_and_fills_zero_profiles(tmp_path):
    """Targets are met for scaled, all-zero (upstream) and static loads."""
    from types import SimpleNamespace

    from mods.demand.heat_demand import apply_heat_demand

    targets = pd.DataFrame(
        {
            "year": 2030,
            "region": "AT211",
            "carrier": ["urban central heat", "urban decentral heat", "rural heat"],
            "value": [80.0, 40.0, 20.0],
        }
    )
    path = tmp_path / "heat_demand_nea_at.csv"
    targets.to_csv(path, index=False)
    snakemake = SimpleNamespace(
        params=SimpleNamespace(apply_at_heat_demand=True),
        wildcards=SimpleNamespace(horizon="2030"),
        input=SimpleNamespace(heat_demand_nea_at=path),
    )

    n = _heat_network()
    apply_heat_demand(n, snakemake)

    weights = n.snapshot_weightings.generators
    actual = n.loads.p_set * weights.sum()
    dynamic = n.loads_t.p_set.mul(weights, axis=0).sum()
    actual.loc[dynamic.index] = dynamic
    expected = targets.set_index("carrier")["value"].rename(lambda c: f"AT211 {c}")

    pd.testing.assert_series_equal(
        actual.loc[expected.index],
        expected,
        check_names=False,
        check_index_type=False,
    )
    # the shape of the scaled profile is kept, the all-zero profile is dropped
    assert n.loads_t.p_set["AT211 urban central heat"].tolist() == [10.0, 30.0]
    assert "AT211 urban decentral heat" not in n.loads_t.p_set.columns
