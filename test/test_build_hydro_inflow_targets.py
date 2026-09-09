# SPDX-FileCopyrightText: 2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""Tests for the plant-location based KLIEN section → region allocation."""

import geopandas as gpd
import pandas as pd
import pytest
from build_hydro_inflow_targets import (
    aggregate_by_region,
    allocate_section_energy,
    assign_plants_to_sections,
    build_inflow_targets,
)
from shapely.geometry import box

CRS = "EPSG:3857"


def _to_lonlat(x: float, y: float) -> tuple[float, float]:
    """Project a planar EPSG:3857 point back to (lon, lat)."""
    pt = gpd.GeoSeries(gpd.points_from_xy([x], [y]), crs=CRS).to_crs("EPSG:4326")
    return float(pt.x.iloc[0]), float(pt.y.iloc[0])


@pytest.fixture
def regions() -> gpd.GeoDataFrame:
    # R1: x 0..10, R2: x 10..20 (kilometre-scale boxes, y 0..10)
    return gpd.GeoDataFrame(
        {"geometry": [box(0, 0, 10_000, 10_000), box(10_000, 0, 20_000, 10_000)]},
        index=pd.Index(["R1", "R2"], name="bus"),
        crs=CRS,
    )


@pytest.fixture
def sections() -> gpd.GeoDataFrame:
    # S1 spans the R1/R2 border ("anteilig" case), S2 lies fully in R2,
    # S3 carries energy but will hold no plant.
    return gpd.GeoDataFrame(
        {
            "E_current": [100.0, 50.0, 7.0],
            "geometry": [
                box(0, 0, 14_000, 5_000),
                box(14_000, 0, 20_000, 5_000),
                box(0, 5_000, 20_000, 10_000),
            ],
        },
        index=pd.Index(["S1", "S2", "S3"], name="section"),
        crs=CRS,
    )


@pytest.fixture
def plants() -> pd.DataFrame:
    lon_a, lat_a = _to_lonlat(5_000, 2_500)  # in S1 ∩ R1
    lon_b, lat_b = _to_lonlat(12_000, 2_500)  # in S1 ∩ R2
    lon_d, lat_d = _to_lonlat(15_000, 2_500)  # in S2 ∩ R2 (PHS)
    return pd.DataFrame(
        {
            "bus": ["R1", "R2", "R2", "R2"],
            "carrier": ["ror", "ror", "ror", "PHS"],
            "p_nom": [10.0, 30.0, 10.0, 500.0],
            "lat": [lat_a, lat_b, None, lat_d],
            "lon": [lon_a, lon_b, None, lon_d],
        },
        index=pd.Index(["A", "B", "C", "D"], name="plant"),
    )


def test_coordinate_plants_split_border_section_by_location(plants, sections, regions):
    membership = assign_plants_to_sections(plants, sections, regions)
    m = membership.set_index(["plant", "section"])["weight"]
    assert m.loc[("A", "S1")] == 1.0
    assert m.loc[("B", "S1")] == 1.0
    assert m.loc[("D", "S2")] == 1.0


def test_coordless_plant_weighted_by_region_overlap(plants, sections, regions):
    membership = assign_plants_to_sections(plants, sections, regions)
    c = membership.query("plant == 'C'").set_index("section")["weight"]
    # R2 overlaps: S1 4x5 km², S2 6x5 km², S3 10x5 km² → weights 0.2/0.3/0.5
    assert c.loc["S1"] == pytest.approx(0.2)
    assert c.loc["S2"] == pytest.approx(0.3)
    assert c.loc["S3"] == pytest.approx(0.5)
    assert c.sum() == pytest.approx(1.0)


def test_section_energy_follows_plant_capacity(plants, sections, regions):
    membership = assign_plants_to_sections(plants, sections, regions)
    plant_energy, _ = allocate_section_energy(sections, membership, plants)
    # S1 weights: A 10, B 30, C 0.2*10=2 → shares 10/42, 30/42, 2/42 of 100
    assert plant_energy["A"] == pytest.approx(100 * 10 / 42)
    assert plant_energy["B"] == pytest.approx(100 * 30 / 42)


def test_phs_takes_no_energy(plants, sections, regions):
    membership = assign_plants_to_sections(plants, sections, regions)
    plant_energy, _ = allocate_section_energy(sections, membership, plants)
    assert "D" not in plant_energy.index
    # S2 goes fully to C (weight 0.3, only eligible member)
    s2_to_c = 50.0
    assert plant_energy["C"] == pytest.approx(100 * 2 / 42 + s2_to_c + 7.0)


