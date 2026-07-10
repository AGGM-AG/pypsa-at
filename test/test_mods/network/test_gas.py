# SPDX-FileCopyrightText: 2023-2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""Integration tests for mods/network/gas.py — gas storage capacity overrides."""

from importlib import import_module

import pandas as pd
import pytest
from pypsa import NetworkCollection

from evals.utils import filter_by
from mods.clustering.utils import combine_regions_by_clustering
from mods.network.gas import _TANAP_PIPELINE_CAPACITY
from test.conftest import require_config

update_gas_transport_data = import_module(
    "scripts.pypsa-at.modify_brownfield_gas_network_AT"
).update_gas_transport_data

GAS_NETWORK_COLUMNS = [
    "bus0",
    "bus1",
    "p_nom",
    "p_nom_diameter",
    "max_pressure_bar",
    "build_year",
    "diameter_mm",
    "length",
    "name",
    "p_min_pu",
]


def gas_network(rows: list[tuple[str, str, float, str]]) -> pd.DataFrame:
    """Build a gas network DataFrame from (bus0, bus1, p_nom, name) rows."""
    df = pd.DataFrame(rows, columns=["bus0", "bus1", "p_nom", "name"])
    for column in GAS_NETWORK_COLUMNS:
        if column not in df:
            df[column] = 0
    # corridor identifiers are the index, as in the clustered gas network files
    df.index = "gas pipeline " + df["bus0"] + " -> " + df["bus1"]
    return df[GAS_NETWORK_COLUMNS]


def test_gas_storage_update(nc, project_root, is_testrun):
    """
    Verify input data values in solve networks.

    Parameters
    ----------
    nc
        The solved networks.
    """
    file_name = "gas_input_locations_s_AT35DE16_updated.csv"
    file_path = project_root / "data" / "pypsa-at" / file_name
    expected = pd.read_csv(file_path, index_col=0)["storage update (GWh)"]
    expected = expected.dropna().mul(1e3)
    expected = expected[expected > 0]
    # aggregate update values depending on custom clustering
    clustering = require_config(nc, "mods", "modify_nuts3_shapes")
    expected = combine_regions_by_clustering(expected, clustering)

    gas_storage_capacity = nc.statistics.optimal_capacity(
        groupby="location",
        components="Store",
        bus_carrier="gas",
    )

    # align indices for CI regions
    if is_testrun:
        model_locations = list(gas_storage_capacity.index.unique("location"))
        expected = filter_by(expected, Region=model_locations)

    expected_store_names = {f"{loc} gas Store" for loc in expected.index}

    for year, n in nc.networks.items():
        gas_stores = n.stores.query("carrier == 'gas'")
        # All gas stores are non-extendable
        assert not gas_stores["e_nom_extendable"].any()
        # Only the expected gas Stores exist
        assert set(gas_stores.index) == expected_store_names
        pd.testing.assert_series_equal(
            gas_storage_capacity[year], expected, rtol=1e-03, check_names=False
        )


@pytest.mark.parametrize("block_name", ["eastern_border_block", "turkstream_block"])
def test_block_russian_gas_imports(nc, block_name):
    """
    Verify blockade of Russian gas imports functionality for all years.
    Find country based generators that should be turned off, assert that they are.

    Parameters
    ----------
    nc
        The solved networks.
    block_name
        name of each corridor that can be blocked.
    """
    corridors = require_config(nc, "mods", "block_russian_gas_imports", enable=False)
    model_countries = require_config(nc, "countries")

    block_config = corridors[block_name]
    if block_config is None:
        pytest.skip(f"No block config for {block_name}, skipping")

    config_countries = block_config.get("countries", [])
    assert config_countries, "No countries in config."

    start_year = block_config["start_year"]
    end_year = block_config.get("end_year", float("inf"))
    countries = [c for c in config_countries if c in model_countries]

    if not countries:
        pytest.skip(
            f"No countries from {block_name} blockade in modeled scope, skipping test."
        )

    # drop years not covered by the block feature
    nc = NetworkCollection(
        pd.Series(
            {
                year: n
                for year, n in nc.networks.items()
                if start_year <= int(year) <= end_year
            }
        )
    )

    # edge case BG has remaining import capacities
    countries_wo_bg = [c for c in countries if c != "BG"]

    pipeline_capacity = nc.statistics.optimal_capacity(
        groupby=["country", "carrier"],
        components="Generator",
        carrier="pipeline gas",
        drop_zero=False,
    )
    pipeline_capacity_wo_bg = filter_by(pipeline_capacity, country=countries_wo_bg)
    assert pipeline_capacity_wo_bg.sum() == 0, (
        f"Remaining pipeline imports detected: {pipeline_capacity}"
    )

    # test for edge case Bulgarian imports. The guard is needed to prevent running the check for 2025
    if block_name == "turkstream_block":
        pipeline_capacity_bg = filter_by(pipeline_capacity, country="BG")
        assert all(pipeline_capacity_bg.sub(_TANAP_PIPELINE_CAPACITY).abs() <= 0.001), (
            f"Bulgarian gas pipeline import capacities not as expected: {pipeline_capacity_bg}"
        )

    pipeline_supply = nc.statistics.supply(
        groupby=["country", "carrier"],
        components="Generator",
        carrier="pipeline gas",
        drop_zero=False,
    ).pipe(filter_by, country=countries_wo_bg)
    assert pipeline_supply.sum() == 0, (
        f"Remaining pipeline imports detected: {pipeline_supply}"
    )


