# SPDX-FileCopyrightText: 2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""Tests for the Anlagenregister retrieve and build scripts."""

import pandas as pd
import pytest
from build_anlagenregister_at import (
    add_first_feedin_year,
    aggregate_to_nuts3,
    clean_plz,
    load_postal_to_nuts,
    map_plants_to_nuts3,
)
from retrieve_anlagenregister_at import (
    BUNDESLAND_CODES,
    QUERIES,
    RAW_COLUMNS,
    parse_reference_year,
    rename_feedin_columns,
    rows_to_frame,
)

LANDING_SNIPPET = """
    sum2021Gas: "Eingespeistes Gas (kWh)" + " " + 2026,
    engpassStrom: "Engpassleistung (kW <sub>el</sub>)",
    sum2021Strom: "Eingespeister Strom (kWh)" + " " + 2026,
    sum2020Strom: "Eingespeister Strom (kWh)" + " " + 2025,
"""

API_ROW = {
    "ID": 0,
    "AnlPlz": "6890",
    "AnlOrt": "Lustenau",
    "TechCode": None,
    "Bundesland": "V",
    "Kontaktdaten": None,
    "Typ": None,
    "Energietraeger": "Erneuerbare Gase",
    "Inbetriebnahme": None,
    "Anlagenbetreiber": None,
    "Engpassleistung": 5000.0,
    "Jahressumme_Minus_1": 0.0,
    "Jahressumme_Minus_2": 0.0,
    "Jahressumme_Minus_3": 0.0,
    "Jahressumme_Minus_4": 8711157.0,
    "Jahressumme_Minus_5": 9445873.0,
    "Jahressumme_Minus_6": 0.0,
}


# ---------------------------------------------------------------------------
# retrieve
# ---------------------------------------------------------------------------


def test_parse_reference_year():
    assert parse_reference_year(LANDING_SNIPPET) == 2026


def test_parse_reference_year_missing():
    with pytest.raises(ValueError, match="reference year"):
        parse_reference_year("<html></html>")


def test_rows_to_frame_keeps_raw_columns_and_labels():
    df = rows_to_frame([API_ROW], "Gas", "V")
    assert list(df.columns) == ["typ", *RAW_COLUMNS]
    assert "Kontaktdaten" not in df.columns
    assert df.loc[0, "typ"] == "Gas"
    assert df.loc[0, "Bundesland"] == "V"


def test_rows_to_frame_keeps_api_bundesland_for_all_austria_query():
    rows = [{**API_ROW, "Bundesland": "NO"}, {**API_ROW, "Bundesland": "T"}]
    df = rows_to_frame(rows, "Gas", "")
    assert df["Bundesland"].tolist() == ["NO", "T"]


def test_queries_cover_strom_per_bundesland_and_gas_once():
    assert QUERIES["Strom"] == list(BUNDESLAND_CODES)
    assert QUERIES["Gas"] == [""]


def test_rows_to_frame_empty():
    df = rows_to_frame([], "Strom", "W")
    assert df.empty
    assert list(df.columns) == ["typ", *RAW_COLUMNS]


def test_rename_feedin_columns():
    df = rename_feedin_columns(rows_to_frame([API_ROW], "Gas", "V"), 2026)
    assert "feedin_kwh_2026" in df.columns
    assert "feedin_kwh_2021" in df.columns
    assert "Jahressumme_Minus_1" not in df.columns
    assert df.loc[0, "feedin_kwh_2023"] == 8711157.0
    assert df.loc[0, "engpassleistung_kw"] == 5000.0
    assert df.loc[0, "plz"] == "6890"


# ---------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------