def test_energy_conservation_with_unallocated(plants, sections, regions):
    targets, diag = build_inflow_targets(plants, sections, regions)
    total = targets["energy"].sum() + diag["unallocated"].sum()
    assert total == pytest.approx(sections["E_current"].sum())


def test_unallocated_section_reported(plants, sections, regions):
    # remove C: S3 has no member plant left, and S2's only member is the
    # ineligible PHS plant D — both must show up as unallocated
    plants_no_c = plants.drop("C")
    _, diag = build_inflow_targets(plants_no_c, sections, regions)
    assert sorted(diag["unallocated"].index) == ["S2", "S3"]
    assert diag["unallocated"].loc["S2"] == pytest.approx(50.0)
    assert diag["unallocated"].loc["S3"] == pytest.approx(7.0)


def test_region_aggregation_by_plant_bus_not_area(plants, sections, regions):
    # The border section S1 splits by plant location/capacity (10 vs 30+2),
    # not by area (10/14 vs 4/14).
    targets, _ = build_inflow_targets(plants, sections, regions)
    per_bus = targets.groupby("bus")["energy"].sum()
    assert per_bus["R1"] == pytest.approx(100 * 10 / 42)
    assert per_bus["R2"] == pytest.approx(100 * 32 / 42 + 50.0 + 7.0)


def test_crs_mismatch_raises(plants, sections, regions):
    with pytest.raises(ValueError, match="CRS"):
        assign_plants_to_sections(plants, sections, regions.to_crs("EPSG:4326"))


def test_aggregate_by_region_shape(plants, sections, regions):
    membership = assign_plants_to_sections(plants, sections, regions)
    plant_energy, _ = allocate_section_energy(sections, membership, plants)
    targets = aggregate_by_region(plant_energy, plants)
    assert set(targets.columns) == {"bus", "carrier", "energy"}
    assert targets["energy"].min() >= 0


@pytest.fixture
def plz_polygons() -> gpd.GeoDataFrame:
    # 1111: fully inside S2 → unique assignment
    # 2222: far away, overlaps no section → must cascade to bus
    # 3333: n:m — two polygons, together spanning S1 (4 km²) and S2 (8 km²)
    return gpd.GeoDataFrame(
        {
            "geometry": [
                box(15_000, 1_000, 17_000, 3_000),
                box(50_000, 50_000, 51_000, 51_000),
                box(12_000, 0, 14_000, 2_000),
                box(14_000, 0, 18_000, 2_000),
            ]
        },
        index=pd.Index(["1111", "2222", "3333", "3333"], name="plz"),
        crs=CRS,
    )


def _coordless(bus: str, plz: str | None) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "bus": [bus],
            "carrier": ["ror"],
            "p_nom": [5.0],
            "lat": [None],
            "lon": [None],
            "plz": [plz],
        },
        index=pd.Index(["X"], name="plant"),
    )


def test_plz_lookup_unique_when_fully_inside(sections, regions, plz_polygons):
    membership = assign_plants_to_sections(
        _coordless("R2", "1111"), sections, regions, [("plz", plz_polygons)]
    )
    m = membership.set_index(["plant", "section"])["weight"]
    assert m.to_dict() == {("X", "S2"): 1.0}


def test_plz_lookup_missing_key_cascades_to_bus(sections, regions, plz_polygons):
    membership = assign_plants_to_sections(
        _coordless("R2", None), sections, regions, [("plz", plz_polygons)]
    )
    w = membership.set_index("section")["weight"]
    # same as the plain bus fallback: R2 overlaps S1/S2/S3 as 0.2/0.3/0.5
    assert w.loc["S1"] == pytest.approx(0.2)
    assert w.loc["S2"] == pytest.approx(0.3)
    assert w.loc["S3"] == pytest.approx(0.5)


def test_plz_polygon_outside_sections_cascades_to_bus(sections, regions, plz_polygons):
    membership = assign_plants_to_sections(
        _coordless("R2", "2222"), sections, regions, [("plz", plz_polygons)]
    )
    w = membership.set_index("section")["weight"]
    assert w.loc["S3"] == pytest.approx(0.5)
    assert w.sum() == pytest.approx(1.0)


