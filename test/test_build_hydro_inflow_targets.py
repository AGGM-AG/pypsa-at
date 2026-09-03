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


def test_override_missing_name_ignored(sections, regions, caplog):
    plants = _named("X", "R2", None, None)
    ov = pd.DataFrame({"name": ["NotThere"], "section": ["S1"]})
    with caplog.at_level("WARNING"):
        membership = assign_plants_to_sections(plants, sections, regions, overrides=ov)
    assert "not in the fleet" in caplog.text
    # X falls through to the bus fallback instead
    assert set(membership["plant"]) == {"X"}


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
