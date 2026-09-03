# SPDX-FileCopyrightText: 2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.

"""
Build capacity trajectories for components based on PEMMDB and other data.

Outputs
-------

- ``resources/trajectories.csv``:

    ===================  =======================  =========================================================
    Field                Index                    Description
    ===================  =======================  =========================================================
    value                year, region, carrier,   Trajectory values (either p_nom_min or p_nom_max)
                         variable, sense
    ===================  =======================  =========================================================
"""

import logging
from pathlib import Path

import pandas as pd
from snakemake.script import Snakemake

from mods.constants import HYDRO_CARRIER_MAPPING
from mods.utils import resolve_tyndp_locations
from scripts._helpers import (
    configure_logging,
    load_costs,
    set_scenario_config,
)
from scripts.add_electricity import load_and_aggregate_powerplants

logger = logging.getLogger(__name__)


def extract_hydro_capacities_tyndp(
    hydro_inflows_dir: str,
) -> pd.DataFrame:
    """
    Extract PEMMDB hydropower capacities from Excel files.

    Reads all Excel files in hydro_inflows_dir/.

    Parameters
    ----------
    hydro_inflows_dir
        Directory for the hydro inflows data

    Returns
    -------
    hydro_capacities
        DataFrame of capacities for hydro components
    """
    hydro_dir = Path(hydro_inflows_dir)
    years = [p.name for p in hydro_dir.iterdir() if p.is_dir()]
    market_info_data = []  # {country: {label: value}}
    for year in years:
        subdir = hydro_dir / year
        excel_files = sorted(subdir.glob("*.xlsx"))
        for excel_file in excel_files:
            logger.info(f"Processing {excel_file.name}")
            parts = excel_file.stem.split("_")
            country_code = parts[1]

            df_market = pd.read_excel(
                excel_file, sheet_name="MarketNodeInfo", header=5, index_col=0
            )
            df_market.index.name = "carrier"
            df_market.columns = pd.MultiIndex.from_tuples(
                [(year, country_code)], names=["year", "region"]
            )
            market_info_data.append(df_market.T.stack().rename("value"))

    market_info_df = pd.concat(market_info_data)
    return market_info_df.fillna(0)


def _map_index(
    df: pd.DataFrame,
    mapping: dict[str, str | tuple[str | None, ...]],
    column: str,
    new_name: str | tuple[str, ...] | None = None,
) -> pd.DataFrame:
    """
    Uses a mapping to map a column in a MultiIndex to one or more new MultiIndex columns

    If mapping values are tuples, the original level is expanded into multiple
    levels named by `new_name`.

    Parameters
    ----------
    df
        DataFrame with index to map
    mapping
        Mapping dictionary of values for column
    column
        Name of the column to map
    new_name
        New column name(s) to use. Needs to be passed when mapping values are tuples.

    Returns
    -------
    out
        Copy of the DataFrame with modified index.
    """
    idx = df.index.to_frame(index=False)
    loc = idx.columns.get_loc(column)
    mapped = pd.DataFrame(idx.pop(column).map(mapping).tolist())

    names = column if new_name is None else new_name
    names = [names] if isinstance(names, str) else list(names)

    if mapped.shape[1] != len(names):
        raise ValueError("new_name needs to match the number of mapped columns")

    mapped.columns = names

    out = df.copy()
    out.index = pd.MultiIndex.from_frame(
        pd.concat([idx.iloc[:, :loc], mapped, idx.iloc[:, loc:]], axis=1)
    )
    return out


def add_missing_years(s: pd.Series, snakemake: Snakemake) -> pd.Series:
    """
    Add missing planning horizons to the index in the given Series.

    Missing entries are filled with value 0.

    Parameters
    ----------
    s
        The Series to extend
    snakemake
        The Snakemake workflow object.

    Returns
    -------
    :
        The extended Series

    """
    data = s.copy()
    years_pemmdb = set(data.index.get_level_values("year"))
    planning_horizons = snakemake.params.planning_horizons
    missing_years = [
        str(year) for year in planning_horizons if str(year) not in years_pemmdb
    ]
    for year in sorted(missing_years):
        df_year = data.loc[data.index.get_level_values("year") == "2030"].copy()
        df_year = df_year.rename(index={"2030": year}, level="year")
        df_year[:] = 0
        data = pd.concat([df_year, data]).abs()
    return data


def add_missing_regions(s: pd.Series, location_mapping: dict) -> pd.Series:
    """
    Add missing regions to the index in the given Series.

    Missing entries are filled with value 0.

    Parameters
    ----------
    s
        The Series to extend
    location_mapping
        The resolved TYNDP location mapping for the clustering.

    Returns
    -------
    :
        The extended Series
    """
    data = s.copy()
    regions_pemmdb = set(data.index.get_level_values("region"))
    all_regions = {r for r in location_mapping.values() if r is not None}
    missing_regions = [region for region in all_regions if region not in regions_pemmdb]
    for region in sorted(missing_regions):
        df_region = data.loc[data.index.get_level_values("region") == "AT"].copy()
        df_region = df_region.rename(index={"AT": region}, level="region")
        df_region[:] = 0
        data = pd.concat([df_region, data]).abs()
    return data


