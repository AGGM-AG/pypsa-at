# SPDX-FileCopyrightText: 2023-2025 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""Functions to update resources during the `snakemake` workflow."""

from logging import getLogger
from types import SimpleNamespace

import pandas as pd
import pypsa
from snakemake.script import Snakemake

from mods.pemmdb_overwrites import overwrite_pemmdb_capacities

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


def add_methane_pyrolysis_plasma(
    n: pypsa.Network,
    snakemake: Snakemake,
    costs: pd.DataFrame,
    nodes: pd.Index,
    spatial: SimpleNamespace,
) -> None:
    """
    Add Methane Pyrolysis (Plasma) H₂ production Links to the sector network.

    Methane pyrolysis (plasma variant) splits CH₄ into H₂ and solid carbon
    (carbon black) using a plasma torch.  No CO₂ is emitted during the
    process; the carbon is captured as a solid material, enabling turquoise
    hydrogen production with negative emissions potential if the carbon black
    is permanently stored.

    * bus0 = gas (CH₄ input, ``p_nom`` reference in MW_CH4)
    * bus1 = H2  (H₂ output)
    * bus2 = AC  (electricity consumption for plasma torch)
    * bus3 = urban central heat  — **only** where district heating exists
    * CO₂ stored bus is intentionally **not** connected: carbon black is
      a solid transported by road/rail/ship, not through the CO₂ pipeline
      network.

    All cost parameters in ``costs`` are normalized to MWh_H₂.  Since bus0
    is gas (MW_CH4), efficiencies and capital cost are converted using
    ``eta_H2 = 1 / methane-input``.

    Carbon black revenue: carbon black sold to the market is valued at
    the CO₂ price of the same planning horizon, scaled by the stoichiometric
    CO₂ intensity of carbon black.

    Parameters
    ----------
    n
        Pre-network to modify in place.
    snakemake
        The workflow snakemake object.
    costs
        Processed cost DataFrame for the current planning horizon.
    nodes
        Clustered node index (``pop_layout.index``).
    spatial
        Spatial namespace produced by ``define_spatial``.

    Returns
    -------
    :
        Modifies ``n`` in place.
    """
    config = snakemake.config.get("mods", {}).get("methane_pyrolysis", {})
    # config = {"plasma": True, "utilization_share": 0.0}

    if not config.get("plasma", False):
        logger.info("Methane pyrolysis plasma: disabled — skipping.")
        return

    # carrier name. Used to mitigate downstream repetitions
    tech = "methane pyrolysis plasma"

    # Guard: technology not available before 2030 (no cost data in custom_costs).
    # process_cost_data fills missing investment with 0; capital_cost would also
    # be 0, making capacity free. Skip silently for those planning horizons.
    if tech not in costs.index or costs.at[tech, "investment"] == 0:
        logger.info(
            f"Methane pyrolysis plasma not available in "
            f"{snakemake.wildcards.planning_horizons} "
            f"(not available before 2030) — skipping."
        )
        return

    logger.info("Adding Methane Pyrolysis (Plasma) H₂ production Links.")

    # All costs.csv values are normalized to MWh_H2. This is a DEA choice preserved
    # in technology-data and ultimately a consequence here at model level. Since
    # bus0 = gas → need to convert efficiencies and capital cost to per-MWh_CH4.
    ch4_input = costs.at[tech, "methane-input"]  # MWh_CH4/MWh_H2
    eta_H2 = 1.0 / ch4_input  # MWh_H2/MWh_CH4

    cb_revenue = 0  # no revenue from carbon black sales by default
    if cb_utilization := float(config.get("utilization_share", 0.0)):
        # Carbon black (cb) revenue: priced at CO2 cost of the same planning horizon.
        co2_price = costs.at["CO2", "fuel"]  # EUR/tCO2
        co2_stored_total = costs.at[tech, "CO2 stored"]  # tCO2/MWh_H2
        cb_energy = costs.at[tech, "carbon-black-output"]  # MWh_Cblack/MWh_H2
        cb_co2_intensity = co2_stored_total / cb_energy  # tCO2/MWh_Cblack
        cb_revenue = (
            cb_utilization * cb_energy * cb_co2_intensity * co2_price
        )  # EUR/MWh_H2

    cost_capital = costs.at[tech, "capital_cost"] * eta_H2  # to EUR/MW_CH4
    cost_marginal = costs.at[tech, "VOM"] * eta_H2 - cb_revenue  # EUR/MWh_CH4
    efficiency_elec = -costs.at[tech, "electricity-input"] * eta_H2
    efficiency_heat = costs.at[tech, "heat-output"] * eta_H2
    lifetime = costs.at[tech, "lifetime"]

    # heat output only where urban central heating infrastructure exists.
    urban_heat_buses = n.buses.index[n.buses.carrier == "urban central heat"]
    heat_mask = pd.array(
        [f"{node} urban central heat" in urban_heat_buses for node in nodes]
    )
    nodes_w_central_heat = nodes[heat_mask]
    nodes_no_central_heat = nodes[~heat_mask]

    common_kwargs = dict(
        carrier=tech,
        suffix=f" {tech}",
        p_nom_extendable=True,
        efficiency=eta_H2,
        efficiency2=efficiency_elec,
        capital_cost=cost_capital,
        marginal_cost=cost_marginal,
        lifetime=lifetime,
        # Note: CO2 stored bus (bus4) intentionally NOT connected.
        # Carbon black is a solid transported by road/rail/ship,
        # not via the CO2 pipeline network.
    )

    if len(nodes_w_central_heat):
        n.add(
            "Link",
            nodes_w_central_heat,
            bus0=spatial.gas.df.loc[nodes_w_central_heat, "nodes"].values,
            bus1=nodes_w_central_heat + " H2",
            bus2=nodes_w_central_heat,
            bus3=nodes_w_central_heat + " urban central heat",
            efficiency3=efficiency_heat,
            **common_kwargs,
        )

    if len(nodes_no_central_heat):
        n.add(
            "Link",
            nodes_no_central_heat,
            bus0=spatial.gas.df.loc[nodes_no_central_heat, "nodes"].values,
            bus1=nodes_no_central_heat + " H2",
            bus2=nodes_no_central_heat,
            **common_kwargs,
        )

    logger.info(
        f"Added methane pyrolysis plasma Links: "
        f"{len(nodes_w_central_heat)} with heat recovery, "
        f"{len(nodes_no_central_heat)} without."
    )