@pytest.fixture
def plants() -> pd.DataFrame:
    years = range(2021, 2027)
    base = {
        "reference_year": 2026,
        "typ": ["Strom", "Strom", "Strom", "Gas"],
        "id": [0, 1, 2, 0],
        "plz": ["6890", "6890", "7540", "6890"],
        "ort": ["Lustenau", "Lustenau", "Güssing", "Lustenau"],
        "bundesland": ["V", "V", "B", "V"],
        "techcode": ["Photovoltaik", "Photovoltaik", "Biogas", None],
        "energietraeger": [None, None, None, "Erneuerbare Gase"],
        "inbetriebnahme": [None] * 4,
        "engpassleistung_kw": [10.0, 20.0, 500.0, 5000.0],
    }
    feedin = {
        # pv 1: feed-in since 2024, pv 2: never, biogas: whole window, gas: 2022-2023
        "feedin_kwh_2021": [0, 0, 1e6, 0],
        "feedin_kwh_2022": [0, 0, 1e6, 9e6],
        "feedin_kwh_2023": [0, 0, 1e6, 8e6],
        "feedin_kwh_2024": [1e4, 0, 1e6, 0],
        "feedin_kwh_2025": [1e4, 0, 1e6, 0],
        "feedin_kwh_2026": [5e3, 0, 5e5, 0],
    }
    assert list(feedin) == [f"feedin_kwh_{y}" for y in years]
    return pd.DataFrame({**base, **feedin})


@pytest.fixture
def postal_to_nuts(tmp_path) -> pd.Series:
    p = tmp_path / "plz.csv"
    p.write_text("NUTS3,CODE\nAT342,6890\nAT113,7540\n")
    return load_postal_to_nuts(p)


def test_load_postal_to_nuts_zero_pads(tmp_path):
    p = tmp_path / "plz.csv"
    p.write_text("NUTS3,CODE\nAT130,1010\nAT342,6890\n")
    s = load_postal_to_nuts(p)
    assert s["1010"] == "AT130"
    assert (s.index.str.len() == 4).all()


def test_add_first_feedin_year(plants):
    out = add_first_feedin_year(plants)
    assert out["first_feedin_year"].dtype == "Int64"
    assert out["first_feedin_year"].tolist()[0] == 2024
    assert pd.isna(out["first_feedin_year"].iloc[1])
    assert out["first_feedin_year"].tolist()[2] == 2021  # lower bound only
    assert out["first_feedin_year"].tolist()[3] == 2022


def test_map_plants_to_nuts3(plants, postal_to_nuts):
    out = map_plants_to_nuts3(plants, postal_to_nuts)
    assert out["nuts3"].tolist() == ["AT342", "AT342", "AT113", "AT342"]


def test_map_plants_to_nuts3_drops_small_unmapped_share(plants, postal_to_nuts):
    plants.loc[0, "plz"] = "9999"  # 10 kW of 5530 kW
    out = map_plants_to_nuts3(plants, postal_to_nuts, max_unmapped_share=0.01)
    assert len(out) == 3
    assert 0 not in out.index


def test_map_plants_to_nuts3_large_unmapped_share_raises(plants, postal_to_nuts):
    plants.loc[3, "plz"] = "9999"  # the 5 MW gas plant
    with pytest.raises(ValueError, match="9999"):
        map_plants_to_nuts3(plants, postal_to_nuts)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("6890", "6890"),
        ("4600 ", "4600"),
        ("6933,", "6933"),
        ("5431 Kuchl", "5431"),
        ("23253", None),
        ("Scheibbs", None),
        (None, None),
    ],
)
def test_clean_plz(raw, expected):
    result = clean_plz(pd.Series([raw]))[0]
    assert result == expected if expected else pd.isna(result)


def test_aggregate_to_nuts3(plants, postal_to_nuts):
    df = add_first_feedin_year(map_plants_to_nuts3(plants, postal_to_nuts))
    agg = aggregate_to_nuts3(df)

    # the two PVs in AT342 have different first_feedin_year -> separate groups
    assert len(agg) == 4
    pv_2024 = agg[
        (agg["technology"] == "Photovoltaik") & (agg["first_feedin_year"] == 2024)
    ]
    assert pv_2024["capacity_mw"].item() == pytest.approx(0.01)
    assert pv_2024["n_plants"].item() == 1
    assert pv_2024["feedin_gwh_2024"].item() == pytest.approx(1e4 / 1e6)

    pv_never = agg[
        (agg["technology"] == "Photovoltaik") & agg["first_feedin_year"].isna()
    ]
    assert pv_never["capacity_mw"].item() == pytest.approx(0.02)

    gas = agg[agg["typ"] == "Gas"]
    assert gas["technology"].item() == "Erneuerbare Gase"
    assert gas["capacity_mw"].item() == pytest.approx(5.0)

    assert not any(c.startswith("feedin_kwh_") for c in agg.columns)
    assert agg["capacity_mw"].sum() == pytest.approx(5.53)