def test_plz_duplicate_key_polygons_use_union(sections, regions, plz_polygons):
    membership = assign_plants_to_sections(
        _coordless("R2", "3333"), sections, regions, [("plz", plz_polygons)]
    )
    w = membership.set_index("section")["weight"]
    # 3333 covers 4 km² of S1 and 8 km² of S2 → weights 1/3 and 2/3
    assert w.loc["S1"] == pytest.approx(1 / 3)
    assert w.loc["S2"] == pytest.approx(2 / 3)


def test_plz_lookup_crs_mismatch_raises(sections, regions, plz_polygons):
    with pytest.raises(ValueError, match="CRS"):
        assign_plants_to_sections(
            _coordless("R2", "1111"),
            sections,
            regions,
            [("plz", plz_polygons.to_crs("EPSG:4326"))],
        )


def test_coordinates_beat_plz_lookup(plants, sections, regions, plz_polygons):
    # plant B has coordinates in S1; a conflicting plz must be ignored
    b = plants.loc[["B"]].assign(plz="1111")
    membership = assign_plants_to_sections(
        b, sections, regions, [("plz", plz_polygons)]
    )
    m = membership.set_index(["plant", "section"])["weight"]
    assert m.to_dict() == {("B", "S1"): 1.0}


def _named(name, bus, lat, lon):
    return pd.DataFrame(
        {
            "bus": [bus],
            "carrier": ["hydro"],
            "p_nom": [100.0],
            "lat": [lat],
            "lon": [lon],
            "name": [name],
        },
        index=pd.Index([name], name="plant"),
    )


def test_override_pins_plant_to_section(sections, regions):
    # a diversion plant with no coords, pinned to S3 by name
    plants = _named("Prutz", "R2", None, None)
    ov = pd.DataFrame({"name": ["Prutz"], "section": ["S3"]})
    membership = assign_plants_to_sections(plants, sections, regions, overrides=ov)
    m = membership.set_index(["plant", "section"])["weight"]
    assert m.to_dict() == {("Prutz", "S3"): 1.0}


def test_override_beats_point_in_polygon(plants, sections, regions):
    # plant B has coords in S1; override pins it to S2 instead
    b = plants.loc[["B"]].assign(name="B")
    ov = pd.DataFrame({"name": ["B"], "section": ["S2"]})
    membership = assign_plants_to_sections(b, sections, regions, overrides=ov)
    m = membership.set_index(["plant", "section"])["weight"]
    assert m.to_dict() == {("B", "S2"): 1.0}


def test_override_multi_section_weights_normalized(sections, regions):
    plants = _named("X", "R2", None, None)
    ov = pd.DataFrame(
        {"name": ["X", "X"], "section": ["S1", "S2"], "weight": [3.0, 1.0]}
    )
    membership = assign_plants_to_sections(plants, sections, regions, overrides=ov)
    w = membership.set_index("section")["weight"]
    assert w.loc["S1"] == pytest.approx(0.75)
    assert w.loc["S2"] == pytest.approx(0.25)


def test_override_unknown_section_raises(sections, regions):
    plants = _named("X", "R2", None, None)
    ov = pd.DataFrame({"name": ["X"], "section": ["S9"]})
    with pytest.raises(ValueError, match="unknown section"):
        assign_plants_to_sections(plants, sections, regions, overrides=ov)


def test_override_missing_name_raises(sections, regions):
    plants = _named("X", "R2", None, None)
    ov = pd.DataFrame({"name": ["NotThere"], "section": ["S1"]})
    with pytest.raises(ValueError, match="not in the fleet"):
        assign_plants_to_sections(plants, sections, regions, overrides=ov)


def test_override_requires_name_column(plants, sections, regions):
    ov = pd.DataFrame({"name": ["A"], "section": ["S1"]})
    with pytest.raises(ValueError, match="'name' column"):
        assign_plants_to_sections(plants, sections, regions, overrides=ov)


def test_override_section_energy_end_to_end(sections, regions):
    # coordless hydro plant pinned to S1 absorbs S1 energy by capacity
    plants = pd.DataFrame(
        {
            "bus": ["R2"],
            "carrier": ["hydro"],
            "p_nom": [100.0],
            "lat": [None],
            "lon": [None],
            "name": ["Diverter"],
        },
        index=pd.Index(["Diverter"], name="plant"),
    )
    ov = pd.DataFrame({"name": ["Diverter"], "section": ["S1"]})
    targets, _ = build_inflow_targets(plants, sections, regions, overrides=ov)
    assert targets.set_index(["bus", "carrier"]).at[("R2", "hydro"), "energy"] == (
        pytest.approx(100.0)
    )


