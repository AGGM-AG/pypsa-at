# SPDX-FileCopyrightText: Contributors to PyPSA-AT <https://github.com/AGGM-AG/pypsa-at>
#
# SPDX-License-Identifier: MIT

"""
Tests the functionalities of scripts/pypsa-at/build_osm_network_at.py.
"""

import importlib.util
import json
import pathlib

import pandas as pd
import pytest

# The script lives in a directory with a dash in its name, so it cannot be
# imported as a normal module path.
_SPEC = importlib.util.spec_from_file_location(
    "build_osm_network_at",
    pathlib.Path(__file__).parents[1] / "scripts/pypsa-at/build_osm_network_at.py",
)
build_osm_network_at = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(build_osm_network_at)

add_operator_columns = build_osm_network_at.add_operator_columns
canonical_operator = build_osm_network_at.canonical_operator
drop_cross_border_lines_lv = build_osm_network_at.drop_cross_border_lines_lv
load_osm_tags = build_osm_network_at.load_osm_tags
match_operator_alias = build_osm_network_at.match_operator_alias
is_traction = build_osm_network_at.is_traction
parse_frequencies = build_osm_network_at.parse_frequencies
drop_traction_lines = build_osm_network_at.drop_traction_lines


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Austrian Power Grid AG", "APG"),
        ("APG", "APG"),
        ("Verbund / APG", "APG"),
        ("Verbund Austrian Power Grid AG", "APG"),
        ("Austrian Grid Power AG", "APG"),  # transposed name, a typo in OSM
        ("APG;Netz NÖ", "APG"),
        ("ÖBB", "ÖBB-Infrastruktur"),
        ("ÖBB-Infrastruktur AG", "ÖBB-Infrastruktur"),
        ("Netz Oberösterreich", "Netz OÖ"),
        ("Netz OÖ", "Netz OÖ"),
        ("Netz Niederösterreich GmbH", "Netz NÖ"),
        ("TIWAG-Netz AG", "TINETZ"),
        ("STEWEAG-STEG", "Energienetze Steiermark"),
    ],
)
def test_canonical_operator_maps_known_aliases(raw, expected):
    assert canonical_operator(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["Verbund Hydro Power GmbH", "VHP", "verbund hydro power"],
)
def test_verbund_hydro_power_is_not_the_tso(raw):
    """The generation arm must never be mapped onto the TSO alias."""
    assert canonical_operator(raw) == "Verbund Hydro Power"


def test_unknown_operator_passes_through_verbatim():
    assert canonical_operator("Some Unlisted Grid GmbH") == "Some Unlisted Grid GmbH"


@pytest.fixture
def osm_tags():
    return {
        "way/1": {"operator": "Austrian Power Grid AG", "frequency": "50"},
        "way/2": {"operator": "ÖBB-Infrastruktur AG", "frequency": "16.7"},
        "way/3": {"operator": None, "frequency": "16.7"},
        "relation/4": {"operator": "APG", "frequency": None},
        "way/5": {"operator": "Netz OÖ", "frequency": "50"},
    }


def test_add_operator_columns_resolves_single_reference(osm_tags):
    df = pd.DataFrame({"tags": ["way/1"]}, index=["l1"])

    out = add_operator_columns(df, osm_tags)

    assert out.loc["l1", "operator"] == "Austrian Power Grid AG"
    assert out.loc["l1", "operator_clean"] == "APG"
    assert out.loc["l1", "tag_frequency"] == "50"


def test_add_operator_columns_joins_disagreeing_references(osm_tags):
    """A merged component keeps every value rather than picking one."""
    df = pd.DataFrame({"tags": ["way/1;way/5"]}, index=["l1"])

    out = add_operator_columns(df, osm_tags)

    assert out.loc["l1", "operator"] == "Austrian Power Grid AG | Netz OÖ"
    assert out.loc["l1", "operator_clean"] == "APG | Netz OÖ"


def test_add_operator_columns_deduplicates_equivalent_aliases(osm_tags):
    """Two spellings of one operator collapse in operator_clean but not in operator."""
    df = pd.DataFrame({"tags": ["way/1;relation/4"]}, index=["l1"])

    out = add_operator_columns(df, osm_tags)

    assert out.loc["l1", "operator"] == "Austrian Power Grid AG | APG"
    assert out.loc["l1", "operator_clean"] == "APG"


def test_add_operator_columns_keeps_traction_frequency(osm_tags):
    """16.7 Hz must survive, since upstream overwrites frequency with 50."""
    df = pd.DataFrame({"tags": ["way/2"]}, index=["l1"])

    out = add_operator_columns(df, osm_tags)

    assert out.loc["l1", "tag_frequency"] == "16.7"
    assert out.loc["l1", "operator_clean"] == "ÖBB-Infrastruktur"


def test_add_operator_columns_handles_frequency_without_operator(osm_tags):
    df = pd.DataFrame({"tags": ["way/3"]}, index=["l1"])

    out = add_operator_columns(df, osm_tags)

    assert pd.isna(out.loc["l1", "operator"])
    assert out.loc["l1", "tag_frequency"] == "16.7"


