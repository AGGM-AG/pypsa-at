# SPDX-FileCopyrightText: 2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""Unit tests for mods/network/biogas.py."""

from types import SimpleNamespace

import pandas as pd
import pypsa
import pytest

from mods.network.biogas import (
    CARRIER,
    COST_KEY,
    add_existing_biogas_chp_at,
    aggregate_biogas_plants,
    build_biogas_chp_links,
)

GROUPING_YEARS = [1900, 1950, 2000, 2005, 2010, 2025]


@pytest.fixture
def costs():
    """Technology data with the row the mod reads."""
    return pd.DataFrame(
        {
            "efficiency": [0.25],
            "capital_cost": [1000.0],
            "investment": [500000.0],
            "VOM": [4.0],
            "lifetime": [25.0],
        },
        index=pd.Index([COST_KEY], name="technology"),
    )


def plants_frame(rows: list[tuple]) -> pd.DataFrame:
    """Plants from (Name, bus, Capacity, DateIn) tuples."""
    return pd.DataFrame(rows, columns=["Name", "bus", "Capacity", "DateIn"])


class TestAggregateBiogasPlants:
    """Tests for aggregate_biogas_plants."""

    def test_capacities_sum_per_node_and_vintage(self):
        plants = plants_frame(
            [
                ("a", "AT11", 1.0, 2003),
                ("b", "AT11", 2.0, 2003),
                ("c", "AT12", 5.0, 2003),
            ]
        )

        result = aggregate_biogas_plants(plants, GROUPING_YEARS, 25, 2025, 0)

        assert result["capacity"].to_dict() == {
            ("AT11", 2005): 3.0,
            ("AT12", 2005): 5.0,
        }

    def test_date_in_is_binned_into_the_next_grouping_year(self):
        plants = plants_frame([("a", "AT11", 1.0, 2003), ("b", "AT11", 1.0, 2005)])

        result = aggregate_biogas_plants(plants, GROUPING_YEARS, 25, 2025, 0)

        assert result.index.get_level_values("grouping_year").tolist() == [2005]
        assert result["capacity"].iloc[0] == 2.0

    def test_lifetime_counts_from_the_grouping_year(self):
        """2003 + 25 = 2028, phase-out at year end: 2028 - 2005 + 1."""
        plants = plants_frame([("a", "AT11", 1.0, 2003)])

        result = aggregate_biogas_plants(plants, GROUPING_YEARS, 25, 2025, 0)

        assert result["lifetime"].iloc[0] == 24

    def test_lifetime_is_capacity_weighted(self):
        plants = plants_frame([("a", "AT11", 3.0, 2001), ("b", "AT11", 1.0, 2005)])

        result = aggregate_biogas_plants(plants, GROUPING_YEARS, 25, 2025, 0)

        # (22 * 3 + 26 * 1) / 4
        assert result["lifetime"].iloc[0] == pytest.approx(23.0)

    def test_threshold_drops_small_nodes(self):
        plants = plants_frame([("a", "AT11", 1.5, 2003), ("b", "AT12", 2.5, 2003)])

        result = aggregate_biogas_plants(plants, GROUPING_YEARS, 25, 2025, 2)

        assert result.index.get_level_values("bus").tolist() == ["AT12"]

    def test_threshold_applies_to_the_node_sum(self):
        plants = plants_frame([("a", "AT11", 1.5, 2003), ("b", "AT11", 1.5, 2003)])

        result = aggregate_biogas_plants(plants, GROUPING_YEARS, 25, 2025, 2)

        assert result["capacity"].iloc[0] == 3.0

    def test_retired_plants_are_dropped(self):
        plants = plants_frame([("a", "AT11", 1.0, 1990), ("b", "AT11", 1.0, 2003)])

        result = aggregate_biogas_plants(plants, GROUPING_YEARS, 25, 2025, 0)

        assert result["capacity"].to_dict() == {("AT11", 2005): 1.0}

    def test_missing_date_in_raises(self):
        plants = plants_frame([("a", "AT11", 1.0, None)])

        with pytest.raises(ValueError, match="DateIn"):
            aggregate_biogas_plants(plants, GROUPING_YEARS, 25, 2025, 0)

    def test_date_in_after_last_grouping_year_raises(self):
        plants = plants_frame([("a", "AT11", 1.0, 2026)])

        with pytest.raises(ValueError, match="grouping_years_power"):
            aggregate_biogas_plants(plants, GROUPING_YEARS, 25, 2025, 0)

    def test_input_is_not_modified(self):
        plants = plants_frame([("a", "AT11", 1.0, 2003)])
        before = plants.copy()

        aggregate_biogas_plants(plants, GROUPING_YEARS, 25, 2025, 0)

        pd.testing.assert_frame_equal(plants, before)


