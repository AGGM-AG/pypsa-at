# SPDX-FileCopyrightText: 2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""Tests for p_nom_max and p_nom_min of generators in solved networks against reference CSV files."""

import pathlib
import re

import pandas as pd
import pytest


def _check_p_nom_bound(nc, carrier, csv_path, attr):
    """
    Compare solved-network generator p_nom bound against a reference CSV.

    For each planning horizon in the network collection, filters the reference
    CSV to rows matching the given carrier and year, then compares against the
    solved network. The ``attr`` column is used for extendable generators;
    ``p_nom`` is used for non-extendable generators (via ``Series.where``).
    Skips at runtime if ``csv_path`` does not exist.

    Parameters
    ----------
    nc
        A ``pypsa.NetworkCollection`` whose ``.networks`` maps year → Network.
    carrier
        Exact carrier string to filter generators (e.g. ``"solar"``).
    csv_path
        Path to the reference CSV file (``pathlib.Path``).
    attr
        Generator attribute to compare (``"p_nom_max"`` or ``"p_nom_min"``).

    Raises
    ------
    FileNotFoundError
        If the dedicated test file is not found.
    """
    if not csv_path.exists():
        raise FileNotFoundError(f"Reference file not found: {csv_path}")

    ref = pd.read_csv(csv_path, index_col=0)

    for year, n in nc.networks.items():
        # \b prevents partial matches (e.g. "bussolar" matching "solar")
        mask = ref.index.str.contains(rf"\b{re.escape(carrier)}-{year}$", regex=True)
        expected = ref.loc[mask]
        if (
            expected.empty
        ):  # carrier not present in reference for this horizon — skip year
            continue

        expected.index = expected.index.str.replace(r"-\d{4}$", "", regex=True)
        generators = n.generators
        generators.index = generators.index.str.replace(r"-\d{4}$", "", regex=True)
        generators = generators[generators.index.isin(expected.index)]

        actual = pd.concat(
            [
                generators.loc[generators["p_nom_extendable"], attr],
                generators.loc[~generators["p_nom_extendable"], "p_nom"].rename(attr),
            ]
        )
        actual = actual.groupby(level=0).sum()

        expected = expected[attr].sort_index()
        expected.index.name = "name"
        actual = actual.sort_index()

        pd.testing.assert_series_equal(actual, expected)


@pytest.mark.AT
@pytest.mark.parametrize("carrier", ["onwind", "solar", "solar-hsat", "solar rooftop"])
def test_p_nom_max(nc, carrier):
    """Verify p_nom_max (extendable) / p_nom (non-extendable) against reference CSV."""
    _check_p_nom_bound(
        nc,
        carrier,
        pathlib.Path(__file__).parent.parent / "test_data" / "gen_p_nom_max.csv",
        "p_nom_max",
    )
