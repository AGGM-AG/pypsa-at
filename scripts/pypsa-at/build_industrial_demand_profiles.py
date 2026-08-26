# SPDX-FileCopyrightText: 2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""
Build normalized hourly industry demand profiles, one resource file for all
planning horizons.

Overview
--------
For each planning horizon and network node:

1. Each JRC-IDEES industry subsector (e.g. "Integrated steelworks", "Cement")
   is mapped to one of the FfE (Forschungsstelle für Energiewirtschaft)
   normalized industry load-profile categories (:data:`INDUSTRY_CATEGORY_TO_PROFILE`).
2. The node's subsector electricity demands (TWh/a, from
   ``industry_sector_ratios`` x ``industrial_production_per_node``) weight and
   sum the corresponding FfE profiles into one nodal profile.
3. The FfE profiles are normalized, hourly, and for reference year 2017; their
   timestamps are relabelled to the model snapshot year and aggregated onto
   the model's temporally aggregated snapshots. The model reuses the same
   snapshot calendar (e.g. 2013) for every planning horizon, so only the
   subsector demand mix -- not the calendar -- differs per year.
4. The result is normalized to sum to 1 per (year, region, carrier) and
   written with columns ``year, region, carrier, snapshot, value``. The
   snapshot column contains the model's temporally aggregated timestamps.

