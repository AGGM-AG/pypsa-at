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


def _find_duplicate_gas_pipeline_reversals(links: pd.DataFrame) -> pd.Index:
    """
    Identify fabricated reverse gas pipeline Links that duplicate a real,
    independently-specified opposite-direction Link pair.

    ``lossy_bidirectional_links`` (prepare_sector_network.py) mirrors every
    "gas pipeline" carrier Link into a same-capacity reverse Link, marked
    ``reversed=True``, assuming each Link represents one physically
    bidirectional pipe.
    AGGM brownfield data instead sometimes supplies two
    independent, different capacity Links for AT corridors, representing
    the real gas grid's capacity to transport gas depending on compressors.
    The mirroring step still runs on them, fabricating a duplicate reverse
    Link on top of the real opposite-direction Link, summing both real direction
    capacities onto both final directions and doubling the capacity of a pipeline.

    Parameters
    ----------
    links
        ``n.links``, with ``bus0``, ``bus1``, ``carrier`` and ``reversed``
        columns.

    Returns
    -------
    :
        Index of fabricated Links that already have a monodirectional counterpart.
        Applies only to already existing Link pairs, allowing the duplication
        of real monodirectional Links without reverse counterpart.
    """
    gas_pipes = links[links["carrier"] == "gas pipeline"]
    if "reversed" not in gas_pipes:
        return gas_pipes.index[:0]

    is_reversed = gas_pipes["reversed"].fillna(False)
    real = gas_pipes[~is_reversed]
    fabricated = gas_pipes[is_reversed]

    at_touching = fabricated["bus0"].str.startswith("AT") | fabricated[
        "bus1"
    ].str.startswith("AT")

    real_bus_pairs = set(zip(real["bus0"], real["bus1"]))
    is_duplicate = fabricated.apply(
        lambda link: (link["bus0"], link["bus1"]) in real_bus_pairs, axis=1
    )

    return fabricated.index[at_touching & is_duplicate]


def remove_duplicate_gas_pipeline_reversals(
    n: pypsa.Network, snakemake: Snakemake
) -> None:
    """
    Remove synthetic reverse Links fabricated for real AGGM directional pairs.

    See :func:`_find_duplicate_gas_pipeline_reversals` for why these Links
    are fabricated and why removing them (rather than the real Links) is
    correct.

    Parameters
    ----------
    n
        The pre-network to be modified in place.
    snakemake
        The Snakemake workflow object providing config.

    Returns
    -------
    :
        Removes fabricated duplicate Links from ``n.links`` in place.
    """
    mods = snakemake.config["mods"]
    if not mods.get("modify_brownfield_gas_network_AT"):
        logger.info(
            "Skip removing duplicate gas pipeline reversals because the "
            "brownfield gas network modification is disabled."
        )
        return

    to_remove = _find_duplicate_gas_pipeline_reversals(n.links)
    if to_remove.empty:
        logger.info("No fabricated AT gas pipeline reversals found.")
        return

    n.remove("Link", to_remove)
    logger.info(
        f"Removed {len(to_remove)} synthetic gas pipeline reversal(s) that "
        f"duplicated a real AGGM-supplied opposite-direction Link: "
        f"{list(to_remove)}."
    )


def _find_secondary_direction_gas_pipeline_links(links: pd.DataFrame) -> pd.Index:
    """
    Identify the smaller-capacity direction of each real AT gas pipeline
    corridor that has both directions present.

    AGGM's asymmetric direction pairs (eg. TAG: 45000 MW one way, 11000 MW
    the other) represent one physical pipe whose throughput differs by
    direction because of compressor placement, not two separate pipes.
    ``prepare_sector_network.py`` still computes ``capital_cost`` per Link
    row independently (``length * costs.at["CH4 (g) pipeline", "capital_cost"]``),
    and since length is now identical for both directions (centroid distance
    doesn't depend on order), both rows carry the full investment cost of
    what is actually one asset — doubling reported CAPEX for that corridor.

    Parameters
    ----------
    links
        ``n.links``, expected to already have fabricated reversals removed
        (see :func:`_find_duplicate_gas_pipeline_reversals`) so only real
        rows are considered.

    Returns
    -------
    :
        Index of the smaller-capacity-direction Links whose cost should be
        zeroed. A corridor with only one AGGM-supplied direction is left
        alone — there's only one row, nothing to double-count.
    """
    gas_pipes = links[links["carrier"] == "gas pipeline"]
    if "reversed" in gas_pipes:
        gas_pipes = gas_pipes[~gas_pipes["reversed"].fillna(False)]

    at_touching = gas_pipes["bus0"].str.startswith("AT") | gas_pipes[
        "bus1"
    ].str.startswith("AT")
    gas_pipes = gas_pipes[at_touching]

    bus_pair = gas_pipes.apply(
        lambda link: tuple(sorted((link["bus0"], link["bus1"]))), axis=1
    )

    secondary = []
    for _, group in gas_pipes.groupby(bus_pair):
        if len(group) != 2:
            continue
        primary = group["p_nom"].idxmax()
        secondary.extend(group.index.difference([primary]))

    return pd.Index(secondary)


def zero_secondary_direction_gas_pipeline_costs(
    n: pypsa.Network, snakemake: Snakemake
) -> None:
    """
    Zero capital cost on the smaller-capacity direction of each real AT gas
    pipeline corridor pair, so one physical pipe's investment cost is
    counted once rather than once per direction.

    See :func:`_find_secondary_direction_gas_pipeline_links` for why.

    Parameters
    ----------
    n
        The pre-network to be modified in place.
    snakemake
        The Snakemake workflow object providing config.

    Returns
    -------
    :
        Zeroes ``capital_cost`` and ``onight_cost`` on the affected Links in
        place. ``p_nom`` and ``length`` are untouched — both directions keep
        their real capacity and their (identical) physical length.
    """
    mods = snakemake.config["mods"]
    if not mods.get("modify_brownfield_gas_network_AT"):
        logger.info(
            "Skip zeroing secondary-direction gas pipeline costs "
            "because the brownfield gas network modification is disabled."
        )
        return

    to_zero = _find_secondary_direction_gas_pipeline_links(n.links)
    if to_zero.empty:
        logger.info("No secondary-direction AT gas pipeline links to zero cost for.")
        return

    n.links.loc[to_zero, ["capital_cost", "onight_cost"]] = 0
    logger.info(
        f"Zeroed capital cost on {len(to_zero)} secondary-direction gas "
        f"pipeline link(s), avoiding double-counting one physical pipe's "
        f"investment cost: {list(to_zero)}."
    )


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
