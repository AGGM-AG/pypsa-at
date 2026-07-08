# SPDX-FileCopyrightText: 2023-2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""
Snakemake script: override DateOut on matched CH nuclear reactors.

Reads the matched powerplants table, applies the CH nuclear DateOut
override, and writes the patched table consumed (only) by ``add_existing_baseyear``.

See Also
--------
mods.network.powerplants.overwrite_nuclear_dateout : the underlying implementation.
"""

import logging

import pandas as pd

from scripts._helpers import configure_logging

logger = logging.getLogger(__name__)

# Real-world / operator retirement years for the four matched CH reactors
CH_NUCLEAR_DATEOUT = {
    "Beznau 1": 2020,
    "Beznau 2": 2020,
    "Goesgen": 2035,  # operation to ~2040; dropped at 2040 horizon
    "Leibstadt": 2040,  # operation to ~2045
}


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


def overwrite_biogas_to_power_plants_AT(
    ppl: pd.DataFrame,
    anlagenregister_file: str,
    postal_to_nuts_file: str,
    threshold_capacity: float,
) -> pd.DataFrame:
    """
    Add Austrian biogas powerplants from the Anlagenregister (https://anlagenregister.at/).
    Geographical mapping file from European Commission (https://gisco-services.ec.europa.eu/tercet/NUTS-2024/pc2025_AT_NUTS-2024_v1.0.zip).

    Parameters
    ----------
    ppl
        Powerplants table with at least ``Name``, ``Country``, ``Fueltype`` and
        ``Capacity`` columns (as produced by ``build_powerplants``).
    anlagenregister_file
        input file of relevant powerplants published for Austria.
    postal_to_nuts_file
        file that maps all Austrian postal codes (PLZ) to NUTS3 region codes.
    threshold_capacity
        capacity threshold (MW) applied downstream when aggregating existing
        plants per node. Must be <= 5 MW, otherwise the small Austrian biogas
        plants added here would be filtered out again.

    Returns
    -------
    A copy of ``ppl`` with added biogas powerplants for Austria from the Anlagenregister.

    Raises
    ------
    ValueError
        If small biogas powerplants are found in the original powerplant file.
        This indicates a change in the upstream file that warrants investigation.
        Also if ``threshold_capacity`` exceeds 5 MW.
    """
    at_small_bioenergy_ppl = ppl[
        (ppl["Country"] == "AT")
        & (ppl["Fueltype"] == "Bioenergy")
        & (ppl["Capacity"] < 2)
    ]
    if not at_small_bioenergy_ppl.empty:
        raise ValueError(
            "Detected biogas powerplants in powerplantmatching data for Austria."
            "Go and check if dataset has changed upstream!"
        )

    if threshold_capacity > 5:
        raise ValueError(
            f"threshold_capacity for adding existing capacities per node is {threshold_capacity} MW,"
            "but must be <= 5 MW to keep small Austrian biogas plants."
            "Change config.at.yaml setting accordingly."
        )

    postal_to_nuts = (
        pd.read_csv(
            postal_to_nuts_file, sep=";", dtype=str, names=["nuts3", "plz"], header=0
        )
        .assign(
            plz=lambda x: x["plz"].str.strip("'"),
            nuts3=lambda x: x["nuts3"].str.strip("'"),
        )
        .set_index("plz")["nuts3"]
    )

    anlreg = pd.read_csv(anlagenregister_file)
    anlreg = anlreg.dropna(subset=["Plz"])
    anlreg["Plz"] = anlreg["Plz"].astype("Int64").astype(str).str.zfill(4)
    anlreg["nuts"] = anlreg["Plz"].map(postal_to_nuts)

    new_ppls = pd.DataFrame(
        {
            "Name": "Biogas AT " + anlreg["ID"].astype(int).astype(str),
            "Fueltype": "Bioenergy",
            "Technology": "Combustion Engine",
            "Set": "PP",
            "Country": "AT",
            "DateIn": 2010,  # assumed build year at the height of Förderung in AT
            "Capacity": anlreg["Engpassleistung (kW <sub>el</sub>)"] / 1000,
            "bus": anlreg["nuts"].values,
        }
    )

    logger.info(
        f"Added {len(new_ppls)} Austrian biogas plants with "
        f"{new_ppls['Capacity'].sum():.1f} MW from Anlagenregister."
    )
    return pd.concat([ppl, new_ppls], ignore_index=True)


def overwrite_powerplants():
    """Orchestrator function."""
    _ppl = pd.read_csv(snakemake.input.powerplants, index_col=0)
    ppl_overwrite = overwrite_nuclear_dateout(_ppl, CH_NUCLEAR_DATEOUT)
    if not snakemake.params.add_biogas_to_power_plants_AT:
        logger.info(
            "Skipping Austrian biogas plant addition. config option add_biogas_to_power_plants_AT is false."
        )
        return ppl_overwrite
    ppl_overwrite = overwrite_biogas_to_power_plants_AT(
        ppl_overwrite,
        anlagenregister_file=snakemake.input.anlagenregister,
        postal_to_nuts_file=snakemake.input.postal_to_nuts,
        threshold_capacity=snakemake.params.threshold_capacity,
    )
    return ppl_overwrite


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
