# SPDX-FileCopyrightText: 2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""Unit tests for the existing capacity deduction of AT potentials."""

import numpy as np
import pandas as pd
import pypsa
import pytest

from mods.network.potentials import (
    deduct_existing_capacities,
    raise_potentials_to_minimum,
)


@pytest.fixture
def network():
    """AT111/AT112 onwind with existing capacities and an untouched DE node."""
    n = pypsa.Network()
    n.add("Bus", ["AT111", "AT112", "DE1"])
    for bus in n.buses.index:
        n.add(
            "Generator",
            f"{bus} onwind-2030",
            bus=bus,
            carrier="onwind",
            p_nom_extendable=True,
            p_nom_max=np.inf,
        )
        n.add(
            "Generator",
            f"{bus} onwind-2015",
            bus=bus,
            carrier="onwind",
            p_nom=300.0,
        )
    n.add(
        "Generator",
        "AT111 onwind-2020",
        bus="AT111",
        carrier="onwind",
        p_nom=200.0,
    )
    return n


def test_deducts_existing_only_from_changed_potentials(network):
    before = network.generators.p_nom_max.copy()
    network.generators.loc["AT111 onwind-2030", "p_nom_max"] = 1000.0
    network.generators.loc["AT112 onwind-2030", "p_nom_max"] = 1000.0

    deduct_existing_capacities(network, before, 2030)

    p_nom_max = network.generators.p_nom_max
    assert p_nom_max["AT111 onwind-2030"] == 500.0  # 1000 - 300 - 200
    assert p_nom_max["AT112 onwind-2030"] == 700.0  # 1000 - 300
    assert p_nom_max["DE1 onwind-2030"] == np.inf  # not changed by AT


def test_existing_above_potential_is_kept_as_potential(network):
    before = network.generators.p_nom_max.copy()
    network.generators.loc["AT111 onwind-2030", "p_nom_max"] = 400.0
    network.generators.loc["AT111 onwind-2030", "p_nom_min"] = 50.0

    deduct_existing_capacities(network, before, 2030)

    # 400 - 500 existing < p_nom_min, so p_nom_min wins
    assert network.generators.at["AT111 onwind-2030", "p_nom_max"] == 50.0


def test_ignores_carriers_without_land_use_constraint(network):
    network.add(
        "Generator",
        "AT111 ror-2030",
        bus="AT111",
        carrier="ror",
        p_nom_extendable=True,
    )
    network.add("Generator", "AT111 ror-2015", bus="AT111", carrier="ror", p_nom=80.0)
    before = network.generators.p_nom_max.copy()
    network.generators.loc["AT111 ror-2030", "p_nom_max"] = 100.0

    deduct_existing_capacities(network, before, 2030)

    pd.testing.assert_series_equal(
        network.generators.p_nom_max.drop("AT111 ror-2030"),
        before.drop("AT111 ror-2030"),
    )
    assert network.generators.at["AT111 ror-2030", "p_nom_max"] == 100.0


def test_raise_potentials_to_minimum(network):
    network.generators.loc["DE1 onwind-2030", ["p_nom_min", "p_nom_max"]] = [980, 818]
    network.generators.loc["AT111 onwind-2030", ["p_nom_min", "p_nom_max"]] = [10, 20]

    raise_potentials_to_minimum(network)

    assert network.generators.at["DE1 onwind-2030", "p_nom_max"] == 980
    assert network.generators.at["AT111 onwind-2030", "p_nom_max"] == 20
