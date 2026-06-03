# SPDX-FileCopyrightText: 2023-2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""Gas-related pre-network modifications for the ``modify_prenetwork`` step."""

from logging import getLogger
from pathlib import Path

import pandas as pd
import pypsa
from snakemake.script import Snakemake

from mods.clustering.constants import VALID_CONFIGURATIONS
from mods.clustering.utils import combine_regions_by_clustering

logger = getLogger(__name__)


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
    if gas_generators.empty and config["gas_compression_losses"]:
        logger.debug(
            "Skipping unravel gas generators because "
            "industry.gas_compression_losses is set."
        )
        return

    if not config["mods"]["unravel_natural_gas_imports"]["enable"]:
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
    if not snakemake.params["ukrainian_gas_transit_stop"]:
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
    mods = snakemake.config["mods"]
    if not mods.get("modify_brownfield_gas_network_AT"):
        logger.info(
            "Skip fixing gas pipeline capacities because the feature is disabled."
        )
        return

    # disable extendability of gas pipelines until including year in config
    pyear = int(snakemake.wildcards.planning_horizons)
    threshold_year = int(mods["threshold_year_for_gas_grid_expansion"])

    to_fix = ["gas pipeline", "gas pipeline new"]
    if pyear <= threshold_year:
        n.links.loc[n.links.carrier.isin(to_fix), "p_nom_extendable"] = False


def override_gas_storage_capacities(n: pypsa.Network, snakemake: Snakemake) -> None:
    """
    Override gas Store e_nom_min with validated storage capacities.

    Reads ``data/pypsa-at/gas_input_locations_s_AT35DE16_updated.csv`` (AT NUTS3
    + DE NUTS1 resolution) and overwrites ``e_nom_min`` on all matched gas Store
    components. Aggregates to the network's actual bus resolution:

    - DE NUTS1 → DE5 macro-regions when the network uses DE5 clustering
      (detected from bus location names; DE NUTS1 states use letter suffixes DEA–DEG)
    - AT NUTS3 → NUTS2 when the network uses AT10 clustering
      (detected from bus location names; AT35 buses have 5-char codes)

    DE aggregation uses :func:`mods.clustering.map_de_nuts1_to_de5`;
    AT aggregation uses :func:`mods.clustering.map_at_nuts3_to_nuts2`.
    Buses not present in the CSV keep the ``e_nom_min`` set by
    ``prepare_sector_network``. No percentile clipping is applied.

    Parameters
    ----------
    n
        The pre-network to update in place.
    snakemake
        The Snakemake workflow object providing config.

    Returns
    -------
    :
        Updates ``n.stores.e_nom_min`` in place for matched gas Stores.
    """
    mods = snakemake.config["mods"]
    if mods["override_gas_storage_capacities"]["enable"] is not True:
        logger.info("Skipping gas storage capacity override (disabled in config).")
        return

    clustering = mods["modify_nuts3_shapes"]
    if clustering not in VALID_CONFIGURATIONS:
        logger.warning(f"Clustering {clustering} is not supported.")
        return

    logger.info("Overriding gas storage capacities.")

    # prefer relative path over extending upstream pypsa-de snakemake rule
    file_name = "gas_input_locations_s_AT35DE16_updated.csv"
    file_path = Path(__file__).parents[2] / "data" / "pypsa-at" / file_name
    storage = pd.read_csv(file_path, index_col=0)["storage update (GWh)"]

    # calculate total existing gas storage capacities
    total_previous = n.stores.query("carrier == 'gas'")["e_nom_min"].sum()

    # NaN rows have no storage data
    storage = storage.dropna()

    # The input data file holds 0 values to use. This is to make the
    # reduction from SciGRID to new values transparent. Stores with
    # e_nom=0 cannot be used by the model because they are not extendable.
    # Drop them to keep only Stores with usable capacity in the model.
    storage = storage[storage > 0]

    # scale GWh to MWh
    storage = storage.mul(1e3)

    # aggregate update values depending on custom clustering
    storage = combine_regions_by_clustering(storage, clustering)

    # drop gas Stores for regions not covered by the input file
    stores_all_regions = n.stores.query("carrier == 'gas'").index
    stores_to_update = pd.Index(f"{region} gas Store" for region in storage.index)
    to_drop = stores_all_regions.difference(stores_to_update)
    n.remove("Store", to_drop)
    logger.info(f"Dropped {len(to_drop)} gas Stores with no capacity data.")

    # needed to align with CI integration test regions
    if snakemake.config["run"]["prefix"] == "test-sector-myopic-at10":
        stores_to_update = stores_to_update.intersection(n.stores.index)

    # gas storage sites are geologically constrained assets with decade-long lead times.
    # capacity within any planning horizon is fixed by what physically exists
    n.stores.loc[stores_to_update, "e_nom_extendable"] = False
    logger.info("Setting 'e_nom_extendable=False' for all gas Stores.")

    # set existing capacity
    for idx in stores_to_update:
        region = idx.split(" ")[0]
        e_nom = storage[region]
        n.stores.at[idx, "e_nom"] = e_nom
        e_nom_old = n.stores.at[idx, "e_nom_min"]
        logger.info(
            f"Update e_nom at '{idx}' from "
            f"{e_nom_old / 1e6:.1f} TWh to {e_nom / 1e6:.1f} TWh."
        )

    total_updated = n.stores.query("carrier == 'gas'")["e_nom"].sum()
    relative_change = total_updated / total_previous * 100
    logger.info(
        f"Changed total system gas storage capacity from "
        f"{total_previous / 1e6:.1f} TWh to "
        f"{total_updated / 1e6:.1f} TWh "
        f"({relative_change:.0f}%)."
    )
