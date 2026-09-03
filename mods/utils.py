# SPDX-FileCopyrightText: 2023-2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""Shared utilities used by both `mods.constraints` and `mods.network` subpackages."""

import logging
from pathlib import Path
from typing import Any, Literal

import geopandas as gpd
import numpy as np
import pandas as pd
import pypsa
import xarray as xr
from pypsa import Network
from snakemake.script import Snakemake

from mods.clustering.utils import _map_at_nuts3_to_nuts2
from mods.constants import ISLAND_SPLIT_NODES, TYNDP_TO_PYPSA_LOCATION
from scripts._helpers import load_costs
from scripts.add_electricity import load_and_aggregate_powerplants
from scripts.cluster_gas_network import aggregate_parallel_pipes, reindex_pipes

logger = logging.getLogger(__name__)

__all__ = ["get_tyndp_location", "get_relevant_links_and_lines"]


def get_tyndp_location(n: pypsa.Network) -> dict[str, str]:
    """
    Build a mapping from PyPSA bus names to TYNDP country-level location codes.

    Parameters
    ----------
    n : pypsa.Network
        The PyPSA network whose buses are to be mapped.

    Returns
    -------
    dict[str, str]
        Mapping of bus name to TYNDP location code (e.g. ``"AT31"`` → ``"AT"``,
        ``"XK"`` → ``"RS"``).

    Notes
    -----
    The mapping is built in four steps:

    1. Only *spatial* buses are included — those where
       ``n.buses.index == n.buses.location`` (excludes sector-coupling buses
       such as ``"AT31 gas"``).
    2. The synthetic ``"EU"`` aggregation bus is dropped.
    3. All buses whose name starts with ``"AT"`` or ``"DE"`` are collapsed to
       their country code (``"AT"`` or ``"DE"``), because these countries are
       modelled at NUTS2/3 resolution.
    4. ``"XK"`` (Kosovo) is mapped to ``"RS"`` (Serbia) because Kosovo is not
       a standalone ENTSO-E grid zone and shares the RS zone in the TYNDP data.
    """
    buses = n.buses[n.buses.index == n.buses.location].location.drop(
        index="EU", errors="ignore"
    )

    group_countries = ["AT", "DE"]
    for country in group_countries:
        buses.loc[buses.index.str.startswith(country)] = country

    if "XK" in buses.index:
        buses["XK"] = "RS"
    return buses.to_dict()


def get_relevant_links_and_lines(n: pypsa.Network) -> tuple[pd.DataFrame, pd.DataFrame]:
    """


    Parameters
    ----------
    n : pypsa.Network
        PyPSA network containing the grid topology.

    Returns
    -------
    relevant_links : pd.DataFrame
        Active DC Links that cross a TYNDP border, with two extra columns
        ``bus0_tyndp`` and ``bus1_tyndp`` holding the TYNDP location codes.
    relevant_lines : pd.DataFrame
        Active AC Lines that cross a TYNDP border, with two extra columns
        ``bus0_tyndp`` and ``bus1_tyndp`` holding the TYNDP location codes.

    Raises
    ------
    ValueError
        If any model border corridor (derived from active AC Lines and DC Links)
        is absent from ``tyndp_transmission``. This ensures every cross-border
        flow in the model has a corresponding NTC capacity entry.

    Notes
    -----
    * Bus-to-location mapping is performed by :func:`get_tyndp_location`.
    * Only connections where the two endpoints belong to *different* TYNDP
      locations are treated as cross-border.
    * Border direction is normalised (alphabetically smaller node first) before
      deduplication and comparison, matching the normalisation applied when
      building the TYNDP CSV.
    * The check is asymmetric: model borders missing from TYNDP raise an error
      (strict), whereas TYNDP borders missing from the model emit only a warning
      (lenient) — corridors defined in TYNDP but absent from the network are
      accepted because not all interconnectors may be modelled.
    """
    tyndp_location_dict = get_tyndp_location(n)

    relevant_lines = n.lines[(n.lines.carrier == "AC") & n.lines.active].copy()
    relevant_lines["bus0_tyndp"] = relevant_lines["bus0"].map(tyndp_location_dict)
    relevant_lines["bus1_tyndp"] = relevant_lines["bus1"].map(tyndp_location_dict)
    relevant_lines = relevant_lines[
        relevant_lines["bus0_tyndp"] != relevant_lines["bus1_tyndp"]
    ]

    relevant_links = n.links[(n.links.carrier == "DC") & (n.links.active)].copy()
    relevant_links["bus0_tyndp"] = relevant_links["bus0"].map(tyndp_location_dict)
    relevant_links["bus1_tyndp"] = relevant_links["bus1"].map(tyndp_location_dict)
    relevant_links = relevant_links[
        relevant_links["bus0_tyndp"] != relevant_links["bus1_tyndp"]
    ]

    return relevant_links, relevant_lines


