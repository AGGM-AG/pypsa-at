# SPDX-FileCopyrightText: 2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""Build the Austrian base electricity load table from NEA and regional keys."""

import logging

import pandas as pd
from snakemake.script import Snakemake

from mods.demand.electricity import (
    NEA_BASE_LOAD_SECTORS,
    aggregate_energiemosaik,
    build_base_load_table,
    district_regions,
    municipality_regions,
    nea_base_load_targets,
    read_energiemosaik,
)
from scripts._helpers import configure_logging, set_scenario_config

logger = logging.getLogger(__name__)


def build_distribution_keys(
    population: pd.Series, energiemosaik: pd.DataFrame | None
) -> pd.DataFrame:
    """
    Combine the regional distribution keys of all base-load carriers.

    Parameters
    ----------
    population
        Population per Austrian model region.
    energiemosaik
        Energiemosaik electricity proxies per model region and carrier, or
        ``None`` to distribute every carrier by population.

    Returns
    -------
    :
        Key values per model region (index) and base-load carrier (columns).
        Carriers without an Energiemosaik column (rail) use population.

    Raises
    ------
    ValueError
        If a model region has no Energiemosaik value.
    """
    keys = pd.DataFrame(
        {carrier: population for carrier in NEA_BASE_LOAD_SECTORS},
        index=population.index,
    )
    if energiemosaik is None:
        return keys
    for carrier in energiemosaik.columns:
        keys[carrier] = energiemosaik[carrier].reindex(keys.index)
        if (missing := keys.index[keys[carrier].isna()]).size:
            raise ValueError(
                f"No Energiemosaik '{carrier}' value for model regions {missing.to_list()}."
            )
    return keys


def main(snakemake: Snakemake) -> None:
    """
    Read the inputs, build the regional base-load table and write it.

    Parameters
    ----------
    snakemake
        The Snakemake workflow object providing inputs, params, and config.

    Returns
    -------
    :
        Writes the table with ``region``, ``carrier`` and ``value_TWh``.

    Raises
    ------
    ValueError
        If no NEA source year is configured for the first planning horizon
        or the distribution key is unknown.
    """
    base_year = snakemake.params.planning_horizons[0]
    source_years = snakemake.params.source_years
    try:
        source_year = source_years[base_year]
    except KeyError as err:
        raise ValueError(
            f"No NEA source year configured for base year {base_year}. "
            f"Add it to 'demand: source_years:' (configured: {source_years})."
        ) from err

    targets = nea_base_load_targets(pd.read_csv(snakemake.input.nea_at), source_year)

    keys = pd.read_csv(snakemake.input.industrial_distribution_key, index_col=0)
    population = keys.loc[keys.index.str.startswith("AT"), "population"]

    distribution_key = snakemake.params.distribution_key
    if distribution_key == "energiemosaik":
        register = pd.read_csv(snakemake.input.statistik_at_regions)
        nuts3_regions = snakemake.params.clustering.startswith("AT35")
        energiemosaik = aggregate_energiemosaik(
            read_energiemosaik(snakemake.input.energiemosaik),
            municipality_regions(register, nuts3_regions),
            district_regions(register, nuts3_regions),
        )
    elif distribution_key == "population":
        energiemosaik = None
    else:
        raise ValueError(
            f"Unknown distribution key {distribution_key!r}; "
            "use 'energiemosaik' or 'population'."
        )

    table = build_base_load_table(
        targets, build_distribution_keys(population, energiemosaik)
    )
    table.to_csv(snakemake.output.electricity_base_load, index=False)
    logger.info(
        f"Wrote the base load table for NEA {source_year} with {distribution_key} keys "
        f"[TWh]:\n{table.groupby('carrier')['value_TWh'].sum().round(3)}"
    )


if __name__ == "__main__":
    if "snakemake" not in globals():
        from scripts._helpers import mock_snakemake

        snakemake = mock_snakemake(
            "build_electricity_base_load_at", run="AT_KN2040", clusters="adm"
        )
    configure_logging(snakemake)
    set_scenario_config(snakemake)
    main(snakemake)
