# SPDX-FileCopyrightText: 2023-2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""
Snakemake script: patch the powerplants table and prepare Austrian biogas plants.

Reads the matched powerplants table, applies the CH nuclear DateOut override
and writes the patched table consumed (only) by ``add_existing_baseyear``.
The Austrian biogas plants from the Anlagenregister are written to a separate
table consumed by ``mods.network.biogas`` in ``modify_prenetwork_at``; they
must not enter the powerplants table, where ``add_existing_baseyear`` would
model them as solid biomass CHPs.
"""

import logging

import pandas as pd

from mods.clustering.utils import map_at_nuts3_to_nuts2
from scripts._helpers import configure_logging

logger = logging.getLogger(__name__)

# Real-world / operator retirement years for the matched CH reactors. Names
# follow the powerplantmatching 0.8.1 dataset pinned in data/versions.csv
# (0.6.1 spelled them "Kkb Kernkw Beznau"/"Kernkraftwerk Gosgen"/
# "Kkl Kernkw Leibstadt Ag", and matched both Beznau units into one row).
CH_NUCLEAR_DATEOUT = {
    "Beznau 1": 2020,
    "Beznau 2": 2020,
    "Goesgen": 2035,  # operation to ~2040; dropped at 2040 horizon
    "Leibstadt": 2040,  # operation to ~2045
}


RENEWABLE_GAS_TECHNOLOGIES = ("Biogas", "Klärgas", "Deponiegas")
"""Anlagenregister ``techcode`` values of electricity from renewable gas."""

LARGE_PLANT_THRESHOLD_MW = 5
"""
Capacity split between the Anlagenregister and powerplantmatching for
Austrian biogas-to-power plants. Register plants at or below this size are
added from the Anlagenregister; larger ones are assumed to already be
captured by powerplantmatching under their true fuel type. For example, the
Gratkorn paper mill is registered in the Anlagenregister as 140 MW "Biogas"
but is already modelled via powerplantmatching as a 70 MW gas CCGT CHP.
"""

BIOGAS_BUILD_YEAR = 2003
"""Assumed build year: height of the Austrian Förderung, phase-out before 2030."""

BIOGAS_PLANT_COLUMNS = [
    "Name",
    "Country",
    "Fueltype",
    "Technology",
    "DateIn",
    "Capacity",
    "bus",
]


def overwrite_nuclear_dateout(ppl: pd.DataFrame, dateout: dict) -> pd.DataFrame:
    """
    Set ``DateOut`` on matched CH nuclear reactors that lack a phase-out year.

    Parameters
    ----------
    ppl
        Powerplants table with at least ``Name``, ``Country``, ``Fueltype`` and
        ``DateOut`` columns (as produced by ``build_powerplants``).
    dateout
        Mapping ``{matched Name: DateOut year}`` for the CH nuclear reactors.

    Returns
    -------
    A copy of ``ppl`` with ``DateOut`` overridden on the matched CH nuclear rows.

    Raises
    ------
    ValueError
        If no CH nuclear rows exist, or if any name in ``dateout`` is not found
        among the CH nuclear rows (fail-fast on broken assumptions).
    """
    is_ch_nuclear = (ppl["Country"] == "CH") & (ppl["Fueltype"] == "Nuclear")
    if not is_ch_nuclear.any():
        raise ValueError(
            "No CH nuclear reactors found in the powerplants table; cannot "
            "override DateOut. Has the matching upstream of build_powerplants "
            "changed?"
        )

    found = set(ppl.loc[is_ch_nuclear, "Name"])
    missing = set(dateout) - found
    if missing:
        raise ValueError(
            f"Expected CH nuclear reactor(s) {sorted(missing)} not found among "
            f"CH nuclear rows {sorted(found)}."
        )

    ppl = ppl.copy()
    for name, year in dateout.items():
        ppl.loc[is_ch_nuclear & (ppl["Name"] == name), "DateOut"] = year

    logger.info(f"Overrode DateOut on {len(dateout)} CH nuclear reactors: {dateout}.")

    return ppl


def build_biogas_plants_AT(
    ppl: pd.DataFrame,
    anlagenregister_file: str,
    postal_to_nuts_file: str,
    threshold_capacity: float,
    clustering: str,
) -> pd.DataFrame:
    """
    Prepare Austrian biogas powerplants from the E-Control Anlagenregister.
    Geographical mapping file from European Commission (https://gisco-services.ec.europa.eu/tercet/NUTS-2024/pc2025_AT_NUTS-2024_v1.0.zip).

    Parameters
    ----------
    ppl
        Powerplants table with at least ``Name``, ``Country``, ``Fueltype`` and
        ``Capacity`` columns (as produced by ``build_powerplants``). Only used
        to guard against small Austrian bioenergy plants appearing upstream.
    anlagenregister_file
        Plant-level Anlagenregister CSV (``anlagenregister_plants.csv`` of the
        ``anlagenregister`` dataset in ``data/versions.csv``). Electricity
        plants (``typ == "Strom"``) with a ``techcode`` in
        ``RENEWABLE_GAS_TECHNOLOGIES`` and a capacity at or below
        ``LARGE_PLANT_THRESHOLD_MW`` are used; larger ones are dropped, see
        ``LARGE_PLANT_THRESHOLD_MW``.
    postal_to_nuts_file
        file that maps all Austrian postal codes (PLZ) to NUTS3 region codes.
    threshold_capacity
        capacity threshold (MW) applied downstream when aggregating existing
        plants per node. Must be <= ``LARGE_PLANT_THRESHOLD_MW``, otherwise
        the small Austrian biogas plants would be filtered out again.
    clustering
        clustering identifier, either AT10 (NUTS2) or AT35 (NUTS3). Needed for
        AT10, maps powerplants accordingly using _map_at_nuts3_to_nuts2.

    Returns
    -------
    One row per Anlagenregister plant with ``Name``, ``Country``, ``Fueltype``,
    ``Technology``, ``DateIn``, ``Capacity`` (MW) and ``bus`` (node), consumed
    by ``mods.network.biogas.add_existing_biogas_chp_at``.

    Raises
    ------
    ValueError
        If small biogas powerplants are found in the original powerplant file.
        This indicates a change in the upstream file that warrants investigation.
        Also if ``threshold_capacity`` exceeds ``LARGE_PLANT_THRESHOLD_MW``, if
        the register holds no renewable-gas plants, or if a postal code is not
        in the mapping.
    """
    at_small_bioenergy_ppl = ppl[
        (ppl["Country"] == "AT")
        & (ppl["Fueltype"] == "Bioenergy")
        & (ppl["Capacity"] < LARGE_PLANT_THRESHOLD_MW)
    ]
    if not at_small_bioenergy_ppl.empty:
        raise ValueError(
            "Detected biogas powerplants in powerplantmatching data for Austria."
            "Go and check if dataset has changed upstream!"
        )

    if threshold_capacity > LARGE_PLANT_THRESHOLD_MW:
        raise ValueError(
            f"threshold_capacity for adding existing capacities per node is {threshold_capacity} MW,"
            f"but must be <= {LARGE_PLANT_THRESHOLD_MW} MW to keep small Austrian biogas plants."
            "Change config.at.yaml setting accordingly."
        )

    postal_to_nuts = pd.read_csv(
        postal_to_nuts_file, dtype=str, names=["nuts3", "plz"], header=0
    ).set_index("plz")["nuts3"]

    register = pd.read_csv(anlagenregister_file, low_memory=False)
    register["techcode"] = register["techcode"].fillna("").str.strip()
    anlreg = register[
        (register["typ"] == "Strom")
        & register["techcode"].isin(RENEWABLE_GAS_TECHNOLOGIES)
    ].copy()
    if anlreg.empty:
        raise ValueError(
            f"No electricity plants with techcode in {RENEWABLE_GAS_TECHNOLOGIES} "
            f"found in {anlagenregister_file}. Has the Anlagenregister changed?"
        )

    too_large = anlreg["engpassleistung_kw"] / 1000 > LARGE_PLANT_THRESHOLD_MW
    if too_large.any():
        logger.warning(
            f"Dropped {int(too_large.sum())} renewable-gas plants "
            f"({anlreg.loc[too_large, 'engpassleistung_kw'].sum() / 1e3:.1f} MW) "
            f"above {LARGE_PLANT_THRESHOLD_MW} MW; assumed to already be "
            "captured by powerplantmatching under their true fuel type."
        )
        anlreg = anlreg[~too_large]

    # the register holds free-text postal codes ("4600 ", "5431 Kuchl", ...);
    # take the first run of exactly four digits, like build_anlagenregister_at
    anlreg["Plz"] = (
        anlreg["plz"].fillna("").astype(str).str.extract(r"(?<!\d)(\d{4})(?!\d)")[0]
    )
    without_plz = anlreg["Plz"].isna()
    if without_plz.any():
        logger.warning(
            f"Dropped {int(without_plz.sum())} renewable-gas plants "
            f"({anlreg.loc[without_plz, 'engpassleistung_kw'].sum() / 1e3:.2f} MW) "
            "without a postal code."
        )
        anlreg = anlreg[~without_plz]
    anlreg["nuts"] = anlreg["Plz"].map(postal_to_nuts)

    missing_plz = anlreg.loc[anlreg["nuts"].isna(), "Plz"].unique()
    if len(missing_plz) > 0:
        raise ValueError(
            f"Postal codes {sorted(missing_plz)} from Anlagenregister not found in"
            f"postal-to-nuts-file. Update mapping or check data."
        )

    # Relabel NUTS3 codes to NUTS2 if run has lower resolution
    if clustering.startswith("AT10"):
        anlreg["nuts"] = anlreg["nuts"].map(map_at_nuts3_to_nuts2)

    plants = pd.DataFrame(
        {
            # register ids are scrape row numbers, not stable across versions
            "Name": "Biogas AT " + anlreg["id"].astype(int).astype(str),
            "Country": "AT",
            "Fueltype": "Biogas",
            "Technology": anlreg["techcode"].values,
            "DateIn": BIOGAS_BUILD_YEAR,
            "Capacity": anlreg["engpassleistung_kw"].to_numpy(dtype=float) / 1000,
            "bus": anlreg["nuts"].values,
        }
    )

    logger.info(
        f"Prepared {len(plants)} Austrian biogas plants with "
        f"{plants['Capacity'].sum():.1f} MW from Anlagenregister."
    )
    return plants


def overwrite_powerplants() -> pd.DataFrame:
    """Patch the powerplants table."""
    _ppl = pd.read_csv(snakemake.input.powerplants, index_col=0)
    return overwrite_nuclear_dateout(_ppl, CH_NUCLEAR_DATEOUT)


def biogas_plants(ppl: pd.DataFrame) -> pd.DataFrame:
    """Prepare the Austrian biogas plants, or an empty table when disabled."""
    if not snakemake.params.add_biogas_to_power_plants_AT:
        logger.info(
            "Skipping Austrian biogas plant addition. config option add_biogas_to_power_plants_AT is false."
        )
        return pd.DataFrame(columns=BIOGAS_PLANT_COLUMNS)
    return build_biogas_plants_AT(
        ppl,
        anlagenregister_file=snakemake.input.anlagenregister,
        postal_to_nuts_file=snakemake.input.postal_to_nuts,
        threshold_capacity=snakemake.params.threshold_capacity,
        clustering=snakemake.params.clustering,
    )


if __name__ == "__main__":
    if "snakemake" not in globals():
        from scripts._helpers import mock_snakemake

        snakemake = mock_snakemake(
            "overwrite_powerplants_at",
            simpl="",
            clusters="adm",
            opts="",
            ll="v1.25",
            sector_opts="none",
            planning_horizons="2025",
            run="AT_KN2040",
        )

    configure_logging(snakemake)

    result = overwrite_powerplants()
    result.to_csv(snakemake.output.powerplants)
    biogas_plants(result).to_csv(snakemake.output.biogas_plants, index=False)