def sanity_check_links_and_lines(relevant_links, relevant_lines, tyndp_transmission):
    """
    Validate that all model cross-border corridors are covered by the TYNDP data.

    Maps every active AC Line and DC Link in the network to its TYNDP location
    code, identifies cross-border connections, and checks that the set of model
    corridors is a subset of the corridors defined in the TYNDP CSV.

    Parameters
    ----------
    relevant_links
    relevant_lines
    tyndp_transmission

    Returns
    -------
    :
    """
    border_links = relevant_links[["bus0_tyndp", "bus1_tyndp"]].drop_duplicates()
    border_lines = relevant_lines[["bus0_tyndp", "bus1_tyndp"]].drop_duplicates()
    borders = pd.concat([border_links, border_lines])
    # .values strips the column index so pandas does not attempt to align
    # bus1_tyndp → bus0_tyndp and bus0_tyndp → bus1_tyndp by label, which
    # would produce NaN instead of swapping.
    borders.loc[
        borders.bus0_tyndp > borders.bus1_tyndp, ["bus0_tyndp", "bus1_tyndp"]
    ] = borders.loc[
        borders.bus0_tyndp > borders.bus1_tyndp, ["bus1_tyndp", "bus0_tyndp"]
    ].values
    borders = borders.drop_duplicates().sort_values(["bus0_tyndp", "bus1_tyndp"])

    border_tup = list(borders.itertuples(index=False, name=None))
    df_tup = list(
        tyndp_transmission[["from_node", "to_node"]].itertuples(index=False, name=None)
    )

    df_tup_set = set(df_tup)
    border_tup_set = set(border_tup)
    borders_not_in_tyndp = [bt for bt in border_tup if bt not in df_tup_set]
    tyndp_not_in_borders = [dt for dt in df_tup if dt not in border_tup_set]

    if len(borders_not_in_tyndp) > 0:
        raise ValueError(
            f"The following borders are not part of tyndp: {borders_not_in_tyndp}"
        )

    if len(tyndp_not_in_borders) > 0:
        logger.warning(
            f"The following borders are not part of the model: {tyndp_not_in_borders}"
        )


def attach_resource_to_network_meta(
    n, dct: dict[str, Any], errors: Literal["raise", "warn", "ignore"] = "raise"
) -> None:
    """
    Adds the given dictionary to the network resource metadata for postprocessing.

    Parameters
    ----------
    n
        The network to modify metadata for
    dct
        The dictionary to add to the network metadata
    errors
        Whether key conflict errors should be raised, warned or ignores

    Returns
    -------
    :
        Network is modified inplace
    """
    if not hasattr(n, "meta"):
        raise AttributeError("Network is missing meta attribute!")

    if "resources" not in n.meta.keys():
        n.meta["resources"] = {}

    existing_keys = set(n.meta["resources"].keys())
    new_keys = set(dct.keys())
    key_overlap = existing_keys.intersection(new_keys)
    if len(key_overlap) > 0:
        match errors:
            case "raise":
                raise AttributeError(
                    f"Trying to overwrite existing resource keys in n.meta: {key_overlap}."
                )
            case "warn":
                logger.warning(
                    f"Overwriting existing resource keys in n.meta: {key_overlap}."
                )

    n.meta["resources"] |= dct
    logger.info(f"Attached {dct.keys()} to network meta.")


def attach_resources_to_network_meta(n: Network, snakemake: Snakemake) -> None:
    """
    Attaches given resources to the mets object of the network.

    This function adds a dictionary under n.meta["resources"] containing relevant resource data for testing and
    post-processing.

    Parameters
    ----------
    n
        The pypsa network
    snakemake
        The Snakemake workflow object providing inputs, params, and config.

    Returns
    -------
    :
        Modifies network inplace.
    """
    resources = snakemake.params.resource_meta
    energy_year = snakemake.params["energy_year"]
    investment_year = snakemake.wildcards.planning_horizons

    filename_readers = {
        "energy_totals": lambda path: (
            pd.read_csv(path, index_col=[0, 1])
            .xs(energy_year, level="year")
            .to_dict(orient="tight")
        ),
        "co2_totals": lambda path: pd.read_csv(path, index_col=0).to_dict(
            orient="tight"
        ),
        "aggm_gas_pipeline_data": lambda path: pd.read_csv(path, index_col=0).to_dict(),
        "inflow_data": lambda path: (
            xr.open_dataarray(path)
            .assign_coords(time=lambda ds: pd.to_datetime(ds.time.values).astype(str))
            .to_dict()
        ),
        "powerplants": lambda path: load_and_aggregate_powerplants(
            path,
            load_costs(snakemake.input.costs),
            snakemake.params.consider_efficiency_classes,
            snakemake.params.aggregation_strategies,
            snakemake.params.exclude_carriers,
        ).to_dict(),
    }
    suffix_readers = {
        ".nc": lambda path: xr.open_dataarray(path).to_dict(),
        ".csv": lambda path: pd.read_csv(path).to_dict(),
        ".geopandas": lambda path: gpd.read_file(path).to_dict(),
    }

    for name, file in resources.items():
        path = Path(file)
        suffix = path.suffix
        if name in filename_readers.keys():
            attach_resource_to_network_meta(n, {name: filename_readers[name](path)})
        elif suffix in suffix_readers.keys():
            attach_resource_to_network_meta(n, {name: suffix_readers[suffix](path)})
        else:
            logger.warning(
                f"Unknown file name {name} and extension {path.suffix}. Attaching file path"
            )
            attach_resource_to_network_meta(n, {name: file})
    n.name = f"PyPSA-AT Network {investment_year}"


