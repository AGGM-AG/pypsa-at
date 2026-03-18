# SPDX-FileCopyrightText: 2023-2025 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""Functions to update resources during the `snakemake` workflow."""

from logging import getLogger

import pandas as pd
import pypsa
from snakemake.script import Snakemake

logger = getLogger(__name__)


def attach_resources_to_network_meta(
    n: pypsa.Network,
    snakemake: Snakemake,
) -> None:
    """
    Attach resource tables to the network meta before the netCDF export.

    Embeds ``energy_totals`` and ``co2_totals`` CSV data directly into
    ``n.meta["resources"]`` so that downstream evaluation rules can access
    sectoral energy demand and CO₂ totals without relying on a separate
    post-processing step or extra input files.

    The network name is also updated to a human-readable string that
    includes the planning horizon year.

    Parameters
    ----------
    n
        The solved network whose meta data will be updated in place.
    snakemake
        The Snakemake workflow object providing inputs, params, config,
        and wildcards.

    Raises
    ------
    MissingInputException
        If the required inputs (``energy_totals`` and ``co2_totals_name``) are
        not present on ``snakemake.input``.

    Returns
    -------
    :
        Updates ``n.meta`` and ``n.name`` in place.
    """
    if not hasattr(snakemake.input, "energy_totals"):
        raise ValueError("Required input file not found: energy_totals.")
    if not hasattr(snakemake.input, "co2_totals_name"):
        raise ValueError("Required input parameter not found: energy_totals_name.")

    energy_totals_year = snakemake.params.get(
        "energy_year",
        snakemake.config["energy"]["energy_totals_year"],
    )
    planning_horizon = snakemake.wildcards.planning_horizons

    energy_totals = pd.read_csv(snakemake.input.energy_totals, index_col=[0, 1])
    energy_totals = energy_totals.xs(energy_totals_year, level="year")
    co2_totals = pd.read_csv(snakemake.input.co2_totals_name, index_col=0)

    n.meta["resources"] = {
        "energy_totals": energy_totals.to_dict(orient="tight"),
        "co2_totals": co2_totals.to_dict(orient="tight"),
    }
    n.name = f"PyPSA-AT Network {planning_horizon}"
    logger.info(
        f"Attached energy_totals (year={energy_totals_year}) and co2_totals "
        f"to network meta for planning horizon {planning_horizon}."
    )


def unravel_gas_import_and_production(
    n: pypsa.Network, snakemake: Snakemake, costs: pd.DataFrame
) -> None:
    """
    Differentiate LNG, pipeline and production gas generators.

    Production is cheaper than pipeline gas and LNG is
    more expensive than pipeline gas.

    Parameters
    ----------
    n
        The network before optimisation.
    snakemake
        The snakemake workflow object.
    costs
        The costs data for the current planning horizon.

    Returns
    -------
    :
        Updates the pypsa.Network in place.
    """
    config = snakemake.config
    gas_generators = n.static("Generator").query("carrier == 'gas'")
    if gas_generators.empty and config.get("gas_compression_losses", 0):
        logger.debug(
            "Skipping unravel gas generators because "
            "industry.gas_compression_losses is set."
        )
        return

    if not config.get("mods", {}).get("unravel_natural_gas_imports", {}).get("enable"):
        logger.debug(
            "Skipping unravel natural gas imports because "
            "the modification was not requested."
        )
        return

    logger.info("Unravel gas import types.")
    gas_input_nodes = pd.read_csv(
        snakemake.input.gas_input_nodes_simplified, index_col=0
    )

    # remove combined gas generators
    n.remove("Generator", gas_generators.index)
    ariadne_gas_fuel_price = costs.at["gas", "fuel"]
    cost_factors = config["mods"]["unravel_natural_gas_imports"]

    for import_type in ("lng", "pipeline", "production"):
        cost_factor = cost_factors[import_type]
        p_nom = gas_input_nodes[import_type].dropna()
        p_nom.rename(lambda x: x + " gas", inplace=True)
        nodes = p_nom.index
        suffix = (
            " production" if import_type == "production" else f" {import_type} import"
        )
        carrier = f"{import_type} gas"
        marginal_cost = ariadne_gas_fuel_price * cost_factor
        n.add(
            "Generator",
            nodes,
            suffix=suffix,
            bus=nodes,
            carrier=carrier,
            p_nom_extendable=False,
            marginal_cost=marginal_cost,
            p_nom=p_nom,
        )
        # reuse settings from mixed gas carrier
        n.carriers.loc[carrier] = n.carriers.loc["gas"].copy()

    # make sure that this modification does not change the total gas generator capacity
    old_p_nom = gas_generators["p_nom"].sum()
    new_p_nom = (
        n.static("Generator").query("carrier.str.endswith(' gas')")["p_nom"].sum()
    )
    assert old_p_nom.round(8) == new_p_nom.round(8), (
        f"Unraveling imports changed total capacities: old={old_p_nom}, new={new_p_nom}."
    )


def modify_prenetwork(n: pypsa.Network, snakemake: Snakemake) -> None:
    """
    Apply all PyPSA-AT specific modifications to the pre-network.

    This is the single entry point for all AT-specific modifications during
    the ``modify_prenetwork`` Snakemake step. It orchestrates the individual
    modification functions and encapsulates the conditional logic for when
    each modification applies.

    Parameters
    ----------
    n
        The pre-network to be modified in place.
    snakemake
        The Snakemake workflow object providing inputs, params, config,
        and wildcards.

    Returns
    -------
    :
        Updates the :class:`pypsa.Network` in place.
    """
    from scripts.add_electricity import load_costs

    costs = load_costs(snakemake.input.costs)

    unravel_gas_import_and_production(n, snakemake, costs)