class TestBuildBiogasChpLinks:
    """Tests for build_biogas_chp_links."""

    @pytest.fixture
    def links(self, costs):
        aggregated = pd.DataFrame(
            {"capacity": [3.0, 5.0], "lifetime": [24.0, 24.0]},
            index=pd.MultiIndex.from_tuples(
                [("AT11", 2005), ("AT12", 2005)], names=["bus", "grouping_year"]
            ),
        )
        return build_biogas_chp_links(aggregated, costs)

    def test_names_follow_the_pypsa_de_convention(self, links):
        assert links.index.tolist() == [
            "AT11 biogas CHP-2005",
            "AT12 biogas CHP-2005",
        ]

    def test_links_connect_biogas_bus_to_electricity_bus(self, links):
        assert links["bus0"].tolist() == ["AT11 biogas", "AT12 biogas"]
        assert links["bus1"].tolist() == ["AT11", "AT12"]
        assert links["location"].tolist() == ["AT11", "AT12"]

    def test_carrier(self, links):
        assert (links["carrier"] == CARRIER).all()

    def test_electric_capacity_is_recoverable(self, links, costs):
        """p_nom is biogas input; p_nom * efficiency is the electric capacity."""
        electric = links["p_nom"] * links["efficiency"]

        assert electric.tolist() == pytest.approx([3.0, 5.0])
        assert (links["efficiency"] == costs.at[COST_KEY, "efficiency"]).all()

    def test_costs_are_per_unit_of_biogas_input(self, links, costs):
        efficiency = costs.at[COST_KEY, "efficiency"]

        assert (links["capital_cost"] == 1000.0 * efficiency).all()
        assert (links["onight_cost"] == 500000.0 * efficiency).all()
        assert (links["marginal_cost"] == 4.0 * efficiency).all()

    def test_links_are_not_reversed_legs(self, links):
        """The PyPSA-Eur custom attribute must be set, NaN breaks solve_network."""
        assert links["reversed"].dtype == bool
        assert not links["reversed"].any()

    def test_links_are_brownfield(self, links):
        assert not links["p_nom_extendable"].any()
        assert links["build_year"].tolist() == [2005, 2005]
        assert links["lifetime"].tolist() == [24.0, 24.0]


class TestAddExistingBiogasChpAt:
    """Tests for the orchestrator add_existing_biogas_chp_at."""

    @pytest.fixture
    def network(self):
        n = pypsa.Network()
        n.add("Carrier", ["AC", "biogas"])
        n.add("Bus", ["AT11", "AT12"], carrier="AC")
        n.add("Bus", ["AT11 biogas", "AT12 biogas"], carrier="biogas")
        return n

    @pytest.fixture
    def snakemake(self, tmp_path):
        path = tmp_path / "biogas_plants_at_adm.csv"
        plants_frame(
            [
                ("a", "AT11", 1.0, 2003),
                ("b", "AT11", 2.0, 2003),
                ("c", "AT12", 5.0, 2003),
            ]
        ).to_csv(path, index=False)
        return SimpleNamespace(
            input=SimpleNamespace(biogas_plants_at=str(path)),
            wildcards=SimpleNamespace(planning_horizons="2025"),
            params=SimpleNamespace(
                add_biogas_to_power_plants_AT=True,
                planning_horizons=[2025, 2030, 2040],
                existing_capacities={
                    "grouping_years_power": GROUPING_YEARS,
                    "threshold_capacity": 2,
                },
            ),
            config={"plotting": {"tech_colors": {CARRIER: "#92d46c"}}},
        )

    def test_adds_one_link_per_node_and_vintage(self, network, snakemake, costs):
        add_existing_biogas_chp_at(network, snakemake, costs)

        links = network.links.query("carrier == @CARRIER")
        assert links.index.tolist() == [
            "AT11 biogas CHP-2005",
            "AT12 biogas CHP-2005",
        ]
        assert (links["p_nom"] * links["efficiency"]).tolist() == pytest.approx(
            [3.0, 5.0]
        )

    def test_adds_the_carrier_with_its_colour(self, network, snakemake, costs):
        add_existing_biogas_chp_at(network, snakemake, costs)

        assert network.carriers.at[CARRIER, "color"] == "#92d46c"

    def test_skips_later_horizons(self, network, snakemake, costs):
        snakemake.wildcards.planning_horizons = "2030"

        add_existing_biogas_chp_at(network, snakemake, costs)

        assert network.links.empty

    def test_skips_when_disabled(self, network, snakemake, costs):
        snakemake.params.add_biogas_to_power_plants_AT = False

        add_existing_biogas_chp_at(network, snakemake, costs)

        assert network.links.empty

    def test_enabled_without_plants_raises(self, network, snakemake, costs, tmp_path):
        path = tmp_path / "empty.csv"
        plants_frame([]).to_csv(path, index=False)
        snakemake.input.biogas_plants_at = str(path)

        with pytest.raises(ValueError, match="No Austrian biogas plants"):
            add_existing_biogas_chp_at(network, snakemake, costs)

    def test_missing_biogas_bus_raises(self, network, snakemake, costs):
        network.remove("Bus", "AT12 biogas")

        with pytest.raises(ValueError, match="AT12 biogas"):
            add_existing_biogas_chp_at(network, snakemake, costs)

    def test_existing_link_raises(self, network, snakemake, costs):
        network.add("Link", "AT11 biogas CHP-2005", bus0="AT11 biogas", bus1="AT11")

        with pytest.raises(ValueError, match="already exist"):
            add_existing_biogas_chp_at(network, snakemake, costs)
