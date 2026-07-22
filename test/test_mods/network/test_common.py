# SPDX-FileCopyrightText: 2023-2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""Integration tests for mods/network/common.py — load clipping and bus topology invariants."""

import pandas as pd
from pypsa.statistics import get_transmission_carriers

from evals.utils import get_location
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


def test_one_vintage_asset_per_build_year(nc):
    """
    Each sited asset is unique in ``(component, location, carrier, build_year)``.

    PyPSA-AT represents brownfield capacity as one non-extendable *vintage* per
    ``(location, carrier, build_year)``. Several mods rely on this — e.g.
    ``register_extendable_nuclear`` picks the newest vintage per location with
    ``build_year.idxmax()``, which is only well-defined when no two vintages of a
    location share a build year. This guards that invariant against regressions.

    Transport assets are excluded: they are not sited at a single location and
    legitimately repeat an endpoint location.

    * ``Line`` components (parallel AC circuits),
    * transmission-carrier branches (pipelines, DC, ... per
      :func:`get_transmission_carriers`) and their ``-reversed`` transport twins
      (e.g. ``electricity distribution grid``, which crosses voltage levels and
      so is missed by :func:`get_transmission_carriers`),
    * carriers in ``MULTI_VARIANT_CARRIERS`` that legitimately host several assets
      per location (``DAC`` per heat sector; ``import H2`` per route / cost tier),
    * ``EU`` global conversion assets.
    """
    # Carriers that, by design, place more than one asset at the same location and
    # are therefore exempt from the per-location uniqueness check:
    #   * ``DAC`` — one unit per heat sector (urban central + urban decentral),
    #   * ``import H2`` — one generator per import route / cost tier (LOW/HIGH).
    multi_variant_carriers = {"DAC", "import H2"}

    for n in nc:
        transmission = set(get_transmission_carriers(n).get_level_values("carrier"))

        assets = []
        for c in n.all_components:
            static = n.components[c].static
            if c == "Line" or static.empty or "build_year" not in static.columns:
                continue
            assets.append(
                pd.DataFrame(
                    {
                        "component": c,
                        "location": get_location(n, c).to_numpy(),
                        "carrier": static["carrier"].to_numpy(),
                        "build_year": static["build_year"].to_numpy(),
                    },
                    index=static.index,
                )
            )

        assets = pd.concat(assets)
        sited = assets[
            (assets["location"] != "EU")
            & (~assets["carrier"].isin(transmission))
            & (~assets["carrier"].isin(multi_variant_carriers))
            & (~assets.index.str.contains("-reversed"))
        ]

        duplicates = sited[sited.duplicated(keep=False)].sort_values(
            list(sited.columns)
        )
        assert duplicates.empty, (
            f"Multiple vintage assets share (component, location, carrier, "
            f"build_year) in {n.year}:\n{duplicates}"
        )
