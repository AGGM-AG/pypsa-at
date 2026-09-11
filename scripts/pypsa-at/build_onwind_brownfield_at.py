# SPDX-FileCopyrightText: 2026 Austrian Gas Grid Management AG
# SPDX-License-Identifier: MIT
"""Build Austrian onshore-wind brownfield capacities."""

from collections.abc import Mapping
from math import ceil
from typing import Literal

import pandas as pd
from snakemake.script import Snakemake

from mods.clustering.utils import map_at_nuts3_to_nuts2
from scripts._helpers import configure_logging, set_scenario_config


def extrapolate_production(
    wind_production: pd.DataFrame,
    onwind_lifetime: float,
    at_regions: pd.DataFrame,
    errors: Literal["raise", "ignore"] = "raise",
) -> pd.DataFrame:
    """
    Map federal-state wind production to model regions and extend it backwards
    to the onshore-wind lifetime.

    Parameters
    ----------
    wind_production
        Wind production by year per federal state.
    onwind_lifetime
        Onshore-wind lifetime in years.
    at_regions
        Regional register for mapping federal states to model regions.
    errors
        If errors should be raised or not

    Returns
    -------
    :
        Long-form production data sorted by region and year.
    """
    max_year = int(wind_production["Jahr"].max())
    start_year = max_year - ceil(onwind_lifetime) + 1
    production = (
        wind_production.set_index("Jahr")
        .reindex(range(start_year, max_year + 1))
        .reset_index()
    )
    production = production.melt(
        "Jahr", var_name="federal_state", value_name="production"
    )
    production["federal_state"] = production.federal_state.str.removesuffix(" in GWh")
    mapping = at_regions.assign(
        federal_state=at_regions.federal_state.str.strip(),
        region=at_regions.nuts2_code.astype(str).str[:4],
    )[["federal_state", "region"]].drop_duplicates("federal_state")
    production = (
        production.merge(mapping, on="federal_state")
        .rename(columns={"Jahr": "year"})
        .sort_values(["region", "year"])
    )
    if production["region"].nunique() != 9 and errors == "raise":
        raise ValueError(
            f"Unexpected number of federal states {production['region'].nunique()} in production data."
        )

    production["production"] = (
        production.groupby("region")["production"]
        .transform(
            lambda s: s.interpolate(
                method="slinear", limit_direction="both", fill_value="extrapolate"
            )
        )
        .clip(lower=0)
    )
    return production[["region", "year", "production"]].sort_values(
        ["region", "year"], ignore_index=True
    )


def create_buildup(wind_production_long: pd.DataFrame) -> pd.DataFrame:
    """
    Convert production changes into normalized five-year vintage shares.

    Parameters
    ----------
    wind_production_long
        Long-form production data.

    Returns
    -------
    :
        Vintage buildup shares. Years are rounded to five-year periods and shares are
        normalized within each region.
    """
    result = wind_production_long.copy()
    result["buildup"] = (
        wind_production_long.groupby("region").production.diff().clip(lower=0).fillna(0)
    )
    result["buildup"] /= result.groupby("region").buildup.transform("sum")
    result["buildup"] = result.buildup.fillna(0)
    result["year"] = result.year.add(4).floordiv(5).mul(5)
    return result.groupby(["region", "year"], as_index=False).buildup.sum()


def prepare_potentials(
    klien_potentials: pd.DataFrame, admin_levels: Mapping[str, int]
) -> pd.DataFrame:
    """
    Prepare current KLIEN capacities at the configured regional level.

    Parameters
    ----------
    klien_potentials
        KLIEN wind-potential records.
    admin_levels
        Mapping of country codes to administrative levels. Determines
        whether NUTS3 capacities are aggregated to NUTS2.

    Returns
    -------
    :
        Current capacities aggregated by region.
    """
    result = klien_potentials[["nuts3", "C_current"]].rename(
        columns={"nuts3": "region", "C_current": "capacity"}
    )
    if int(admin_levels["AT"]) == 2:
        result["region"] = result.region.map(map_at_nuts3_to_nuts2)
    return result.groupby("region", as_index=False).capacity.sum()


def create_brownfield(
    wind_capacities: pd.DataFrame, wind_buildup: pd.DataFrame
) -> pd.DataFrame:
    """
    Apply vintage shares to current regional capacities.

    Parameters
    ----------
    wind_capacities
        Current regional capacities.
    wind_buildup
        Vintage buildup shares.

    Returns
    -------
    :
        Brownfield capacities sorted by region and year.
    """
    capacities = wind_capacities.assign(nuts2=wind_capacities.region.str[:4])
    buildup = wind_buildup.assign(nuts2=wind_buildup.region.str[:4])
    result = capacities.merge(buildup[["nuts2", "year", "buildup"]], on="nuts2")
    result["capacity"] *= result.buildup
    result = result[["region", "year", "capacity"]].sort_values(
        ["region", "year"], ignore_index=True
    )
    return result


def main(snakemake: Snakemake, errors: Literal["raise", "ignore"] = "raise") -> None:
    """
    Build the regional onshore-wind brownfield CSV.

    Parameters
    ----------
    snakemake
        The Snakemake workflow object providing input files, parameters, and
        the output path.
    errors
        If errors should be raised or not

    Returns
    -------
    :
        Result is written to the ``wind_brownfield`` Snakemake output.
    """
    costs = pd.read_csv(snakemake.input.costs)
    production = pd.read_excel(
        snakemake.input.wind_production, sheet_name="Sheet1", nrows=20
    )
    potentials = pd.read_csv(snakemake.input.nuts3_wind)
    regions = pd.read_csv(snakemake.input.at_regions)
    lifetime = costs.loc[costs.technology.eq("onwind"), "lifetime"].iloc[0]
    production_long = extrapolate_production(production, lifetime, regions, errors)
    buildup = create_buildup(production_long)
    capacities = prepare_potentials(potentials, snakemake.params.admin_levels)
    create_brownfield(capacities, buildup).to_csv(
        snakemake.output.wind_brownfield, index=False
    )


if __name__ == "__main__":
    if "snakemake" not in globals():
        from scripts._helpers import mock_snakemake

        snakemake = mock_snakemake(
            "build_onwind_brownfield_at", clusters="adm", run="AT_KN2040"
        )
    configure_logging(snakemake)
    set_scenario_config(snakemake)
    main(snakemake)
