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
def postal_centroids_file(tmp_path) -> str:
    path = tmp_path / "AT.txt"
    rows = [
        ["AT", "9872", "Millstatt", "", "", "", "", "", "", "46.80", "13.58", "4"],
        ["AT", "9872", "Obermillstatt", "", "", "", "", "", "", "46.82", "13.60", "4"],
        ["AT", "9906", "Lavant", "", "", "", "", "", "", "46.79", "12.82", "4"],
    ]
    pd.DataFrame(rows).to_csv(path, sep="\t", header=False, index=False)
    return str(path)


def test_kleinwasserkraft_rows_get_postal_centroids(
    ppl, anlagenregister_plants_file, postal_to_nuts_file, postal_centroids_file
):
    out = add_kleinwasserkraft_to_power_plants_at(
        ppl,
        anlagenregister_plants_file=anlagenregister_plants_file,
        postal_to_nuts_file=postal_to_nuts_file,
        clustering="AT35",
        postal_centroids_file=postal_centroids_file,
    )
    kwk = out[out["Name"].str.startswith(KLEINWASSERKRAFT_NAME_PREFIX, na=False)]
    # two localities share 9872: the centroid is their mean
    assert kwk["lat"].tolist() == pytest.approx([46.81, 46.79])
    assert kwk["lon"].tolist() == pytest.approx([13.59, 12.82])


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


def test_missing_plants_buses_follow_at10_clustering(ppl, missing_plants_file):
    from overwrite_powerplants import add_missing_hydro_plants_at

    out = add_missing_hydro_plants_at(ppl, missing_plants_file, clustering="AT10DE5")
    added = out[out["Name"].isin(["Ottenstein", "Dobra Krumau"])]
    assert added["bus"].tolist() == ["AT12", "AT12"]


def test_curated_small_plant_survives_register_replacement(
    ppl, anlagenregister_plants_file, postal_to_nuts_file, tmp_path
):
    """The register step drops AT run-of-river plants <= 10 MW; curated plants come after."""
    from overwrite_powerplants import (
        add_kleinwasserkraft_to_power_plants_at,
        add_missing_hydro_plants_at,
    )

    path = tmp_path / "missing_small.csv"
    pd.DataFrame(
        {
            "Name": ["Goessnitz"],
            "bus": ["AT212"],
            "technology": ["Run-Of-River"],
            "capacity_mw": [8.0],
            "date_in": [1962],
            "lat": [46.93],
            "lon": [13.09],
            "note": ["not in the register"],
        }
    ).to_csv(path, index=False)

    out = add_kleinwasserkraft_to_power_plants_at(
        ppl,
        anlagenregister_plants_file=anlagenregister_plants_file,
        postal_to_nuts_file=postal_to_nuts_file,
        clustering="AT35",
    )
    out = add_missing_hydro_plants_at(out, str(path))

    assert (out["Name"] == "Goessnitz").sum() == 1


@pytest.fixture
def grenzkraftwerke_file(tmp_path) -> str:
    path = tmp_path / "grenzkraftwerke.csv"
    pd.DataFrame(
        {
            "Name": ["Jochenstein", "Jochenstein", "Scharding Neuhaus"],
            "country": ["AT", "DE", "DE"],
            "bus": ["AT311", "DE2", "DE2"],
            "capacity_mw": [132.0, 132.0, 96.0],
            "share": [0.5, 0.5, 0.5],
            "action": ["scale", "scale", "add"],
            "date_in": [1956, 1956, 1961],
            "river": ["Danube", "Danube", "Inn"],
            "note": ["treaty", "treaty", "German half missing in ppm"],
        }
    ).to_csv(path, index=False)
    return str(path)


def test_grenzkraftwerke_scaled_to_treaty_share_and_german_half_added(
    grenzkraftwerke_file,
):
    from overwrite_powerplants import apply_grenzkraftwerke_shares_at

    ppl = pd.DataFrame(
        {
            "Name": ["Jochenstein", "Jochenstein"],
            "Country": ["AT", "DE"],
            "Fueltype": ["Hydro", "Hydro"],
            "Technology": ["Run-Of-River", "Run-Of-River"],
            "Capacity": [132.0, 132.0],
            "bus": ["AT311", "DE2"],
        }
    )

    out = apply_grenzkraftwerke_shares_at(ppl, grenzkraftwerke_file)

    assert out.query("Name == 'Jochenstein'")["Capacity"].tolist() == [66.0, 66.0]
    added = out.query("Name == 'Scharding Neuhaus'").iloc[0]
    assert added["Country"] == "DE" and added["bus"] == "DE2"
    assert added["Capacity"] == pytest.approx(48.0)


