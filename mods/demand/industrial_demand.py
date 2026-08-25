# SPDX-FileCopyrightText: 2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""
Apply normalized industrial demand profiles to network Loads.

The resource contains normalized values per model snapshot and region. The
configured carrier mapping selects the profile carrier and corresponding
network Load carrier. Values are scaled by the original Load power and the
snapshot-weighting correction so annual energy is preserved.

The public entry point is :func:`apply_industrial_demand_profiles`.
"""

from logging import getLogger

import pandas as pd
import pypsa
from snakemake.script import Snakemake

logger = getLogger(__name__)


def apply_industrial_demand_profiles(n: pypsa.Network, snakemake: Snakemake) -> None:
    """
    Apply configured normalized profiles for the current planning horizon.

    The resource is expected to contain ``year``, ``region``, ``carrier``,
    ``snapshot`` and normalized ``value`` columns. Profile carriers are
    mapped to network Load carriers through
    ``industry.demand_profiles.definitions.*.carrier_mapping``.

    Parameters
    ----------
    n
        The pre-network to be modified in place.
    snakemake
        The Snakemake workflow object providing inputs, params, and config.

    Returns
    -------
    :
        Updates the :class:`pypsa.Network` in place.
    """
    cfg = snakemake.config["industry"].get("demand_profiles", {})
    if not cfg.get("enable", False):
        return

    year = snakemake.wildcards.planning_horizons
    profiles = pd.read_csv(
        snakemake.input.industrial_demand_profiles, parse_dates=["snapshot"]
    )
    profiles = profiles[profiles["year"].astype(str) == str(year)].drop(columns="year")

    loads = n.loads.reset_index()[["name", "carrier", "p_set"]]
    loads["region"] = loads["name"].map(lambda x: x.split(" ")[0])

    snapshot_weights = (
        n.snapshot_weightings["generators"].sum() / n.snapshot_weightings["generators"]
    )
    snapshot_weights.name = "snapshot_weights"
    merged = profiles.merge(loads, on=["region", "carrier"], how="inner").merge(
        snapshot_weights, left_on="snapshot", right_index=True, how="inner"
    )
    merged["value"] *= merged["p_set"] * merged["snapshot_weights"]
    merged_long = merged.pivot(index="snapshot", columns="name", values="value")

    n.components.loads.dynamic["p_set"].loc[:, merged_long.columns] = merged_long
    n.components.loads.static.loc[merged_long.columns, "p_set"] = 0