def test_add_operator_columns_marks_unknown_references_as_missing(osm_tags):
    df = pd.DataFrame({"tags": ["way/999", ""]}, index=["l1", "l2"])

    out = add_operator_columns(df, osm_tags)

    assert out["operator"].isna().all()
    assert out["operator_clean"].isna().all()


def test_add_operator_columns_preserves_input_columns(osm_tags):
    df = pd.DataFrame({"tags": ["way/1"], "voltage": [110.0]}, index=["l1"])

    out = add_operator_columns(df, osm_tags)

    assert out.loc["l1", "voltage"] == 110.0
    assert "tags" in out.columns


def test_add_operator_columns_requires_tags_column():
    with pytest.raises(ValueError, match="no 'tags' column"):
        add_operator_columns(pd.DataFrame({"voltage": [110.0]}), {})


def test_load_osm_tags_indexes_by_type_and_id(tmp_path):
    payload = {
        "elements": [
            {"type": "way", "id": 1, "tags": {"operator": "APG", "frequency": "50"}},
            {"type": "relation", "id": 2, "tags": {"operator": "ÖBB"}},
            {"type": "way", "id": 3},  # no tags key at all
        ]
    }
    path = tmp_path / "lines_way.json"
    path.write_text(json.dumps(payload))

    tags = load_osm_tags([str(path)])

    assert tags["way/1"] == {"operator": "APG", "frequency": "50"}
    assert tags["relation/2"] == {"operator": "ÖBB", "frequency": None}
    assert tags["way/3"] == {"operator": None, "frequency": None}


def test_load_osm_tags_merges_multiple_files(tmp_path):
    for name, ident in (("lines_way.json", 1), ("cables_way.json", 2)):
        (tmp_path / name).write_text(
            json.dumps({"elements": [{"type": "way", "id": ident, "tags": {}}]})
        )

    tags = load_osm_tags(
        [str(tmp_path / "lines_way.json"), str(tmp_path / "cables_way.json")]
    )

    assert set(tags) == {"way/1", "way/2"}


def test_drop_cross_border_lines_lv_removes_only_low_voltage_crossings():
    buses = pd.DataFrame({"country": ["AT", "AT", "DE"]}, index=["at0", "at1", "de0"])
    lines = pd.DataFrame(
        {
            "bus0": ["at0", "at0", "at0"],
            "bus1": ["at1", "de0", "de0"],
            "voltage": [110.0, 110.0, 380.0],
        },
        index=["domestic", "crossing_lv", "crossing_hv"],
    )

    out = drop_cross_border_lines_lv(lines, buses, max_voltage=220.0)

    assert out.index.tolist() == ["domestic", "crossing_hv"]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("APG", "APG"),  # spelled exactly like its own alias
        ("Netz NÖ", "Netz NÖ"),
        ("Wien Energie GmbH", "Wien Energie"),
        ("Ikb AG", "IKB"),
    ],
)
def test_match_operator_alias_reports_a_hit(raw, expected):
    """A value identical to its alias must count as matched, not as unlisted."""
    assert match_operator_alias(raw) == expected


def test_match_operator_alias_returns_none_when_unlisted():
    assert match_operator_alias("Some Unlisted Grid GmbH") is None


def test_wien_energie_is_not_wiener_netze():
    """Supplier and DNO are separate entities and must not collapse."""
    assert canonical_operator("Wien Energie GmbH") == "Wien Energie"
    assert canonical_operator("Wiener Netze GmbH") == "Wiener Netze"


@pytest.mark.parametrize(
    ("operator_clean", "tag_frequency", "expected"),
    [
        ("ÖBB-Infrastruktur", "16.7", True),
        (None, "16.7", True),  # frequency alone is decisive
        ("ÖBB-Infrastruktur", "16.67", True),  # occasional OSM spelling
        ("ÖBB-Infrastruktur", None, True),  # ÖBB without a frequency tag
        ("ÖBB-Infrastruktur", "50", False),  # ÖBB's public-grid feeds stay
        ("APG", "50", False),
        ("APG", None, False),
        ("Netz OÖ", "0", False),  # DC is not traction
        ("ÖBB-Infrastruktur | APG", "16.7 | 50", False),  # explicit 50 Hz wins
    ],
)
def test_is_traction(operator_clean, tag_frequency, expected):
    assert is_traction(operator_clean, tag_frequency) is expected


def test_parse_frequencies_handles_joined_and_invalid_values():
    assert parse_frequencies("16.7 | 50") == {16.7, 50.0}
    assert parse_frequencies("50") == {50.0}
    assert parse_frequencies(None) == set()
    assert parse_frequencies("") == set()


def test_drop_traction_lines_removes_only_traction():
    lines = pd.DataFrame(
        {
            "operator_clean": ["ÖBB-Infrastruktur", "ÖBB-Infrastruktur", "APG"],
            "tag_frequency": ["16.7", "50", None],
        },
        index=["traction", "oebb_public", "tso"],
    )

    out = drop_traction_lines(lines)

    assert out.index.tolist() == ["oebb_public", "tso"]


def test_drop_traction_lines_requires_recovered_columns():
    with pytest.raises(ValueError, match="add_operator_columns"):
        drop_traction_lines(pd.DataFrame({"voltage": [110.0]}))
