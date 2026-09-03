# SPDX-FileCopyrightText: 2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""Tests for the Anlagenregister Kleinwasserkraft addition."""

import pandas as pd
import pytest
from overwrite_powerplants import (
    KLEINWASSERKRAFT_NAME_PREFIX,
    add_kleinwasserkraft_to_power_plants_at,
)


@pytest.fixture
def anlagenregister_plants_file(tmp_path) -> str:
    plants = pd.DataFrame(
        {
            "typ": ["Strom", "Strom", "Strom"],
            "id": [1, 2, 3],
            "plz": ["9872", "9906", "7571"],
            "bundesland": ["K", "T", "B"],
            "techcode": [
                "Kleinwasserkraft bis 10 MW",
                "Kleinwasserkraft bis 10 MW",
                "Photovoltaik",
            ],
            "engpassleistung_kw": [500.0, 1200.0, 15.0],
            "feedin_kwh_2024": [1000.0, 0.0, 10.0],
            "feedin_kwh_2025": [1000.0, 2000.0, 10.0],
        }
    )
    path = tmp_path / "anlagenregister_plants.csv"
    plants.to_csv(path, index=False)
    return str(path)


@pytest.fixture
def postal_to_nuts_file(tmp_path) -> str:
    path = tmp_path / "postal_to_nuts.csv"
    pd.DataFrame(
        {"NUTS3": ["AT212", "AT333", "AT111"], "CODE": ["9872", "9906", "7571"]}
    ).to_csv(path, index=False)
    return str(path)


@pytest.fixture
def ppl() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Name": ["Big Dam"],
            "Country": ["AT"],
            "Fueltype": ["Hydro"],
            "Technology": ["Run-Of-River"],
            "Set": ["PP"],
            "Capacity": [100.0],
            "bus": ["AT212"],
        }
    )


def test_kleinwasserkraft_rows_carry_plz(
    ppl, anlagenregister_plants_file, postal_to_nuts_file
):
    out = add_kleinwasserkraft_to_power_plants_at(
        ppl,
        anlagenregister_plants_file=anlagenregister_plants_file,
        postal_to_nuts_file=postal_to_nuts_file,
        clustering="AT35",
    )
    kwk = out[out["Name"].str.startswith(KLEINWASSERKRAFT_NAME_PREFIX, na=False)]
    assert len(kwk) == 2
    assert kwk["plz"].tolist() == ["9872", "9906"]
    assert kwk["plz"].map(type).eq(str).all()
    # existing plants keep no plz (the big plant stays, > 10 MW)
    assert out.query("Name == 'Big Dam'")["plz"].isna().all()


def test_kleinwasserkraft_plz_matches_bus_mapping(
    ppl, anlagenregister_plants_file, postal_to_nuts_file
):
    out = add_kleinwasserkraft_to_power_plants_at(
        ppl,
        anlagenregister_plants_file=anlagenregister_plants_file,
        postal_to_nuts_file=postal_to_nuts_file,
        clustering="AT35",
    )
    kwk = out[out["Name"].str.startswith(KLEINWASSERKRAFT_NAME_PREFIX, na=False)]
    assert dict(zip(kwk["plz"], kwk["bus"])) == {"9872": "AT212", "9906": "AT333"}


@pytest.fixture
def missing_plants_file(tmp_path) -> str:
    path = tmp_path / "missing_hydro_plants_AT.csv"
    pd.DataFrame(
        {
            "Name": ["Ottenstein", "Dobra Krumau"],
            "bus": ["AT124", "AT124"],
            "technology": ["Pumped Storage", "Reservoir"],
            "capacity_mw": [48.0, 16.2],
            "date_in": [1957, 1953],
            "lat": [48.6072, 48.5561],
            "lon": [15.2567, 15.3203],
            "note": ["Kamp PS", "Kamp storage"],
        }
    ).to_csv(path, index=False)
    return str(path)


def test_missing_plants_added_with_coordinates(ppl, missing_plants_file):
    from overwrite_powerplants import add_missing_hydro_plants_at

    out = add_missing_hydro_plants_at(ppl, missing_plants_file)
    added = out[out["Name"].isin(["Ottenstein", "Dobra Krumau"])]
    assert len(added) == 2
    assert added.set_index("Name")["Technology"].to_dict() == {
        "Ottenstein": "Pumped Storage",
        "Dobra Krumau": "Reservoir",
    }
    assert (added["Fueltype"] == "Hydro").all()
    assert (added["Country"] == "AT").all()
    assert added[["lat", "lon"]].notna().all().all()
    assert added.set_index("Name").at["Ottenstein", "Capacity"] == pytest.approx(48.0)


def test_missing_plants_clash_raises(ppl, missing_plants_file):
    from overwrite_powerplants import add_missing_hydro_plants_at

    clashing = ppl.assign(Name="Ottenstein")
    with pytest.raises(ValueError, match="already exist"):
        add_missing_hydro_plants_at(clashing, missing_plants_file)
