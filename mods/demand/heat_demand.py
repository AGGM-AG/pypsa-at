# SPDX-FileCopyrightText: 2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""Apply recalibrated heat-demand totals to network Loads."""

import numpy as np
import pandas as pd
import pypsa
from snakemake.script import Snakemake

from mods.demand.annual import region_by_load


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
    if not snakemake.params.apply_at_heat_demand:
        return
    year = int(snakemake.wildcards.planning_horizons)
    demand = pd.read_csv(snakemake.input.heat_demand_nea_at)
    load_regions = region_by_load(n)
    names = n.loads.loc[
        load_regions.isin(demand.region) & n.loads.carrier.isin(demand.carrier),
        ["carrier"],
    ]
    names["region"] = load_regions
    demand = demand[demand["year"].eq(year)].copy()
    demand = demand.merge(
        names.reset_index(),
        on=["carrier", "region"],
        how="left",
        validate="one_to_many",
    )
    missing = demand[(demand["value"] > 0) & demand["name"].isna()]
    if not missing.empty:
        raise ValueError(f"Non zero heat nodes {missing} missing from network")
    targets = demand.groupby(["name"]).value.sum().fillna(0)
    names = names.index
    targets = targets.loc[names]

    dynamic = names.intersection(n.loads_t.p_set.columns)
    annual = (
        n.loads_t.p_set.loc[:, dynamic]
        .mul(n.snapshot_weightings.generators, axis=0)
        .sum()
    )
    factor = np.where(annual > 0, targets.loc[dynamic] / annual, 0)
    n.loads_t.p_set.loc[:, dynamic] *= factor
    n.loads.loc[dynamic, "p_set"] = 0.0

    static = names.difference(dynamic)
    n.loads.loc[static, "p_set"] = (
        targets.loc[static].to_numpy() / n.snapshot_weightings.generators.sum()
    )
