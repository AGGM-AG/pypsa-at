# SPDX-FileCopyrightText: 2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.

"""
Build the KLIEN run-of-river capacity corridor per Austrian model region.

The realisable river hydropower pathway of the KLIEN study "Erneuerbare
Energiepotenziale in Oesterreich fuer 2030 und 2040" (Resch et al. 2026,
served by GTIF Austria) gives, per river catchment, the installed capacity
today (``C_current``) and in 2040 and 2070 (``C_{year}_{ambition}_{climate}``)
together with the energy (``E_*``). The catchments are located in the model
regions through the plants they contain (``hydro_catchment_regions_{clusters}.csv``,
built by ``build_hydro_inflow_targets_at``), and the study's capacity increment
becomes the run-of-river headroom of that region:

    value(region, year) = existing_ror_MW(region) + delta_C(region, year)

The whole increment is treated as run-of-river (the study does not split it
by technology; reservoir turbines keep their PEMMDB corridor). Capacities are
interpolated linearly per catchment between ``KLIEN_BASE_YEAR``, 2040 and
2070 and held flat afterwards; the ``wocc`` climate scenario falls back to
``mocc`` (RCP4.5) because the study publishes pathways only for mocc/stcc.

Each region also gets a yield factor for the capacity that is added: the
study's marginal energy per added megawatt (``delta_E / delta_C`` of the
region's catchments, scaled to the weather year) over the full-load hours of
the region's existing run-of-river fleet, capped at one. A new vintage in
``mods.network.hydro`` receives the existing profile times this factor.

When ``mods.update_hydro_capacities_AT.enable`` is false, an empty file with
the same header is written so the DAG does not depend on the configuration.

Outputs
-------

- ``resources/klien_ror_trajectory_{clusters}.csv``:

    ===================  =======================  =========================================================
    Field                Index                    Description
    ===================  =======================  =========================================================
    existing_ror_mw      year, region             Calibrated AT ror capacity of the region
    delta_c_mw           year, region             KLIEN capacity increment located in the region
    value                year, region             Resulting ror ``p_nom_max`` of the region in MW
    marginal_flh         year, region             KLIEN energy per added MW in hours of the weather year
    yield_factor         year, region             min(1, marginal_flh / existing full-load hours)
    ===================  =======================  =========================================================
"""

import logging

import numpy as np
import pandas as pd
from snakemake.script import Snakemake

from scripts._helpers import configure_logging, set_scenario_config

logger = logging.getLogger(__name__)

# Reference year of the KLIEN study capacities the buildout is anchored at
# (study publication; the calibrated brownfield fleet has the same vintage).
# The increment is zero in this year regardless of the configured horizons.
KLIEN_BASE_YEAR = 2025
KLIEN_LAST_YEAR = 2070
KLIEN_ANCHOR_YEARS = (KLIEN_BASE_YEAR, 2040, KLIEN_LAST_YEAR)
COLUMNS = [
    "year",
    "region",
    "existing_ror_mw",
    "delta_c_mw",
    "value",
    "marginal_flh",
    "yield_factor",
]


def resolve_climate_scenario(climate_scenario: str) -> str:
    """
    Map the configured climate scenario to one published by the hydro study.

    Parameters
    ----------
    climate_scenario
        One of ``wocc``, ``mocc`` or ``stcc``.

    Returns
    -------
    :
        ``mocc`` for ``wocc``, otherwise the input unchanged.
    """
    if climate_scenario == "wocc":
        logger.info(
            "The KLIEN hydro pathway has no wocc variant; falling back to "
            "mocc (RCP4.5) for the AT ror buildout."
        )
        return "mocc"
    return climate_scenario


