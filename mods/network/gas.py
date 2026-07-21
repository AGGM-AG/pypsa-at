# SPDX-FileCopyrightText: 2023-2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""Gas-related pre-network modifications for the ``modify_prenetwork`` step."""

from logging import getLogger

import pandas as pd
import pypsa
from snakemake.script import Snakemake

from mods.clustering.constants import VALID_CONFIGURATIONS
from mods.clustering.utils import combine_regions_by_clustering

logger = getLogger(__name__)

# Trans-Anatolia-Gas-Pipeline (TANAP), Azerbaijani gas pipeline to Bulgaria via Turkey
# Capacity is independent of Russian TurkStream and remains available after blocking Russian gas imports
# Value: 702.2 GWh/d converted to MWh/h
# Source: https://view.officeapps.live.com/op/view.aspx?src=https%3A%2F%2Fwww.entsog.eu%2Fsites%2Fdefault%2Ffiles%2F2026-03%2FSystem%2520Capacity%2520Map%25202026%2520-%2520Capacities.xlsx&wdOrigin=BROWSELINK
_TANAP_PIPELINE_CAPACITY = 702.2 * 1000 / 24


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


def block_russian_gas_imports(n: pypsa.Network, snakemake: Snakemake) -> None:
    """
    Block Russian gas imports via Ukrainian land borders and TurkStream.
    Two optional route blocks from config mods.block_russian_gas_imports:

    - eastern_border_block: countries receiving Russian gas via Ukraine
      (FI, EE, LV, LT, PL, SK, RO). Applied from start_year onward.
    - ``turkstream_block``: Bulgaria receiving Russian gas via TurkStream (BG).
      Residual capacity is set to _TANAP_PIPELINE_CAPACITY, still allowing
      gas imports via Bulgaria from Azerbaijan.
      Applied from ``start_year`` onward.

    For each active block, the pipeline import generator capacity for each
    listed country is zeroed out and made non-extendable.
    Each block can have an individual start_year and end_year.

    Parameters
    ----------
    n
        The network before optimisation.
    snakemake
        The Snakemake workflow object.

    Returns
    -------
    :
        Updates network in place.
    """
    corridors = snakemake.params["block_russian_gas_imports"]
    if not corridors["enable"]:
        logger.info("Skipping Russian gas import blockade (disabled in config).")
        return

    pyear = int(snakemake.wildcards.planning_horizons)
    blocks = {
        "eastern_border_block": corridors["eastern_border_block"],
        "turkstream_block": corridors["turkstream_block"],
    }

    generators = n.generators.query("carrier == 'pipeline gas'")
    countries_with_pipeline_import = generators.index.str[:2]

    for block_name, block_config in blocks.items():
        start_year = block_config["start_year"]
        end_year = block_config.get("end_year", float("inf"))
        outside_block_time = pyear < start_year or pyear > end_year
        if outside_block_time:
            logger.info(
                f"Skipping {block_name} for {pyear} "
                f"(active only {start_year}–{'∞' if end_year == float('inf') else end_year})."
            )
            continue

        active_countries = [
            c for c in block_config["countries"] if c in countries_with_pipeline_import
        ]

        for cc in active_countries:
            generator_name = f"{cc} gas pipeline import"
            if generator_name not in n.generators.index:
                raise ValueError(
                    f"Gas pipeline import location '{generator_name}' not found in modeled countries."
                )

            residual_capacity = _TANAP_PIPELINE_CAPACITY if cc == "BG" else 0
            n.generators.loc[generator_name, "p_nom"] = residual_capacity
            n.generators.loc[generator_name, "p_nom_extendable"] = False
            logger.info(
                f"Blocked Russian gas import at '{generator_name}' ({block_name}), "
                f"residual capacity set to {residual_capacity:.1f} MW."
            )

    logger.info("Completed blockade of Russian gas imports.")


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

    Reads ``snakemake.input.gas_storage_capacities`` (AT NUTS3
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

    storage = pd.read_csv(snakemake.input.gas_storage_capacities, index_col=0)[
        "storage update (GWh)"
    ]

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
