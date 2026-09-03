# SPDX-FileCopyrightText: 2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.

"""
Build the KLIEN-scaled Austrian run-of-river capacity corridor.

The realisable river hydropower pathway of the KLIEN study "Erneuerbare
Energiepotenziale in Oesterreich fuer 2030 und 2040" (Resch et al. 2026,
served by GTIF Austria) defines a country-wide buildout factor
``C_pathway(year) / C_current``. The factor is applied to the calibrated
Austrian brownfield ror capacity from ``powerplants_s_{clusters}-overwrite.csv``.
Factors are anchored at ``KLIEN_BASE_YEAR`` (1.0), 2040 and 2070, interpolated
linearly in between and held flat afterwards. The ``wocc`` climate scenario
falls back to ``mocc`` (RCP4.5) because the study publishes pathways only for
mocc/stcc.

When ``mods.update_hydro_capacities_AT.enable`` is false, an empty file with
the same header is written so the DAG does not depend on the configuration.

Outputs
-------

- ``resources/klien_ror_trajectory_{clusters}.csv``:

    ===================  =======================  =========================================================
    Field                Index                    Description
    ===================  =======================  =========================================================
    factor               year                     KLIEN buildout factor relative to ``KLIEN_BASE_YEAR``
    brownfield_mw        year                     Calibrated AT ror capacity the factor is applied to
    value                year                     Resulting AT ror ``p_nom_max`` in MW
    ===================  =======================  =========================================================
"""

import logging

import pandas as pd
from snakemake.script import Snakemake

from scripts._helpers import configure_logging, set_scenario_config

logger = logging.getLogger(__name__)

# Reference year of the KLIEN study capacities the buildout factor is
# normalised to (study publication; the calibrated brownfield fleet has the
# same vintage). The factor is 1.0 in this year regardless of the configured
# planning horizons.
KLIEN_BASE_YEAR = 2025
KLIEN_LAST_YEAR = 2070
COLUMNS = ["factor", "brownfield_mw", "value"]


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
            "mocc (RCP4.5) for the AT ror buildout factor."
        )
        return "mocc"
    return climate_scenario


def klien_buildout_factors(
    klien: pd.DataFrame, ambition: str, climate_scenario: str
) -> pd.Series:
    """
    Yearly KLIEN buildout factors from ``KLIEN_BASE_YEAR`` to ``KLIEN_LAST_YEAR``.

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


def build_klien_ror_trajectory(
    klien: pd.DataFrame,
    brownfield_mw: float,
    planning_horizons: list[int],
    ambition: str,
    climate_scenario: str,
) -> pd.DataFrame:
    """
    Scale the calibrated AT ror fleet with the KLIEN buildout factors.

    Parameters
    ----------
    klien
        Per-catchment KLIEN hydro table (see ``klien_buildout_factors``).
    brownfield_mw
        Calibrated Austrian run-of-river capacity in MW.
    planning_horizons
        Planning horizons to build the corridor for.
    ambition
        Pathway ambition (``low`` / ``medium`` / ``high``).
    climate_scenario
        Configured climate scenario (``wocc`` / ``mocc`` / ``stcc``).

    Returns
    -------
    :
        DataFrame indexed by ``year`` with ``factor``, ``brownfield_mw`` and
        ``value`` columns. Horizons outside the study range are clipped to the
        nearest anchor year.
    """
    factors = klien_buildout_factors(
        klien, ambition, resolve_climate_scenario(climate_scenario)
    )
    years = sorted(int(year) for year in planning_horizons)
    clipped = [min(max(year, KLIEN_BASE_YEAR), KLIEN_LAST_YEAR) for year in years]
    out = pd.DataFrame(
        {"factor": factors.loc[clipped].to_numpy()},
        index=pd.Index(years, name="year"),
    )
    out["brownfield_mw"] = brownfield_mw
    out["value"] = out["brownfield_mw"] * out["factor"]
    return out


def main(snakemake: Snakemake) -> pd.DataFrame:
    """
    Build the KLIEN-scaled AT ror corridor from the workflow inputs.

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
        return pd.DataFrame(columns=COLUMNS, index=pd.Index([], name="year"))

    planning_horizons = snakemake.params.planning_horizons
    base_year = min(planning_horizons)
    if base_year != KLIEN_BASE_YEAR:
        logger.warning(
            f"The KLIEN buildout factor is anchored at {KLIEN_BASE_YEAR} "
            f"(study reference), but the first planning horizon is "
            f"{base_year}; horizons before {KLIEN_BASE_YEAR} keep factor 1.0."
        )

    klien = pd.read_csv(snakemake.input.klien_hydro_potentials, sep=";", decimal=",")
    klien.columns = klien.columns.str.strip()

    brownfield_mw = (
        pd.read_csv(snakemake.input.powerplants_overwrite, index_col=0)
        .query(
            "Country == 'AT' and Fueltype == 'Hydro' and Technology == 'Run-Of-River'"
        )["Capacity"]
        .sum()
    )

    ambition = snakemake.params.klien_ambition
    climate_scenario = snakemake.params.klien_climate_scenario
    corridor = build_klien_ror_trajectory(
        klien, brownfield_mw, planning_horizons, ambition, climate_scenario
    )
    for year, row in corridor.iterrows():
        logger.info(
            f"KLIEN ror buildout for AT {year} ({ambition}/{climate_scenario}): "
            f"factor {row['factor']:.4f} -> max {row['value']:.0f} MW."
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

    logger.info("Building the KLIEN-scaled AT ror capacity corridor...")
    corridor = main(snakemake)
    corridor.to_csv(snakemake.output.klien_ror_trajectory)
    logger.info(f"Saved corridor to {snakemake.output.klien_ror_trajectory}")