def klien_buildout_factors(
    klien: pd.DataFrame, ambition: str, climate_scenario: str
) -> pd.Series:
    """
    Yearly national KLIEN buildout factors from ``KLIEN_BASE_YEAR`` to ``KLIEN_LAST_YEAR``.

    Kept as the national cross-check of the regional corridor: the factor
    times the study's current capacity is the national capacity increment.

    Parameters
    ----------
    klien
        Per-catchment KLIEN hydro table with ``C_current`` and
        ``C_{2040,2070}_{ambition}_{climate}`` capacity columns in MW.
    ambition
        Pathway ambition (``low`` / ``medium`` / ``high``).
    climate_scenario
        Study climate scenario (``mocc`` / ``stcc``).

    Returns
    -------
    :
        Factors indexed by integer year, anchored at ``KLIEN_BASE_YEAR`` (1.0),
        2040 and 2070 and linearly interpolated in between.
    """
    current_mw = klien["C_current"].sum()
    anchors = pd.Series(
        {
            KLIEN_BASE_YEAR: 1.0,
            2040: klien[f"C_2040_{ambition}_{climate_scenario}"].sum() / current_mw,
            KLIEN_LAST_YEAR: klien[f"C_2070_{ambition}_{climate_scenario}"].sum()
            / current_mw,
        }
    )
    return (
        anchors.reindex(range(KLIEN_BASE_YEAR, KLIEN_LAST_YEAR + 1))
        .interpolate(method="index")
        .rename("factor")
        .rename_axis("year")
    )


def interpolate_catchment_pathway(
    klien: pd.DataFrame,
    years: list[int],
    ambition: str,
    climate_scenario: str,
    quantity: str = "C",
) -> pd.DataFrame:
    """
    KLIEN pathway per catchment for the requested years.

    Parameters
    ----------
    klien
        Per-catchment KLIEN hydro table indexed by catchment id with
        ``{quantity}_current`` and ``{quantity}_{2040,2070}_{ambition}_{climate}``.
    years
        Years to evaluate; those outside the study range are clipped to the
        nearest anchor year.
    ambition
        Pathway ambition (``low`` / ``medium`` / ``high``).
    climate_scenario
        Study climate scenario (``mocc`` / ``stcc``).
    quantity
        ``C`` for capacity in MW or ``E`` for energy in GWh/a.

    Returns
    -------
    :
        Frame indexed like ``klien`` with one column per year, linearly
        interpolated between the anchor years.
    """
    anchors = klien[
        [
            f"{quantity}_current",
            f"{quantity}_2040_{ambition}_{climate_scenario}",
            f"{quantity}_2070_{ambition}_{climate_scenario}",
        ]
    ].to_numpy(dtype=float)
    out = {}
    for year in years:
        clipped = min(max(int(year), KLIEN_BASE_YEAR), KLIEN_LAST_YEAR)
        out[int(year)] = np.array(
            [np.interp(clipped, KLIEN_ANCHOR_YEARS, row) for row in anchors]
        )
    return pd.DataFrame(out, index=klien.index).rename_axis(columns="year")


def locate_in_regions(
    per_catchment: pd.DataFrame,
    catchment_regions: pd.DataFrame,
    tolerance: float = 1.0,
) -> pd.DataFrame:
    """
    Roll a per-catchment quantity up to the model regions.

    Parameters
    ----------
    per_catchment
        Frame indexed by catchment id with one column per year (or any
        other column set); only non-negative values are placed.
    catchment_regions
        Catchment to region weights (``section``, ``bus``, ``weight``) from
        ``build_hydro_inflow_targets_at``.
    tolerance
        Largest value (per column) a catchment without a region may carry;
        such catchments are dropped with a warning. Larger ones raise.

    Returns
    -------
    :
        Frame indexed by region with the columns of ``per_catchment``.

    Raises
    ------
    ValueError
        If a catchment with a value above ``tolerance`` has no region.
    """
    values = per_catchment.clip(lower=0.0)
    values.index = values.index.astype(str)
    weights = catchment_regions.assign(section=catchment_regions["section"].astype(str))
    unplaced = values.index[(values.sum(axis=1) > 0)].difference(weights["section"])
    if len(unplaced):
        too_large = values.loc[unplaced].max(axis=1) > tolerance
        if too_large.any():
            raise ValueError(
                f"KLIEN catchments {sorted(unplaced[too_large])} carry a capacity "
                "increment but hold no plant of the calibrated fleet, so they "
                "cannot be located in a model region. Add the plants (or a KLIEN "
                "residual plant) to the fleet."
            )
        logger.warning(
            f"Dropping the increment of {len(unplaced)} KLIEN catchments without "
            f"a plant in the fleet (at most {values.loc[unplaced].max().max():.2f} "
            f"per catchment): {sorted(unplaced)}."
        )
    merged = weights.merge(values, left_on="section", right_index=True, how="inner")
    columns = values.columns
    merged[columns] = merged[columns].mul(merged["weight"], axis=0)
    return merged.groupby("bus")[list(columns)].sum().rename_axis(index="region")


