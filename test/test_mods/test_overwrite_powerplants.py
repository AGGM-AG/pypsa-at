# SPDX-FileCopyrightText: 2025-2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""
Unit test for scripts/pypsa-at/overwrite_powerplants.py function overwrite_biogas_to_power_plants_AT
"""

import textwrap

import pandas as pd
import pytest
from overwrite_powerplants import overwrite_biogas_to_power_plants_AT

# Column header of the capacity field in the real Anlagenregister CSV.
CAPACITY_COL = "Engpassleistung (kW <sub>el</sub>)"


@pytest.fixture
def postal_to_nuts_file(tmp_path):
    """Minimal PLZ->NUTS3 file, mirrors data/pypsa-at/AT-Postal-to-NUTS.csv"""
    path = tmp_path / "postal_to_nuts.csv"
    path.write_text(
        textwrap.dedent(
            """\
            NUTS3;CODE
            'AT226';'8761'
            'AT113';'2022'
            'AT321';'8010'
            """
        )
    )
    return str(path)


@pytest.fixture
def anlagenregister_file(tmp_path):
    """
    Anlagenregister sample: three powerplants to map, plus one row with an empty
    Plz that must be dropped.
    """
    path = tmp_path / "anlagenregister.csv"
    df = pd.DataFrame(
        {
            "ID": [6, 4, 204, 999],
            "Plz": [8761, 2022, 8010, pd.NA],
            "Technologie": ["Biogas", "Biogas", "Klärgas", "Biogas"],
            CAPACITY_COL: [500, 250, 140000, 70],
        }
    )
    df.to_csv(path, index=False)
    return str(path)


@pytest.fixture
def ppl():
    """
    Powerplants file without small AT bioenergy rows.
    To check has-powerplantmatching-changed? guard
    """
    return pd.DataFrame(
        {
            "Name": ["Existing DE", "AT Hydro"],
            "Country": ["DE", "AT"],
            "Fueltype": ["Hard Coal", "Hydro"],
            "Capacity": [500.0, 100.0],
        }
    )


@pytest.fixture
def result(ppl, anlagenregister_file, postal_to_nuts_file):
    return overwrite_biogas_to_power_plants_AT(
        ppl, anlagenregister_file, postal_to_nuts_file, threshold_capacity=2
    )


def _biogas(df):
    """Rows are added by the function are called "Biogas AT"."""
    return df[df["Name"].str.startswith("Biogas AT")]


def test_all_valid_rows_added(result, ppl):
    """Every Anlagenregister row with a non-null Plz becomes one biogas plant for ppl file"""
    added = _biogas(result)
    assert len(added) == 3  # ID 999 dropped (empty Plz)
    assert len(result) == len(ppl) + 3


def test_ids_map_to_names(result):
    assert set(_biogas(result)["Name"]) == {
        "Biogas AT 6",
        "Biogas AT 4",
        "Biogas AT 204",
    }


def test_build_year(result):
    added = _biogas(result)
    assert (added["DateIn"] == 2010).all()


def test_mapped_all_plz_to_nuts3(result):
    added = _biogas(result)
    assert not added["bus"].isna().any()  # every PLZ is in one NUTS3 region
    by_name = added.set_index("Name")["bus"]
    assert by_name["Biogas AT 6"] == "AT226"
    assert by_name["Biogas AT 4"] == "AT113"
    assert by_name["Biogas AT 204"] == "AT321"


def test_preserves_existing_rows(result):
    assert {"Existing DE", "AT Hydro"} <= set(result["Name"])


def test_guard_raises_on_small_at_bioenergy(anlagenregister_file, postal_to_nuts_file):
    """Pre-existing small AT bioenergy rows signal an upstream change -> ValueError."""
    ppl = pd.DataFrame(
        {
            "Name": ["Sneaky tiny biogas plant"],
            "Country": ["AT"],
            "Fueltype": ["Bioenergy"],
            "Capacity": [1.5],  # < 2 MW threshold of powerplantmatching
        }
    )
    with pytest.raises(ValueError, match="powerplantmatching"):
        overwrite_biogas_to_power_plants_AT(
            ppl, anlagenregister_file, postal_to_nuts_file, threshold_capacity=2
        )


def test_guard_raises_on_high_threshold(ppl, anlagenregister_file, postal_to_nuts_file):
    """threshold_capacity > 5 MW would filter out small biogas plants -> ValueError."""
    with pytest.raises(ValueError, match="threshold_capacity"):
        overwrite_biogas_to_power_plants_AT(
            ppl, anlagenregister_file, postal_to_nuts_file, threshold_capacity=6
        )
