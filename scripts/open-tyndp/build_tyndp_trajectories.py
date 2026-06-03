# SPDX-FileCopyrightText: Contributors to Open-TYNDP <https://github.com/open-energy-transition/open-tyndp>
#
# SPDX-License-Identifier: MIT
"""
Loads and cleans the TYNDP capacity trajectories for a given TYNDP scenario.

Outputs
-------
Cleaned CSV file with all TYNDP trajectories (`p_nom_min`, `p_nom_max`) in long format.

- ``resources/tyndp_trajectories.csv`` in long format.
"""

import logging

import pandas as pd

from scripts._helpers import configure_logging, set_scenario_config
from scripts._tyndp_helpers import SCENARIO_DICT, map_tyndp_carrier_names

logger = logging.getLogger(__name__)


def collapse_nuclear_scenarios(df: pd.DataFrame, tyndp_scenario: str) -> pd.DataFrame:
    """
    Reduce per-scenario nuclear trajectories to a single row per (bus, pyear).

    Unlike the RES/storage carriers (which only carry the scenario-independent
    ``"All"`` label), TYNDP provides nuclear trajectories per scenario
    (``DE``/``GA``/``NT``).  Downstream readers do not filter by scenario, so
    nuclear must be collapsed to one row per location and horizon:

    - ``tyndp_scenario == "All"``: take the smallest ``p_nom_min`` and the
      largest ``p_nom_max`` across all scenarios, labelled ``"All"``.
    - any concrete scenario (e.g. ``"GA"``): keep that scenario's values
      directly.

    Non-nuclear rows are returned unchanged.

    Parameters
    ----------
    df:
        Long-format trajectory DataFrame with columns ``bus``, ``scenario``,
        ``pyear``, ``p_nom_min``, ``p_nom_max``, ``index_carrier``, and the
        remaining metadata columns.
    tyndp_scenario:
        Configured TYNDP scenario key (``mods.PEMMDB_trajectories.tyndp_scenario``).

    Returns
    -------
    pd.DataFrame
        DataFrame with the same columns where nuclear rows are reduced to one
        row per ``(bus, pyear)``.
    """
    valid_scenarios = sorted(SCENARIO_DICT.values()) + ["All"]
    if tyndp_scenario not in valid_scenarios:
        raise ValueError(f"Scenario {tyndp_scenario} not recognized.")

    is_nuclear = df["index_carrier"] == "nuclear"
    nuclear, rest = df[is_nuclear], df[~is_nuclear]

    if tyndp_scenario == "All":
        group_keys = [
            "carrier",
            "index_carrier",
            "bus",
            "pyear",
            "pypsa_eur_carrier",
            "open_tyndp_type",
        ]
        nuclear = (
            nuclear.groupby(group_keys, as_index=False)
            .agg(p_nom_min=("p_nom_min", "min"), p_nom_max=("p_nom_max", "max"))
            .assign(scenario="All")
        )
    else:
        nuclear = nuclear[nuclear["scenario"] == tyndp_scenario]

    return pd.concat([rest, nuclear[df.columns]], ignore_index=True)


if __name__ == "__main__":
    if "snakemake" not in globals():
        from scripts._helpers import mock_snakemake

        snakemake = mock_snakemake(
            "build_tyndp_trajectories",
            clusters="adm",
            planning_horizons=2030,
        )
    configure_logging(snakemake)
    set_scenario_config(snakemake)

    # Parameters
    fn = snakemake.input.trajectories
    column_names = {
        "NODE": "bus",
        "SCENARIO": "scenario",
        "TECHNOLOGY": "investment_dataset_carrier",
        "YEAR": "pyear",
        "MIN CAPACITY [MW]": "p_nom_min",
        "MAX CAPACITY [MW]": "p_nom_max",
    }

    df = (
        pd.read_excel(fn, sheet_name="GLOBAL")
        .rename(column_names, axis="columns")
        .replace(SCENARIO_DICT, regex=True)
        .replace("UK", "GB", regex=True)
    )

    carrier_mapping_fn = snakemake.input.carrier_mapping

    # col = "investment_dataset_carrier"
    # mapping = pd.read_csv(carrier_mapping_fn)[[col, "pypsa_eur_carrier"]]
    # mapping = mapping.dropna(subset=col, axis=0).set_index(col)
    # df
    df = map_tyndp_carrier_names(
        df, carrier_mapping_fn, ["investment_dataset_carrier"], drop_on_columns=True
    )

    # Add 2025 planning horizon (not present in TYNDP data) with zero values as placeholder
    rows_2025 = (
        df[df["pyear"] == 2030].copy().assign(pyear=2025, p_nom_min=0.0, p_nom_max=0.0)
    )
    df = pd.concat([df, rows_2025], ignore_index=True)

    # Extrapolate backward to fill leading zeros (covers both 2025 and any 2030 zeros)
    # Uses the slope between the two earliest non-zero values per group
    group_keys = [
        "pypsa_eur_carrier",
        "index_carrier",
        "bus",
        "scenario",
        "open_tyndp_type",
    ]

    def extrapolate_backward(group):
        group = group.sort_values("pyear").copy()
        for col in ["p_nom_min", "p_nom_max"]:
            nonzero = group[group[col] != 0]
            if len(nonzero) < 2:
                continue
            y1, y2 = nonzero["pyear"].iloc[0], nonzero["pyear"].iloc[1]
            v1, v2 = nonzero[col].iloc[0], nonzero[col].iloc[1]
            slope = (v2 - v1) / (y2 - y1)
            if col == "p_nom_min":
                slope = max(0, slope)  # prevent negative
            mask = (group["pyear"] < y1) & (group[col] == 0)
            group.loc[mask, col] = ((group.loc[mask, "pyear"] - y1) * slope + v1).clip(
                lower=0.0
            )
        # extrapolated p_nom_min must never exceed p_nom_max (e.g. when p_nom_max clips to 0)
        group["p_nom_min"] = group[["p_nom_min", "p_nom_max"]].min(axis=1)
        return group

    df = pd.concat(
        [extrapolate_backward(group) for _, group in df.groupby(group_keys)],
        ignore_index=True,
    )

    # Final sanity check
    delta = df["p_nom_max"] - df["p_nom_min"]
    if delta.lt(0).any():
        raise ValueError(
            f"Trajectory floors are larger than ceilings:\n{df.loc[delta.index]}"
        )

    # set p_nom_min to zero for RES in 2025. The 2025 may be correct and optimal.
    # Don't want to shift the optimum for the historical base year
    _idx = df.query("index_carrier != 'nuclear' & pyear == 2025").index
    df.loc[_idx, "p_nom_min"] = 0

    # Nuclear trajectories are provided per scenario (DE/GA/NT) — collapse them to
    # one row per (bus, pyear) so the scenario-agnostic readers see a single value.
    df = collapse_nuclear_scenarios(df, snakemake.params.tyndp_scenario)

    df.to_csv(snakemake.output.tyndp_trajectories, index=False)
