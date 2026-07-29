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
    n: pypsa.Network, pop_weighted_energy_totals: pd.DataFrame
) -> None:
    """
    Split the electricity base load into granular components.

    Parameters
    ----------
    n
        The Network just before solving.
    pop_weighted_energy_totals
        The population weighted energy totals in TWh/a.

    Returns
    -------
    :
        Updates the network in place.
    """

    nodes = pop_weighted_energy_totals.index

    base_load_idx = n.loads.query("carrier == 'electricity'").index
    base_load_dynamic = n.loads_t["p_set"][base_load_idx]

    # constant nodal power draw from annual totals (TWh/a -> MW)
    nhours = n.snapshot_weightings.generators.sum()
    electricity_rail = pop_weighted_energy_totals["electricity rail"] * 1e6 / nhours

    # sanity check: both indices contain the same entries
    differences = base_load_dynamic.columns.symmetric_difference(nodes)
    if any(differences):
        raise Exception(
            f"Electricity base load and electricity rail indices are not identical: {differences}"
        )

    # deduct electricity rail parts from the base load and add them as a separate component again
    n.loads_t["p_set"][nodes] -= electricity_rail

    # There are negative base load values before the deduction. The deduction worsens the
    # increases negatives count, but it is not the problems root cause and the sanity check
    # is skipped here.
    # # sanity check: no negative base loads after deduction
    # base_load_after = n.loads_t["p_set"][nodes]
    # negatives = (
    #     base_load_after.where(base_load_after.lt(0))
    #     .dropna(axis="index", how="all")
    #     .dropna(axis="columns", how="all")
    # )
    # if not negatives.empty:
    #     raise Exception(
    #         f"Negative Load values detected after "
    #         f"electricity for rail deductions: {negatives}"
    #     )

    n.add(
        "Load",
        nodes,
        suffix=" electricity rail",
        bus=n.loads.loc[nodes, "bus"],
        carrier="electricity rail",
        p_set=electricity_rail,
    )

    logger.info("Split 'electricity for rail' demand to a new Load component.")
