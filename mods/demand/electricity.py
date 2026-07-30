# SPDX-FileCopyrightText: 2023-2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""Electricity demand update module."""

import logging

import pandas as pd
import pypsa

logger = logging.getLogger(__name__)

#: Carriers of the Loads the electricity base load is split into.
BASE_LOAD_CARRIERS = (
    "electricity for residential",
    "electricity for services",
    "electricity for road",
    "electricity for rail",
    "agriculture electricity",
)


def base_load_load_splitting(
    n: pypsa.Network, pop_weighted_energy_totals: pd.DataFrame
) -> None:
    """
    Split the electricity base load into sectoral components.

    The base load time series of every node is distributed without
    remainder into sectoral Loads, using weights normalised over the
    sectoral energies from the JRC-IDEES based energy totals. All parts
    keep the measured ENTSO-E profile shape and sum up to the original
    base load, so grid losses and the statistical gap between measured
    load and the JRC-IDEES bottom-up totals are distributed across
    the sectors.

    The sectoral energies are composed as follows:

    - ``electricity for residential`` and ``electricity for services``
      exclude the space and water heating amounts, because those are
      already deducted from the base load in ``build_heat_demand()``.
    - ``electricity for road`` uses the aggregate ``electricity road``
      column, which includes the PHEV electricity share missing from
      the granular vehicle-class columns.
    - ``electricity for rail`` covers rail passenger and freight.
    - the ``total agriculture electricity`` share replaces the flat
      ``agriculture electricity`` Loads added in ``add_agriculture()``
      with a profiled time series. This avoids double counting the
      demand, which would occur if the amount stayed in the base load
      next to the flat Loads.

    Negative sectoral energies from source data inconsistencies (e.g.
    Norway reports less total services electricity than services space
    and water heating combined) are clipped to zero with a warning.

    The original base load components are removed from the network,
    because their demand is fully distributed to the sectoral Loads.

    Parameters
    ----------
    n
        The Network during ``prepare_sector_network``.
    pop_weighted_energy_totals
        The population weighted energy totals in TWh per calendar year.

    Returns
    -------
    :
        Updates the network in place.
    """
    pwet = pop_weighted_energy_totals
    nodes = pwet.index

    base_load_idx = n.loads.query("carrier == 'electricity'").index
    base_load = n.loads_t["p_set"][base_load_idx]

    # sanity check: both indices contain the same entries
    if not (differences := base_load.columns.symmetric_difference(nodes)).empty:
        raise ValueError(
            f"Electricity base load and energy totals indices are not identical: {differences}"
        )

    # n.add requires p_set columns to match the passed names positionally
    base_load = base_load[nodes]

    # annual sectoral energies in TWh per calendar year; the unit cancels
    # out in the weight normalisation below
    sector_energies = pd.DataFrame(
        {
            "electricity for residential": (
                pwet["electricity residential"]
                - pwet["electricity residential space"]  # heat already deducted
                - pwet["electricity residential water"]  # heat already deducted
            ),
            "electricity for services": (
                pwet["electricity services"]
                - pwet["electricity services space"]  # heat already deducted
                - pwet["electricity services water"]  # heat already deducted
            ),
            "electricity for road": pwet["electricity road"],
            "electricity for rail": pwet["electricity rail"],
            # replaces the flat Loads from add_agriculture(), see below
            "agriculture electricity": pwet["total agriculture electricity"],
        }
    )

    if not (negative := sector_energies[sector_energies.lt(0).any(axis=1)]).empty:
        logger.warning(
            f"Clipping negative sectoral energies to zero [TWh/a]:\n{negative.round(3)}"
        )
        sector_energies = sector_energies.clip(lower=0)

    weights = sector_energies.div(sector_energies.sum(axis="columns"), axis="index")

    # sanity check: 0/0 yields NaN weights for nodes without any sectoral energy
    if not (invalid := weights[weights.isna().any(axis=1)]).empty:
        raise ValueError(
            f"Nodes without any sectoral energy: {invalid.index.to_list()}"
        )

    # distribute the base load without remainder: all parts keep the ENTSO-E
    # profile. No need to register the new carriers because
    # add_missing_carriers() runs at the end of prepare_sector_network.py.
    new_load_carriers = weights.columns.drop("agriculture electricity")
    for carrier in new_load_carriers:
        n.add(
            "Load",
            nodes,
            suffix=f" {carrier}",
            bus=n.loads.loc[nodes, "bus"],
            carrier=carrier,
            p_set=base_load.mul(weights[carrier], axis="columns"),
        )

    # the agriculture share replaces the flat Loads from add_agriculture():
    # a time-varying p_set takes precedence over the static value
    agriculture_loads = nodes + " agriculture electricity"
    if not (missing := agriculture_loads.difference(n.loads.index)).empty:
        raise ValueError(f"Missing agriculture electricity Loads: {missing}")
    agriculture_profile = base_load.mul(
        weights["agriculture electricity"], axis="columns"
    )
    agriculture_profile.columns = agriculture_loads

    # the profiled shares intentionally rescale the agriculture demand to the
    # measured base load: factor = measured base energy / JRC bottom-up total
    weightings = n.snapshot_weightings.generators
    profile_energy = agriculture_profile.mul(weightings, axis="index").sum()
    flat_energy = n.loads.loc[agriculture_loads, "p_set"] * weightings.sum()
    rescaling = (profile_energy / flat_energy).round(2)
    logger.info(
        "Replaced flat agriculture electricity Loads with profiled shares; "
        f"energy rescaling factors (measured/JRC): min {rescaling.min()}, "
        f"median {rescaling.median()}, max {rescaling.max()}"
    )

    n.loads_t["p_set"][agriculture_loads] = agriculture_profile
    n.loads.loc[agriculture_loads, "p_set"] = 0.0

    # the base load is fully distributed to the sectoral Loads
    n.remove("Load", base_load_idx)

    logger.info(
        f"Split the electricity base load into sectoral Loads {list(new_load_carriers)}"
        " and moved the 'agriculture electricity' share onto the existing Loads."
    )