# --- rule-level helpers ----------------------------------------------------


def test_select_hydro_plants_keeps_at_fleet_and_de_grenzkraftwerke_twins():
    from build_hydro_inflow_targets import select_hydro_plants

    ppl = pd.DataFrame(
        {
            "Name": ["Danube A", "Jochenstein", "Jochenstein", "Isar B", "Gas C"],
            "Country": ["AT", "AT", "DE", "DE", "AT"],
            "Fueltype": ["Hydro", "Hydro", "Hydro", "Hydro", "Natural Gas"],
            "Technology": [
                "Reservoir",
                "Run-Of-River",
                "Run-Of-River",
                "Run-Of-River",
                "CCGT",
            ],
            "Capacity": [100.0, 66.0, 66.0, 10.0, 400.0],
            "bus": ["AT126", "AT311", "DE2", "DE2", "AT130"],
            "lat": [48.4, 48.5, 48.5, 48.0, 48.2],
            "lon": [15.7, 13.7, 13.7, 12.0, 16.4],
        },
        index=[10, 11, 12, 13, 14],
    )
    gkw = pd.DataFrame(
        {"Name": ["Jochenstein", "Jochenstein"], "country": ["AT", "DE"]}
    )

    plants = select_hydro_plants(ppl, gkw)

    assert plants.index.tolist() == [10, 11, 12]
    assert plants["carrier"].tolist() == ["hydro", "ror", "ror"]
    assert plants.columns.tolist() == ["bus", "carrier", "p_nom", "name", "lat", "lon"]


@pytest.fixture
def econtrol_file(tmp_path) -> str:
    """Synthetic ``BStGes-JR1_Bilanz.xlsx`` with the sheet ``Erz`` layout."""
    from build_hydro_inflow_targets import (
        BIL_COLUMNS,
        BIL_FIRST_ROW,
        ECONTROL_COLUMNS,
        ECONTROL_FIRST_ROW,
    )

    years = [1985, 1990, 1995, *range(2000, 2026)]  # annual only from 2000
    rows = [[None] * len(ECONTROL_COLUMNS) for _ in range(ECONTROL_FIRST_ROW)]
    for year in years:
        lauf = 30_000.0 if year != 2013 else 33_000.0
        speicher_gt10 = 12_000.0 if year != 2013 else 15_000.0
        pumped_storage = 6_000.0 if year != 2013 else 8_000.0
        rows.append(
            [
                year,
                5_000.0,
                lauf - 5_000.0,
                lauf,
                500.0,
                50.0,
                speicher_gt10,
                pumped_storage,
            ]
        )
    rows.append(["Quelle: E-Control"] + [None] * (len(ECONTROL_COLUMNS) - 1))
    # sheet "Bil": pumping consumption 4,000 GWh, 5,000 in 2013
    balance = [[None] * len(BIL_COLUMNS) for _ in range(BIL_FIRST_ROW)]
    for year in years:
        pumping = 4_000.0 if year != 2013 else 5_000.0
        balance.append(
            [year, 60_000.0, 20_000.0, 80_000.0, 20_000.0, 60_000.0, pumping, 56_000.0]
        )
    path = tmp_path / "BStGes-JR1_Bilanz.xlsx"
    with pd.ExcelWriter(path) as writer:
        pd.DataFrame(rows).to_excel(writer, sheet_name="Erz", header=False, index=False)
        pd.DataFrame(balance).to_excel(
            writer, sheet_name="Bil", header=False, index=False
        )
    return str(path)


def test_read_econtrol_annual_generation(econtrol_file):
    from build_hydro_inflow_targets import read_econtrol_annual_generation

    econtrol = read_econtrol_annual_generation(econtrol_file)

    from build_hydro_inflow_targets import PUMPED_WATER_SHARE

    assert econtrol.columns.tolist() == ["lauf", "speicher", "phs_natural"]
    assert econtrol.index.min() == 1985 and econtrol.index.max() == 2025
    assert econtrol.at[2013, "lauf"] == pytest.approx(33_000.0)
    assert econtrol.at[2013, "speicher"] == pytest.approx(15_500.0)
    # pumped-storage generation 8,050 minus the pumped-water share of 5,000 GWh pumping
    assert econtrol.at[2013, "phs_natural"] == pytest.approx(
        8_050.0 - 5_000.0 * PUMPED_WATER_SHARE
    )