def marginal_full_load_hours(
    klien: pd.DataFrame,
    catchment_regions: pd.DataFrame,
    ambition: str,
    climate_scenario: str,
) -> pd.Series:
    """
    KLIEN energy per added megawatt per region, in hours of the reference period.

    Parameters
    ----------
    klien
        Per-catchment KLIEN hydro table indexed by catchment id.
    catchment_regions
        Catchment to region weights.
    ambition
        Pathway ambition (``low`` / ``medium`` / ``high``).
    climate_scenario
        Study climate scenario (``mocc`` / ``stcc``).

    Returns
    -------
    :
        ``delta_E_2040 / delta_C_2040`` of the region's catchments in hours,
        indexed by region; NaN where the region has no increment.
    """
    delta_c = interpolate_catchment_pathway(klien, [2040], ambition, climate_scenario)
    delta_e = interpolate_catchment_pathway(
        klien, [2040], ambition, climate_scenario, quantity="E"
    )
    delta = pd.DataFrame(
        {
            "delta_c": delta_c[2040] - klien["C_current"],
            "delta_e": delta_e[2040] - klien["E_current"],
        }
    )
    delta = delta[delta["delta_c"] > 0]
    regional = locate_in_regions(delta, catchment_regions)
    return (regional["delta_e"] * 1e3 / regional["delta_c"]).rename("marginal_flh")


def build_regional_ror_corridor(
    klien: pd.DataFrame,
    catchment_regions: pd.DataFrame,
    existing_ror_mw: pd.Series,
    existing_flh: pd.Series,
    year_factor: float,
    planning_horizons: list[int],
    ambition: str,
    climate_scenario: str,
) -> pd.DataFrame:
    """
    Run-of-river corridor and yield factor per Austrian region and horizon.

    Parameters
    ----------
    klien
        Per-catchment KLIEN hydro table indexed by catchment id.
    catchment_regions
        Catchment to region weights (``section``, ``bus``, ``weight``).
    existing_ror_mw
        Calibrated run-of-river capacity per Austrian region.
    existing_flh
        Full-load hours of that capacity in the weather year (inflow target
        over capacity); regions without a value get yield factor one.
    year_factor
        Run-of-river weather-year factor of the inflow targets; scales the
        study's reference-period marginal hours to the weather year.
    planning_horizons
        Planning horizons to build the corridor for.
    ambition
        Pathway ambition (``low`` / ``medium`` / ``high``).
    climate_scenario
        Configured climate scenario (``wocc`` / ``mocc`` / ``stcc``).

    Returns
    -------
    :
        Frame with ``COLUMNS``, one row per horizon and region, sorted.
    """
    climate_scenario = resolve_climate_scenario(climate_scenario)
    years = sorted(int(year) for year in planning_horizons)
    pathway = interpolate_catchment_pathway(klien, years, ambition, climate_scenario)
    delta_c = locate_in_regions(
        pathway.sub(klien["C_current"], axis=0), catchment_regions
    )
    regions = existing_ror_mw.index.union(delta_c.index)
    delta_c = delta_c.reindex(regions, fill_value=0.0)
    existing = existing_ror_mw.reindex(regions, fill_value=0.0)

    marginal = marginal_full_load_hours(
        klien, catchment_regions, ambition, climate_scenario
    ).reindex(regions)
    marginal_weather_year = marginal * year_factor
    yield_factor = (
        (marginal_weather_year / existing_flh.reindex(regions))
        .clip(upper=1.0)
        .fillna(1.0)
    )

    rows = []
    for year in years:
        rows.append(
            pd.DataFrame(
                {
                    "year": year,
                    "region": regions,
                    "existing_ror_mw": existing.to_numpy(),
                    "delta_c_mw": delta_c[year].to_numpy(),
                    "value": (existing + delta_c[year]).to_numpy(),
                    "marginal_flh": marginal_weather_year.to_numpy(),
                    "yield_factor": yield_factor.to_numpy(),
                }
            )
        )
    return pd.concat(rows, ignore_index=True)[COLUMNS]


