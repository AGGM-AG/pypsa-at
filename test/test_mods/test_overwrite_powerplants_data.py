# SPDX-FileCopyrightText: 2025-2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""
Layer 2 of the biogas-brownfield test route: run overwrite_biogas_to_power_plants_AT
against the REAL committed input files (data/pypsa-at/) and assert the produced
biogas powerplants match the Anlagenregister source.

Catches real-world data drift the synthetic unit tests cannot: silent row drops,
postal codes missing from the NUTS mapping, capacity-column/unit changes, and
duplicate IDs. Needs no solved network (no ``AT`` marker, no ``--result-path``).
"""

import pathlib

import pandas as pd
import pytest
from overwrite_powerplants import overwrite_biogas_to_power_plants_AT

# Column header of the capacity field in the real Anlagenregister CSV.
CAPACITY_COL = "Engpassleistung (kW <sub>el</sub>)"

# Real committed input files consumed by the overwrite_powerplants_at rule.
_DATA = pathlib.Path.cwd() / "data" / "pypsa-at"
ANLAGENREGISTER = _DATA / "Anlagenregister_electricity_from_renewable_gas_AT.csv"
POSTAL_TO_NUTS = _DATA / "AT-Postal-to-NUTS.csv"


@pytest.fixture(scope="module")
def source():
    """Raw Anlagenregister rows with a usable postal code (the ones that must be added)."""
    return pd.read_csv(ANLAGENREGISTER).dropna(subset=["Plz"])


@pytest.fixture(scope="module")
def nuts3_codes():
    """Set of all Austrian NUTS3 codes in the postal->NUTS mapping."""
    postal = pd.read_csv(
        POSTAL_TO_NUTS, sep=";", dtype=str, names=["nuts3", "plz"], header=0
    )
    return set(postal["nuts3"].str.strip("'"))


@pytest.fixture(scope="module")
def added():
    """Biogas plants the function adds when run against the real committed data."""
    # Minimal base with no small AT bioenergy rows (guard 1 must not trigger);
    # the added biogas plants are isolated by the "Biogas AT" name prefix.
    ppl = pd.DataFrame(
        {
            "Name": ["Existing DE", "AT Hydro"],
            "Country": ["DE", "AT"],
            "Fueltype": ["Hard Coal", "Hydro"],
            "Capacity": [500.0, 100.0],
        }
    )
    result = overwrite_biogas_to_power_plants_AT(
        ppl,
        str(ANLAGENREGISTER),
        str(POSTAL_TO_NUTS),
        threshold_capacity=2,
    )
    return result[result["Name"].str.startswith("Biogas AT")]


def test_every_source_plant_is_added(added, source):
    """No silent drops: one biogas plant per Anlagenregister row with a valid Plz."""
    assert len(added) == len(source)


def test_ids_and_names_unique(added, source):
    """Names key on ID; duplicate IDs would collide into fewer/ambiguous plants."""
    assert source["ID"].is_unique
    assert added["Name"].is_unique


def test_no_unmapped_bus(added):
    """Every real postal code resolves to a NUTS3 region (no silent NaN bus)."""
    assert not added["bus"].isna().any()


def test_all_buses_are_at_nuts3(added, nuts3_codes):
    """Assigned buses are valid Austrian NUTS3 codes from the mapping file."""
    assert set(added["bus"]) <= nuts3_codes


def test_capacity_sum_matches_source(added, source):
    """Total added capacity equals the source Engpassleistung converted kW -> MW."""
    assert added["Capacity"].sum() == pytest.approx(source[CAPACITY_COL].sum() / 1000)


def test_covers_all_regions(added, nuts3_codes):
    """Biogas plants land in every Austrian NUTS3 region (full regional coverage)."""
    assert set(added["bus"]) == nuts3_codes
