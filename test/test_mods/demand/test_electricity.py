# SPDX-FileCopyrightText: 2023-2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""Test electricity demand modifications."""

import pytest
from pypsa import NetworkCollection

from test.conftest import require_config


@pytest.mark.parametrize("location", ["AT"])
def test_yearly_total_electricity_demand(nc: NetworkCollection, location: str):
    """
    Compare configuration entries with solved network values for electricity Loads.

    Parameters
    ----------
    nc
        The solved networks.
    location
        The location under ``mods.demand.{location}`` to compare.
    """
    cfg = require_config(nc, "mods", "demand", "electricity")
    expected = cfg[location]  # KeyError on misalignment of config and parametrize
    print(expected)
