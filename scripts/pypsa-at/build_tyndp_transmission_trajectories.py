# SPDX-FileCopyrightText: 2025-2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""
Read TYNDP transmission investment (GRID.xlsx) and electricity reference grid
(ReferenceGrid_Electricity.xlsx) xlsx files and aggregate NTC per border and year.
"""

import logging
from pathlib import Path

import pandas as pd

from mods import TYNDP_TO_PYPSA_LOCATION_TRANSMISSION
from mods.utils import resolve_tyndp_locations
from scripts._helpers import configure_logging, set_scenario_config

logger = logging.getLogger(__name__)


def sort_data(df: pd.DataFrame) -> pd.DataFrame:
    """
    Normalise border direction and sort rows for consistent aggregation.

    Drops rows with NaN values and self-loops, then canonicalises border
    direction so that ``from_node < to_node`` lexicographically (swapping
    direct/indirect capacities where needed). Finally sorts by
    ``from_node``, ``to_node``.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame containing at least the columns ``from_node``,
        ``to_node``, ``direct_capacity``, and ``indirect_capacity``.

    Returns
    -------
    pd.DataFrame
        Cleaned and sorted DataFrame with a canonical border direction.
    """
    df = df.dropna()
    df = df[df["from_node"] != df["to_node"]]
    mask = df["from_node"] > df["to_node"]
    canonical = df.loc[~mask]
    flipped = df.loc[mask].rename(
        columns={
            "from_node": "to_node",
            "to_node": "from_node",
            "direct_capacity": "indirect_capacity",
            "indirect_capacity": "direct_capacity",
        }
    )
    df = pd.concat([canonical, flipped])
    df = df.sort_values(["from_node", "to_node"])
    return df


def read_elec_reference_grid(fn: str | Path) -> pd.DataFrame:
    """
    Read the TYNDP Electricity Reference Grid Excel file for year 2030.

    Parses the ``"2030"`` sheet, splits the ``"Border"`` column on ``"-"``
    into ``FROM NODE`` / ``TO NODE``, and renames the summary capacity
    columns to ``direct_capacity`` / ``indirect_capacity``.

    Parameters
    ----------
    fn : str | Path
        Path to the ``ReferenceGrid_Electricity.xlsx`` file.

    Returns
    -------
    pd.DataFrame
        DataFrame with at least the columns ``FROM NODE``, ``TO NODE``,
        ``direct_capacity``, and ``indirect_capacity``.
    """
    ref_sheets = pd.read_excel(fn, sheet_name=None)
    tyndp_2030 = ref_sheets["2030"]
    borders = tyndp_2030["Border"].str.split("-", expand=True)
    tyndp_2030["FROM NODE"] = borders[0]
    tyndp_2030["TO NODE"] = borders[1]
    tyndp_2030 = tyndp_2030.rename(
        columns={
            "Summary Direction 1": "direct_capacity",
            "Summary Direction 2": "indirect_capacity",
        }
    )
    return tyndp_2030


def read_invest_grid(fn: str | Path) -> pd.DataFrame:
    """
    Read the TYNDP Grid Investment Dataset Excel file.

    Parses the ``"Electricity"`` sheet and renames the capacity-increase
    columns to ``direct_capacity`` / ``indirect_capacity``.

    Parameters
    ----------
    fn : str | Path
        Path to the ``GRID.xlsx`` (Grid Investment Dataset) file.

    Returns
    -------
    pd.DataFrame
        DataFrame with at least the columns ``FROM NODE``, ``TO NODE``,
        ``BORDER``, ``direct_capacity``, and ``indirect_capacity``.
    """
    invest_sheets = pd.read_excel(fn, sheet_name=None)
    investments = invest_sheets["Electricity"]
    investments = investments.rename(
        columns={
            "DIRECT CAPACITY INCREASE (MW)": "direct_capacity",
            "INDIRECT CAPACITY INCREASE (MW)": "indirect_capacity",
        }
    )
    return investments


def map_tyndp_nodes(df: pd.DataFrame, mapping: dict) -> pd.DataFrame:
    """
    Validate TYNDP node codes and add slugified PyPSA location columns.

    Checks that every value in ``FROM NODE`` and ``TO NODE`` is a key in
    *mapping*, then creates lower-snake-case columns ``from_node`` and
    ``to_node`` by applying the mapping.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame containing ``FROM NODE`` and ``TO NODE`` columns
        with TYNDP node codes (e.g. ``"AT00"``).
    mapping : dict
        Dict mapping TYNDP node codes to PyPSA location strings
        (e.g. ``{"AT00": "AT"}``). Codes not modelled in PyPSA may
        map to ``None``.

    Returns
    -------
    pd.DataFrame
        The input DataFrame with two new columns: ``from_node`` and
        ``to_node``.

    Raises
    ------
    ValueError
        If any TYNDP node code in ``FROM NODE`` or ``TO NODE``
        is not present in *mapping*.
    """
    for col in ["FROM NODE", "TO NODE"]:
        if not df[col].isin(mapping.keys()).all():
            raise ValueError(
                f"Unknown TYNDP node code in column '{col}'. "
                "Update TYNDP_TO_PYPSA_LOCATION_TRANSMISSION in mods/constants.py."
            )
        df[col.lower().replace(" ", "_")] = df[col].map(mapping)
    return df


def build_trajectories(
    tyndp_2030: pd.DataFrame,
    investments: pd.DataFrame,
) -> pd.DataFrame:
    """
    Aggregate TYNDP border capacities into a multi-year trajectory table.

    Constructs four annual snapshots:

    * **2025** — same NTC as 2030 reference grid (assumed already built).
    * **2030** — summed NTC from the Electricity Reference Grid.
    * **2040** — 2030 base plus ``"Real"`` projects from the investment dataset.
    * **2050** — 2040 base plus ``"Concept"`` projects from the investment dataset.

    Parameters
    ----------
    tyndp_2030 : pd.DataFrame
        Cleaned reference-grid DataFrame as returned by
        :func:`read_elec_reference_grid` after node mapping and
        :func:`sort_data`.  Must contain ``from_node``, ``to_node``,
        ``direct_capacity``, ``indirect_capacity``.
    investments : pd.DataFrame
        Cleaned investment DataFrame as returned by
        :func:`read_invest_grid` after node mapping and
        :func:`sort_data`.  Must additionally contain a ``BORDER``
        column used to filter ``"Real"`` and ``"Concept"`` projects.

    Returns
    -------
    pd.DataFrame
        DataFrame indexed by ``(from_node, to_node)`` with columns
        ``direct_capacity``, ``indirect_capacity``, and ``year``,
        sorted by ``year``, ``from_node``, ``to_node``.
    """
    capacity_cols = ["direct_capacity", "indirect_capacity"]

    base = tyndp_2030.groupby(["from_node", "to_node"])[capacity_cols].sum()
    base["year"] = 2030

    base_2025 = base.copy()
    base_2025["year"] = 2025

    invest_2040 = (
        investments.loc[
            investments["BORDER"].str.contains("Real", na=False),
            ["from_node", "to_node", *capacity_cols],
        ]
        .copy()
        .groupby(["from_node", "to_node"])[capacity_cols]
        .sum()
        .add(base.drop(columns=["year"]), fill_value=0)
    )
    invest_2040["year"] = 2040

    invest_2050 = (
        investments.loc[
            investments["BORDER"].str.contains("Concept", na=False),
            ["from_node", "to_node", *capacity_cols],
        ]
        .copy()
        .groupby(["from_node", "to_node"])[capacity_cols]
        .sum()
        .add(invest_2040.drop(columns=["year"]), fill_value=0)
    )
    invest_2050["year"] = 2050

    tyndp_transmission = pd.concat([base_2025, base, invest_2040, invest_2050])
    tyndp_transmission = tyndp_transmission.sort_values(
        ["year", "from_node", "to_node"]
    )
    return tyndp_transmission


def build_tyndp_transmission_trajectories(
    elec_reference_grid_fn: str | Path,
    invest_grid_fn: str | Path,
    location_mapping: dict,
) -> pd.DataFrame:
    """
    Read, map, and aggregate TYNDP transmission data into a multi-year NTC table.

    Orchestrates the full pipeline: reads the Electricity Reference Grid and
    Grid Investment Dataset Excel files, validates and maps TYNDP node codes to
    PyPSA location strings, canonicalises border directions, and builds a
    four-year (2025/2030/2040/2050) NTC trajectory DataFrame.

    Parameters
    ----------
    elec_reference_grid_fn : str | Path
        Path to ``ReferenceGrid_Electricity.xlsx``.
    invest_grid_fn : str | Path
        Path to ``GRID.xlsx`` (Grid Investment Dataset).
    location_mapping : dict
        The resolved TYNDP location mapping for the clustering.

    Returns
    -------
    pd.DataFrame
        DataFrame indexed by ``(from_node, to_node)`` with columns
        ``direct_capacity``, ``indirect_capacity``, and ``year``,
        sorted by ``year``, ``from_node``, ``to_node``.
    """
    tyndp_2030 = read_elec_reference_grid(elec_reference_grid_fn)
    investments = read_invest_grid(invest_grid_fn)

    tyndp_2030 = map_tyndp_nodes(tyndp_2030, location_mapping)
    investments = map_tyndp_nodes(investments, location_mapping)

    tyndp_2030 = sort_data(tyndp_2030)
    investments = sort_data(investments)

    return build_trajectories(tyndp_2030, investments)


def main(snakemake) -> None:
    """
    Write TYNDP transmission trajectories CSV from Snakemake inputs.

    Parameters
    ----------
    snakemake : snakemake object
        Snakemake object providing ``input.elec_reference_grid``,
        ``input.invest_grid``, and
        ``output.tyndp_transmission_trajectories``.
    """
    location_mapping = resolve_tyndp_locations(
        snakemake.params.admin_levels,
        snakemake.params.custom_clustering,
        TYNDP_TO_PYPSA_LOCATION_TRANSMISSION,
    )
    tyndp_transmission = build_tyndp_transmission_trajectories(
        snakemake.input.elec_reference_grid,
        snakemake.input.invest_grid,
        location_mapping,
    )
    out_path = snakemake.output.tyndp_transmission_trajectories
    tyndp_transmission.to_csv(out_path)
    logger.info(f"Wrote tyndp transmission limits to '{out_path}'")


if __name__ == "__main__":
    if "snakemake" not in globals():
        from scripts._helpers import mock_snakemake

        snakemake = mock_snakemake("build_tyndp_transmission_trajectories")
    configure_logging(snakemake)
    set_scenario_config(snakemake)
    main(snakemake)