def main(snakemake: Snakemake) -> pd.DataFrame:
    """
    Build the regional KLIEN ror corridor from the workflow inputs.

    Parameters
    ----------
    snakemake
        The Snakemake workflow object.

    Returns
    -------
    :
        The corridor, or an empty frame when the feature is disabled.
    """
    if not snakemake.params.update_hydro_capacities_AT:
        logger.info(
            "Skipping the KLIEN ror buildout for AT. config option "
            "mods.update_hydro_capacities_AT.enable is false."
        )
        return pd.DataFrame(columns=COLUMNS)

    planning_horizons = [int(year) for year in snakemake.params.planning_horizons]
    base_year = min(planning_horizons)
    if base_year != KLIEN_BASE_YEAR:
        logger.warning(
            f"The KLIEN buildout is anchored at {KLIEN_BASE_YEAR} (study "
            f"reference), but the first planning horizon is {base_year}; "
            f"horizons before {KLIEN_BASE_YEAR} get no increment."
        )

    klien = pd.read_csv(snakemake.input.klien_hydro_potentials, sep=";", decimal=",")
    klien.columns = klien.columns.str.strip()
    klien = klien.set_index(klien["id"].astype(str))

    ppl = pd.read_csv(snakemake.input.powerplants, index_col=0, low_memory=False)
    ror = ppl.query(
        "Country == 'AT' and Fueltype == 'Hydro' and Technology == 'Run-Of-River'"
    )
    existing_ror_mw = ror.groupby("bus")["Capacity"].sum().rename_axis("region")

    targets = pd.read_csv(snakemake.input.hydro_inflow_targets)
    ror_targets = targets[targets["carrier"] == "ror"].set_index("bus")
    existing_flh = ror_targets["inflow"] / existing_ror_mw.reindex(ror_targets.index)
    year_factor = float(ror_targets["year_factor"].iloc[0])

    catchment_regions = pd.read_csv(
        snakemake.input.catchment_regions, dtype={"section": str}
    )

    ambition = snakemake.params.klien_ambition
    climate_scenario = snakemake.params.klien_climate_scenario
    corridor = build_regional_ror_corridor(
        klien,
        catchment_regions,
        existing_ror_mw,
        existing_flh,
        year_factor,
        planning_horizons,
        ambition,
        climate_scenario,
    )

    factors = klien_buildout_factors(
        klien, ambition, resolve_climate_scenario(climate_scenario)
    )
    for year, group in corridor.groupby("year"):
        national = klien["C_current"].sum() * (
            factors.loc[min(max(year, KLIEN_BASE_YEAR), KLIEN_LAST_YEAR)] - 1
        )
        logger.info(
            f"KLIEN ror buildout for AT {year} ({ambition}/{climate_scenario}): "
            f"+{group['delta_c_mw'].sum():.0f} MW over {len(group)} regions "
            f"(study total +{national:.0f} MW) -> {group['value'].sum():.0f} MW; "
            f"yield factor below one in "
            f"{group.loc[group['yield_factor'] < 1, 'region'].tolist()}."
        )
    return corridor


if __name__ == "__main__":
    if "snakemake" not in globals():
        from scripts._helpers import mock_snakemake

        snakemake = mock_snakemake(
            "build_klien_hydro_trajectory_at",
            run="AT_KN2040",
            clusters="adm",
        )

    configure_logging(snakemake)
    set_scenario_config(snakemake)

    logger.info("Building the KLIEN run-of-river capacity corridor per AT region...")
    corridor = main(snakemake)
    corridor.to_csv(snakemake.output.klien_ror_trajectory, index=False)
    logger.info(f"Saved corridor to {snakemake.output.klien_ror_trajectory}")
