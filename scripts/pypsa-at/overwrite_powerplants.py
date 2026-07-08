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


def overwrite_powerplants():
    """Orchestrator function."""
    _ppl = pd.read_csv(snakemake.input.powerplants, index_col=0)
    ppl_overwrite = overwrite_nuclear_dateout(_ppl, CH_NUCLEAR_DATEOUT)

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
            planning_horizons="2020",
            run="AT_KN2040",
        )

    configure_logging(snakemake)

    result = overwrite_powerplants()
    result.to_csv(snakemake.output.powerplants)
