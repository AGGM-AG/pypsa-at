# SPDX-FileCopyrightText: 2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""Apply recalibrated heat-demand totals to network Loads."""

import pandas as pd
import pypsa
from snakemake.script import Snakemake

from mods.demand.annual import _region_by_load


def apply_heat_demand(n: pypsa.Network, snakemake: Snakemake) -> None:
    """
    Apply recalibrated annual heat demand to matching network Loads.

    Parameters
    ----------
    n
        The pre-network to be modified in place.
    snakemake
        The Snakemake workflow object providing inputs, params, and config.

    Returns
    -------
    :
        Modifies the network in place.
    """
    year = int(snakemake.wildcards.planning_horizons)
    demand = pd.read_csv(snakemake.input.heat_demand_nea_at)
    demand = demand[demand["year"].eq(year)]
    demand["name"] = demand["region"] + " " + demand["carrier"]
    targets = demand.groupby(["name"]).value.sum()

    load_regions = _region_by_load(n)
    keys = pd.MultiIndex.from_arrays([load_regions, n.loads.carrier])
    values = pd.Series(targets.reindex(keys).to_numpy(), index=n.loads.index)
    mask = values.notna()
    total_weight = n.snapshot_weightings.generators.sum()
    names = n.loads.index[mask]
    dynamic = names.intersection(n.loads_t.p_set.columns)
    n.loads_t.p_set.loc[:, dynamic] = values.loc[dynamic].to_numpy() / total_weight
    static = names.difference(dynamic)
    n.loads.loc[static, "p_set"] = values.loc[static].to_numpy() / total_weight
    n.loads.loc[dynamic, "p_set"] = 0.0
