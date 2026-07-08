# SPDX-FileCopyrightText: 2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.

"""Unit tests for scripts/open-tyndp/build_tyndp_trajectories.py nuclear scenario collapse."""

import pandas as pd
from build_tyndp_trajectories import collapse_nuclear_scenarios

_COLS = [
    "carrier",
    "index_carrier",
    "bus",
    "scenario",
    "pyear",
    "p_nom_min",
    "p_nom_max",
    "pypsa_eur_carrier",
    "open_tyndp_type",
]


def _nuclear_row(scenario, p_nom_min, p_nom_max, bus="CZ00", pyear=2050):
    return {
        "carrier": "uranium",
        "index_carrier": "nuclear",
        "bus": bus,
        "scenario": scenario,
        "pyear": pyear,
        "p_nom_min": p_nom_min,
        "p_nom_max": p_nom_max,
        "pypsa_eur_carrier": "nuclear",
        "open_tyndp_type": "nuclear",
    }


def _onwind_row(p_nom_min, p_nom_max, bus="BE00", pyear=2050):
    return {
        "carrier": "AC",
        "index_carrier": "onwind",
        "bus": bus,
        "scenario": "All",
        "pyear": pyear,
        "p_nom_min": p_nom_min,
        "p_nom_max": p_nom_max,
        "pypsa_eur_carrier": "onwind",
        "open_tyndp_type": "onwind-onshore",
    }


def test_collapse_all_takes_min_of_min_and_max_of_max():
    """For 'All', nuclear collapses to one row: smallest p_nom_min, largest p_nom_max."""
    df = pd.DataFrame(
        [
            _nuclear_row("DE", 3000.0, 4000.0),
            _nuclear_row("GA", 3500.0, 9000.0),
            _nuclear_row("NT", 2000.0, 5000.0),
        ],
        columns=_COLS,
    )

    result = collapse_nuclear_scenarios(df, "All")

    nuclear = result[result["index_carrier"] == "nuclear"]
    assert len(nuclear) == 1
    row = nuclear.iloc[0]
    assert row["scenario"] == "All"
    assert row["p_nom_min"] == 2000.0
    assert row["p_nom_max"] == 9000.0


def test_collapse_all_keeps_buses_and_years_separate():
    """Collapse groups by (bus, pyear): different buses/years stay distinct rows."""
    df = pd.DataFrame(
        [
            _nuclear_row("DE", 1.0, 2.0, bus="CZ00", pyear=2030),
            _nuclear_row("GA", 3.0, 4.0, bus="CZ00", pyear=2030),
            _nuclear_row("DE", 10.0, 20.0, bus="FR00", pyear=2050),
            _nuclear_row("GA", 30.0, 40.0, bus="FR00", pyear=2050),
        ],
        columns=_COLS,
    )

    result = collapse_nuclear_scenarios(df, "All")
    nuclear = result[result["index_carrier"] == "nuclear"]

    assert len(nuclear) == 2
    cz = nuclear[(nuclear["bus"] == "CZ00") & (nuclear["pyear"] == 2030)].iloc[0]
    fr = nuclear[(nuclear["bus"] == "FR00") & (nuclear["pyear"] == 2050)].iloc[0]
    assert (cz["p_nom_min"], cz["p_nom_max"]) == (1.0, 4.0)
    assert (fr["p_nom_min"], fr["p_nom_max"]) == (10.0, 40.0)


def test_collapse_specific_scenario_filters_nuclear():
    """A concrete scenario selects nuclear values for that scenario directly."""
    df = pd.DataFrame(
        [
            _nuclear_row("DE", 3000.0, 4000.0),
            _nuclear_row("GA", 3500.0, 9000.0),
            _nuclear_row("NT", 2000.0, 5000.0),
        ],
        columns=_COLS,
    )

    result = collapse_nuclear_scenarios(df, "GA")
    nuclear = result[result["index_carrier"] == "nuclear"]

    assert len(nuclear) == 1
    row = nuclear.iloc[0]
    assert row["scenario"] == "GA"
    assert row["p_nom_min"] == 3500.0
    assert row["p_nom_max"] == 9000.0


def test_collapse_leaves_non_nuclear_untouched():
    """Non-nuclear carriers (only the 'All' label) pass through unchanged."""
    onwind = _onwind_row(10.0, 50.0)
    df = pd.DataFrame(
        [
            onwind,
            _nuclear_row("DE", 1.0, 2.0),
            _nuclear_row("GA", 3.0, 4.0),
        ],
        columns=_COLS,
    )

    result = collapse_nuclear_scenarios(df, "All")
    non_nuclear = result[result["index_carrier"] != "nuclear"]

    assert len(non_nuclear) == 1
    pd.testing.assert_series_equal(
        non_nuclear.iloc[0][_COLS], pd.Series(onwind, name=non_nuclear.index[0])
    )
