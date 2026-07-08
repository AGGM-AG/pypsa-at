# SPDX-FileCopyrightText: 2023-2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""Unit tests for mods.clustering — DE5_GROUPS, map_at_nuts3_to_nuts2, map_de_nuts1_to_de5."""

import pytest

from mods.clustering.constants import DE5_GROUPS
from mods.clustering.utils import _map_at_nuts3_to_nuts2, _map_de_nuts1_to_de5
from test.conftest import require_config


class TestDE5Groups:
    def test_covers_all_16_nuts1_states(self):
        all_nuts1 = {
            "DE1",
            "DE2",
            "DE3",
            "DE4",
            "DE5",
            "DE6",
            "DE7",
            "DE8",
            "DE9",
            "DEA",
            "DEB",
            "DEC",
            "DED",
            "DEE",
            "DEF",
            "DEG",
        }
        grouped = {code for codes in DE5_GROUPS.values() for code in codes}
        assert grouped == all_nuts1

    def test_no_state_belongs_to_multiple_groups(self):
        seen = []
        for codes in DE5_GROUPS.values():
            seen.extend(codes)
        assert len(seen) == len(set(seen))

    def test_produces_exactly_five_aggregates(self):
        assert set(DE5_GROUPS) == {"DE1", "DE2", "DE3", "DE4", "DE5"}


class TestMapAtNuts3ToNuts2:
    @pytest.mark.parametrize(
        "code,expected",
        [
            # AT NUTS3 → NUTS2
            ("AT125", "AT12"),
            ("AT126", "AT12"),
            ("AT311", "AT31"),
            ("AT312", "AT31"),
            ("AT314", "AT31"),
            ("AT315", "AT31"),
            ("AT323", "AT32"),
            # AT333 preserved as standalone NUTS2 region
            ("AT333", "AT333"),
            # AT NUTS2 codes pass through unchanged
            ("AT11", "AT11"),
            ("AT12", "AT12"),
            ("AT32", "AT32"),
            # non-AT codes pass through unchanged
            ("DE7", "DE7"),
            ("BE", "BE"),
            ("SK", "SK"),
        ],
    )
    def test_mapping(self, code, expected):
        assert _map_at_nuts3_to_nuts2(code) == expected


class TestMapDeNuts1ToDe5:
    @pytest.mark.parametrize(
        "code,expected",
        [
            # DE NUTS1 → DE5
            ("DE1", "DE1"),
            ("DE2", "DE2"),
            ("DE7", "DE3"),
            ("DEB", "DE3"),
            ("DEC", "DE3"),
            ("DEA", "DE3"),
            ("DE3", "DE4"),
            ("DE4", "DE4"),
            ("DE8", "DE4"),
            ("DED", "DE4"),
            ("DEE", "DE4"),
            ("DEG", "DE4"),
            ("DEF", "DE5"),
            ("DE6", "DE5"),
            ("DE9", "DE5"),
            ("DE5", "DE5"),
            # non-DE codes pass through unchanged
            ("AT125", "AT125"),
            ("FR0", "FR0"),
            ("NL", "NL"),
        ],
    )
    def test_mapping(self, code, expected):
        assert _map_de_nuts1_to_de5(code) == expected


def test_custom_clustering(nc, is_testrun):
    """
    Make sure the custom clustering yields the expected regions.
    """
    if is_testrun:
        pytest.xfail(
            "Testrun has different countries and is expected to fail this test."
        )
    clustering = require_config(nc, "mods", "modify_nuts3_shapes")
    for n in nc:
        locations = n.buses.location.unique()
        locations_at = [loc for loc in locations if loc.startswith("AT")]
        locations_de = [loc for loc in locations if loc.startswith("DE")]
        if clustering == "AT10DE5":
            # 34 countries, + 9 AT, + 4 DE, + 2 IT, + 1 DK-GB, +1 EU (FR and ES merged)
            assert len(locations) == 52
            assert len(locations_at) == 10
            assert len(locations_de) == 5
        elif clustering == "AT10DE16":
            assert len(locations) == 63
            assert len(locations_at) == 10
            assert len(locations_de) == 16
        elif clustering == "AT35DE5":
            assert len(locations) == 77
            assert len(locations_at) == 35
            assert len(locations_de) == 5
        elif clustering == "AT35DE16":
            assert len(locations) == 88
            assert len(locations_at) == 35
            assert len(locations_de) == 16
        else:
            raise AssertionError(f"Unexpected clustering detected: {clustering}")

        assert len([loc for loc in locations if loc.startswith("IT")]) == 3
        assert len([loc for loc in locations if loc.startswith("DK")]) == 2
        assert len([loc for loc in locations if loc.startswith("GB")]) == 2
        assert len([loc for loc in locations if loc.startswith("FR")]) == 1
        assert len([loc for loc in locations if loc.startswith("ES")]) == 1
