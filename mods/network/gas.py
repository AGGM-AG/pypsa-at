# SPDX-FileCopyrightText: 2023-2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""Gas-related pre-network modifications for the ``modify_prenetwork`` step."""

from logging import getLogger

import numpy as np
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


def _gas_pipeline_legs(retrofits: pd.Index) -> pd.Index:
    """
    Map retrofitted H2 pipeline names to their gas pipeline leg.

    ``H2 pipeline retrofitted A <-> B-reversed-2030`` becomes
    ``gas pipeline A <-> B-reversed``: the build-year suffix of a myopic
    run is stripped and the carrier prefix swapped.

    Parameters
    ----------
    retrofits
        Names of ``H2 pipeline retrofitted`` links.

    Returns
    -------
    :
        The matching ``gas pipeline`` leg names, in the same order.
    """
    return retrofits.str.replace(r"-\d{4}$", "", regex=True).str.replace(
        "H2 pipeline retrofitted", "gas pipeline", regex=False
    )


def _forward(links: pd.DataFrame) -> pd.DataFrame:
    """Drop the reverse legs of split bidirectional links."""
    is_reversed = links.get("reversed", pd.Series(False, index=links.index))
    return links[~is_reversed.fillna(False).astype(bool)]


def check_retrofit_pairing(n: pypsa.Network) -> None:
    """
    Verify that upstream's positional retrofit coupling is well-defined.

    ``add_pipe_retrofit_constraint`` in ``scripts/solve_network.py`` adds
    ``gas + H2 / ratio = p_nom`` by pairing the extendable forward
    ``gas pipeline`` legs with the extendable forward ``H2 pipeline
    retrofitted`` candidates by position. With unequal counts linopy silently
    drops the H2 term, fixes the gas pipelines at ``p_nom`` and leaves the
    retrofits unconstrained; with a different order it couples the wrong
    corridors. Both cases fail here instead.

    Parameters
    ----------
    n
        Pre-network after the gas pipeline modifications.

    Raises
    ------
    ValueError
        If the two sets differ in length, membership or order.
    """
    links = _forward(n.links[n.links["p_nom_extendable"]])
    gas_legs = links.index[links["carrier"] == "gas pipeline"]
    candidates = links.index[links["carrier"] == "H2 pipeline retrofitted"]
    if candidates.empty:
        return

    paired = _gas_pipeline_legs(candidates)
    if len(gas_legs) != len(paired) or (gas_legs.to_numpy() != paired.to_numpy()).any():
        unpaired = gas_legs.symmetric_difference(paired)
        raise ValueError(
            "Extendable gas pipelines and retrofit candidates are not paired one to "
            f"one in the same order ({len(gas_legs)} gas pipelines, {len(paired)} "
            f"candidates). Unpaired: {list(unpaired)[:10]}."
        )


def retrofit_start_year(config: dict) -> float:
    """
    First planning horizon in which gas pipelines may be retrofitted to H2.

    Reuses the upstream ``first_technology_occurrence`` entry for the
    ``H2 pipeline retrofitted`` carrier, which PyPSA-DE drops before that
    year. Without the entry retrofitting is allowed from the first horizon
    on; with ``sector.H2_retrofit`` disabled it is never allowed.

    Parameters
    ----------
    config
        The workflow configuration.

    Returns
    -------
    :
        The retrofit start year, ``inf`` when retrofitting is disabled.
    """
    if not config["sector"].get("H2_retrofit", False):
        return float("inf")
    first_occurrence = config.get("first_technology_occurrence") or {}
    return float(first_occurrence.get("Link", {}).get("H2 pipeline retrofitted", 0))