def test_grenzkraftwerke_add_raises_when_plant_exists(grenzkraftwerke_file):
    from overwrite_powerplants import apply_grenzkraftwerke_shares_at

    ppl = pd.DataFrame(
        {
            "Name": ["Jochenstein", "Jochenstein", "Scharding Neuhaus"],
            "Country": ["AT", "DE", "DE"],
            "Fueltype": ["Hydro"] * 3,
            "Technology": ["Run-Of-River"] * 3,
            "Capacity": [132.0, 132.0, 96.0],
            "bus": ["AT311", "DE2", "DE2"],
        }
    )
    with pytest.raises(ValueError, match="already exists"):
        apply_grenzkraftwerke_shares_at(ppl, grenzkraftwerke_file)


def test_kleinwasserkraft_scaled_to_bestandsstatistik_anchor(monkeypatch):
    import overwrite_powerplants as op

    ppl = pd.DataFrame(
        {
            "Name": [f"{op.KLEINWASSERKRAFT_NAME_PREFIX}K-1", "Big Dam"],
            "Country": ["AT", "AT"],
            "Fueltype": ["Hydro", "Hydro"],
            "Technology": ["Run-Of-River", "Run-Of-River"],
            "Capacity": [1000.0, 100.0],
            "bus": ["AT212", "AT212"],
        }
    )
    monkeypatch.setattr(op, "_read_small_hydro_anchor_mw", lambda path: 900.0)

    out = op.scale_kleinwasserkraft_to_bestandsstatistik_at(ppl, "unused.xlsx")

    assert out["Capacity"].tolist() == pytest.approx([900.0, 100.0])

    monkeypatch.setattr(op, "_read_small_hydro_anchor_mw", lambda path: 500.0)
    with pytest.raises(ValueError, match="deviates more than"):
        op.scale_kleinwasserkraft_to_bestandsstatistik_at(ppl, "unused.xlsx")


@pytest.fixture
def residual_inputs(tmp_path) -> dict:
    """One KLIEN catchment (100 MW, 400 GWh/a) inside one Austrian region."""
    import geopandas as gpd
    from shapely.geometry import box

    catchments = tmp_path / "catchments_hydro.geojson"
    gpd.GeoDataFrame(
        {"id": [51200], "C_current": [100.0], "E_current": [400.0]},
        geometry=[box(14.0, 47.0, 15.0, 48.0)],
        crs="EPSG:4326",
    ).to_file(catchments, driver="GeoJSON")
    regions = tmp_path / "regions.geojson"
    gpd.GeoDataFrame(
        {"name": ["AT121"]}, geometry=[box(13.5, 46.5, 15.5, 48.5)], crs="EPSG:4326"
    ).to_file(regions, driver="GeoJSON")
    corrections = tmp_path / "corrections.csv"
    corrections.write_text("id,C_current_new,E_current_new,note\n")
    overrides = tmp_path / "overrides.csv"
    overrides.write_text("name,section,weight,note\n")
    grenz = tmp_path / "grenzkraftwerke.csv"
    grenz.write_text("Name,country,bus,capacity_mw,share,action,date_in,river,note\n")
    return dict(
        klien_catchments_file=str(catchments),
        catchment_corrections_file=str(corrections),
        regions_file=str(regions),
        diversion_overrides_file=str(overrides),
        grenzkraftwerke_file=str(grenz),
    )


def _plant(capacity: float) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Name": ["Real plant"],
            "Country": ["AT"],
            "Fueltype": ["Hydro"],
            "Technology": ["Run-Of-River"],
            "Set": ["PP"],
            "Capacity": [capacity],
            "bus": ["AT121"],
            "lat": [47.5],
            "lon": [14.5],
        }
    )


