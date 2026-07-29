# SPDX-FileCopyrightText: 2023-2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""Electricity demand update module."""

import logging

import pandas as pd
import pypsa

logger = logging.getLogger(__name__)


def base_load_load_splitting(
    n: pypsa.Network, pop_weighted_energy_totals: pd.DataFrame, nyears: float
) -> None:
    """
    Split the electricity base load into granular components.

    The electricity for rail demand is carved out of the base load
    proportionally: each node's base load time series is scaled down by
    its rail share and the removed part is re-added as a separate
    ``electricity for rail`` Load with the same profile shape, so the
    hourly sum of both components equals the original base load.

    Parameters
    ----------
    n
        The Network during ``prepare_sector_network``.
    pop_weighted_energy_totals
        The population weighted energy totals in TWh per calendar year.
    nyears
        Fraction of a calendar year covered by the snapshots
        (``nhours / 8760``); scales the annual energy totals to the
        model period.

    Returns
    -------
    :
        Updates the network in place.
    """
    nodes = pop_weighted_energy_totals.index

    base_load_idx = n.loads.query("carrier == 'electricity'").index
    base_load = n.loads_t["p_set"][base_load_idx]

    # sanity check: both indices contain the same entries
    if any(differences := base_load.columns.symmetric_difference(nodes)):
        raise Exception(
            f"Electricity base load and electricity rail indices are not identical: {differences}"
        )

    # nodal annual energy of the (residual) base load in MWh/a
    weightings = n.snapshot_weightings.generators
    base_energy = base_load.mul(weightings, axis="index").sum()
    rail_energy = (
        pop_weighted_energy_totals["electricity rail"].mul(nyears).mul(1e6)
    )  # to MWh/a
    rail_share = rail_energy / base_energy

    # sanity check: the rail share must be a true fraction of the base load,
    # otherwise the energy totals and the disaggregated base load are inconsistent
    if any(invalid := rail_share[rail_share.lt(0) | rail_share.ge(1)]):
        raise Exception(f"Electricity for rail shares out of bounds [0, 1): {invalid}")

    # split the base load proportionally: both parts keep the ENTSO-E profile
    rail_profile = base_load.mul(rail_share, axis="columns")
    n.loads_t["p_set"][nodes] -= rail_profile

    carrier = "electricity for rail"
    # No need to register the new carrier because add_missing_carriers()
    # runs at the end of prepare_sector_network.py.
    n.add(
        "Load",
        nodes,
        suffix=f" {carrier}",
        bus=n.loads.loc[nodes, "bus"],
        carrier=carrier,
        p_set=rail_profile,
    )

    logger.info(f"Split 'electricity rail' JRC-IDEE demands to a new Load '{carrier}'.")
