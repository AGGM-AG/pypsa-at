# SPDX-FileCopyrightText: 2023-2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""Tests for the Austrian base electricity load regionalisation."""

import io
import warnings
import zipfile
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pypsa
import pytest

from mods.demand import electricity as el
from test.conftest import require_config

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def nea() -> pd.DataFrame:
    """Minimal NEA long table: two Bundesländer, electricity plus one gas row."""
    rows = [
        # (nuts2, sector, use, carrier, value)
        ("AT11", "Private Haushalte", "Standmotoren", "Elektrische Energie", 4.0),
        (
            "AT11",
            "Private Haushalte",
            "Raumklima und Warmwasser",
            "Elektrische Energie",
            1.0,
        ),
        (
            "AT11",
            "Offentliche und Private Dienstleistungen",
            "Beleuchtung und EDV",
            "Elektrische Energie",
            2.0,
        ),
        (
            "AT11",
            "Offentliche und Private Dienstleistungen",
            "Raumklima und Warmwasser",
            "Elektrische Energie",
            0.5,
        ),
        (
            "AT11",
            "Landwirtschaft",
            "Raumklima und Warmwasser",
            "Elektrische Energie",
            0.3,
        ),
        ("AT11", "Landwirtschaft", "Standmotoren", "Elektrische Energie", 0.7),
        ("AT11", "Eisenbahn", "Verkehr", "Elektrische Energie", 0.5),
        ("AT11", "Private Haushalte", "Raumklima und Warmwasser", "Erdgas", 9.0),
        ("AT33", "Private Haushalte", "Standmotoren", "Elektrische Energie", 6.0),
        (
            "AT33",
            "Offentliche und Private Dienstleistungen",
            "Standmotoren",
            "Elektrische Energie",
            3.0,
        ),
        ("AT33", "Landwirtschaft", "Standmotoren", "Elektrische Energie", 1.0),
        ("AT33", "Eisenbahn", "Verkehr", "Elektrische Energie", 1.5),
    ]
    df = pd.DataFrame(
        rows,
        columns=[
            "NUTS-2 Code",
            "Bereich",
            "Nutzenergiekategorie",
            "Energieträger",
            "value_TWh",
        ],
    )
    df["year"] = 2024
    return df


@pytest.fixture
def targets(nea) -> pd.DataFrame:
    return el.nea_base_load_targets(nea, 2024)


@pytest.fixture
def energiemosaik_archive(tmp_path):
    """A zip with the Energiemosaik CSV layout (cp1252, semicolon) for 3 municipalities."""
    columns = [
        "",
        "Gemeindecode",
        "Bezirkscode",
        "Bezirksname",
        "Gemeindename",
        "Energieverbrauch insgesamt (MWh / a)",
        el.ENERGIEMOSAIK_COLUMNS["electricity for residential"],
        el.ENERGIEMOSAIK_COLUMNS["electricity for services"],
        el.ENERGIEMOSAIK_COLUMNS["agriculture electricity"],
    ]
    rows = [
        [0, 10101, 101, "Eisenstadt(Stadt)", "Eisenstadt", 1000, 100, 200, 10],
        [1, 10201, 102, "Rust(Stadt)", "Rust", 500, 300, 100, 30],
        [2, 70701, 707, "Lienz", "Lienz", 400, 50, 50, 5],
    ]
    csv = io.StringIO()
    pd.DataFrame(rows, columns=columns).to_csv(csv, sep=";", index=False)
    archive = tmp_path / "Energiemosaik_Datenpaket_AT.zip"
    with zipfile.ZipFile(archive, "w") as package:
        package.writestr(el.ENERGIEMOSAIK_FILE, csv.getvalue().encode("cp1252"))
        package.writestr("README.txt", "CC BY-NC-SA 3.0 AT")
    return archive


@pytest.fixture
def register() -> pd.DataFrame:
    """Municipality register with one duplicate row (several postal codes)."""
    return pd.DataFrame(
        {
            "district_code": [101.0, 101.0, 102.0, 707.0, 108.0],
            "municipality_code": [10101.0, 10101.0, 10201.0, 70701.0, np.nan],
            "nuts3_code": ["AT112", "AT112", "AT112", "AT333", "AT111"],
            "postal_code": [7000, 7001, 7071, 9900, np.nan],
            "population": [10, 10, 2, 12, 5],
        }
    )


