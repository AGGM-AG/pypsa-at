# SPDX-FileCopyrightText: 2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""Apply recalibrated heat-demand totals to network Loads."""

import numpy as np
import pandas as pd
import pypsa
from snakemake.script import Snakemake


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
    demand = demand[demand["year"].eq(year)]
    demand["name"] = demand["region"] + " " + demand["carrier"]
    targets = demand.groupby(["name"]).value.sum()
    names = targets[targets.index.isin(n.loads.index) | (targets > 0)].index
    targets = targets.loc[names]

    dynamic = names.intersection(n.loads_t.p_set.columns)
    factors = n.loads_t.p_set.copy()
    factors = pd.DataFrame(
        np.where(
            n.loads_t.p_set.loc[:, dynamic] > 0,
            targets.loc[dynamic] / n.loads_t.p_set.loc[:, dynamic],
            0,
        ),
        columns=dynamic,
        index=factors.index,
    )
    factor = factors.mul(n.snapshot_weightings.generators, axis=0).sum()
    n.loads_t.p_set.loc[:, dynamic] *= factor
    n.loads.loc[dynamic, "p_set"] = 0.0

    static = names.difference(dynamic)
    n.loads.loc[static, "p_set"] = (
        targets.loc[static].to_numpy() / n.snapshot_weightings.generators.sum()
    )
