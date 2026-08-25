# SPDX-FileCopyrightText: 2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""Apply prepared annual demand totals to network Loads."""

import numpy as np
import pandas as pd
import pypsa
from snakemake.script import Snakemake


def _region_by_load(n: pypsa.Network) -> pd.Series:
    """
    Return the model region belonging to each Load.

    Parameters
    ----------
    n
        Network containing the Loads and their buses.

    Returns
    -------
    :
        Model region indexed by Load name.
    """
    location = n.loads.bus.map(n.buses.location)
    return location.fillna(n.loads.bus)


def apply_annual_demand_overrides(n: pypsa.Network, snakemake: Snakemake) -> None:
    """
    Apply configured TWh/a totals as flat weighted Load power.

    The prepared CSV is filtered to the current planning year, mapped to Load
    carriers, aggregated by region and carrier, and written to static or
    dynamic ``p_set`` depending on how the matching Load is represented.

    Parameters
    ----------
    n
        The pre-network to be modified in place.
    snakemake
        The Snakemake workflow object providing inputs, params, wildcards, and
        configuration.

    Returns
    -------
    :
        Updates the network in place.
    """
    cfg = snakemake.params.annual_demand_overrides
    year = int(snakemake.wildcards.planning_horizons)
    if not cfg["enable"] or year not in cfg["target_years"]:
        return

    totals = pd.read_csv(snakemake.input.annual_demand_overrides)
    totals = totals[totals["year"].eq(year)]
    mapping = snakemake.params.carrier_to_load_mapping

    totals["load_carrier"] = [
        mapping[sector][carrier]
        for sector, carrier in zip(totals["sector"], totals["carrier"])
    ]

    targets = totals.groupby(
        ["region", "load_carrier"],
        as_index=False,
    )["value_TWh"].sum()

    load_regions = _region_by_load(n)
    total_weight = n.snapshot_weightings["generators"].sum()
    for row in targets.itertuples(index=False):
        names = n.loads.index[
            load_regions.eq(row.region) & n.loads.carrier.eq(row.load_carrier)
        ]
        value = row.value_TWh * 1e6
        dynamic_names = names.intersection(n.loads_t.p_set.columns)
        annual_dynamic_energy = (
            n.loads_t.p_set.loc[:, dynamic_names]
            .mul(n.snapshot_weightings.generators, axis=0)
            .sum()
        )
        factor = np.where(annual_dynamic_energy > 0, value / annual_dynamic_energy, 0)
        n.loads_t.p_set.loc[:, dynamic_names] *= factor
        n.loads.loc[dynamic_names, "p_set"] = 0.0
        n.loads.loc[names.difference(dynamic_names), "p_set"] = value / total_weight
