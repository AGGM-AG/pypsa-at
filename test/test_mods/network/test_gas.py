# SPDX-FileCopyrightText: 2023-2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""Integration tests for mods/network/gas.py — gas storage capacity overrides."""

from importlib import import_module
from types import SimpleNamespace

import pandas as pd
import pypsa
import pytest
from pypsa import NetworkCollection

from evals.utils import filter_by
from mods.clustering.utils import combine_regions_by_clustering
from mods.network.gas import (
    _TANAP_PIPELINE_CAPACITY,
    restore_asymmetric_pipeline_capacities,
)
from test.conftest import require_config

_modify_brownfield_gas_network_AT = import_module(
    "scripts.pypsa-at.modify_brownfield_gas_network_AT"
)
update_gas_transport_data = _modify_brownfield_gas_network_AT.update_gas_transport_data
aggregate_gas_pipeline_corridors_to_nuts2 = (
    _modify_brownfield_gas_network_AT.aggregate_gas_pipeline_corridors_to_nuts2
)
apply_reverse_flow_limits = _modify_brownfield_gas_network_AT.apply_reverse_flow_limits

GAS_NETWORK_COLUMNS = [
    "bus0",
    "bus1",
    "p_nom",
    "p_nom_reverse",
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

    @pytest.fixture
    def expected_output(self, raw, input_data) -> pd.DataFrame:
        """Foreign corridors unchanged, AT corridors dropped, AGGM corridors appended."""
        foreign = ["sci2grid_de_internal", "sci2grid_sk_hu"]
        expected_foreign = raw[raw["name"].isin(foreign)]
        return pd.concat([expected_foreign, input_data])

    def test_update_gas_transport_data(self, raw, input_data, expected_output):
        """AT corridors dropped from raw, foreign corridors preserved, AGGM corridors added."""
        result = update_gas_transport_data(raw, input_data)

        pd.testing.assert_frame_equal(result, expected_output)


def corridor_frame(rows: list[tuple]) -> pd.DataFrame:
    """
    Build AGGM corridor rows from (bus0, bus1, p_nom, p_nom_reverse, p_min_pu) tuples.

    ``p_nom_reverse`` is ``None`` for every corridor that is not asymmetric,
    matching the blank column entries of the AGGM input file.
    """
    df = pd.DataFrame(
        rows, columns=["bus0", "bus1", "p_nom", "p_nom_reverse", "p_min_pu"]
    )
    df["p_nom_reverse"] = df["p_nom_reverse"].astype(float)
    connector = df["p_min_pu"].map({-1: " <-> "}).fillna(" -> ")
    df.index = "gas pipeline " + df["bus0"] + connector + df["bus1"]
    for column in ("p_nom_diameter", "max_pressure_bar", "diameter_mm", "length"):
        df[column] = 0
    df["build_year"] = 1974
    df["name"] = [f"AGGM_pipeline{i:02d}" for i in range(len(df))]
    return df


class TestApplyReverseFlowLimits:
    """Unit tests for converting AGGM reverse capacities into p_min_pu bounds."""

    @pytest.fixture
    def corridors(self) -> pd.DataFrame:
        """One corridor of every shape the AGGM file can hold."""
        return corridor_frame(
            [
                ("AT225", "AT213", 16672.0, 6015.0, -1),  # asymmetric
                ("AT342", "AT341", 575.0, None, -1),  # symmetric
                ("DE2", "AT342", 1269.0, None, 0),  # one way
                ("AT311", "DE2", 7274.0, 7274.0, -1),  # reverse equals forward
                ("AT126", "HU", 6378.0, 0.0, -1),  # reverse capacity of zero
            ]
        )

    def test_asymmetric_corridor_becomes_a_fraction(self, corridors):
        """p_min_pu holds the reverse capacity as a share of the forward one."""
        result = apply_reverse_flow_limits(corridors)

        assert result.loc["gas pipeline AT225 <-> AT213", "p_min_pu"] == pytest.approx(
            -6015.0 / 16672.0
        )

    def test_reverse_capacity_is_recoverable(self, corridors):
        """The reverse capacity can be read back from p_min_pu and p_nom."""
        result = apply_reverse_flow_limits(corridors)
        row = result.loc["gas pipeline AT225 <-> AT213"]

        assert -row["p_min_pu"] * row["p_nom"] == pytest.approx(6015.0)

    @pytest.mark.parametrize(
        "corridor, expected",
        [
            ("gas pipeline AT342 <-> AT341", -1.0),  # symmetric stays bidirectional
            ("gas pipeline DE2 -> AT342", 0.0),  # one way stays one way
            ("gas pipeline AT311 <-> DE2", -1.0),  # equal capacities are symmetric
            ("gas pipeline AT126 <-> HU", 0.0),  # zero reverse capacity is one way
        ],
    )
    def test_corridor_shapes_map_to_expected_bounds(
        self, corridors, corridor, expected
    ):
        """Corridors without an asymmetry keep or reach the bound they imply."""
        result = apply_reverse_flow_limits(corridors)

        assert result.loc[corridor, "p_min_pu"] == pytest.approx(expected)

    def test_reverse_capacity_column_is_dropped(self, corridors):
        """The clustered gas network keeps the column set of a PyPSA gas network."""
        result = apply_reverse_flow_limits(corridors)

        assert "p_nom_reverse" not in result.columns

    def test_column_is_dropped_without_any_asymmetry(self, corridors):
        """The column also goes when no corridor carries a reverse capacity."""
        symmetric_only = corridors[corridors["p_nom_reverse"].isna()]

        result = apply_reverse_flow_limits(symmetric_only)

        assert "p_nom_reverse" not in result.columns
        assert result["p_min_pu"].tolist() == [-1, 0]

    def test_input_is_not_modified(self, corridors):
        """The caller's frame is left untouched."""
        before = corridors.copy()

        apply_reverse_flow_limits(corridors)

        pd.testing.assert_frame_equal(corridors, before)

    def test_rows_are_preserved(self, corridors):
        """Converting bounds neither drops nor reorders corridors."""
        result = apply_reverse_flow_limits(corridors)

        assert result.index.equals(corridors.index)


class TestAggregateReverseCapacities:
    """Unit tests for carrying AGGM reverse capacities through the NUTS2 aggregation."""

    def test_parallel_asymmetric_pipes_sum_per_direction(self):
        """Merged parallel pipes sum their forward and reverse capacities separately."""
        corridors = corridor_frame(
            [
                ("AT225", "AT213", 16672.0, 6015.0, -1),
                ("AT225", "AT213", 16672.0, 6015.0, -1),
            ]
        )
        corridors.index = ["first", "second"]

        result = aggregate_gas_pipeline_corridors_to_nuts2(corridors)

        assert len(result) == 1
        assert result["p_nom"].iloc[0] == pytest.approx(2 * 16672.0)
        assert result["p_nom_reverse"].iloc[0] == pytest.approx(2 * 6015.0)

    def test_blank_reverse_capacity_follows_the_corridor_bound(self):
        """A bidirectional pipe contributes its p_nom, a one-way pipe contributes zero."""
        corridors = corridor_frame(
            [
                ("AT225", "AT213", 16672.0, 6015.0, -1),  # asymmetric
                ("AT226", "AT212", 1000.0, None, -1),  # symmetric, same NUTS2 pair
            ]
        )
        corridors.index = ["asymmetric", "symmetric"]

        result = aggregate_gas_pipeline_corridors_to_nuts2(corridors)

        assert len(result) == 1
        assert result["p_nom"].iloc[0] == pytest.approx(17672.0)
        assert result["p_nom_reverse"].iloc[0] == pytest.approx(6015.0 + 1000.0)

    def test_reverse_capacity_survives_aggregation(self):
        """The column reaches the caller rather than being dropped on the way."""
        corridors = corridor_frame([("AT225", "AT213", 16672.0, 6015.0, -1)])

        result = aggregate_gas_pipeline_corridors_to_nuts2(corridors)

        assert "p_nom_reverse" in result.columns
        assert result["p_nom_reverse"].notna().all()

    def test_aggregation_then_conversion_keeps_the_asymmetry(self):
        """The two ingestion steps compose into the bound the corridors imply."""
        corridors = corridor_frame(
            [
                ("AT225", "AT213", 16672.0, 6015.0, -1),
                ("AT225", "AT213", 16672.0, 6015.0, -1),
            ]
        )
        corridors.index = ["first", "second"]

        result = apply_reverse_flow_limits(
            aggregate_gas_pipeline_corridors_to_nuts2(corridors)
        )

        row = result.iloc[0]
        assert -row["p_min_pu"] * row["p_nom"] == pytest.approx(2 * 6015.0)


class TestAGGMGasNetworkCapacityData:
    """Data integrity tests for the AGGM brownfield gas network capacity input files."""

    @pytest.fixture(params=["AT10", "AT35"])
    def aggm_data(self, request, project_root) -> pd.DataFrame:
        """
        AGGM brownfield gas network for both supported custom clusterings is present.

        AT35 is the maintained source file; AT10 is derived from it via
        ``aggregate_gas_pipeline_corridors_to_nuts2`` rather than a separate
        static file (see ``modify_brownfield_gas_network_AT.py``).
        """
        at35 = pd.read_csv(
            project_root / "data" / "pypsa-at" / "AGGM_gas_network_base_AT35.csv",
            index_col=0,
        )
        if request.param == "AT10":
            return aggregate_gas_pipeline_corridors_to_nuts2(at35)
        return at35

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

    def test_reverse_capacities_are_valid(self, aggm_data):
        """
        Reverse capacities are numeric and never exceed the forward direction.

        A reverse capacity above the forward one would put ``p_min_pu`` below
        -1, which PyPSA accepts silently while meaning a pipe that carries more
        gas backwards than the direction its row is written in.
        """
        reverse = aggm_data["p_nom_reverse"].dropna()
        if reverse.empty:
            pytest.skip("No asymmetric corridors in this file.")

        assert pd.api.types.is_numeric_dtype(reverse)
        assert (reverse >= 0).all()
        assert (reverse <= aggm_data.loc[reverse.index, "p_nom"]).all()

    def test_reverse_capacities_belong_to_bidirectional_corridors(self, aggm_data):
        """
        Only a corridor marked bidirectional may carry a reverse capacity.

        A reverse capacity on a one-way row contradicts itself, and the
        ingestion would resolve it silently in favour of the reverse capacity.
        """
        asymmetric = aggm_data["p_nom_reverse"].notna()
        assert (aggm_data.loc[asymmetric, "p_min_pu"] == -1).all()

    def test_directions_are_not_split_across_rows(self, aggm_data):
        """
        One physical pipe is one row, so no bus pair holds one-way rows in both
        directions. Two such rows would be built as two Links, billing the pipe
        twice and retrofitting it twice into hydrogen.
        """
        one_way = aggm_data[aggm_data["p_min_pu"] == 0]
        bus_pair = one_way.apply(
            lambda c: " <-> ".join(sorted((c["bus0"], c["bus1"]))), axis=1
        )
        for corridor, group in one_way.groupby(bus_pair):
            assert group["bus0"].nunique() == 1, (
                f"Corridor {corridor} has one-way rows in both directions: "
                f"{list(group.index)}. Merge them into one row with p_nom_reverse."
            )

    def test_capacities_are_added_to_csv(self, raw, aggm_data):
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


class TestBrownfieldGasNetworkLinks:
    """Verify the AGGM transport corridor capacities reach the brownfield"""

    @pytest.fixture(scope="class")
    def brownfield_network(self, nc) -> pypsa.Network:
        """Solved 2025 network — topology (Links, buses) matches the pre-solve brownfield build."""
        return nc.networks["2025"]

    @pytest.fixture(scope="class")
    def aggm_data(self, brownfield_network) -> pd.DataFrame:
        """
        Raw corridors touching AT are all dropped by update_gas_transport_data.
        Any AT corridor left in the merged resource originates from the AGGM input data.
        """
        merged = pd.DataFrame.from_dict(
            brownfield_network.meta["resources"]["aggm_gas_pipeline_data"]
        )
        at_bus0 = merged["bus0"].str.startswith("AT")
        at_bus1 = merged["bus1"].str.startswith("AT")
        return merged[at_bus0 | at_bus1]

    @pytest.fixture(scope="class")
    def gas_pipelines(self, brownfield_network) -> pd.DataFrame:
        """Gas pipeline Links of the brownfield network."""
        links = brownfield_network.links
        gas_pipes = links[links["carrier"] == "gas pipeline"]
        return gas_pipes[~gas_pipes.index.str.endswith("-reversed")]

    @pytest.fixture(scope="class")
    def expected_corridors(self, brownfield_network, aggm_data) -> pd.DataFrame:
        """
        To conform to reduced country scope (eg. in CI test runs), drop busses
        that are outside the modeled regions from expected corridors.
        """
        gas_buses = set(
            brownfield_network.buses.index[brownfield_network.buses["carrier"] == "gas"]
        )
        in_scope = aggm_data.apply(
            lambda c: {f"{c.bus0} gas", f"{c.bus1} gas"} <= gas_buses, axis=1
        )
        expected = aggm_data[in_scope]
        assert not expected.empty, "No AGGM corridors within the modeled scope."
        return expected

    def test_every_corridor_is_built(self, gas_pipelines, expected_corridors):
        """Every in-scope AGGM corridor exists as a Link in the brownfield network."""
        missing = set(expected_corridors.index) - set(gas_pipelines.index)
        assert not missing, f"AGGM corridors missing from brownfield network: {missing}"

    def test_corridors_connect_the_expected_buses(
        self, gas_pipelines, expected_corridors
    ):
        """Each AGGM corridor connects the gas buses of its AGGM bus pair."""
        built = gas_pipelines.loc[expected_corridors.index]

        assert (built["bus0"] == expected_corridors["bus0"] + " gas").all()
        assert (built["bus1"] == expected_corridors["bus1"] + " gas").all()

    def test_capacities_are_built(self, gas_pipelines, expected_corridors):
        """Every AGGM transport capacity is present as Link capacity in brownfield network."""
        built = gas_pipelines.loc[expected_corridors.index, "p_nom"]

        pd.testing.assert_series_equal(
            built, expected_corridors["p_nom"], check_names=False, check_dtype=False
        )


class TestRestoreAsymmetricPipelineCapacities:
    """Unit tests for resizing the reverse leg of asymmetric gas pipelines."""

    @staticmethod
    def clustered_gas_network(tmp_path) -> str:
        """
        Clustered gas network holding one asymmetric corridor, one symmetric
        corridor, one one-way corridor and one corridor outside the modelled
        scope.
        """
        path = tmp_path / "gas_network.csv"
        pd.DataFrame(
            {
                "bus0": ["AT225", "AT342", "DE2", "AT999"],
                "bus1": ["AT213", "AT341", "AT342", "AT998"],
                "p_nom": [16672.0, 575.0, 1269.0, 100.0],
                "p_min_pu": [-6015.0 / 16672.0, -1.0, 0.0, -0.5],
            },
            index=[
                "gas pipeline AT225 <-> AT213",
                "gas pipeline AT342 <-> AT341",
                "gas pipeline DE2 -> AT342",
                "gas pipeline AT999 <-> AT998",
            ],
        ).to_csv(path)
        return str(path)

    @staticmethod
    def snakemake(path: str, enabled: bool = True) -> SimpleNamespace:
        """Minimal Snakemake stand-in exposing the config flag and the resource."""
        return SimpleNamespace(
            config={"mods": {"modify_brownfield_gas_network_AT": enabled}},
            input=SimpleNamespace(clustered_gas_network=path),
        )

    @staticmethod
    def network(split: bool = True, drop: str | None = None) -> pypsa.Network:
        """Brownfield network as prepare_sector_network leaves it, split into legs."""
        n = pypsa.Network()
        n.add("Bus", ["AT225 gas", "AT213 gas", "AT342 gas", "AT341 gas", "DE2 gas"])

        legs = {
            "gas pipeline AT225 <-> AT213": ("AT225 gas", "AT213 gas", 16672.0, False),
            "gas pipeline AT342 <-> AT341": ("AT342 gas", "AT341 gas", 575.0, False),
            "gas pipeline DE2 -> AT342": ("DE2 gas", "AT342 gas", 1269.0, False),
        }
        if split:
            legs |= {
                "gas pipeline AT225 <-> AT213-reversed": (
                    "AT213 gas",
                    "AT225 gas",
                    16672.0,
                    True,
                ),
                "gas pipeline AT342 <-> AT341-reversed": (
                    "AT341 gas",
                    "AT342 gas",
                    575.0,
                    True,
                ),
                "gas pipeline DE2 -> AT342-reversed": (
                    "AT342 gas",
                    "DE2 gas",
                    1269.0,
                    True,
                ),
            }
        legs.pop(drop, None)

        for name, (bus0, bus1, p_nom, reversed_leg) in legs.items():
            n.add(
                "Link",
                name,
                bus0=bus0,
                bus1=bus1,
                p_nom=p_nom,
                p_nom_extendable=True,
                carrier="gas pipeline",
                reversed=reversed_leg,
            )
        return n

    @pytest.fixture
    def restored(self, tmp_path) -> pypsa.Network:
        """Network after the reverse legs have been resized."""
        n = self.network()
        restore_asymmetric_pipeline_capacities(
            n, self.snakemake(self.clustered_gas_network(tmp_path))
        )
        return n

    def test_reverse_leg_carries_the_reverse_capacity(self, restored):
        """The reverse leg drops from the copied forward capacity to its own."""
        assert restored.links.at[
            "gas pipeline AT225 <-> AT213-reversed", "p_nom"
        ] == pytest.approx(6015.0)

    def test_reverse_leg_bounds_follow_the_capacity(self, restored):
        """p_nom_min and p_nom_max move with p_nom so the leg cannot drift back."""
        leg = restored.links.loc["gas pipeline AT225 <-> AT213-reversed"]

        assert leg["p_nom_min"] == pytest.approx(6015.0)
        assert leg["p_nom_max"] == pytest.approx(6015.0)

    def test_reverse_leg_is_fixed(self, restored):
        """
        A fixed reverse leg is skipped by add_lossy_bidirectional_link_constraints,
        which would otherwise even the asymmetry out again wherever gas pipelines
        may still be expanded.
        """
        assert not restored.links.at[
            "gas pipeline AT225 <-> AT213-reversed", "p_nom_extendable"
        ]

    def test_forward_leg_is_untouched(self, restored):
        """The forward direction keeps its full capacity and stays expandable."""
        leg = restored.links.loc["gas pipeline AT225 <-> AT213"]

        assert leg["p_nom"] == pytest.approx(16672.0)
        assert leg["p_nom_extendable"]

    @pytest.mark.parametrize(
        "leg",
        [
            "gas pipeline AT342 <-> AT341-reversed",  # symmetric corridor
            "gas pipeline DE2 -> AT342-reversed",  # one-way corridor
        ],
    )
    def test_other_corridors_are_untouched(self, restored, leg):
        """Only corridors with an asymmetry are resized."""
        assert restored.links.at[leg, "p_nom_extendable"]

    def test_corridor_outside_the_modelled_scope_is_skipped(self, restored):
        """Reduced country scope drops corridors, which is not an error."""
        assert "gas pipeline AT999 <-> AT998-reversed" not in restored.links.index

    def test_disabled_feature_changes_nothing(self, tmp_path):
        """Without the AGGM brownfield network there is nothing to restore."""
        n = self.network()
        before = n.links["p_nom"].copy()

        restore_asymmetric_pipeline_capacities(
            n, self.snakemake(self.clustered_gas_network(tmp_path), enabled=False)
        )

        pd.testing.assert_series_equal(n.links["p_nom"], before)

    def test_unsplit_network_changes_nothing(self, tmp_path):
        """
        Without the split the corridors are single Links that still carry their
        own asymmetric bounds, so there is no reverse leg to correct.
        """
        n = self.network(split=False)
        before = n.links["p_nom"].copy()

        restore_asymmetric_pipeline_capacities(
            n, self.snakemake(self.clustered_gas_network(tmp_path))
        )

        pd.testing.assert_series_equal(n.links["p_nom"], before)

    def test_missing_reverse_leg_raises(self, tmp_path):
        """
        A corridor built without its reverse leg is a silent loss of the
        asymmetry: lossy_bidirectional_links has zeroed the p_min_pu that
        recorded it, so nothing downstream would notice.
        """
        n = self.network(drop="gas pipeline AT225 <-> AT213-reversed")

        with pytest.raises(ValueError, match="without a reverse leg"):
            restore_asymmetric_pipeline_capacities(
                n, self.snakemake(self.clustered_gas_network(tmp_path))
            )


class TestAsymmetricGasPipelineCapacitiesInNetwork:
    """Verify the AGGM flow asymmetries survive into the solved networks."""

    @pytest.fixture(scope="class")
    def brownfield_network(self, nc) -> pypsa.Network:
        """Solved 2025 network — Link capacities match the pre-solve brownfield build."""
        return nc.networks["2025"]

    @pytest.fixture(scope="class")
    def asymmetric_corridors(self, brownfield_network) -> pd.DataFrame:
        """
        Corridors whose two flow directions differ, taken from the clustered gas
        network the run was built from, and reduced to those actually built.
        """
        merged = pd.DataFrame.from_dict(
            brownfield_network.meta["resources"]["aggm_gas_pipeline_data"]
        )
        asymmetric = merged[merged["p_min_pu"].between(-1, 0, inclusive="neither")]
        built = asymmetric[asymmetric.index.isin(brownfield_network.links.index)]
        if built.empty:
            pytest.skip("No asymmetric gas pipeline corridors in this run.")
        return built

    def test_forward_legs_keep_the_full_capacity(
        self, brownfield_network, asymmetric_corridors
    ):
        """The stronger direction is unaffected by the reverse leg correction."""
        built = brownfield_network.links.loc[asymmetric_corridors.index, "p_nom"]

        pd.testing.assert_series_equal(
            built, asymmetric_corridors["p_nom"], check_names=False, check_dtype=False
        )

    def test_reverse_legs_carry_the_reverse_capacity(
        self, brownfield_network, asymmetric_corridors
    ):
        """
        The reverse leg holds the corridor's own reverse capacity rather than the
        forward capacity lossy_bidirectional_links copies onto it.
        """
        expected = -asymmetric_corridors["p_min_pu"] * asymmetric_corridors["p_nom"]
        reverse_legs = asymmetric_corridors.index + "-reversed"

        missing = set(reverse_legs) - set(brownfield_network.links.index)
        assert not missing, f"Asymmetric corridors without a reverse leg: {missing}"

        built = brownfield_network.links.loc[reverse_legs, "p_nom"]
        assert built.to_numpy() == pytest.approx(expected.to_numpy())

    def test_reverse_legs_are_smaller_than_forward_legs(
        self, brownfield_network, asymmetric_corridors
    ):
        """The whole point of the asymmetry: less capacity against the compressors."""
        forward = brownfield_network.links.loc[asymmetric_corridors.index, "p_nom"]
        reverse = brownfield_network.links.loc[
            asymmetric_corridors.index + "-reversed", "p_nom"
        ]

        assert (reverse.to_numpy() < forward.to_numpy()).all()

    def test_reverse_legs_are_fixed(self, brownfield_network, asymmetric_corridors):
        """
        Guards against upstream re-synchronising the pair: an extendable reverse
        leg would be tied back to its forward leg by
        add_lossy_bidirectional_link_constraints.
        """
        reverse_legs = asymmetric_corridors.index + "-reversed"

        assert not brownfield_network.links.loc[reverse_legs, "p_nom_extendable"].any()

    def test_corridor_is_billed_once(self, brownfield_network, asymmetric_corridors):
        """
        One physical pipe carries one investment cost: the reverse leg is free,
        so the corridor is not billed twice for its two flow directions.
        """
        reverse_legs = asymmetric_corridors.index + "-reversed"
        costs = brownfield_network.links.loc[reverse_legs, "capital_cost"]

        # noisy_costs adds a small length-proportional perturbation at solve time,
        # and the reverse legs carry length 0, so their cost stays exactly zero
        assert (costs == 0).all()