def test_read_econtrol_annual_generation_raises_on_changed_layout(tmp_path):
    from build_hydro_inflow_targets import read_econtrol_annual_generation

    path = tmp_path / "broken.xlsx"
    pd.DataFrame([[2013, 1.0]]).to_excel(
        path, sheet_name="Erz", header=False, index=False
    )
    with pytest.raises(ValueError, match="Unexpected layout"):
        read_econtrol_annual_generation(str(path))


def test_weather_year_factors_relative_to_reference_period(econtrol_file):
    from build_hydro_inflow_targets import (
        read_econtrol_annual_generation,
        weather_year_factors,
    )

    econtrol = read_econtrol_annual_generation(econtrol_file)
    factors = weather_year_factors(econtrol, 2013)

    # available reference years 1995, 2000-2020: 21 at 30000 + one at 33000
    assert factors["ror"] == pytest.approx(33_000.0 / ((21 * 30_000.0 + 33_000.0) / 22))
    assert factors["hydro"] == pytest.approx(
        15_500.0 / ((21 * 12_500.0 + 15_500.0) / 22)
    )
    assert weather_year_factors(econtrol, 2000)["ror"] < 1.0


def test_weather_year_factors_unknown_year_raises(econtrol_file):
    from build_hydro_inflow_targets import (
        read_econtrol_annual_generation,
        weather_year_factors,
    )

    econtrol = read_econtrol_annual_generation(econtrol_file)
    with pytest.raises(ValueError, match="weather year 1950"):
        weather_year_factors(econtrol, 1950)


def test_phs_shares_section_energy_only_where_klien_counts_it():
    """PHS members take energy in sections whose C_current includes them."""
    sections = pd.DataFrame(
        # S1: KLIEN capacity 600 ~ ror 100 + PHS 500 -> PHS counted
        # S2: KLIEN capacity 100 ~ ror 100 -> PHS excluded
        {"E_current": [600.0, 100.0], "C_current": [600.0, 100.0]},
        index=pd.Index(["S1", "S2"], name="section"),
    )
    plants = pd.DataFrame(
        {
            "carrier": ["ror", "PHS", "ror", "PHS"],
            "p_nom": [100.0, 500.0, 100.0, 500.0],
        },
        index=pd.Index(["r1", "p1", "r2", "p2"], name="plant"),
    )
    membership = pd.DataFrame(
        {
            "plant": ["r1", "p1", "r2", "p2"],
            "section": ["S1", "S1", "S2", "S2"],
            "weight": [1.0, 1.0, 1.0, 1.0],
        }
    )

    energy, _ = allocate_section_energy(
        sections, membership, plants, capacity_col="C_current"
    )

    assert energy["r1"] == pytest.approx(100.0)
    assert energy["p1"] == pytest.approx(500.0)
    assert energy["r2"] == pytest.approx(100.0)
    assert "p2" not in energy.index

    # without the capacity column PHS is never eligible
    energy_default, _ = allocate_section_energy(sections, membership, plants)
    assert energy_default["r1"] == pytest.approx(600.0)


def test_plants_never_exceed_section_full_load_hours():
    """With C_current given, missing capacity leaves energy unallocated."""
    sections = pd.DataFrame(
        {"E_current": [500.0], "C_current": [100.0]},  # 5000 h per MW
        index=pd.Index(["S1"], name="section"),
    )
    plants = pd.DataFrame(
        {"carrier": ["ror"], "p_nom": [40.0]},  # 60 MW of the section missing
        index=pd.Index(["r1"], name="plant"),
    )
    membership = pd.DataFrame({"plant": ["r1"], "section": ["S1"], "weight": [1.0]})

    energy, unallocated = allocate_section_energy(
        sections, membership, plants, capacity_col="C_current"
    )

    assert energy["r1"] == pytest.approx(200.0)  # 40 MW x 5000 h
    assert unallocated["S1"] == pytest.approx(300.0)
    # more fleet capacity than KLIEN counts: the section energy is simply split
    plants.loc["r1", "p_nom"] = 150.0
    energy, unallocated = allocate_section_energy(
        sections, membership, plants, capacity_col="C_current"
    )
    assert energy["r1"] == pytest.approx(500.0)
    assert unallocated.empty


