# SPDX-FileCopyrightText: 2023-2025 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""Modify the clustered gas network in Austria with more accurate data from AGGM experts."""

import logging

import pandas as pd

from scripts._helpers import configure_logging

logger = logging.getLogger(__name__)


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
        if custom_clustering.startswith("AT10"):
            gas_network_input = snakemake.input.brownfield_gas_network_AT10
        elif custom_clustering.startswith("AT35"):
            gas_network_input = snakemake.input.brownfield_gas_network_AT35
        else:
            raise ValueError(
                f"Unexpected clustering detected: {custom_clustering}. "
                f"Chose from {('AT10DE5', 'AT35DE5')}."
            )
        gas_network_input_df = pd.read_csv(gas_network_input, index_col=0)

        # update data in raw where AGGM data is supplied
        new_gas_network_df = update_gas_transport_data(
            gas_network_raw_df, gas_network_input_df
        )

        # return updated dataset
        new_gas_network_df.to_csv(snakemake.output.clustered_gas_network)

        logger.info("Modified Austrian gas network with AGGM input data.")

    else:
        gas_network_raw_df.to_csv(snakemake.output.clustered_gas_network)