def make_network(carriers=("electricity for residential", "electricity for rail")):
    """Two Austrian regions and one German region with sectoral base Loads."""
    n = pypsa.Network()
    n.set_snapshots(pd.date_range("2013-01-01", periods=4, freq="h"))
    n.snapshot_weightings.loc[:, :] = 2190.0  # 4 snapshots represent a year
    for region in ("AT111", "AT333", "DE1"):
        n.add("Bus", f"{region} low voltage", carrier="low voltage", location=region)
        for carrier in (*carriers, "electricity for road"):
            n.add(
                "Load",
                f"{region} {carrier}",
                bus=f"{region} low voltage",
                carrier=carrier,
                p_set=pd.Series([10.0, 20.0, 0.0, 10.0], index=n.snapshots)
                * (2 if region == "AT333" else 1),
            )
    return n


def make_snakemake(table: pd.DataFrame, tmp_path, year=2030, factor=1.2, use_nea=True):
    path = tmp_path / "electricity_base_load_at_adm.csv"
    table.to_csv(path, index=False)
    return SimpleNamespace(
        params=SimpleNamespace(
            electricity_base_load={
                "enable": True,
                "distribution_key": "energiemosaik",
                "scaling_factors": {2025: 1.0, year: factor},
            },
            use_nea_transport_demand=use_nea,
        ),
        input=SimpleNamespace(electricity_base_load_at=str(path)),
        wildcards=SimpleNamespace(planning_horizons=str(year)),
    )


def annual_energy(n: pypsa.Network) -> pd.Series:
    return n.loads_t.p_set.mul(n.snapshot_weightings.generators, axis=0).sum()


# =============================================================================
# NEA targets
# =============================================================================


def test_nea_parent_maps_osttirol_to_tirol():
    assert el.nea_parent("AT125") == "AT12"
    assert el.nea_parent("AT333") == "AT33"
    assert el.nea_parent("AT12") == "AT12"
    with pytest.raises(ValueError):
        el.nea_parent("DE1")


def test_nea_targets_exclude_heat_only_for_households_and_services(targets):
    expected = pd.DataFrame(
        {
            "electricity for residential": [4.0, 6.0],
            "electricity for services": [2.0, 3.0],
            "agriculture electricity": [1.0, 1.0],
            "electricity for rail": [0.5, 1.5],
        },
        index=pd.Index(["AT11", "AT33"], name="parent"),
    )
    pd.testing.assert_frame_equal(targets, expected)


def test_nea_targets_ignore_other_carriers(targets):
    assert targets.sum().sum() == pytest.approx(19.0)  # the 9 TWh gas row is ignored


def test_nea_targets_raise_for_missing_year(nea):
    with pytest.raises(ValueError, match="source year 2010"):
        el.nea_base_load_targets(nea, 2010)


# =============================================================================
# Energiemosaik
# =============================================================================


def test_read_energiemosaik(energiemosaik_archive):
    data = el.read_energiemosaik(energiemosaik_archive)
    assert data.index.to_list() == [10101, 10201, 70701]
    assert list(data.columns) == [*el.ENERGIEMOSAIK_COLUMNS, "district"]
    assert data.loc[10201, "electricity for residential"] == 300
    assert data.loc[70701, "district"] == 707


def test_read_energiemosaik_raises_on_missing_columns(tmp_path):
    archive = tmp_path / "broken.zip"
    with zipfile.ZipFile(archive, "w") as package:
        package.writestr(el.ENERGIEMOSAIK_FILE, "Gemeindecode;x\n1;2\n")
    with pytest.raises(ValueError, match="lacks columns"):
        el.read_energiemosaik(archive)


