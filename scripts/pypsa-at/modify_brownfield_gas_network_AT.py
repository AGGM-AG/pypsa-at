# SPDX-FileCopyrightText: 2023-2025 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""Modify the clustered gas network in Austria with more accurate data from AGGM experts."""

import logging

import geopandas as gpd
import numpy as np
import pandas as pd
from pypsa.geo import haversine_pts

from mods.clustering.utils import _map_at_nuts3_to_nuts2
from scripts._helpers import configure_logging
from scripts.cluster_gas_network import (
    aggregate_parallel_pipes,
    load_bus_regions,
    reindex_pipes,
)

logger = logging.getLogger(__name__)

# correction factor for pipeline length between region centroids; same value as cluster_gas_network default
LENGTH_FACTOR = 1.25

# suffix "(1)", "(2)", marking parallel pipes along the same corridor
_PARALLEL_SUFFIX = r"(\(\d+\))$"


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


def _corridor_keys(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """
    Build directionless corridor keys for pairing opposite-direction rows.

    Parameters
    ----------
    df
        AGGM gas pipeline corridor data with ``bus0`` and ``bus1`` columns.

    Returns
    -------
    :
        The bus pair alone, and the bus pair combined with the ``(n)``
        parallel-line suffix parsed off the row index.
    """
    suffix = df.index.to_series().str.extract(_PARALLEL_SUFFIX, expand=False).fillna("")
    bus_pair = pd.Series(
        [" <-> ".join(sorted(buses)) for buses in zip(df["bus0"], df["bus1"])],
        index=df.index,
    )
    return bus_pair, bus_pair + " " + suffix


def collapse_directional_pipeline_pairs(df: pd.DataFrame) -> pd.DataFrame:
    """
    Collapse opposite-direction pipeline data row pairs into one asymmetric bidirectional row.

    A corridor whose compressors move more gas one way than the other is
    supplied as two unidirectional rows in data. Physically that is a single pipe, so
    both rows are merged into one that carries both capacities: ``p_nom`` holds
    the forward (larger) capacity and ``p_min_pu`` the reverse capacity as a
    fraction of it, as p_min_pu = -1 * reverse-capacity / forward-capacity.

    One row per physical pipe is necessary for the remaining workflow to be consistent.
    ``prepare_sector_network`` then builds a single Link, which
    ``lossy_bidirectional_links`` splits into a forward leg plus a zero-cost
    reverse leg, so investment cost is counted once per pipe.

    Rows pair on their unordered bus pair plus their ``(n)`` parallel-line
    suffix. Everything else passes through untouched: rows that are already
    bidirectional, one-way corridors without a counterpart, and parallel lines
    running in the same direction.

    Parameters
    ----------
    df
        AGGM gas pipeline corridor data with the standard gas network columns.

    Returns
    -------
    :
        The same columns with each directional pair reduced to a single row.

    Notes
    -----
    The collapsed row keeps the forward row's index. Relabelling it to a
    ``<->`` name would collide with genuinely separate parallel corridors that
    already carry that label.

    ``p_min_pu`` is zeroed for the whole carrier by
    ``prepare_sector_network.lossy_bidirectional_links`` before the solve, so
    the fraction written here never reaches the optimisation. It records the
    reverse capacity for the reverse leg to be sized from after the split.
    """
    df = df.copy()
    # the source column is integer typed, as only 0 and -1 occur in the input
    df["p_min_pu"] = df["p_min_pu"].astype(float)

    bus_pair, parallel_line = _corridor_keys(df)
    directional = df["p_min_pu"] == 0
    reverse_rows = []

    for corridor, group in df[directional].groupby(
        parallel_line[directional], sort=False
    ):
        if len(group) != 2 or group["bus0"].nunique() != 2:
            continue  # one-way corridor, or parallel lines in the same direction

        forward = group["p_nom"].idxmax()
        reverse = group.index[group.index != forward][0]
        forward_capacity = group.at[forward, "p_nom"]

        if forward_capacity == 0:
            logger.warning(f"Corridor {corridor} has zero capacity in both directions.")
            continue

        if group["build_year"].nunique() > 1:
            logger.warning(
                f"Corridor {corridor} pairs rows with differing build years "
                f"{sorted(group['build_year'])}. Keeping the forward direction's."
            )

        df.at[forward, "p_min_pu"] = -group.at[reverse, "p_nom"] / forward_capacity
        df.at[forward, "name"] = (
            f"{group.at[forward, 'name']} {group.at[reverse, 'name']}"
        )
        reverse_rows.append(reverse)

    df = df.drop(index=reverse_rows)

    # rows left in both directions mean the parallel line suffixes did not line
    # up one to one, so the pair was skipped above
    unpaired = df[df["p_min_pu"] == 0]
    for corridor, group in unpaired.groupby(bus_pair[unpaired.index], sort=False):
        if group["bus0"].nunique() == 2:
            logger.warning(
                f"Corridor {corridor} still has rows in both directions after pairing "
                f"by parallel line suffix: {list(group.index)}. Left as one-way rows."
            )

    logger.info(f"Collapsed {len(reverse_rows)} directional AGGM row pair(s).")
    return df


def calculate_corridor_lengths(
    df: pd.DataFrame,
    bus_regions: gpd.GeoDataFrame,
    length_factor: float = LENGTH_FACTOR,
) -> pd.Series:
    """
    Calculate region-center to node-center lengths of corridors for AGGM added gas pipelines.
    This function mirrors the original ``cluster_gas_network.build_clustered_gas_network`` used for the rest of Europe.
    It returns the haversine distance between the two bus regions' centroids, scaled by the LENGTH_FACTOR to approximate
    real life routing distance.

    Parameters
    ----------
    df
        AGGM provided transport corridors with only the ``bus0`` and ``bus1`` columns.
    bus_regions
        region shapes as returned by ``cluster_gas_network.load_bus_regions``, indexed by region name
    length_factor
        factor applied to straight centroid distance to account for real-life routing distance

    Returns
    -------
    :
        Corridor lengths in km, indexed the same as ``df``.
    """
    centroids = bus_regions.to_crs(3035).centroid.to_crs(4326)
    point0 = df["bus0"].map(centroids)
    point1 = df["bus1"].map(centroids)

    missing = df.index[point0.isna() | point1.isna()]
    if not missing.empty:
        raise ValueError(
            f"No regional centroid found for corridor bus(es) of: {list(missing)}."
        )
    length = pd.Series(
        [
            length_factor * haversine_pts([p0.x, p0.y], [p1.x, p1.y])
            for p0, p1 in zip(point0, point1)
        ],
        index=df.index,
    )
    return length


def update_gas_transport_data(
    gas_network_raw_df: pd.DataFrame, gas_network_input_df: pd.DataFrame
) -> pd.DataFrame:
    """
    Combine transport corridors in gas_network_input_df and gas_network_raw_df.

    Parameters
    ----------
    gas_network_raw_df :
        clustered gas network data generated from Sci2Grid dataset in normal PyPSA-Eur workflow
    gas_network_input_df :
        clustered gas network data with input from AGGM gas grid experts for Austria


    Returns
    -------
    new_gas_network_df :
        clustered gas network data of combined inputs

    Notes
    -----
    This function overwrites all accessible physical parameters of the brownfield gas network with AGGM expert data.
    Only changes Austria specific transport corridors.
    Overwrites raw_df data with new input data where available.
    Adds new input data of transport corridors not in raw_df to new_df.
    """
    raw = gas_network_raw_df.copy()
    raw = raw[~(raw["bus0"].str.startswith("AT") | raw["bus1"].str.startswith("AT"))]

    input_data = gas_network_input_df.copy()
    valid_buses = set(gas_network_raw_df["bus0"]).union(set(gas_network_raw_df["bus1"]))

    input_data = input_data[
        (
            input_data["bus0"].str.startswith("AT")
            | input_data["bus1"].str.startswith("AT")
        )
        & (
            input_data["bus0"].str.startswith("AT")
            | input_data["bus0"].isin(valid_buses)
        )
        & (
            input_data["bus1"].str.startswith("AT")
            | input_data["bus1"].isin(valid_buses)
        )
    ]

    return pd.concat([raw, input_data])


if __name__ == "__main__":
    if "snakemake" not in globals():
        from scripts._helpers import mock_snakemake

        snakemake = mock_snakemake(
            "modify_brownfield_gas_network_AT",
            simpl="",
            clusters="adm",
            opts="",
            ll="v1.25",
            sector_opts="none",
            planning_horizons="2020",
            run="AT_KN2040",
        )
    configure_logging(snakemake)
    config = snakemake.config

    mods = config["mods"]
    custom_clustering = mods["modify_nuts3_shapes"]

    gas_network_raw = snakemake.input.clustered_gas_network_raw
    gas_network_raw_df = pd.read_csv(gas_network_raw, index_col=0)

    if mods["modify_brownfield_gas_network_AT"]:
        gas_network_input_df = pd.read_csv(
            snakemake.input.brownfield_gas_network_AT35, index_col=0
        )
        if custom_clustering.startswith("AT10"):
            gas_network_input_df = aggregate_gas_pipeline_corridors_to_nuts2(
                gas_network_input_df
            )
        elif not custom_clustering.startswith("AT35"):
            raise ValueError(
                f"Unexpected clustering detected: {custom_clustering}. "
                f"Chose from {('AT10DE5', 'AT35DE5')}."
            )

        # merge opposite-direction rows of one physical pipe into a single
        # bidirectional corridor. Must run after the NUTS2 aggregation.
        gas_network_input_df = collapse_directional_pipeline_pairs(gas_network_input_df)

        # update data in raw where AGGM data is supplied
        new_gas_network_df = update_gas_transport_data(
            gas_network_raw_df, gas_network_input_df
        )

        # calculate lengths for Austrian gas pipelines in the standard
        # node-center to node-center distance calculation. Only for
        # AGGM-originated rows added in update_gas_transport_data.
        aggm_rows = new_gas_network_df.index.isin(gas_network_input_df.index)
        bus_regions = load_bus_regions(
            snakemake.input.regions_onshore, snakemake.input.regions_offshore
        )
        new_gas_network_df.loc[aggm_rows, "length"] = calculate_corridor_lengths(
            new_gas_network_df.loc[aggm_rows], bus_regions
        )

        # return updated dataset
        new_gas_network_df.to_csv(snakemake.output.clustered_gas_network)

        logger.info("Modified Austrian gas network with AGGM input data.")

    else:
        gas_network_raw_df.to_csv(snakemake.output.clustered_gas_network)