def make_gas_pipelines_unextendable(n: pypsa.Network, snakemake: Snakemake) -> None:
    """
    Fix the methane grid at its target capacity up to the threshold year.

    Up to and including ``mods.threshold_year_for_gas_grid_expansion`` no
    new methane pipelines (``gas pipeline new``) can be built. Existing
    pipelines (``gas pipeline``) are fixed only before the retrofit start
    year (see :func:`retrofit_start_year`). From the retrofit start year on
    they stay extendable within their target capacity (``p_nom_min = 0``,
    ``p_nom_max = p_nom``), so the upstream retrofit constraint
    ``gas + H2 / H2_retrofit_capacity_per_CH4 = p_nom`` binds and retrofitted
    H2 capacity gives way to gas capacity on the same corridor.

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

    pyear = int(snakemake.wildcards.planning_horizons)
    threshold_year = int(mods["threshold_year_for_gas_grid_expansion"])
    if pyear > threshold_year:
        logger.info(
            f"Skip fixing gas pipeline capacities in {pyear}, after the "
            f"threshold year {threshold_year}."
        )
        return

    is_new = n.links["carrier"] == "gas pipeline new"
    n.links.loc[is_new, "p_nom_extendable"] = False

    is_existing = n.links["carrier"] == "gas pipeline"
    retrofit_start = retrofit_start_year(snakemake.config)
    if pyear < retrofit_start:
        n.links.loc[is_existing, "p_nom_extendable"] = False
        logger.info(
            f"Fixed {is_existing.sum()} gas pipeline(s) and {is_new.sum()} candidate(s) "
            f"for new gas pipelines in {pyear}, before the retrofit start year."
        )
        return

    # keep the pipelines extendable within their target capacity, so that the
    # upstream retrofit constraint couples gas and retrofitted H2 capacity.
    # The constraint pairs gas pipelines and candidates by position, so a gas
    # pipeline without an extendable candidate (e.g. a German corridor frozen
    # by the Kernnetz logic) is fixed: it cannot be retrofitted anyway and
    # would otherwise shift the pairing.
    candidates = n.links.index[
        (n.links["carrier"] == "H2 pipeline retrofitted") & n.links["p_nom_extendable"]
    ]
    paired = is_existing & n.links.index.isin(_gas_pipeline_legs(candidates))
    n.links.loc[is_existing & ~paired, "p_nom_extendable"] = False
    n.links.loc[paired, "p_nom_extendable"] = True
    n.links.loc[paired, "p_nom_min"] = 0.0
    n.links.loc[paired, "p_nom_max"] = n.links.loc[paired, "p_nom"]
    check_retrofit_pairing(n)
    logger.info(
        f"Fixed {is_new.sum()} candidate(s) for new gas pipelines and "
        f"{(is_existing & ~paired).sum()} gas pipeline(s) without a retrofit "
        f"candidate in {pyear}. {paired.sum()} gas pipeline(s) may be retrofitted "
        "to H2 within their target capacity."
    )


def restore_asymmetric_pipeline_capacities(
    n: pypsa.Network, snakemake: Snakemake
) -> None:
    """
    Resize the reverse legs of Austrian one-way and asymmetric gas pipelines.

    ``lossy_bidirectional_links`` copies ``p_nom`` onto every reverse leg. Up to
    ``mods.threshold_year_for_gas_grid_expansion`` and before the retrofit start
    year (see :func:`retrofit_start_year`) this resets those legs to the reverse
    capacity (zero for one-way pipes) and fixes them. From the retrofit start
    year on the reverse leg follows the forward leg: adapting the compressor
    stations is assumed to be free next to the retrofit itself.

    Parameters
    ----------
    n
        Pre-network, modified in place.
    snakemake
        Provides the config and the clustered gas network.

    Raises
    ------
    ValueError
        If a corridor in the network has no reverse leg.
    """
    mods = snakemake.config["mods"]
    if not mods.get("modify_brownfield_gas_network_AT"):
        logger.info(
            "Skip restoring asymmetric gas pipeline capacities because the "
            "brownfield gas network modification is disabled."
        )
        return

    pyear = int(snakemake.wildcards.planning_horizons)
    threshold_year = int(mods["threshold_year_for_gas_grid_expansion"])
    if pyear > threshold_year:
        logger.info(
            f"Skip restoring asymmetric gas pipeline capacities in {pyear}, after the "
            f"threshold year {threshold_year}. One-way and asymmetric corridors regain "
            "their full reverse capacity at no cost (known limitation)."
        )
        return

    retrofit_start = retrofit_start_year(snakemake.config)
    if pyear >= retrofit_start:
        logger.info(
            f"Skip restoring asymmetric gas pipeline capacities in {pyear}, from the "
            f"retrofit start year {retrofit_start:.0f} on. Reverse legs follow the "
            "forward leg, so retrofitting shrinks both flow directions alike."
        )
        return

    gas_network = pd.read_csv(snakemake.input.clustered_gas_network, index_col=0)
    austrian = gas_network["bus0"].str.startswith("AT") | gas_network[
        "bus1"
    ].str.startswith("AT")
    # interval (-1, 0] contains every corridor whose reverse direction carries less than its
    # forward direction, from a compressor-limited one down to a one-way pipe at
    # exactly 0. A symmetric corridor sits at -1 and is left alone.
    constrained = gas_network["p_min_pu"].between(-1, 0, inclusive="right")
    directional = gas_network[austrian & constrained]
    if directional.empty:
        logger.info(
            "No Austrian gas pipelines with a constrained reverse direction in "
            "the clustered gas network."
        )
        return

    gas_pipes = n.links[n.links["carrier"] == "gas pipeline"]
    is_reversed = gas_pipes.get("reversed", pd.Series(False, index=gas_pipes.index))
    if not is_reversed.fillna(False).any():
        logger.info(
            "Gas pipelines were not split into separate flow directions, so the "
            "asymmetric bounds of the corridors themselves still apply."
        )
        return

    # corridors outside the modeled scope never made it into the network
    corridors = directional.index.intersection(gas_pipes.index)
    reverse_legs = corridors + "-reversed"

    missing = reverse_legs.difference(gas_pipes.index)
    if not missing.empty:
        raise ValueError(
            f"Asymmetric gas pipelines without a reverse leg to resize: {list(missing)}."
        )

    # p_min_pu lies in (-1, 0] here, so its magnitude is the reverse share of
    # p_nom. Negating it instead would put -0.0 on the one-way reverse legs.
    reverse_capacity = pd.Series(
        (
            directional.loc[corridors, "p_min_pu"].abs()
            * directional.loc[corridors, "p_nom"]
        ).to_numpy(),
        index=reverse_legs,
    )

    for attribute in ("p_nom", "p_nom_min", "p_nom_max"):
        n.links.loc[reverse_legs, attribute] = reverse_capacity
    n.links.loc[reverse_legs, "p_nom_extendable"] = False

    one_way = reverse_capacity == 0
    logger.info(
        f"Restored the reverse capacity of {len(reverse_legs)} Austrian gas pipeline(s), "
        f"totalling {reverse_capacity.sum() / 1e3:.1f} GW, of which {one_way.sum()} "
        f"one-way corridor(s) were closed in the reverse direction."
    )


def deduct_retrofitted_gas_capacity(n: pypsa.Network, snakemake: Snakemake) -> None:
    """
    Lower the gas pipeline capacity by the H2 capacity retrofitted earlier.

    Upstream ``add_brownfield`` means to subtract carried-over
    ``H2 pipeline retrofitted`` capacity from the ``gas pipeline`` legs, but
    its name mapping keeps the build-year suffix of the retrofit while gas
    pipelines never carry one, so nothing is deducted. This function maps
    every carried-over retrofit (build year before the planning horizon, both
    legs) to its gas pipeline leg and lowers ``p_nom`` and ``p_nom_max`` to
    ``target - carried / H2_retrofit_capacity_per_CH4``, where the target is
    the forward capacity in the clustered gas network for both legs.

    The new values are the minimum of the current and the deducted capacity,
    clipped at zero. This keeps the function idempotent and guards against a
    double deduction should upstream fix its mapping. On corridors where
    upstream lowers the gas capacity for other reasons (Wasserstoff-Kernnetz)
    only the larger reduction survives.

    Parameters
    ----------
    n
        Pre-network, modified in place.
    snakemake
        Provides the config, the planning horizon and the clustered gas network.

    Raises
    ------
    ValueError
        If a carried-over retrofit maps to no gas pipeline leg, or a gas
        pipeline leg has no target capacity in the clustered gas network.
    """
    sector = snakemake.config["sector"]
    if not sector.get("H2_retrofit", False):
        logger.info(
            "Skip deducting retrofitted gas capacity because H2 retrofitting is disabled."
        )
        return

    pyear = int(snakemake.wildcards.planning_horizons)
    retrofits = n.links[n.links["carrier"] == "H2 pipeline retrofitted"]
    carried = retrofits[retrofits["build_year"] < pyear]
    if carried.empty:
        logger.info(f"No retrofitted H2 pipelines carried over into {pyear}.")
        return

    gas_legs = _gas_pipeline_legs(carried.index)
    carried_h2 = carried["p_nom"].groupby(gas_legs.to_numpy()).sum()

    gas_pipes = n.links[n.links["carrier"] == "gas pipeline"]
    missing = carried_h2.index.difference(gas_pipes.index)
    if not missing.empty:
        raise ValueError(
            "Carried-over retrofitted H2 pipelines without a gas pipeline leg: "
            f"{list(missing)}."
        )

    legs = carried_h2.index
    corridors = legs.str.replace("-reversed", "", regex=False)
    gas_network = pd.read_csv(snakemake.input.clustered_gas_network, index_col=0)
    target = gas_network["p_nom"].reindex(corridors)
    if target.isna().any():
        raise ValueError(
            "Gas pipelines without a target capacity in the clustered gas network: "
            f"{list(corridors[target.isna()])}."
        )

    ch4_per_h2 = 1 / sector["H2_retrofit_capacity_per_CH4"]
    remaining = pd.Series(
        (target.to_numpy() - ch4_per_h2 * carried_h2.to_numpy()).clip(min=0),
        index=legs,
    )
    deducted = 0.0
    for attribute in ("p_nom", "p_nom_max"):
        current = n.links.loc[legs, attribute]
        updated = np.minimum(current, remaining)
        if attribute == "p_nom":
            deducted = (current - updated).sum()
        n.links.loc[legs, attribute] = updated

    logger.info(
        f"Deducted {deducted / 1e3:.1f} GW of gas pipeline capacity on {len(legs)} "
        f"leg(s) for {len(carried)} retrofitted H2 pipeline(s) carried over into {pyear}."
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
