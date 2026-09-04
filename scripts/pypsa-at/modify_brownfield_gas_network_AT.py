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
        ``p_nom_reverse``, ``p_nom_diameter``, ``max_pressure_bar``,
        ``build_year``, ``diameter_mm``, ``length``, ``name``, ``p_min_pu``).

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

    ``p_nom_reverse`` is aggregated here rather than by
    ``aggregate_parallel_pipes``, whose strategy mapping silently drops columns
    it does not know. Parallel pipes merge by summing each flow direction on
    its own, so blank entries are first resolved to the reverse capacity the
    row implies: the full ``p_nom`` for a bidirectional pipe, zero for a
    one-way one.
    """
    columns = df.columns
    df = df.copy()
    df["bus0"] = df["bus0"].map(_map_at_nuts3_to_nuts2)
    df["bus1"] = df["bus1"].map(_map_at_nuts3_to_nuts2)
    df = df.loc[df["bus0"] != df["bus1"]]

    df["bidirectional"] = df["p_min_pu"] == -1
    df["build_year"] = df["build_year"].astype(float).replace(0, np.nan)
    reverse_capacity = df["p_nom_reverse"].fillna(-df["p_min_pu"] * df["p_nom"])

    reindex_pipes(df)
    # reindex_pipes relabels in place without reordering rows, so the corridor
    # labels transfer to the reverse capacities positionally
    reverse_capacity.index = df.index

    df = aggregate_parallel_pipes(df)
    df["p_nom_reverse"] = reverse_capacity.groupby(level=0).sum()

    df["build_year"] = df["build_year"].fillna(0).round().astype(int)
    return df[columns]


def apply_reverse_flow_limits(df: pd.DataFrame) -> pd.DataFrame:
    """
    Turn the AGGM reverse capacity column into the PyPSA ``p_min_pu`` bound.

    A pipe whose compressors move more gas one way than the other is supplied
    as a single row carrying the forward capacity in ``p_nom`` and the reverse
    capacity in ``p_nom_reverse``. PyPSA expresses that as a fraction of
    ``p_nom``, so the column is converted into
    ``p_min_pu = -p_nom_reverse / p_nom`` and dropped afterwards: the clustered
    gas network resource keeps the standard column set it shares with the
    Sci2Grid corridors it is concatenated with.

    Rows without a reverse capacity keep the ``p_min_pu`` they came with, so
    fully bidirectional (``-1``) and one-way (``0``) pipes pass through
    unchanged.

    Parameters
    ----------
    df
        AGGM gas pipeline corridor data including the ``p_nom_reverse`` column.

    Returns
    -------
    :
        The same rows without ``p_nom_reverse``, with ``p_min_pu`` holding the
        reverse capacity of every asymmetric pipe.

    Notes
    -----
    ``p_min_pu`` is zeroed for the whole carrier by
    ``prepare_sector_network.lossy_bidirectional_links`` before the solve, which
    splits every gas pipeline into a forward leg and a reverse leg of equal
    capacity. The fraction written here is what
    ``mods.network.gas`` reads back to resize that reverse leg.
    """
    df = df.copy()
    reverse_capacity = df.pop("p_nom_reverse")
    asymmetric = reverse_capacity.notna()

    if asymmetric.sum() == 0:
        return df

    # the source column only holds 0 and -1, so it cannot take fractions as is
    df["p_min_pu"] = df["p_min_pu"].astype(float)
    df.loc[asymmetric, "p_min_pu"] = -(
        reverse_capacity[asymmetric] / df.loc[asymmetric, "p_nom"]
    )

    logger.info(
        f"Applied reverse flow limits to {int(asymmetric.sum())} asymmetric gas pipeline(s)."
    )
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

        # express the AGGM reverse capacities as PyPSA p_min_pu bounds. Must run
        # after the NUTS2 aggregation, which sums the reverse capacities of
        # merged parallel pipes.
        gas_network_input_df = apply_reverse_flow_limits(gas_network_input_df)

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