def test_catchment_corrections_overwrite_capacity_and_energy():
    from build_hydro_inflow_targets import apply_catchment_corrections

    sections = pd.DataFrame(
        {"C_current": [215.13, 108.29], "E_current": [980.2, 521.2]},
        index=pd.Index([51200, 30800], name="id"),
    )
    corrections = pd.DataFrame(
        {
            "id": [51200],
            "C_current_new": [122.6],
            "E_current_new": [576.3],
            "note": ["company total booked on one stretch"],
        }
    )

    out = apply_catchment_corrections(sections, corrections)

    assert out.loc[51200, "C_current"] == pytest.approx(122.6)
    assert out.loc[51200, "E_current"] == pytest.approx(576.3)
    assert out.loc[30800, "C_current"] == pytest.approx(108.29)
    assert sections.loc[51200, "C_current"] == pytest.approx(215.13)

    with pytest.raises(ValueError, match="not in the KLIEN table"):
        apply_catchment_corrections(sections, corrections.assign(id=[99999]))


def test_phs_inflow_targets_follow_fleet_capacity(econtrol_file):
    from build_hydro_inflow_targets import (
        PUMPED_WATER_SHARE,
        phs_inflow_targets,
        read_econtrol_annual_generation,
    )

    econtrol = read_econtrol_annual_generation(econtrol_file)
    plants = pd.DataFrame(
        {
            "bus": ["AT322", "AT341", "AT212", "DE2"],
            "carrier": ["PHS", "PHS", "hydro", "PHS"],
            "p_nom": [300.0, 100.0, 50.0, 500.0],
        }
    )

    out = phs_inflow_targets(econtrol, 2013, plants, {"AT322", "AT341", "AT212"})

    assert out["carrier"].eq("PHS").all()
    assert out["bus"].tolist() == ["AT322", "AT341"]
    # 2013: 8,050 - 5,000 x share; every other reference year 6,050 - 4,000 x share
    natural_2013 = 8_050.0 - 5_000.0 * PUMPED_WATER_SHARE
    assert out["inflow"].sum() == pytest.approx(natural_2013 * 1e3)
    assert out["rav_gwh"].tolist() == pytest.approx(
        [0.75 * out["rav_gwh"].sum(), 0.25 * out["rav_gwh"].sum()]
    )
    assert out["year_factor"].iloc[0] > 1.0


def test_residual_plants_size_capacity_at_catchment_full_load_hours():
    from build_hydro_inflow_targets import KLIEN_CRS, residual_plants
    from shapely.geometry import box

    # two square catchments; the second one lies outside the Austrian region
    sections = gpd.GeoDataFrame(
        {"C_current": [100.0, 40.0], "E_current": [400.0, 200.0]},
        geometry=[box(0, 0, 10, 10), box(20, 0, 30, 10)],
        index=pd.Index([51200, 60303], name="id"),
        crs=KLIEN_CRS,
    )
    regions = gpd.GeoDataFrame(
        {"name": ["AT121", "AT313", "DE2"]},
        geometry=[box(0, 0, 10, 10), box(20, 0, 25, 10), box(25, 0, 40, 10)],
        crs=KLIEN_CRS,
    ).set_index("name")
    unallocated = pd.Series({51200: 100.0, 60303: 50.0, 70800: 0.0})

    out = residual_plants(sections, unallocated, regions)

    assert out["section"].tolist() == ["51200", "60303"]
    # 100 GWh at 4,000 h -> 25 MW; 50 GWh at 5,000 h -> 10 MW
    assert out["capacity_mw"].tolist() == pytest.approx([25.0, 10.0])
    assert out["energy_gwh"].tolist() == pytest.approx([100.0, 50.0])
    # the second point lies in the German half: largest Austrian overlap wins
    assert out["bus"].tolist() == ["AT121", "AT313"]
    assert out["lat"].notna().all() and out["lon"].notna().all()


def test_residual_plants_empty_when_everything_is_allocated():
    from build_hydro_inflow_targets import KLIEN_CRS, residual_plants
    from shapely.geometry import box

    sections = gpd.GeoDataFrame(
        {"C_current": [100.0], "E_current": [400.0]},
        geometry=[box(0, 0, 10, 10)],
        index=pd.Index([51200], name="id"),
        crs=KLIEN_CRS,
    )
    regions = gpd.GeoDataFrame(
        {"name": ["AT121"]}, geometry=[box(0, 0, 10, 10)], crs=KLIEN_CRS
    ).set_index("name")

    out = residual_plants(sections, pd.Series({51200: 0.0}), regions)

    assert out.empty
    assert out.columns.tolist() == [
        "section",
        "bus",
        "capacity_mw",
        "energy_gwh",
        "lat",
        "lon",
    ]
