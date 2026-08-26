# SPDX-FileCopyrightText: 2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""Tests for the NEA industry-demand preparation script."""

import importlib

import pandas as pd
import pytest

bni = importlib.import_module("scripts.pypsa-at.build_nea_industry_demand")


@pytest.fixture
def nea():
    return pd.DataFrame(
        [
            {
                "NUTS-2 Code": "AT11",
                "year": 2024,
                "Kategorie": "Produzierender Bereich",
                "Bereich": "Chemie und Petrochemie",
                "Nutzenergiekategorie": "Standmotoren",
                "Energieträger": "Elektrische Energie",
                "value_TWh": 10,
            },
            {
                "NUTS-2 Code": "AT11",
                "year": 2024,
                "Kategorie": "Produzierender Bereich",
                "Bereich": "Bau",
                "Nutzenergiekategorie": "Standmotoren",
                "Energieträger": "Elektrische Energie",
                "value_TWh": 8,
            },
            {
                "NUTS-2 Code": "AT13",
                "year": 2024,
                "Kategorie": "Sonstige Wirtschaftsbereiche",
                "Bereich": "Private Haushalte",
                "Nutzenergiekategorie": "Standmotoren",
                "Energieträger": "Elektrische Energie",
                "value_TWh": 100,
            },
            {
                "NUTS-2 Code": "AT13",
                "year": 2024,
                "Kategorie": "Produzierender Bereich",
                "Bereich": "Private Haushalte",
                "Nutzenergiekategorie": "Standmotoren",
                "Energieträger": "Erdgas",
                "value_TWh": 100,
            },
        ]
    )


@pytest.fixture
def distribution_keys():
    return pd.DataFrame(
        {
            "Chemical industry": [3, 1, 0, 0],
            "population": [1, 3, 2, 2],
            "Other non-classified": [1, 3, 2, 2],
        },
        index=["AT111", "AT112", "AT131", "AT132"],
    )


@pytest.fixture
def expected():
    return pd.DataFrame(
        {
            "year": 2025,
            "region": ["AT111", "AT112", "AT131", "AT132"],
            "sector": "industry",
            "carrier": ["electricity", "electricity", "methane", "methane"],
            "value_TWh": [9.5, 8.5, 50, 50],
        }
    )


def test_build_demand_uses_source_year_proxy_and_conserves_parent_totals(
    nea, distribution_keys, expected
):
    """Use sector keys and population fallback while conserving parent totals."""

    result = bni.build_demand(
        nea,
        distribution_keys,
        [2025],
        {2025: 2024},
        "Produzierender Bereich",
    )

    pd.testing.assert_frame_equal(result, expected)
