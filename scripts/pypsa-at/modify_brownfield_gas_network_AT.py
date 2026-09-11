# SPDX-FileCopyrightText: 2023-2025 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""Modify the clustered gas network in Austria with more accurate data from AGGM experts."""

import logging
from pathlib import Path

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


def read_aggm_gas_network(path: str | Path) -> pd.DataFrame:
    """
    Read the AGGM gas network file and reject corridors with zero capacity.

    Parameters
    ----------
    path
        Path to the AGGM gas network CSV file.

    Returns
    -------
    :
        Corridors indexed by name.
    """
    df = pd.read_csv(path, index_col=0)
    zero_capacity = df.index[df["p_nom"] == 0]
    if not zero_capacity.empty:
        raise ValueError(
            f"Gas pipeline corridors with p_nom = 0 in {path}: {list(zero_capacity)}. "
            "Check the file: give each of these corridors its capacity or remove the row."
        )
    return df


def _reverse_direction(df: pd.DataFrame, flip: pd.Series) -> pd.DataFrame:
    """Swap buses and directional capacities of the rows flagged in ``flip``."""
    df = df.copy()
    for first, second in (("bus0", "bus1"), ("p_nom", "p_nom_reverse")):
        df.loc[flip, [first, second]] = df.loc[flip, [second, first]].to_numpy()
    return df


def aggregate_gas_pipeline_corridors_to_nuts2(df: pd.DataFrame) -> pd.DataFrame:
    """
    Merge AT35 (NUTS3) corridors into one corridor per AT10 (NUTS2) region pair.

    Parameters
    ----------
    df
        AGGM corridors at NUTS3 resolution, including ``p_nom_reverse``.

    Returns
    -------
    :
        The same columns at NUTS2 resolution, each flow direction summed on its
        own and the corridor pointing along its stronger direction.
    """
    columns = df.columns
    df = df.copy()
    df["bus0"] = df["bus0"].map(_map_at_nuts3_to_nuts2)
    df["bus1"] = df["bus1"].map(_map_at_nuts3_to_nuts2)
    df = df.loc[df["bus0"] != df["bus1"]].copy()

    # 0 marks an unknown build year; keep it out of the mean
    df["build_year"] = df["build_year"].astype(float).replace(0, np.nan)
    df["p_nom"] = df["p_nom"].astype(float)
    df["p_nom_reverse"] = df["p_nom_reverse"].fillna(-df["p_min_pu"] * df["p_nom"])

    # one orientation per region pair, so parallel rows share a label whichever
    # region AGGM wrote first and whether they are one-way or not
    df = _reverse_direction(df, df["bus0"] > df["bus1"])
    df.index = "gas pipeline " + df["bus0"] + " <-> " + df["bus1"]
    # summed here, as aggregate_parallel_pipes drops columns it does not know
    reverse_capacity = df["p_nom_reverse"].groupby(level=0).sum()

    df = aggregate_parallel_pipes(df)
    df["p_nom_reverse"] = reverse_capacity

    # point each merged corridor along its stronger direction
    df = _reverse_direction(df, df["p_nom_reverse"] > df["p_nom"])
    df["bidirectional"] = df["p_nom_reverse"] > 0
    reindex_pipes(df)

    df["build_year"] = df["build_year"].fillna(0).round().astype(int)
    return df[columns]


def apply_reverse_flow_limits(df: pd.DataFrame) -> pd.DataFrame:
    """
    Express ``p_nom_reverse`` as a ``p_min_pu`` bound and drop the column.

    Parameters
    ----------
    df
        AGGM corridors including ``p_nom_reverse``.

    Returns
    -------
    :
        The corridors without ``p_nom_reverse``; rows without a reverse capacity
        keep their ``p_min_pu``.
    """
    df = df.copy()
    reverse_capacity = df.pop("p_nom_reverse")
    asymmetric = reverse_capacity.notna()

    if asymmetric.sum() == 0:
        return df

    # the source column only holds 0 and -1, so it cannot take fractions as is
    df["p_min_pu"] = df["p_min_pu"].astype(float)
    fraction = -(reverse_capacity[asymmetric] / df.loc[asymmetric, "p_nom"])
    # a reverse capacity of zero is a one-way pipe; write 0.0 rather than -0.0
    df.loc[asymmetric, "p_min_pu"] = fraction.where(
        reverse_capacity[asymmetric] > 0, 0.0
    )

    logger.info(
        f"Applied reverse flow limits to {int(asymmetric.sum())} asymmetric gas pipeline(s)."
    )
    return df


def calculate_corridor_lengths(
    df: pd.DataFrame,
    bus_regions: gpd.GeoDataFrame,
    length_factor: float,
) -> pd.Series:
    """
    Compute corridor lengths from the distance between region centroids.

    Parameters
    ----------
    df
        Corridors with ``bus0`` and ``bus1``.
    bus_regions
        Region shapes indexed by region name, from ``load_bus_regions``; every bus
        needs one.
    length_factor
        Detour factor on the straight distance (``links: length_factor``).

    Returns
    -------
    :
        Lengths in km, indexed like ``df``.
    """
    centroids = bus_regions.to_crs(3035).centroid.to_crs(4326)
    coordinates = pd.DataFrame({"x": centroids.x, "y": centroids.y})
    xy0 = coordinates.reindex(df["bus0"]).to_numpy()
    xy1 = coordinates.reindex(df["bus1"]).to_numpy()

    missing = df.index[np.isnan(xy0).any(axis=1) | np.isnan(xy1).any(axis=1)]
    if not missing.empty:
        raise ValueError(
            f"No regional centroid found for corridor bus(es) of: {list(missing)}."
        )
    return pd.Series(length_factor * haversine_pts(xy0, xy1), index=df.index)


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
        gas_network_input_df = read_aggm_gas_network(
            snakemake.input.brownfield_gas_network_AT35
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
            new_gas_network_df.loc[aggm_rows],
            bus_regions,
            length_factor=snakemake.params.length_factor,
        )

        # return updated dataset
        new_gas_network_df.to_csv(snakemake.output.clustered_gas_network)

        logger.info("Modified Austrian gas network with AGGM input data.")

    else:
        gas_network_raw_df.to_csv(snakemake.output.clustered_gas_network)