def test_klien_residual_plant_fills_the_catchment_capacity(residual_inputs):
    from overwrite_powerplants import (
        KLIEN_RESIDUAL_NAME_PREFIX,
        add_klien_residual_plants_at,
    )

    # 50 MW present out of 100 MW: half the energy at 4,000 h is unallocated
    out, residual = add_klien_residual_plants_at(_plant(50.0), **residual_inputs)

    assert residual["section"].tolist() == ["51200"]
    assert residual["capacity_mw"].iloc[0] == pytest.approx(50.0)
    assert residual["energy_gwh"].iloc[0] == pytest.approx(200.0)
    added = out[out["Name"] == f"{KLIEN_RESIDUAL_NAME_PREFIX}51200"].iloc[0]
    assert added["Technology"] == "Run-Of-River" and added["bus"] == "AT121"
    assert added["Capacity"] == pytest.approx(50.0)
    assert 47.0 < added["lat"] < 48.0 and 14.0 < added["lon"] < 15.0


def test_klien_residual_plant_absent_when_catchment_is_covered(residual_inputs):
    from overwrite_powerplants import add_klien_residual_plants_at

    out, residual = add_klien_residual_plants_at(_plant(100.0), **residual_inputs)

    assert residual.empty
    assert len(out) == 1


def test_reclassification_relocates_plant_when_new_location_given(tmp_path):
    from overwrite_powerplants import reclassify_hydro_technologies_at

    ppl = pd.DataFrame(
        {
            "Name": ["St Pantaleon"],
            "Country": ["AT"],
            "Fueltype": ["Hydro"],
            "Technology": ["Run-Of-River"],
            "Capacity": [52.0],
            "bus": ["AT311"],
            "lat": [48.0076],
            "lon": [12.8942],
        }
    )
    path = tmp_path / "reclassification.csv"
    pd.DataFrame(
        {
            "Name": ["St Pantaleon"],
            "bus": ["AT311"],
            "capacity_mw": [52.0],
            "technology_old": ["Run-Of-River"],
            "technology_new": ["Run-Of-River"],
            "group": ["Enns"],
            "note": ["geocoded to the wrong village"],
            "capacity_new": [None],
            "bus_new": ["AT121"],
            "lat_new": [48.205],
            "lon_new": [14.505],
        }
    ).to_csv(path, index=False)

    out = reclassify_hydro_technologies_at(ppl, str(path)).iloc[0]

    assert out["bus"] == "AT121"
    assert out["lat"] == pytest.approx(48.205)
    assert out["lon"] == pytest.approx(14.505)
    assert out["Capacity"] == pytest.approx(52.0)
    assert out["Technology"] == "Run-Of-River"


def test_reclassification_relocation_follows_at10_clustering(tmp_path):
    from overwrite_powerplants import reclassify_hydro_technologies_at

    ppl = pd.DataFrame(
        {
            "Name": ["St Pantaleon"],
            "Country": ["AT"],
            "Fueltype": ["Hydro"],
            "Technology": ["Run-Of-River"],
            "Capacity": [52.0],
            "bus": ["AT31"],
            "lat": [48.0076],
            "lon": [12.8942],
        }
    )
    path = tmp_path / "reclassification.csv"
    pd.DataFrame(
        {
            "Name": ["St Pantaleon"],
            "bus": ["AT311"],
            "capacity_mw": [52.0],
            "technology_old": ["Run-Of-River"],
            "technology_new": ["Run-Of-River"],
            "group": ["Enns"],
            "note": ["geocoded to the wrong village"],
            "capacity_new": [None],
            "bus_new": ["AT121"],
            "lat_new": [48.2249],
            "lon_new": [14.5308],
        }
    ).to_csv(path, index=False)

    out = reclassify_hydro_technologies_at(ppl, str(path), clustering="AT10DE5")

    assert out["bus"].tolist() == ["AT12"]