def test_municipality_regions_nuts3_and_nuts2(register):
    nuts3 = el.municipality_regions(register, nuts3_regions=True)
    assert nuts3.to_dict() == {10101: "AT112", 10201: "AT112", 70701: "AT333"}
    nuts2 = el.municipality_regions(register, nuts3_regions=False)
    assert nuts2.to_dict() == {10101: "AT11", 10201: "AT11", 70701: "AT333"}


def test_aggregate_energiemosaik_sums_per_region(energiemosaik_archive, register):
    data = el.read_energiemosaik(energiemosaik_archive)
    regions = el.municipality_regions(register, nuts3_regions=True)
    result = el.aggregate_energiemosaik(data, regions)
    assert result.loc["AT112", "electricity for residential"] == 400
    assert result.loc["AT333", "agriculture electricity"] == 5


def test_district_regions_pick_the_most_populated_nuts3(register):
    register.loc[4, "district_code"] = 707.0  # AT111 row now competes in district 707
    assert el.district_regions(register, nuts3_regions=True).to_dict() == {
        101: "AT112",
        102: "AT112",
        707: "AT333",
    }
    assert el.district_regions(register, nuts3_regions=False)[707] == "AT333"


def test_aggregate_energiemosaik_falls_back_to_district(
    energiemosaik_archive, register
):
    data = el.read_energiemosaik(energiemosaik_archive)
    regions = el.municipality_regions(register.iloc[:2], nuts3_regions=True)
    with pytest.raises(ValueError, match="no model region"):
        el.aggregate_energiemosaik(data, regions)
    result = el.aggregate_energiemosaik(
        data, regions, el.district_regions(register, nuts3_regions=True)
    )
    assert result.loc["AT112", "electricity for residential"] == 400
    assert result.loc["AT333", "electricity for services"] == 50
    assert "district" not in result.columns


# =============================================================================
# Table
# =============================================================================


@pytest.fixture
def keys() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "electricity for residential": [1.0, 3.0, 5.0],
            "electricity for services": [1.0, 1.0, 5.0],
            "agriculture electricity": [2.0, 2.0, 5.0],
            "electricity for rail": [1.0, 0.0, 5.0],
        },
        index=["AT111", "AT112", "AT333"],
    )


def test_table_conserves_targets_and_splits_within_bundesland(targets, keys):
    table = el.build_base_load_table(targets, keys)
    assert list(table.columns) == ["region", "carrier", "value_TWh"]
    sums = table.groupby("carrier")["value_TWh"].sum()
    pd.testing.assert_series_equal(sums, targets.sum().sort_index(), check_names=False)
    wide = table.pivot(index="region", columns="carrier", values="value_TWh")
    assert wide.loc["AT111", "electricity for residential"] == pytest.approx(1.0)
    assert wide.loc["AT112", "electricity for residential"] == pytest.approx(3.0)
    assert wide.loc["AT112", "electricity for rail"] == 0.0
    assert wide.loc["AT333", "electricity for rail"] == pytest.approx(
        1.5
    )  # AT333 -> AT33


def test_table_raises_for_missing_carrier_key(targets, keys):
    with pytest.raises(ValueError, match="missing"):
        el.build_base_load_table(targets, keys.drop(columns="electricity for rail"))


def test_table_raises_for_uncovered_bundesland(targets, keys):
    with pytest.raises(ValueError, match="No model region"):
        el.build_base_load_table(targets, keys.drop(index="AT333"))
    with pytest.raises(ValueError, match="No NEA target"):
        el.build_base_load_table(targets, keys.rename(index={"AT333": "AT221"}))


def test_table_raises_for_zero_key(targets, keys):
    keys.loc[:, "electricity for rail"] = 0.0
    with pytest.raises(ValueError, match="zero"):
        el.build_base_load_table(targets, keys)


# =============================================================================
# Orchestrator
# =============================================================================


@pytest.fixture
def table() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "region": ["AT111", "AT333", "AT111", "AT333"],
            "carrier": ["electricity for residential"] * 2
            + ["electricity for rail"] * 2,
            "value_TWh": [1.0, 3.0, 0.5, 0.5],
        }
    )


