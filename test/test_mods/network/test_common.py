# SPDX-FileCopyrightText: 2023-2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""Integration tests for mods/network/common.py — load clipping and bus topology invariants."""

import pandas as pd

from test.conftest import require_config


def test_no_load_supply(nc):
    """
    Verify that no Load components supply energy to buses. Ever.

    The ``process emissions`` carrier is excluded: PyPSA-Eur models exogenous
    industrial CO2 emissions as a Load with negative ``p_set`` on a CO2 bus
    (``unit="t_co2"``), so that ``-p_set`` injects positive flow representing
    emissions. This is an upstream design pattern, not energy supply, but
    ``statistics.supply`` cannot distinguish the bus unit and reports it.
    See ``scripts/prepare_sector_network.py`` (upstream) for the construction.
    """
    load_supply = nc.statistics.supply(
        components="Load", groupby=["location", "carrier"]
    )
    load_supply = load_supply.drop(
        "process emissions", level="carrier", errors="ignore"
    )

    assert load_supply.empty, (
        f"Detected node supply from Load components: {load_supply}"
    )


def test_constant_buses_topology(nc):
    """
    Needs a filter because retired technologies and their buses vanish.

    todo: docstring + explanation why this is needed
    """
    fuels = require_config(nc, "mods", "net_zero_electricity", "fuels")  # noqa
    expr = "carrier.isin(@fuels)"

    first = nc[0].buses.query(expr).index
    for n in nc[1:]:
        subsequent = n.buses.query(expr).index
        pd.testing.assert_index_equal(first, subsequent, check_order=False)