class TestModifyBrownfieldGasNetworkAT:
    """Unit tests for adding AGGM brownfield gas grid"""

    @pytest.fixture
    def raw(self) -> pd.DataFrame:
        """Clustered gas network as built by PyPSA-Eur standard from Sci2Grid data."""
        return gas_network(
            [
                ("AT12", "AT13", 19616.0, "sci2grid_at_internal"),
                ("AT12", "SI", 4689.0, "sci2grid_at_border"),
                ("SK", "AT12", 96080.0, "sci2grid_border_at"),
                ("DE1", "DE2", 12000.0, "sci2grid_de_internal"),
                ("SK", "HU", 8000.0, "sci2grid_sk_hu"),
            ]
        )

    @pytest.fixture
    def input_data(self) -> pd.DataFrame:
        """Mock AGGM expert data for Austrian transport corridors."""
        return gas_network(
            [
                ("AT12", "AT13", 1234.0, "AGGM_pipeline01"),
                ("AT12", "SI", 4500.0, "AGGM_pipeline02"),
                ("SK", "AT12", 65300.0, "AGGM_pipeline03"),
            ]
        )

    def test_at_removed_from_raw(self, raw, input_data):
        """Raw corridors touching Austria are dropped, no matter the bus position."""
        result = update_gas_transport_data(raw, input_data)

        assert not result["name"].str.startswith("sci2grid_at").any()
        assert "sci2grid_border_at" not in set(result["name"])

    def test_foreign_corridors_are_preserved_in_raw(self, raw, input_data):
        """Corridors without an AT bus pass through unchanged."""
        foreign = ["sci2grid_de_internal", "sci2grid_sk_hu"]

        result = update_gas_transport_data(raw, input_data)

        out = result[result["name"].isin(foreign)]
        expected = raw[raw["name"].isin(foreign)]
        assert out.compare(expected).empty

    def test_input_at_corridors_are_added(self, raw, input_data):
        """Check that all AGGM provided transport corridors are added"""
        result = update_gas_transport_data(raw, input_data)

        out = result[result["name"].str.startswith("AGGM_")]
        assert out.compare(input_data).empty


class TestAGGMGasNetworkCapacityData:
    """Data integrity tests for the AGGM brownfield gas network capacity input files."""

    @pytest.fixture(params=["AT10", "AT35"])
    def aggm_data(self, request, project_root) -> pd.DataFrame:
        """AGGM brownfield gas network for both supported custom clusterings is present."""
        file_name = f"AGGM_gas_network_base_{request.param}.csv"
        return pd.read_csv(project_root / "data" / "pypsa-at" / file_name, index_col=0)

    @pytest.fixture
    def raw(self) -> pd.DataFrame:
        """
        Mock network that contains every bus that borders AT regions
        (Germany DE1, DE2, CH, IT0, SI, HU, SK, CZ)
        """
        return gas_network(
            [
                ("DE1", bus, 1.0, f"sci2grid_DE1_{bus}")
                for bus in ["DE2", "CH", "IT0", "SI", "HU", "SK", "CZ"]
            ]
            + [("AT12", "AT13", 19616.0, "sci2grid_at_internal")]
        )

    def test_columns(self, aggm_data):
        """The AGGM data provides exactly the columns of a PyPSA gas network."""
        assert list(aggm_data.columns) == GAS_NETWORK_COLUMNS

    def test_corridors_are_unique(self, aggm_data):
        """Check that each corridor index and name are unique."""
        assert aggm_data.index.is_unique
        assert aggm_data["name"].is_unique

    def test_capacities_are_valid(self, aggm_data):
        """Transport capacities are numeric, non-negative and not NaN"""
        p_nom = aggm_data["p_nom"]
        assert pd.api.types.is_numeric_dtype(p_nom)
        assert p_nom.notna().all()
        assert (p_nom >= 0).all()

    def test_capacities_are_added(self, raw, aggm_data):
        """All AGGM capacities are actually added to the clustered gas network csv."""
        result = update_gas_transport_data(raw, aggm_data)

        at_bus0 = result["bus0"].str.startswith("AT")
        at_bus1 = result["bus1"].str.startswith("AT")
        at_capacity = result.loc[at_bus0 | at_bus1, "p_nom"].sum()
        assert at_capacity == pytest.approx(aggm_data["p_nom"].sum())

    def test_corridor_count(self, raw, aggm_data):
        """The new file contains all raw non-AT capacities plus all added AGGM AT capacities."""
        at_bus0 = raw["bus0"].str.startswith("AT")
        at_bus1 = raw["bus1"].str.startswith("AT")
        foreign_corridors = (~(at_bus0 | at_bus1)).sum()

        result = update_gas_transport_data(raw, aggm_data)

        assert len(result) == foreign_corridors + len(aggm_data)
