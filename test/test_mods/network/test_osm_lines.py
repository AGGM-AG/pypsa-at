# SPDX-FileCopyrightText: 2023-2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""Tests for mods.network.osm_lines."""

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import box

from mods.network.osm_lines import (
    assign_nuts3_regions,
    designate_feeds,
    filter_inter_regional_lines,
    regions_without_transmission,
    validate_feed_overrides,
)

# Two square NUTS3 regions side by side: R1 spans x 0..1, R2 spans x 1..2.


@pytest.fixture
def nuts3_shapes():
    return gpd.GeoDataFrame(
        {
            "index": ["AT_R1", "AT_R2"],
            "country": ["AT", "AT"],
            "geometry": [box(0, 0, 1, 1), box(1, 0, 2, 1)],
        },
        crs="EPSG:4326",
    )


@pytest.fixture
def buses():
    return pd.DataFrame(
        {
            "x": [0.5, 0.6, 1.5, 1.6, 0.5],
            "y": [0.5, 0.6, 0.5, 0.6, 0.7],
            "voltage": [110.0, 110.0, 110.0, 380.0, 110.0],
            "country": ["AT", "AT", "AT", "AT", "AT"],
        },
        index=["b_r1_a", "b_r1_b", "b_r2_a", "b_r2_hv", "b_r1_c"],
    )


def make_lines(rows):
    df = pd.DataFrame(
        rows,
        columns=[
            "line_id",
            "bus0",
            "bus1",
            "voltage",
            "circuits",
            "length",
            "operator_clean",
        ],
    )
    return df.set_index("line_id")


@pytest.fixture
def overrides_empty():
    return pd.DataFrame(
        columns=["region", "line_id", "substation", "source", "evidence"]
    )


def test_assign_nuts3_regions_point_in_polygon(buses, nuts3_shapes):
    regions = assign_nuts3_regions(buses, nuts3_shapes)

    assert regions.to_dict() == {
        "b_r1_a": "AT_R1",
        "b_r1_b": "AT_R1",
        "b_r2_a": "AT_R2",
        "b_r2_hv": "AT_R2",
        "b_r1_c": "AT_R1",
    }


def test_assign_nuts3_regions_nearest_fallback(nuts3_shapes):
    outside = pd.DataFrame(
        {"x": [-0.1], "y": [0.5], "voltage": [110.0], "country": ["AT"]},
        index=["b_out"],
    )

    regions = assign_nuts3_regions(outside, nuts3_shapes)

    assert regions.loc["b_out"] == "AT_R1"


def test_assign_nuts3_regions_ignores_foreign_buses(nuts3_shapes):
    mixed = pd.DataFrame(
        {
            "x": [0.5, 0.5],
            "y": [0.5, 0.5],
            "voltage": [110.0, 110.0],
            "country": ["AT", "DE"],
        },
        index=["b_at", "b_de"],
    )

    regions = assign_nuts3_regions(mixed, nuts3_shapes)

    assert "b_de" not in regions.index


def test_regions_without_transmission(buses, nuts3_shapes):
    regions = assign_nuts3_regions(buses, nuts3_shapes)

    # R2 hosts a 380 kV bus, R1 only 110 kV.
    assert regions_without_transmission(buses, regions) == {"AT_R1"}


def test_validate_feed_overrides_raises_on_missing_line(buses, nuts3_shapes):
    lines = make_lines([("l1", "b_r1_a", "b_r1_b", 110.0, 2, 1000.0, None)])
    regions = assign_nuts3_regions(buses, nuts3_shapes)
    overrides = pd.DataFrame([{"region": "AT_R1", "line_id": "gone"}])

    with pytest.raises(ValueError, match="not present"):
        validate_feed_overrides(
            overrides, lines, lines["bus0"].map(regions), lines["bus1"].map(regions)
        )


def test_validate_feed_overrides_raises_on_wrong_region(buses, nuts3_shapes):
    lines = make_lines([("l1", "b_r1_a", "b_r1_b", 110.0, 2, 1000.0, None)])
    regions = assign_nuts3_regions(buses, nuts3_shapes)
    overrides = pd.DataFrame([{"region": "AT_R2", "line_id": "l1"}])

    with pytest.raises(ValueError, match="does not touch"):
        validate_feed_overrides(
            overrides, lines, lines["bus0"].map(regions), lines["bus1"].map(regions)
        )


def test_designate_feeds_prefers_override_over_heuristic():
    candidates = make_lines(
        [
            ("thick_short", "a", "b", 110.0, 2, 100.0, None),
            ("thin_long", "a", "b", 110.0, 1, 5000.0, None),
        ]
    )
    r0 = pd.Series(["AT_R1", "AT_R1"], index=candidates.index)
    r1 = pd.Series(["AT_R2", "AT_R2"], index=candidates.index)
    overrides = pd.DataFrame([{"region": "AT_R1", "line_id": "thin_long"}])

    feeds = designate_feeds(overrides, {"AT_R1"}, candidates, r0, r1)

    # The heuristic would pick thick_short; the documented override wins.
    assert feeds == {"thin_long": "AT_R1"}