def test_apply_rebuilds_austrian_loads_to_table_times_factor(table, tmp_path):
    n = make_network()
    before = annual_energy(n)
    el.apply_electricity_base_load(n, make_snakemake(table, tmp_path, factor=1.2))
    after = annual_energy(n)

    assert after["AT111 electricity for residential"] == pytest.approx(1.2e6)
    assert after["AT333 electricity for residential"] == pytest.approx(3.6e6)
    assert after["AT111 electricity for rail"] == pytest.approx(0.6e6)
    assert (n.loads.loc[n.loads.index.str.startswith("AT"), "p_set"] == 0).all()
    # non-AT Loads keep their values
    for name in before.index[before.index.str.startswith("DE")]:
        assert after[name] == before[name]


def test_apply_keeps_the_national_profile_shape(table, tmp_path):
    n = make_network()
    shape_before = (
        n.loads_t.p_set.filter(like="AT").filter(like="residential").sum(axis=1)
    )
    el.apply_electricity_base_load(n, make_snakemake(table, tmp_path))
    for name in (
        "AT111 electricity for residential",
        "AT333 electricity for residential",
    ):
        series = n.loads_t.p_set[name]
        np.testing.assert_allclose(
            series / series.sum(), shape_before / shape_before.sum()
        )


def test_apply_drops_austrian_road_loads_only_with_nea_transport(table, tmp_path):
    n = make_network()
    el.apply_electricity_base_load(n, make_snakemake(table, tmp_path, use_nea=True))
    road = n.loads.index[n.loads.carrier.eq("electricity for road")]
    assert road.to_list() == ["DE1 electricity for road"]

    n = make_network()
    el.apply_electricity_base_load(n, make_snakemake(table, tmp_path, use_nea=False))
    assert n.loads.carrier.eq("electricity for road").sum() == 3


def test_apply_is_a_noop_when_disabled(table, tmp_path):
    n = make_network()
    snakemake = make_snakemake(table, tmp_path)
    snakemake.params.electricity_base_load["enable"] = False
    before = n.loads_t.p_set.copy()
    el.apply_electricity_base_load(n, snakemake)
    pd.testing.assert_frame_equal(n.loads_t.p_set, before)


def test_apply_raises_for_missing_factor(table, tmp_path):
    n = make_network()
    snakemake = make_snakemake(table, tmp_path, year=2040)
    del snakemake.params.electricity_base_load["scaling_factors"][2040]
    with pytest.raises(ValueError, match="No base load scaling factor for 2040"):
        el.apply_electricity_base_load(n, snakemake)


def test_apply_raises_for_region_mismatch(table, tmp_path):
    n = make_network()
    with pytest.raises(ValueError, match="differ"):
        el.apply_electricity_base_load(
            n, make_snakemake(table.replace({"AT333": "AT334"}), tmp_path)
        )


# =============================================================================
# Integration tests on solved networks (AT marker via the ``nc`` fixture)
# =============================================================================

ONIP_TWH = {2030: 90.0, 2040: 121.0}  # ÖNIP electricity demand projections
ONIP_TOLERANCE = 0.10
NEA_PIPELINE_COMPRESSION_TWH = 0.22  # NEA 2024 "Transport in Rohrfernleitungen"
COMPRESSION_TOLERANCE = 0.50
#: AC/low voltage Link withdrawals that only move electricity around
INTERNAL_LINK_CARRIERS = (
    "electricity distribution grid",
    "PHS charger",
    "battery charger",
    "home battery charger",
)


def _at_load_energy(network: pypsa.Network) -> pd.Series:
    """Annual energy of every Austrian Load grouped by region and carrier."""
    regions = network.loads.bus.map(network.buses.location).fillna(network.loads.bus)
    weights = network.snapshot_weightings["generators"]
    energy = network.loads.p_set * weights.sum()
    dynamic = network.loads_t.p_set.mul(weights, axis=0).sum()
    energy.loc[dynamic.index] = dynamic
    at = regions.str.startswith("AT")
    return energy[at].groupby([regions[at], network.loads.carrier[at]]).sum()


