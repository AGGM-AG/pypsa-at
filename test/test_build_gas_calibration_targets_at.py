# SPDX-FileCopyrightText: 2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""Tests for ``scripts/pypsa-at/build_gas_calibration_targets_at.py``."""

import pandas as pd
import pytest
from build_gas_calibration_targets_at import (
    build_gas_calibration_targets,
    read_econtrol_series,
)


def econtrol_workbook(path, sheet, unit, rows, header="Erdgas\nund\nDerivate"):
    """Write a sheet laid out like the E-Control year series."""
    layout = [
        ["Bestandsstatistik", None, None],
        [None, None, None],
        [None, "Derivate\n(2)", header],
        ["Einheit", unit, unit],
        *[[year, "- ", value] for year, value in rows],
        [None, None, None],
        ["(a) Footnote mentioning 2025", None, None],
        ["Quelle: E-Control", None, None],
    ]
    pd.DataFrame(layout).to_excel(path, sheet_name=sheet, header=False, index=False)
    return str(path)


def test_reads_the_gas_column_by_header(tmp_path):
    path = econtrol_workbook(
        tmp_path / "kwepl.xlsx", "Leistung", "MW", [(2024, 4738.4), (2025, 4813.7)]
    )
    series = read_econtrol_series(path, "Leistung", "MW")
    assert series.to_dict() == {2024: 4738.4, 2025: 4813.7}


def test_years_without_a_value_are_dropped(tmp_path):
    path = econtrol_workbook(
        tmp_path / "kwepl.xlsx", "Leistung", "MW", [(1950, "- "), (2025, 4813.7)]
    )
    assert read_econtrol_series(path, "Leistung", "MW").index.tolist() == [2025]


def test_missing_gas_column_raises(tmp_path):
    path = econtrol_workbook(
        tmp_path / "kwepl.xlsx", "Leistung", "MW", [(2025, 4813.7)], header="Erdgas"
    )
    with pytest.raises(ValueError, match="found 0"):
        read_econtrol_series(path, "Leistung", "MW")


def test_unexpected_unit_raises(tmp_path):
    path = econtrol_workbook(tmp_path / "kwepl.xlsx", "Leistung", "GW", [(2025, 4.8)])
    with pytest.raises(ValueError, match="Expected unit 'MW'"):
        read_econtrol_series(path, "Leistung", "MW")


def test_targets_cover_the_years_both_series_share(tmp_path):
    capacity = econtrol_workbook(
        tmp_path / "kwepl.xlsx", "Leistung", "MW", [(2024, 4000.0), (2025, 5000.0)]
    )
    generation = econtrol_workbook(
        tmp_path / "bilanz.xlsx", "Erz", "GWh", [(2025, 10000.0), (2026, 9000.0)]
    )
    targets = build_gas_calibration_targets(capacity, generation)
    assert targets.to_dict("records") == [
        {
            "year": 2025,
            "capacity_mw_gross": 5000.0,
            "generation_gwh_gross": 10000.0,
            "full_load_hours": 2000.0,
        }
    ]
