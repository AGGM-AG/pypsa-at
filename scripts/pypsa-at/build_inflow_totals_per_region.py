# SPDX-FileCopyrightText: 2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.

"""
Build total hydroelectric inflows for each model region based on PEMMDB.

Outputs
-------

- ``resources/inflow_totals_per_region_{clusters}.csv``:

    ===================  ================  =========================================================
    Field                Index             Description
    ===================  ================  =========================================================
    inflow               bus, carrier      Inflow totals per region.
                                           e.g. due to river inflow in hydro reservoir.
    ===================  ================  =========================================================
"""

import logging
from pathlib import Path

import pandas as pd

from mods.constants import PROXIES, TYNDP_TO_PYPSA_LOCATION
from scripts._helpers import (
    configure_logging,
    get_snapshots,
    load_costs,
    set_scenario_config,
)
from scripts.add_electricity import load_and_aggregate_powerplants

logger = logging.getLogger(__name__)


def extract_inflow_totals_tyndp(
    hydro_inflows_dir: str, year: int
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Extract hydropower inflow totals from Excel files.

    Reads all Excel files in hydro_inflows_dir/2030/.
    For each file and each year-dependent sheet, sums all rows matching
    "Energy Inflow [GWh/day]" or "Energy Inflow [GWh/week]" for column year.

    Parameters
    ----------
    hydro_inflows_dir:
        Directory for the hydro inflows data
    year:
        Year to extract from data

    Returns
    -------
    tuple:
         (inflow_df, market_info_df)
            - inflow_df: countries x technologies (sheet names)
            - market_info_df: countries x market node info labels
    """
    hydro_dir = Path(hydro_inflows_dir) / "2030"
    excel_files = sorted(hydro_dir.glob("*.xlsx"))

    # Sheet names to process
    year_dependent_sheets = [
        "Run of River - Year Dependent",
        "Pondage - Year Dependent",
        "Reservoir - Year Dependent",
        "PS Open - Year Dependent",
        "PS Closed - Year Dependent",
    ]

    # Data structures for outputs
    inflow_data = {}  # {country: {technology: sum_value}}
    market_info_data = []  # {country: {label: value}}

    for excel_file in excel_files:
        logger.info(f"Processing {excel_file.name}")
        parts = excel_file.stem.split("_")
        country_code = parts[1]
        inflow_data[country_code] = {}

        dfs = pd.read_excel(
            excel_file, sheet_name=year_dependent_sheets, header=1, index_col=[0, 1, 2]
        )

        # Process year-dependent sheets
        for sheet_name, df in dfs.items():
            inflow = df[
                df.index.get_level_values("Variable").isin(
                    ["Energy Inflow [GWh/day]", "Energy Inflow [GWh/week]"]
                )
            ]
            # Extract values from year column for matching rows
            total = inflow[year].sum()
            inflow_data[country_code][sheet_name] = total
        # Extract MarketNodeInfo
        df_market = pd.read_excel(
            excel_file, sheet_name="MarketNodeInfo", header=5, index_col=0
        )
        df_market.columns = [country_code]
        market_info_data.append(df_market.T)

    # Convert to DataFrames
    inflow_df = pd.DataFrame(inflow_data).T
    inflow_df.index.name = "country"
    market_info_df = pd.concat(market_info_data)

    return inflow_df, market_info_df


def process_inflow_per_region(
    inflow_df: pd.DataFrame, market_info_df: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Group PEMMDB inflow data by model carriers

    Parameters
    ----------
    inflow_df
        DataFrame containing Inflow Totals
    market_info_df
        DataFrame containing market info data for hydro technologies

    Returns
    -------
    tuple:
        (inflow_df, market_info_df)
            - inflow_df: countries x technologies (sheet names)
            - market_info_df: countries x market node info labels
    """
    inflow_df = inflow_df.groupby(inflow_df.index.map(TYNDP_TO_PYPSA_LOCATION)).sum()
    market_info_df = market_info_df.groupby(
        market_info_df.index.map(TYNDP_TO_PYPSA_LOCATION)
    ).sum()

    inflow_df *= 1000  # GWh to MWh

    technology_mapping = {
        "Run of River - Year Dependent": "ror",
        "Pondage - Year Dependent": "ror",
        "Reservoir - Year Dependent": "hydro",
        "PS Open - Year Dependent": "PHS",
        "PS Closed - Year Dependent": "PHS",
    }

    inflow_df = inflow_df.groupby(technology_mapping, axis=1).sum()
    return inflow_df, market_info_df


def normalize_ror(
    inflow_df: pd.DataFrame,
    ppl: pd.DataFrame,
    market_info_df: pd.DataFrame,
) -> tuple[pd.Series, dict[str, str]]:
    """
    Normalize ror inflow data using available powerplants capacities

    Parameters
    ----------
    inflow_df
        DataFrame containing Inflow Totals
    ppl
        DataFrame containing capacities for all hydro powerplants
    market_info_df
        DataFrame containing market info data for hydro technologies

    Returns
    -------
    :
        (inflows, region_to_country_mapping)
            - inflows: Inflows as Series
            - region_to_country_mapping: Mapping of model regions to respective tyndp country codes
    """

    inflow_df = (
        inflow_df.stack().rename_axis(index=["country", "carrier"]).rename("inflow")
    )

    powerplants_df = ppl.copy()

    region_to_country_mapping = {
        region: country
        for region in powerplants_df["bus"]
        for country in inflow_df.index.get_level_values("country")
        if region.startswith(country)
    } | PROXIES

    powerplants_df["country"] = powerplants_df["bus"].map(region_to_country_mapping)
    powerplant_sums = powerplants_df.groupby(["country", "carrier"])["p_nom"].sum()

    combined_df = inflow_df.to_frame().join(powerplant_sums, how="outer")
    combined_df["p_nom"] = combined_df["p_nom"].fillna(0)

    combined_df["pure_ror_capa_pemmdb"] = combined_df.index.get_level_values(
        "country"
    ).map(market_info_df["Run of River - MW"])
    combined_df["pondage_capa_pemmdb"] = combined_df.index.get_level_values(
        "country"
    ).map(market_info_df["Pondage - MW"])
    combined_df["ror_capa_pemmdb"] = (
        combined_df["pure_ror_capa_pemmdb"] + combined_df["pondage_capa_pemmdb"]
    )

    ror_mask = combined_df.index.get_level_values("carrier") == "ror"
    ror_nonzero_mask = ror_mask & (combined_df["ror_capa_pemmdb"] > 0)
    combined_df.loc[ror_nonzero_mask, "inflow"] /= combined_df.loc[
        ror_nonzero_mask, "ror_capa_pemmdb"
    ]

    combined_df.loc[ror_mask, "inflow"] *= combined_df.loc[ror_mask, "p_nom"]

    return combined_df["inflow"], region_to_country_mapping


def distribute_inflow_to_powerplants(
    inflow: pd.Series,
    powerplants_df: pd.DataFrame,
    region_to_country_mapping: dict[str, str],
) -> pd.DataFrame:
    """
    Distribute regional inflow values to individual powerplant bus regions.

    Distribute inflow totals to model regions based on their p_nom share
            - For each hydro-related technology (ror, hydro, PHS):
            - For each powerplant region: inflow = country_inflow * (p_nom_region / p_nom_total_country)

    Parameters
    ----------
    inflow
        Series with inflow regions and technologies (ror, hydro, PHS) as index.
    powerplants_df
        DataFrame with columns ['bus', 'carrier', 'p_nom'].
                       'bus' should be in format like "AT01 ror", "AT02 hydro", etc.
    region_to_country_mapping
        Mapping of model regions to respective tyndp country codes

    Returns
    -------
    :
        DataFrame with containing distributed inflow values.
    """
    powerplants_df["country"] = powerplants_df["bus"].map(region_to_country_mapping)
    inflow_df = inflow.reset_index()
    powerplants_df["dist_key"] = powerplants_df["p_nom"] / powerplants_df.groupby(
        ["country", "carrier"]
    )["p_nom"].transform("sum")
    combined_df = powerplants_df.merge(
        inflow_df, on=["country", "carrier"], how="outer"
    )
    combined_df["bus"] = combined_df["bus"].fillna(combined_df["country"])
    combined_df = combined_df.fillna(0)
    combined_df["inflow"] *= combined_df["dist_key"]

    return combined_df[["bus", "carrier", "inflow"]]


if __name__ == "__main__":
    if "snakemake" not in globals():
        from scripts._helpers import mock_snakemake

        snakemake = mock_snakemake(
            "build_inflow_totals_per_region",
            opts="",
            clusters="adm",
            # configfiles="config/test/config.at10.yaml",
            sector_opts="none",
            planning_horizons="2030",
            run="AT_KN2040",
        )

    configure_logging(snakemake)
    set_scenario_config(snakemake)

    logger.info("Calculating distributed inflow totals totals per region...")

    time = get_snapshots(snakemake.params.snapshots, snakemake.params.drop_leap_day)
    year = pd.DatetimeIndex(time).year.unique().item()

    costs = load_costs(snakemake.input.costs)
    ppl = load_and_aggregate_powerplants(
        snakemake.input.powerplants,
        costs,
        snakemake.params.consider_efficiency_classes,
        snakemake.params.aggregation_strategies,
        snakemake.params.exclude_carriers,
    )
    ppl = ppl[["bus", "carrier", "p_nom"]]
    ppl = ppl[ppl["carrier"].isin(["PHS", "hydro", "ror"])]

    inflow_df, market_info_df = extract_inflow_totals_tyndp(
        snakemake.input.hydro_inflows, year
    )

    inflow_df, market_info_df = process_inflow_per_region(inflow_df, market_info_df)

    inflow, region_to_country_mapping = normalize_ror(inflow_df, ppl, market_info_df)
    distributed_inflow_df = distribute_inflow_to_powerplants(
        inflow, ppl, region_to_country_mapping
    )

    # Write the primary output (distributed inflow totals)
    distributed_inflow_df.to_csv(snakemake.output.totals, index=False)
    logger.info(f"Saved distributed inflow totals to {snakemake.output.totals}")
