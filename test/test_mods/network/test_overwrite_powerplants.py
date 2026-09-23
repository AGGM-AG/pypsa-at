# SPDX-FileCopyrightText: 2025-2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""
Tests for scripts/pypsa-at/overwrite_powerplants.py function build_biogas_plants_AT
and the resulting ``biogas CHP`` Links in solved networks.
"""

import pathlib
import textwrap

import pandas as pd
import pytest
from overwrite_powerplants import LARGE_PLANT_THRESHOLD_MW, build_biogas_plants_AT

# Column header of the capacity in the Anlagenregister plant-level csv
CAPACITY_COL = "engpassleistung_kw"
POSTAL_TO_NUTS = pathlib.Path.cwd() / "data" / "pypsa-at" / "AT-Postal-to-NUTS.csv"


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
    Plant-level Anlagenregister sample in the format of
    ``anlagenregister_plants.csv``: three small renewable-gas power plants to
    map, one with a free-text postal code, plus rows that must be dropped
    (empty Plz, photovoltaics, a gas injection plant, a plant above
    ``LARGE_PLANT_THRESHOLD_MW`` like the real Gratkorn paper mill).
    """
    path = tmp_path / "anlagenregister_plants.csv"
    df = pd.DataFrame(
        {
            "typ": ["Strom", "Strom", "Strom", "Strom", "Strom", "Strom", "Gas"],
            "id": [6, 4, 204, 999, 7, 140, 8],
            "plz": ["8761", "2022 Wullersdorf", "8010", None, "8761", "8010", "8761"],
            "ort": [
                "Judenburg",
                "Wullersdorf",
                "Graz",
                "Nowhere",
                "Judenburg",
                "Graz",
                "X",
            ],
            "techcode": [
                "Biogas",
                "Biogas",
                "Klärgas ",
                "Biogas",
                "Photovoltaik",
                "Biogas",
                "",
            ],
            "energietraeger": [None, None, None, None, None, None, "Biomethan"],
            CAPACITY_COL: [500, 250, 300, 70, 20, 140000, 1000],
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
    return build_biogas_plants_AT(
        ppl,
        anlagenregister_file,
        postal_to_nuts_file,
        threshold_capacity=2,
        clustering=clustering,
    )


@pytest.fixture
def source(anlagenregister_file):
    """
    Renewable-gas power plants with a usable Plz and a capacity at or below
    ``LARGE_PLANT_THRESHOLD_MW`` (the ones that must be added).
    """
    df = pd.read_csv(anlagenregister_file).dropna(subset=["plz"])
    return df[
        (df["typ"] == "Strom")
        & (df["techcode"].str.strip() != "Photovoltaik")
        & (df[CAPACITY_COL] / 1000 <= LARGE_PLANT_THRESHOLD_MW)
    ]


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


def test_all_valid_rows_added(result):
    """Every small renewable-gas power plant with a Plz becomes one biogas plant"""
    # id 999 dropped (empty Plz), PV and Gas dropped, id 140 dropped (> LARGE_PLANT_THRESHOLD_MW)
    assert len(_biogas(result)) == 3
    assert len(result) == 3


def test_capacity_kw_to_mw(result):
    cap = _biogas(result).set_index("Name")["Capacity"]
    assert cap["Biogas AT 6"] == pytest.approx(0.5)
    assert cap["Biogas AT 4"] == pytest.approx(0.25)
    assert cap["Biogas AT 204"] == pytest.approx(0.3)


def test_large_plants_above_threshold_are_dropped(result):
    """
    Plants above LARGE_PLANT_THRESHOLD_MW are dropped, on the assumption that
    powerplantmatching already models them under their true fuel type.
    """
    assert "Biogas AT 140" not in set(result["Name"])


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


def test_powerplants_are_not_returned(result, ppl):
    """The plants are a separate table; the powerplants table stays untouched."""
    assert not set(ppl["Name"]) & set(result["Name"])
    assert (result["Fueltype"] == "Biogas").all()
    assert (result["Country"] == "AT").all()


def test_technology_comes_from_the_register(result):
    """Techcode is used as Technology, stripped of whitespace."""
    by_name = result.set_index("Name")["Technology"]
    assert by_name["Biogas AT 204"] == "Klärgas"


def test_free_text_postal_code_is_parsed(result):
    by_name = result.set_index("Name")["bus"]
    assert by_name["Biogas AT 4"] == "AT113"  # "2022 Wullersdorf"


def test_no_renewable_gas_plants_raises(
    ppl, anlagenregister_file, postal_to_nuts_file, tmp_path
):
    """A register without renewable-gas power plants signals a data change."""
    df = pd.read_csv(anlagenregister_file)
    path = tmp_path / "pv_only.csv"
    df[df["techcode"] == "Photovoltaik"].to_csv(path, index=False)
    with pytest.raises(ValueError, match="No electricity plants"):
        build_biogas_plants_AT(
            ppl,
            str(path),
            postal_to_nuts_file,
            threshold_capacity=2,
            clustering="AT35DE5",
        )


def test_guard_raises_on_small_at_bioenergy(anlagenregister_file, postal_to_nuts_file):
    """Pre-existing small AT bioenergy rows signal an upstream change -> ValueError."""
    ppl = pd.DataFrame(
        {
            "Name": ["Sneaky tiny biogas plant"],
            "Country": ["AT"],
            "Fueltype": ["Bioenergy"],
            "Capacity": [1.5],  # < LARGE_PLANT_THRESHOLD_MW (5 MW)
        }
    )
    with pytest.raises(ValueError, match="powerplantmatching"):
        build_biogas_plants_AT(
            ppl,
            anlagenregister_file,
            postal_to_nuts_file,
            threshold_capacity=2,
            clustering="AT35DE5",
        )


def test_guard_raises_on_high_threshold(ppl, anlagenregister_file, postal_to_nuts_file):
    """threshold_capacity > 5 MW would filter out small biogas plants -> ValueError."""
    with pytest.raises(ValueError, match="threshold_capacity"):
        build_biogas_plants_AT(
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


# --- AT integration: check that biogas plants become biogas CHP Links ---


def _expected_at_biogas_per_node(n, threshold, project_root):
    """
    Sum of biogas capacity per node region from the plant table the run
    prepared (``biogas_plants_at_{clusters}.csv``, already at node
    resolution). The node total must exceed the existing_capacities
    threshold like in add_existing_baseyear.py.
    """
    prefix = n.meta["run"]["prefix"]
    run_name = n.meta["run"]["name"][0]
    clusters = n.meta["wildcards"]["clusters"]
    csv_path = (
        project_root
        / "resources"
        / prefix
        / run_name
        / f"biogas_plants_at_{clusters}.csv"
    )
    plants = pd.read_csv(csv_path)
    per_node = plants.groupby("bus")["Capacity"].sum()
    return per_node[per_node > threshold]


@pytest.mark.AT
def test_at_biogas_capacity_matches_source_per_node(nc, project_root):
    """
    Compare expected biogas capacities in each node with
    biogas CHP capacity of links in the base year network
    """
    # Existing biogas CHP links are not extendable, so the solved base year
    # network carries the capacities mods.network.biogas assigned.
    n = nc[min(nc.index)]

    threshold = n.meta["existing_capacities"]["threshold_capacity"]
    expected = _expected_at_biogas_per_node(n, threshold, project_root)

    at = n.links.query("carrier == 'biogas CHP'")
    at = at[at["bus1"].isin(expected.index)]
    recovered = (at["p_nom"] * at["efficiency"]).groupby(at["bus1"]).sum()

    assert set(recovered.index) == set(expected.index)
    for node, mw in expected.items():
        assert recovered[node] == pytest.approx(mw, rel=1e-6)
    assert (at["bus0"] == at["bus1"] + " biogas").all()
    assert not at["p_nom_extendable"].any()


@pytest.mark.AT
def test_at_biogas_chp_is_retired_before_2030(nc):
    """The 2003 vintage with 25 years lifetime is gone from 2030 onwards."""
    for year, n in nc.networks.items():
        if int(year) < 2030:
            continue
        at = n.links.query("carrier == 'biogas CHP' and index.str.startswith('AT')")
        assert at[at["build_year"] < 2025].empty, f"{year}: {at.index.tolist()}"