def resolve_tyndp_locations(
    admin_levels: dict, custom_clustering: str | bool, mapping: dict | None = None
) -> dict:
    """
    Resolve a TYNDP location mapping for the clustering configuration.

    The static mappings target the custom clustering with all island
    splits applied (e.g. ``IT0``/``IT1``/``IT2``). Island nodes only
    exist if the custom clustering is active and the country is
    clustered at administrative level 1; for any other level the island
    nodes collapse to the plain country code, so locations missing from
    the network never enter the workflow.

    Parameters
    ----------
    admin_levels
        Per-country administrative clustering levels from
        ``config.clustering.administrative``.
    custom_clustering
        The custom clustering name from ``config.mods.modify_nuts3_shapes``
        or a falsy value if the custom clustering is disabled.
    mapping
        The TYNDP location mapping to resolve. Defaults to
        ``TYNDP_TO_PYPSA_LOCATION``.

    Returns
    -------
    :
        The mapping with disabled island nodes replaced by country codes.
    """
    if mapping is None:
        mapping = TYNDP_TO_PYPSA_LOCATION
    if custom_clustering:
        reverse_island_split = {
            node: country
            for country, nodes in ISLAND_SPLIT_NODES.items()
            if admin_levels.get(country) != 1
            for node in nodes
        }
        return {
            region: reverse_island_split.get(node, node)
            for region, node in mapping.items()
        }
    else:
        return mapping


def aggregate_gas_pipeline_corridors_to_nuts2(df: pd.DataFrame) -> pd.DataFrame:
    """
    Aggregate AT gas pipeline corridors from NUTS3 (AT35) to NUTS2 (AT10) resolution.

    Remaps ``bus0``/``bus1`` from AT NUTS3 codes to their NUTS2 parents via
    `mods.clustering.utils._map_at_nuts3_to_nuts2`,  drops corridors that collapse onto a single
    NUTS2 region (self-loops), and collapses parallel corridors between the
    same NUTS2 bus pair by reusing `scripts.cluster_gas_network.reindex_pipes`
    and `scripts.cluster_gas_network.aggregate_parallel_pipes` — the same
    parallel-corridor collapse used to build in the PyPSA-Eur workflow.

    Parameters
    ----------
    df
        AGGM gas pipeline corridor data at AT35 (NUTS3) resolution, with the
        standard gas network columns (``bus0``, ``bus1``, ``p_nom``,
        ``p_nom_diameter``, ``max_pressure_bar``, ``build_year``,
        ``diameter_mm``, ``length``, ``name``, ``p_min_pu``).

    Returns
    -------
    :
        The same columns aggregated to AT NUTS2 (AT10) resolution, reindexed
        to unique ``"gas pipeline BUS0 -> BUS1"`` / ``"... <-> ..."`` labels.

    Notes
    -----
    ``build_year`` uses ``0`` as an "unknown year" sentinel in the AGGM input
    data. Averaging that in with real years would bias the mean towards 0, so
    zeros are treated as missing for the aggregation and only restored where
    every merged corridor segment had an unknown year.
    """
    columns = df.columns
    df = df.copy()
    df["bus0"] = df["bus0"].map(_map_at_nuts3_to_nuts2)
    df["bus1"] = df["bus1"].map(_map_at_nuts3_to_nuts2)
    df = df.loc[df["bus0"] != df["bus1"]]

    df["bidirectional"] = df["p_min_pu"] == -1
    df["build_year"] = df["build_year"].astype(float).replace(0, np.nan)

    reindex_pipes(df)
    df = aggregate_parallel_pipes(df)

    df["build_year"] = df["build_year"].fillna(0).round().astype(int)
    return df[columns]