def update_network_to_stop_ukrainian_gas_transit(
    n: pypsa.Network, snakemake: Snakemake
) -> None:
    """
    Stop Ukrainian gas transit by disabling gas imports in affected locations.
    Selection of relevant cross border points between EU countries and Ukraine
    by AGGM AG experts.

    Locations are identified in data/pypsa-at/ukrainian_gas_transit_stop.json.
    Matched with n.generators using their country_bus.
    Imported capacities via Ukraine are subtracted from summed capacity.
    The relevant countries are only connected to EU countries and Ukraine,
    leaving their import capacity == 0 .

    The network n is updated in place.

    Parameters
    ----------
    n
        The network before optimisation.
    snakemake
        The snakemake workflow object.

    Returns
    -------
    :
        Updates the pypsa.Network in place.

    """
    if not snakemake.params.get("ukrainian_gas_transit_stop", False):
        logger.info(
            "Skip updating network to stop ukrainian gas transit because "
            "ukrainian_gas_transit_stop is off in config.at.yaml ."
        )
        return

    pyear = int(snakemake.wildcards.planning_horizons)
    if pyear <= 2025:
        logger.info(
            "Skip updating network to stop ukrainian gas transit for years after 2025."
        )
        return

    country_bus = "properties.bus"
    capacity = "properties.capacity"

    ukrainian_import_locations = pd.read_json(
        snakemake.input.ukrainian_gas_transit_stop
    )
    to_drop = pd.json_normalize(ukrainian_import_locations.features).astype(
        {capacity: "float"}
    )

    # drop 'None' country with import node in Moldavia
    to_drop = to_drop.dropna(subset=[country_bus])

    # filter for countries in config - or CI pipeline will fail
    to_drop = to_drop[to_drop[country_bus].isin(snakemake.config["countries"])]

    capacity_sum = to_drop[[country_bus, capacity]].groupby(country_bus).sum()
    for cc in capacity_sum.index:
        old_capacity = n.generators.loc[f"{cc} gas pipeline import", "p_nom"]
        capacity_ukrainian_import = capacity_sum.loc[cc]

        capacity_difference = old_capacity - capacity_ukrainian_import

        if (
            abs(capacity_difference.item()) > 0.001
            and snakemake.config["run"]["prefix"] != "test-sector-myopic-at10"
        ):
            raise Exception("Detected capacity difference without ukrainian imports.")
        n.generators.loc[f"{cc} gas pipeline import", "p_nom"] = 0

        # disable optimization of Ukrainian gas imports
        n.generators.loc[f"{cc} gas pipeline import", "p_nom_extendable"] = False

    logger.info("Updated network to stop ukrainian gas transit.")


def make_gas_pipelines_unextendable(n: pypsa.Network, snakemake: Snakemake) -> None:
    """
    Disallow expansion of methane pipelines - both new and existing

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
        Updates the pypsa.Network in place.

    """
    # always disable extendability of new pipelines
    n.links.loc[n.links.carrier == "gas pipeline new", "p_nom_extendable"] = False

    # disable extendability of gas pipelines until 2040
    pyear = int(snakemake.wildcards.planning_horizons)
    if snakemake.config.get("mods").get("threshold_year_for_gas_grid_expansion"):
        threshold_year = int(
            snakemake.config.get("mods").get("threshold_year_for_gas_grid_expansion")
        )
    else:
        threshold_year = 2040

    if pyear < threshold_year:
        n.links.loc[n.links.carrier == "gas pipeline", "p_nom_extendable"] = False


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

    mods = snakemake.config["mods"]
    costs = load_costs(snakemake.input.costs)

    unravel_gas_import_and_production(n, snakemake, costs)

    if mods.get("ukrainian_gas_transit_stop"):
        update_network_to_stop_ukrainian_gas_transit(n, snakemake)

    if mods.get("modify_brownfield_gas_network_AT"):
        make_gas_pipelines_unextendable(n, snakemake)

    overwrite_pemmdb_capacities(n, snakemake)
