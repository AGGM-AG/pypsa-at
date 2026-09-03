# SPDX-FileCopyrightText: 2023-2025 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""Modify the clustered gas network in Austria with more accurate data from AGGM experts."""

import logging

import geopandas as gpd
import pandas as pd
from pypsa.geo import haversine_pts

from mods.utils import aggregate_gas_pipeline_corridors_to_nuts2
from scripts._helpers import configure_logging
from scripts.cluster_gas_network import load_bus_regions

logger = logging.getLogger(__name__)

# correction factor for pipeline length between region centroids; same value as cluster_gas_network default
LENGTH_FACTOR = 1.25


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