This resource is applied to network Loads by
:func:`mods.demand.industrial_demand.apply_industrial_demand_profiles`
during ``prepare_sector_network`` after the profile carrier is mapped to the
network Load carrier
"""

import json
import logging

import numpy as np
import pandas as pd

from scripts._helpers import configure_logging, get_snapshots, set_scenario_config

logger = logging.getLogger(__name__)


# Industry category (JRC-IDEES subsector, as used in `industry_sector_ratios`)
# to FfE profile mapping.
INDUSTRY_CATEGORY_TO_PROFILE = {
    "Electric arc": "Iron & steel industry",
    "DRI + Electric arc": "Iron & steel industry",
    "Integrated steelworks": "Iron & steel industry",
    "HVC": "Non-metallic Minerals",
    "HVC (mechanical recycling)": "Non-metallic Minerals",
    "HVC (chemical recycling)": "Non-metallic Minerals",
    "Ammonia": "Paper, Pulp and Print",
    "Chlorine": "Paper, Pulp and Print",
    "Methanol": "Paper, Pulp and Print",
    "Other chemicals": "Paper, Pulp and Print",
    "Pharmaceutical products etc.": "Food and Tobacco",
    "Cement": "Non-metallic Minerals",
    "Ceramics & other NMM": "Non-metallic Minerals",
    "Glass production": "Non-metallic Minerals",
    "Pulp production": "Paper, Pulp and Print",
    "Paper production": "Paper, Pulp and Print",
    "Printing and media reproduction": "Paper, Pulp and Print",
    "Food, beverages and tobacco": "Food and Tobacco",
    "Alumina production": "Iron & steel industry",
    "Aluminium - primary production": "Iron & steel industry",
    "Aluminium - secondary production": "Iron & steel industry",
    "Other non-ferrous metals": "Non-metallic Minerals",
    "Transport equipment": "Transport Equipment",
    "Machinery equipment": "Machinery",
    "Textiles and leather": "Textile and Leather",
    "Wood and wood products": "Wood and Wood Products",
    "Other industrial sectors": "Non-specified (Industry)",
}

# FfE `internal_id` -> profile name. IDs 0, 2, 3 are not present in the API
# response (see note above).
FFE_ID_TO_PROFILE = {
    1: "Iron & steel industry",
    4: "Non-metallic Minerals",
    5: "Transport Equipment",
    6: "Machinery",
    7: "Mining and Quarrying",
    8: "Food and Tobacco",
    9: "Paper, Pulp and Print",
    10: "Wood and Wood Products",
    11: "Construction",
    12: "Textile and Leather",
    13: "Non-specified (Industry)",
}

# FfE profiles are indexed by hour-of-year for this fixed reference year.
FFE_REFERENCE_YEAR = 2017


def load_ffe_load_profiles(
    json_file: str, snapshots_hourly: pd.DatetimeIndex
) -> pd.DataFrame:
    """
    Load normalized industry load profiles from a pre-downloaded FfE JSON file.

    Parameters
    ----------
    json_file
        Path to the JSON file retrieved from the FfE Open Data API, as produced by the
        ``retrieve_ffe_industry_load_profiles`` Snakemake rule.
    snapshots_hourly
        Hourly model snapshots used to select and relabel the FfE reference
        profile timestamps.

    Returns
    -------
    :
        Long-form DataFrame with ``carrier``, ``sector``, ``timestamp`` and
        ``value`` columns, filtered to ``snapshots_hourly``. The carrier is
        initially the FfE label ``elec`` and is mapped to the network carrier
        in :func:`main`.
    """
    with open(json_file) as f:
        data = json.load(f)

    logger.info(f"Loaded FfE data: {data.get('title', json_file)}")

    timestamps = pd.date_range(
        f"{FFE_REFERENCE_YEAR}-01-01", f"{FFE_REFERENCE_YEAR}-12-31 23:00:00", freq="h"
    )

    df = pd.json_normalize(data["data"])
    df = df.set_index(df["internal_id"].map(lambda x: x[0]))["values"]
    profiles = (
        pd.DataFrame(np.vstack(df), index=df.index, columns=timestamps)
        .rename(index=FFE_ID_TO_PROFILE)
        .T
    )
    profiles = profiles.unstack().reset_index()
    profiles["carrier"] = "elec"
    profiles.columns = ["sector", "timestamp", "value", "carrier"]

    snapshot_year = snapshots_hourly.to_series().dt.year.unique()[0]

    profiles["timestamp"] = profiles["timestamp"].map(
        lambda date: date.replace(year=snapshot_year)
    )
    profiles = profiles[profiles["timestamp"].isin(snapshots_hourly)]
    logger.info(f"Loaded profiles: {list(profiles.columns)}")

    return profiles[["carrier", "sector", "timestamp", "value"]]


def nodal_sector_electricity_demand(
    sector_ratios_file: str, production_file: str
) -> pd.DataFrame:
    """
    Electricity demand per node and industry subsector for one planning horizon.

    Mirrors the aggregation in ``scripts/build_industrial_energy_demand_per_node.py``,
    stopping one level earlier (before summing across subsectors) since the
    subsector mix is what determines each node's demand profile shape.

    Parameters
    ----------
    sector_ratios_file
        Path to ``industry_sector_ratios_{year}.csv``.
    production_file
        Path to ``industrial_production_base_s_{clusters}_{year}.csv``.

    Returns
    -------
    :
        Normalized sector shares with a MultiIndex of ``region`` and source
        industry subsector, and one column per source carrier. Shares are
        normalized across all source carriers and subsectors for each region;
        this intentionally removes absolute demand at this stage.
    """
    sector_ratios = pd.read_csv(sector_ratios_file, header=[0, 1], index_col=0)
    production = pd.read_csv(production_file, index_col=0) / 1e3  # kt/a -> Mt/a

    nodal_sector_ratios = pd.concat(
        {node: sector_ratios[node[:2]] for node in production.index}, axis=1
    ).T
    production_stacked = production.stack()
    production_stacked.index.names = [None, None]

    demand = nodal_sector_ratios.mul(production_stacked, axis=0)
    return demand.div(demand.groupby(level=0).transform("sum")).fillna(0)


def build_nodal_profiles(
    nodal_sector_demand: pd.DataFrame,
    snapshots: pd.DatetimeIndex,
    ffe_profiles: pd.DataFrame,
) -> pd.DataFrame:
    """
    Build one normalized hourly profile per node for a single planning horizon.

    Parameters
    ----------
    nodal_sector_demand
        Normalized demand shares per node, source carrier and industry
        subsector, as returned by :func:`nodal_sector_electricity_demand`.
    snapshots
        The model's snapshot calendar.
    ffe_profiles
        Output of :func:`load_ffe_load_profiles`.

    Returns
    -------
    :
        Long-form DataFrame with ``region``, ``sector``, ``carrier``,
        ``snapshot`` and normalized ``value`` columns. Entries whose
        regional profile does not sum to one are discarded.
    """
    nodal_sector_renamed = nodal_sector_demand.rename(
        index=INDUSTRY_CATEGORY_TO_PROFILE, level=1
    )
    nodal_sector_renamed = nodal_sector_renamed.groupby(level=[0, 1]).sum()
    nodal_sector_renamed = nodal_sector_renamed.stack().reset_index()
    nodal_sector_renamed.columns = ["region", "sector", "carrier", "value"]

    profiles = ffe_profiles.merge(
        nodal_sector_renamed,
        on=["carrier", "sector"],
        suffixes=("_country", "_timestamp"),
    )

    profiles["value"] = profiles["value_country"] * profiles["value_timestamp"]
    profiles = profiles[["region", "carrier", "sector", "timestamp", "value"]]

    profiles = profiles.sort_values("timestamp")

    merge = pd.merge_asof(
        profiles,
        snapshots,
        left_on="timestamp",
        right_on="snapshot",
        direction="backward",
    )

    grouped = merge.groupby(["region", "carrier", "snapshot"], as_index=False)[
        "value"
    ].sum()

    regional_profile = grouped.groupby(["region", "carrier"])["value"].transform("sum")

    missing = grouped[np.isclose(regional_profile, 0)]
    if missing.shape[0] > 0:
        logger.warning(
            f"Non-complete profiles for: {missing[['region', 'carrier']].drop_duplicates()}. Dropping entries"
        )

    grouped = grouped[~np.isclose(regional_profile, 0)]
    return grouped


def main(snakemake) -> None:
    """
    Build and export snapshot-level normalized (per region) profiles for all horizons.
    """
    snapshots_hourly = get_snapshots(
        snakemake.params.snapshots, snakemake.params.drop_leap_day
    )
    snapshots = pd.read_csv(
        snakemake.input.snapshot_weightings, parse_dates=["snapshot"]
    )["snapshot"]
    snapshots = snapshots.sort_values()
    ffe_profiles = load_ffe_load_profiles(
        snakemake.input.ffe_profiles, snapshots_hourly
    )

    years = [str(y) for y in snakemake.params.planning_horizons]
    sector_ratio_files = snakemake.input.industry_sector_ratios
    production_files = snakemake.input.industrial_production_per_node

    rows = []
    for year, sector_ratios_file, production_file in zip(
        years, sector_ratio_files, production_files, strict=True
    ):
        logger.info(f"Building industry demand profiles for {year}...")
        demand = nodal_sector_electricity_demand(sector_ratios_file, production_file)
        profiles = build_nodal_profiles(demand, snapshots, ffe_profiles)

        profiles["year"] = year
        rows.append(profiles)

    result = pd.concat(rows, ignore_index=True)[
        ["year", "region", "carrier", "snapshot", "value"]
    ]
    result["carrier"] = result["carrier"].map(snakemake.params.carrier_mapping)
    result.to_csv(snakemake.output.industrial_demand_profiles, index=False)
    logger.info(
        f"Saved industry demand profiles to {snakemake.output.industrial_demand_profiles}"
    )


if __name__ == "__main__":
    if "snakemake" not in globals():
        from scripts._helpers import mock_snakemake

        snakemake = mock_snakemake(
            "build_industrial_demand_profiles_at",
            run="AT_KN2040",
            configfiles="config/test/config.at10.yaml",
            clusters="adm",
            opts="",
            sector_opts="none",
        )
    configure_logging(snakemake)
    set_scenario_config(snakemake)

    main(snakemake)