def test_reclassification_matches_plant_without_technology(tmp_path):
    from overwrite_powerplants import reclassify_hydro_technologies_at

    ppl = pd.DataFrame(
        {
            "Name": ["Gaming", "Gaming"],
            "Country": ["AT", "AT"],
            "Fueltype": ["Hydro", "Hydro"],
            "Technology": [None, "Run-Of-River"],
            "Capacity": [14.0, 14.0],
            "bus": ["AT130", "AT130"],
            "lat": [48.18, 48.18],
            "lon": [16.48, 16.48],
        }
    )
    path = tmp_path / "reclassification.csv"
    pd.DataFrame(
        {
            "Name": ["Gaming"],
            "bus": ["AT130"],
            "capacity_mw": [14.0],
            "technology_old": [None],
            "technology_new": ["Reservoir"],
            "group": ["Erlauf"],
            "note": ["no technology in ppm"],
            "capacity_new": [None],
            "bus_new": ["AT121"],
            "lat_new": [47.93],
            "lon_new": [15.09],
        }
    ).to_csv(path, index=False)

    out = reclassify_hydro_technologies_at(ppl, str(path))

    # only the entry without a technology is touched
    assert out["Technology"].tolist() == ["Reservoir", "Run-Of-River"]
    assert out["bus"].tolist() == ["AT121", "AT130"]


def test_duplicate_hydro_plants_dropped_by_name_and_capacity(tmp_path):
    from overwrite_powerplants import drop_duplicate_hydro_plants_at

    ppl = pd.DataFrame(
        {
            "Name": [
                "Kaprun Limberg",
                "Kaprun Limberg",
                "Kaprun Main Stage",
                "Kaprun Haupstufe",
            ],
            "Country": ["AT", "AT", "AT", "AT"],
            "Fueltype": ["Hydro", "Hydro", "Hydro", "Hydro"],
            "Technology": ["Pumped Storage", "Pumped Storage", None, "Reservoir"],
            "Capacity": [740.0, 480.0, 240.0, 260.0],
            "bus": ["AT322", "AT322", "AT322", "AT322"],
        }
    )
    path = tmp_path / "duplicates.csv"
    pd.DataFrame(
        {
            "Name": ["Kaprun Main Stage"],
            "bus": ["AT322"],
            "capacity_mw": [240.0],
            "keeps": ["Kaprun Haupstufe"],
            "note": ["twin"],
        }
    ).to_csv(path, index=False)

    out = drop_duplicate_hydro_plants_at(ppl, str(path))

    assert out["Name"].tolist() == [
        "Kaprun Limberg",
        "Kaprun Limberg",
        "Kaprun Haupstufe",
    ]


def test_duplicate_drop_keeps_twin_in_another_country(tmp_path):
    from overwrite_powerplants import drop_duplicate_hydro_plants_at

    ppl = pd.DataFrame(
        {
            "Name": ["Feldkirchen", "Feldkirchen"],
            "Country": ["AT", "DE"],
            "Fueltype": ["Hydro", "Hydro"],
            "Technology": [None, "Run-Of-River"],
            "Capacity": [38.0, 38.2],
            "bus": ["AT212", "DE2"],
        }
    )
    path = tmp_path / "duplicates.csv"
    frame = pd.DataFrame(
        {
            "Name": ["Feldkirchen"],
            "bus": ["AT212"],
            "capacity_mw": [38.0],
            "keeps": ["Feldkirchen"],
            "keeps_country": ["DE"],
            "note": ["Bavarian plant geocoded into Austria"],
        }
    )
    frame.to_csv(path, index=False)

    out = drop_duplicate_hydro_plants_at(ppl, str(path))

    assert out["Country"].tolist() == ["DE"]

    # the kept twin must exist, otherwise the plant would be lost
    frame["keeps_country"] = "AT"
    frame.to_csv(path, index=False)
    with pytest.raises(ValueError, match="kept twin"):
        drop_duplicate_hydro_plants_at(ppl, str(path))


def test_same_named_plants_are_told_apart_by_capacity():
    from overwrite_powerplants import _match_single_hydro_plant

    ppl = pd.DataFrame(
        {
            "Name": ["Kaprun Limberg", "Kaprun Limberg"],
            "Country": ["AT", "AT"],
            "Fueltype": ["Hydro", "Hydro"],
            "Technology": ["Pumped Storage", "Pumped Storage"],
            "Capacity": [740.0, 480.0],
            "bus": ["AT322", "AT322"],
        },
        index=[7, 8],
    )
    assert (
        _match_single_hydro_plant(ppl, "Kaprun Limberg", "AT", 480.0, "AT322", "f") == 8
    )
    with pytest.raises(ValueError, match="found 0"):
        _match_single_hydro_plant(ppl, "Kaprun Limberg", "AT", 600.0, "AT322", "f")
