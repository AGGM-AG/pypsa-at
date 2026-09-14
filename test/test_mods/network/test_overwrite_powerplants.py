# SPDX-FileCopyrightText: 2025-2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""
Tests for scripts/pypsa-at/overwrite_powerplants.py function overwrite_biogas_to_power_plants_AT
"""

import pathlib
import textwrap

import pandas as pd
import pytest
from overwrite_powerplants import overwrite_biogas_to_power_plants_AT

from mods.clustering.utils import map_at_nuts3_to_nuts2

# Column header of the capacity in Anlagenregister csv
CAPACITY_COL = "Engpassleistung (kW <sub>el</sub>)"
_DATA = pathlib.Path.cwd() / "data" / "pypsa-at"
ANLAGENREGISTER = _DATA / "Anlagenregister_electricity_from_renewable_gas_AT.csv"
POSTAL_TO_NUTS = _DATA / "AT-Postal-to-NUTS.csv"


@pytest.fixture
def postal_to_nuts_file(tmp_path):
    """Minimal PLZ->NUTS3 file, mirrors data/pypsa-at/AT-Postal-to-NUTS.csv"""
    path = tmp_path / "postal_to_nuts.csv"
    path.write_text(
        textwrap.dedent(
            """\
            NUTS3,CODE
            AT226,8761
            AT113,2022
            AT321,8010
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
def result(request, ppl, anlagenregister_file, postal_to_nuts_file):
    clustering = getattr(request, "param", "AT35DE5")
    return overwrite_biogas_to_power_plants_AT(
        ppl,
        anlagenregister_file,
        postal_to_nuts_file,
        threshold_capacity=2,
        clustering=clustering,
    )


@pytest.fixture
def source(anlagenregister_file):
    """Anlagenregister rows with a usable Plz (the ones that must be added)."""
    return pd.read_csv(anlagenregister_file).dropna(subset=["Plz"])


@pytest.fixture
def nuts3_codes(postal_to_nuts_file):
    """NUTS3 codes in the postal->NUTS mapping."""
    postal = pd.read_csv(
        postal_to_nuts_file, sep=";", dtype=str, names=["nuts3", "plz"], header=0
    )
    return set(postal["nuts3"].str.strip("'"))


def _biogas(df):
    """Rows are added by the function are called "Biogas AT"."""
    return df[df["Name"].str.startswith("Biogas AT")]


def test_all_valid_rows_added(result, ppl):
    """Every Anlagenregister row with a non-null Plz becomes one biogas plant for ppl file"""
    added = _biogas(result)
    assert len(added) == 3  # ID 999 dropped (empty Plz)
    assert len(result) == len(ppl) + 3


def test_capacity_kw_to_mw(result):
    cap = _biogas(result).set_index("Name")["Capacity"]
    assert cap["Biogas AT 6"] == pytest.approx(0.5)
    assert cap["Biogas AT 4"] == pytest.approx(0.25)
    assert cap["Biogas AT 204"] == pytest.approx(140.0)


def test_ids_map_to_names(result):
    assert set(_biogas(result)["Name"]) == {
        "Biogas AT 6",
        "Biogas AT 4",
        "Biogas AT 204",
    }


def test_build_year(result):
    added = _biogas(result)
    assert (added["DateIn"] <= 2004).all()


def test_mapped_all_plz_to_nuts3(result):
    added = _biogas(result)
    assert not added["bus"].isna().any()  # every PLZ is in one NUTS3 region
    by_name = added.set_index("Name")["bus"]
    assert by_name["Biogas AT 6"] == "AT226"
    assert by_name["Biogas AT 4"] == "AT113"
    assert by_name["Biogas AT 204"] == "AT321"


@pytest.mark.parametrize("result", ["AT10DE5"], indirect=True)
def test_maps_nuts3_to_nuts2_for_at10(result):
    """AT10 clustering collapses the NUTS3 plant buses to NUTS2 node names."""
    by_name = _biogas(result).set_index("Name")["bus"]
    assert by_name["Biogas AT 6"] == "AT22"  # AT226 -> AT22
    assert by_name["Biogas AT 4"] == "AT11"  # AT113 -> AT11
    assert by_name["Biogas AT 204"] == "AT32"  # AT321 -> AT32


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
            ppl,
            anlagenregister_file,
            postal_to_nuts_file,
            threshold_capacity=2,
            clustering="AT35DE5",
        )


def test_guard_raises_on_high_threshold(ppl, anlagenregister_file, postal_to_nuts_file):
    """threshold_capacity > 5 MW would filter out small biogas plants -> ValueError."""
    with pytest.raises(ValueError, match="threshold_capacity"):
        overwrite_biogas_to_power_plants_AT(
            ppl,
            anlagenregister_file,
            postal_to_nuts_file,
            threshold_capacity=6,
            clustering="AT35DE5",
        )


def test_every_source_plant_is_added(result, source):
    """Check if there are the same amount of powerplants as there are valid ones in Anlagenregister"""
    assert len(_biogas(result)) == len(source)


def test_capacity_sum_matches_source(result, source):
    """Total added capacity == converted kW Engpassleistung"""
    assert _biogas(result)["Capacity"].sum() == pytest.approx(
        source[CAPACITY_COL].sum() / 1000
    )


# --- AT integration: check that biogas plants become biogas Links ---


def _expected_at_biogas_per_node(threshold, clustering):
    """
    Sum of biogas capacity per node region.
    2 MW threshold mirrors add_existing_baseyear.py split into
    solid biomass and biogas carriers. Buses are relabelled to the
    clustering's node resolution (AT10 collapses NUTS3 to NUTS2).
    """
    postal = pd.read_csv(
        POSTAL_TO_NUTS, dtype=str, names=["nuts3", "plz"], header=0
    ).set_index("plz")["nuts3"]
    reg = pd.read_csv(ANLAGENREGISTER).dropna(subset=["Plz"])
    reg["bus"] = reg["Plz"].astype("Int64").astype(str).str.zfill(4).map(postal)
    if clustering.startswith("AT10"):
        reg["bus"] = reg["bus"].map(map_at_nuts3_to_nuts2)
    reg["MW"] = reg[CAPACITY_COL] / 1000
    per_node = reg[reg["MW"] < 2].groupby("bus")["MW"].sum()
    return per_node[per_node > threshold]


@pytest.mark.AT
def test_at_biogas_capacity_matches_source_per_node(nc):
    """
    Compare expected biogas capacities in each node with
    biogas capacity of links in the base year network
    """
    # Existing biogas links are not extendable, so the solved base year
    # network carries the capacities add_existing_baseyear assigned.
    n = nc[min(nc.index)]

    threshold = n.meta["existing_capacities"]["threshold_capacity"]
    clustering = n.meta["mods"]["modify_nuts3_shapes"]
    expected = _expected_at_biogas_per_node(threshold, clustering)

    at = n.links.query("carrier == 'biogas'")
    at = at[at["bus1"].isin(expected.index)]
    recovered = (at["p_nom"] * at["efficiency"]).groupby(at["bus1"]).sum()

    assert set(recovered.index) == set(expected.index)
    for node, mw in expected.items():
        assert recovered[node] == pytest.approx(mw, rel=1e-6)