def filter_market_data(snakemake: Snakemake, market_data: pd.DataFrame) -> pd.DataFrame:
    """
    Reduce market data to entries for actually existing powerplants in the model

    Parameters
    ----------
    snakemake
        The Snakemake workflow object.
    market_data
        The extracted market data

    Returns
    -------
    :
        The filtered DataFrame
    """
    costs = load_costs(snakemake.input.costs)
    country_list = snakemake.params.countries
    ppl = load_and_aggregate_powerplants(
        snakemake.input.powerplants,
        costs,
        snakemake.params.consider_efficiency_classes,
        snakemake.params.aggregation_strategies,
        snakemake.params.exclude_carriers,
    )

    market_data_country = market_data.index.get_level_values("region")
    market_data_carrier = (
        market_data.index.get_level_values("carrier").str.split().str[0]
    )
    market_data_keys = pd.MultiIndex.from_arrays(
        [market_data_country, market_data_carrier],
        names=["region_key", "carrier_key"],
    )

    ppl["country"] = ppl["bus"].str[:2]
    ppl = ppl[
        ppl["country"].isin(country_list)
        & (ppl["country"] != "XK")
        & ppl["carrier"].isin(set(market_data_carrier))
    ]
    ppl_keys = pd.MultiIndex.from_frame(
        ppl.assign(
            region_key=ppl["bus"],
            carrier_key=ppl["carrier"],
        )[["region_key", "carrier_key"]]
    )

    market_keys = list(market_data_keys.unique())
    ppl_keys_unique = list(ppl_keys.unique())

    def is_match(market_key, ppl_key):
        market_region, market_carrier = market_key
        ppl_region, ppl_carrier = ppl_key

        return market_carrier == ppl_carrier and ppl_region.startswith(market_region)

    missing = [
        ppl_key
        for ppl_key in ppl_keys_unique
        if not any(is_match(market_key, ppl_key) for market_key in market_keys)
    ]

    if len(missing):
        raise ValueError(
            f"Entries from Missing trajectories for countries: {list(missing)}"
        )

    return market_data[
        [
            any(is_match(market_key, ppl_key) for ppl_key in ppl_keys_unique)
            for market_key in market_data_keys
        ]
    ]


def apply_klien_hydro_buildout_at(
    trajectories: pd.Series, snakemake: Snakemake
) -> pd.Series:
    """
    Override the Austrian ``ror`` upper bound with the KLIEN-scaled corridor.

    The corridor is built by ``build_klien_hydro_trajectory_at`` from the KLIEN
    realisable hydropower pathway and the calibrated Austrian brownfield ror
    fleet. The base planning horizon keeps its PEMMDB row; every later horizon
    takes the corridor value as ``p_nom_max``. Reservoir (``hydro discharger`` /
    ``hydro store``) and PHS keep their PEMMDB rows. Guarded by
    ``mods.update_hydro_capacities_AT.enable``.

    Parameters
    ----------
    trajectories
        Trajectory values indexed by (year, region, carrier, variable, sense).
    snakemake
        The Snakemake workflow object.

    Returns
    -------
    :
        The trajectories with overridden AT ror rows.
    """
    if not snakemake.params.update_hydro_capacities_AT:
        logger.info(
            "Skipping the KLIEN ror buildout for AT. config option "
            "mods.update_hydro_capacities_AT.enable is false."
        )
        return trajectories

    corridor = pd.read_csv(snakemake.input.klien_ror_trajectory, index_col="year")
    base_year = min(snakemake.params.planning_horizons)

    trajectories = trajectories.copy()
    for year in snakemake.params.planning_horizons:
        if year == base_year:
            continue
        if year not in corridor.index:
            raise ValueError(
                f"The KLIEN ror corridor has no entry for {year}. "
                "Check the build_klien_hydro_trajectory_at rule."
            )
        idx = (str(year), "AT", "ror", "Generator-p_nom", "max")
        if idx not in trajectories.index:
            raise ValueError(
                f"Expected AT ror trajectory row for {year} to override, "
                "but it is missing. Check the PEMMDB trajectory build."
            )
        trajectories.loc[idx] = corridor.loc[year, "value"]
        logger.info(
            f"KLIEN ror buildout for AT {year}: max {corridor.loc[year, 'value']:.0f} MW."
        )
    return trajectories


def main(snakemake: Snakemake) -> pd.DataFrame:
    """
    Main function to calculate and return trajectories

    Parameters
    ----------
    snakemake
        The Snakemake workflow object.

    Returns
    -------
    :
        The calculated trajectories DataFrame
    """
    market_info = extract_hydro_capacities_tyndp(snakemake.input.hydro_inflows)

    location_mapping = resolve_tyndp_locations(
        snakemake.params.admin_levels, snakemake.params.custom_clustering
    )
    market_info = _map_index(market_info, location_mapping, "region")
    market_info = _map_index(
        market_info, HYDRO_CARRIER_MAPPING, "carrier", ("carrier", "variable", "sense")
    )
    market_info = market_info[market_info.index.isin(market_info.index.dropna())]
    market_info = market_info.groupby(level=market_info.index.names).sum().abs()
    market_info = add_missing_regions(market_info, location_mapping)
    market_info = filter_market_data(snakemake, market_info)
    market_info = add_missing_years(market_info, snakemake)
    market_info = market_info.sort_index()
    market_info = apply_klien_hydro_buildout_at(market_info, snakemake)
    return market_info


if __name__ == "__main__":
    if "snakemake" not in globals():
        from scripts._helpers import mock_snakemake

        snakemake = mock_snakemake(
            "build_capacity_trajectories",
            run="AT_KN2040",
            clusters="adm",
            # configfiles="config/test/config.at10.yaml",
        )

    configure_logging(snakemake)
    set_scenario_config(snakemake)

    logger.info("Calculating capacity trajectories...")
    trajectories = main(snakemake)
    trajectories.to_csv(snakemake.output.trajectories)
    logger.info(f"Saved trajectories to {snakemake.output.trajectories}")