def test_designate_feeds_heuristic_fallback(overrides_empty):
    candidates = make_lines(
        [
            ("thick", "a", "b", 110.0, 2, 100.0, None),
            ("thin", "a", "b", 110.0, 1, 50.0, None),
        ]
    )
    r0 = pd.Series(["AT_R1", "AT_R1"], index=candidates.index)
    r1 = pd.Series(["AT_R2", "AT_R2"], index=candidates.index)

    feeds = designate_feeds(overrides_empty, {"AT_R1"}, candidates, r0, r1)

    assert feeds == {"thick": "AT_R1"}


class TestFilterInterRegionalLines:
    """End-to-end behaviour of the R2-R5 corridor filter."""

    @pytest.fixture
    def lines(self):
        return make_lines(
            [
                # R2: transmission level, crosses regions — kept
                ("l_hv", "b_r1_a", "b_r2_hv", 380.0, 2, 50_000.0, "APG"),
                # R2b: TSO-operated 110 kV crossing regions — kept
                ("l_apg", "b_r1_a", "b_r2_a", 110.0, 2, 40_000.0, "APG | Netz NÖ"),
                # R3: intra-regional 110 kV — kept
                ("l_intra", "b_r1_a", "b_r1_b", 110.0, 2, 10_000.0, "Netz NÖ"),
                # R5: inter-regional 110 kV DSO line — dropped
                ("l_corridor", "b_r1_b", "b_r2_a", 110.0, 2, 30_000.0, "Netz NÖ"),
                # R4 candidate out of R1 (which has no HV bus)
                ("l_feed", "b_r1_c", "b_r2_a", 110.0, 1, 20_000.0, "Netz NÖ"),
            ]
        )

    def test_rules(self, lines, buses, nuts3_shapes, overrides_empty):
        kept, report = filter_inter_regional_lines(
            lines, buses, nuts3_shapes, overrides_empty
        )

        assert report.loc["l_hv", "rule"] == "R2 TRANSMISSION"
        assert report.loc["l_apg", "rule"] == "R2b APG_TSO"
        assert report.loc["l_intra", "rule"] == "R3 INTRA_REGION"
        # AT_R1 has no >=220 kV bus: the heuristic designates its best branch
        # as the feed. l_corridor (2 circuits) beats l_feed (1 circuit).
        assert report.loc["l_corridor", "rule"] == "R4 SOLE_FEED"
        assert report.loc["l_feed", "rule"] == "R5 INTER_REGION"
        assert not report.loc["l_feed", "active"]
        assert set(kept.index) == {"l_hv", "l_apg", "l_intra", "l_corridor"}

    def test_override_redirects_feed(self, lines, buses, nuts3_shapes):
        overrides = pd.DataFrame(
            [
                {
                    "region": "AT_R1",
                    "line_id": "l_feed",
                    "substation": "X",
                    "source": "test",
                    "evidence": "test",
                }
            ]
        )

        kept, report = filter_inter_regional_lines(
            lines, buses, nuts3_shapes, overrides
        )

        assert report.loc["l_feed", "rule"] == "R4 SOLE_FEED"
        assert not report.loc["l_corridor", "active"]
        assert set(kept.index) == {"l_hv", "l_apg", "l_intra", "l_feed"}

    def test_report_covers_every_line(
        self, lines, buses, nuts3_shapes, overrides_empty
    ):
        _, report = filter_inter_regional_lines(
            lines, buses, nuts3_shapes, overrides_empty
        )

        assert report.index.equals(lines.index)
        assert {"active", "rule", "reason", "region0", "region1"} <= set(report.columns)

    def test_requires_operator_clean(self, buses, nuts3_shapes, overrides_empty):
        bare = make_lines([("l1", "b_r1_a", "b_r1_b", 110.0, 2, 1000.0, None)]).drop(
            columns="operator_clean"
        )

        with pytest.raises(ValueError, match="operator_clean"):
            filter_inter_regional_lines(bare, buses, nuts3_shapes, overrides_empty)

    def test_rejects_unassigned_low_voltage_line(
        self, buses, nuts3_shapes, overrides_empty
    ):
        lines = make_lines([("l1", "b_r1_a", "b_unknown", 110.0, 2, 1000.0, None)])

        with pytest.raises(ValueError, match="outside the Austrian NUTS3"):
            filter_inter_regional_lines(lines, buses, nuts3_shapes, overrides_empty)


def test_tso_cross_border_line_is_kept_despite_missing_region(
    buses, nuts3_shapes, overrides_empty
):
    """
    An APG-operated 110 kV cross-border line survives the corridor filter.

    Its foreign endpoint has no NUTS3 region, which must neither drop the line
    nor trigger the unassigned-endpoint guard.
    """
    lines = make_lines(
        [
            ("l_xb_apg", "b_r1_a", "b_foreign", 110.0, 2, 15_000.0, "APG"),
            ("l_hv", "b_r1_a", "b_r2_hv", 380.0, 2, 50_000.0, None),
        ]
    )

    kept, report = filter_inter_regional_lines(
        lines, buses, nuts3_shapes, overrides_empty
    )

    assert report.loc["l_xb_apg", "rule"] == "R2b APG_TSO"
    assert "l_xb_apg" in kept.index