def test_austrian_base_loads_match_nea_table(nc):
    """Every Austrian base-load Load carries table value × horizon factor."""
    cfg = require_config(nc, "mods", "electricity_base_load")
    if not cfg["enable"]:
        pytest.skip("Austrian base load override disabled.")
    for year, network in nc.networks.items():
        table = pd.DataFrame.from_dict(
            network.meta["resources"]["electricity_base_load_at"]
        )
        expected = table.set_index(["region", "carrier"])["value_TWh"] * 1e6
        expected *= cfg["scaling_factors"][str(year)]
        actual = _at_load_energy(network).reindex(expected.index)
        pd.testing.assert_series_equal(
            actual, expected, check_names=False, check_exact=False, rtol=1e-6, atol=1.0
        )


def test_austrian_base_load_carriers_within_nea_band(nc):
    """Per carrier, the base year Austrian energy is within ±10 % of the NEA target."""
    cfg = require_config(nc, "mods", "electricity_base_load")
    if not cfg["enable"]:
        pytest.skip("Austrian base load override disabled.")
    year, network = min(nc.networks.items(), key=lambda item: int(item[0]))
    table = pd.DataFrame.from_dict(
        network.meta["resources"]["electricity_base_load_at"]
    )
    nea = table.groupby("carrier")["value_TWh"].sum()
    actual = _at_load_energy(network).groupby(level=1).sum().reindex(nea.index) / 1e6
    deviation = (actual / nea - 1).abs()
    assert (deviation <= 0.10).all(), (
        f"Base year {year} deviation from NEA:\n{deviation}"
    )


def test_no_austrian_road_loads_with_nea_transport(nc):
    cfg = require_config(nc, "mods", "electricity_base_load")
    use_nea = require_config(nc, "demand", "transport", "use_nea_demand")
    if not (cfg["enable"] and use_nea):
        pytest.skip("Road share removal requires both overrides.")
    for network in nc:
        regions = network.loads.bus.map(network.buses.location).fillna(
            network.loads.bus
        )
        road = network.loads.carrier.eq(
            "electricity for road"
        ) & regions.str.startswith("AT")
        assert not road.any(), "Austrian 'electricity for road' Loads still present."


def _at_electricity_withdrawal(network: pypsa.Network) -> pd.Series:
    """Austrian AC and low voltage withdrawal per component and carrier in TWh."""
    withdrawal = network.statistics.withdrawal(
        comps=["Load", "Link"],
        groupby=["country", "carrier"],
        bus_carrier=["AC", "low voltage"],
    )
    return withdrawal.xs("AT", level="country").div(1e6)


def test_austrian_electricity_demand_matches_onip(nc):
    """Load plus conversion withdrawal in Austria is within ±10 % of ÖNIP."""
    for year, network in nc.networks.items():
        if int(year) not in ONIP_TWH:
            continue
        withdrawal = _at_electricity_withdrawal(network)
        internal = withdrawal.index.get_level_values("carrier").isin(
            INTERNAL_LINK_CARRIERS
        )
        total = withdrawal[~internal].sum()
        deviation = total / ONIP_TWH[int(year)] - 1
        assert abs(deviation) <= ONIP_TOLERANCE, (
            f"{year}: {total:.1f} TWh vs ÖNIP {ONIP_TWH[int(year)]} TWh ({deviation:+.1%})"
        )


def test_pipeline_compression_electricity_vs_nea(nc):
    """Warn when endogenous gas compression electricity deviates from NEA."""
    year, network = min(nc.networks.items(), key=lambda item: int(item[0]))
    withdrawal = _at_electricity_withdrawal(network)
    compression = (
        withdrawal.xs("Link", level="component").filter(like="gas pipeline").sum()
    )
    deviation = compression / NEA_PIPELINE_COMPRESSION_TWH - 1
    if abs(deviation) > COMPRESSION_TOLERANCE:
        warnings.warn(
            f"{year}: Austrian gas pipeline compression withdraws {compression:.2f} TWh, "
            f"NEA reports {NEA_PIPELINE_COMPRESSION_TWH} TWh ({deviation:+.0%}).",
            stacklevel=1,
        )
