# SPDX-FileCopyrightText: 2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
"""Unit tests for TYNDP-specific helpers vendored into scripts/_tyndp_helpers.py."""

import textwrap

import pandas as pd
import pytest

from scripts._tyndp_helpers import (
    align_demand_to_snapshots,
    check_cyear,
    convert_units,
    interpolate_demand,
    make_index,
    map_tyndp_carrier_names,
    safe_pyear,
)


@pytest.mark.parametrize(
    "year, available, expected",
    [
        (2030, [2030, 2040, 2050], 2030),  # exact match
        (2025, [2030, 2040, 2050], 2030),  # before first available year
        (2035, [2030, 2040, 2050], 2030),  # between years
        (2055, [2030, 2040, 2050], 2050),  # above last available year
        ("2040", [2030, 2040, 2050], 2040),  # string year accepted
    ],
)
def test_safe_pyear(year, available, expected):
    assert safe_pyear(year, available) == expected


def test_safe_pyear_raises_on_empty_years():
    with pytest.raises(ValueError):
        safe_pyear(2030, [])


def test_map_tyndp_carrier_names_basic(tmp_path):
    csv = textwrap.dedent("""\
        investment_dataset_carrier,open_tyndp_carrier,open_tyndp_index,open_tyndp_type,pypsa_eur_carrier
        Solar PV Utility,solar-pv-utility,solar-pv-utility,solar-pv-utility,solar(-hsat)
    """)
    mapping_fn = tmp_path / "_test_carrier_map.csv"
    mapping_fn.write_text(csv)
    df = pd.DataFrame({"investment_dataset_carrier": ["Solar PV Utility"]})
    result = map_tyndp_carrier_names(
        df, str(mapping_fn), ["investment_dataset_carrier"]
    )
    assert "open_tyndp_carrier" in result.columns
    assert result.iloc[0]["open_tyndp_carrier"] == "solar-pv-utility"
    assert result.iloc[0]["pypsa_eur_carrier"] == "solar(-hsat)"


@pytest.mark.parametrize(
    "unit, value, expected_value, expected_unit",
    [
        ("MW", 100.0, 100.0, "MW"),
        ("GW", 1.0, 1000.0, "MW"),
    ],
)
def test_convert_units(unit, value, expected_value, expected_unit):
    df = pd.DataFrame({"unit": [unit], "value": [value]})
    result = convert_units(df)
    assert result.iloc[0]["value"] == pytest.approx(expected_value)
    assert result.iloc[0]["unit"] == expected_unit


@pytest.mark.parametrize(
    "cyear, scenario, expected",
    [
        (2009, "NT", 2009),  # valid year passes through
        (2020, "NT", 2009),  # invalid year falls back to 2009
    ],
)
def test_check_cyear(cyear, scenario, expected):
    assert check_cyear(cyear, scenario) == expected


@pytest.mark.parametrize(
    "request_year, expected",
    [
        (2030, 100.0),  # exact match returns first year's value
        (2035, 150.0),  # midpoint interpolates linearly
    ],
)
def test_interpolate_demand(request_year, expected):
    data = {2030: pd.DataFrame({"AT": [100.0]}), 2040: pd.DataFrame({"AT": [200.0]})}
    result = interpolate_demand([2030, 2040], request_year, lambda pyear: data[pyear])
    assert result.iloc[0]["AT"] == pytest.approx(expected)


def test_align_demand_to_snapshots():
    snapshots = pd.date_range("2030-01-01", periods=3, freq="h")
    demand = pd.DataFrame(
        {"AT": [1.0, 2.0, 3.0]},
        index=pd.date_range("2020-01-01", periods=3, freq="h"),
    )
    result = align_demand_to_snapshots(demand, snapshots)
    assert list(result.index.year) == [2030, 2030, 2030]
    assert list(result["AT"]) == [1.0, 2.0, 3.0]


@pytest.mark.parametrize(
    "row, prefix, expected",
    [
        ({"bus0": "DE00", "bus1": "AT00"}, None, "DE00 -> AT00"),
        ({"bus0": "DE00", "bus1": "AT00"}, "H2 import", "H2 import DE00 -> AT00"),
    ],
)
def test_make_index(row, prefix, expected):
    kwargs = {"prefix": prefix} if prefix is not None else {}
    assert make_index(pd.Series(row), **kwargs) == expected
