import importlib

import pandas as pd

recalibrate = importlib.import_module(
    "scripts.pypsa-at.recalibrate_heat_demand_at"
).recalibrate_heat_demand
allocate = importlib.import_module(
    "scripts.pypsa-at.recalibrate_heat_demand_at"
).allocate_heat_demand


def test_recalibrate_heat_demand_matches_nea_by_nuts2():
    heat_demand = pd.DataFrame(
        {
            "region": ["AT111", "AT112", "AT121", "AT111", "AT112", "AT121"],
            "year": [2025, 2025, 2025, 2030, 2030, 2030],
            "value": [100.0, 300.0, 200.0, 120.0, 280.0, 220.0],
        }
    )
    nea = pd.DataFrame(
        {
            "NUTS-2 Code": ["AT11"] * 4 + ["AT12"] * 4,
            "year": [2023] * 8,
            "Bereich": [
                "Private Haushalte",
                "Private Haushalte",
                "Offentliche und Private Dienstleistungen",
                "Offentliche und Private Dienstleistungen",
            ]
            * 2,
            "Nutzenergiekategorie": ["Raumklima und Warmwasser"] * 8,
            "Energieträger": ["Fernwärme", "Erdgas", "Fernwärme", "Erdgas"] * 2,
            "value_TWh": [0.1, 0.3, 0.05, 0.15, 0.2, 0.4, 0.1, 0.2],
        }
    )
    result = recalibrate(
        nea,
        heat_demand,
        pd.Series({"AT111": "AT11", "AT112": "AT11", "AT121": "AT12"}),
        {2025: 2023},
    )

    expected = pd.DataFrame(
        {
            "year": [2025] * 12 + [2030] * 12,
            "region": (["AT111"] * 4 + ["AT112"] * 4 + ["AT121"] * 4) * 2,
            "sector": (["households"] * 2 + ["services"] * 2) * 6,
            "heating": ["central", "decentral"] * 12,
            "value": [
                25000.0,
                75000.0,
                12500.0,
                37500.0,
                75000.0,
                225000.0,
                37500.0,
                112500.0,
                200000.0,
                400000.0,
                100000.0,
                200000.0,
                30000.0,
                90000.0,
                15000.0,
                45000.0,
                70000.0,
                210000.0,
                35000.0,
                105000.0,
                220000.0,
                440000.0,
                110000.0,
                220000.0,
            ],
        }
    )
    pd.testing.assert_frame_equal(result, expected)


def test_allocate_heat_demand_to_carriers():
    demand = pd.DataFrame(
        {
            "year": [2025] * 4,
            "region": ["AT111"] * 4,
            "sector": ["households", "households", "services", "services"],
            "heating": ["central", "decentral"] * 2,
            "value": [10.0, 20.0, 30.0, 40.0],
        }
    )
    urban_fraction = pd.DataFrame({2025: [0.6]}, index=["AT111"])

    result = allocate(demand, urban_fraction)

    expected = pd.DataFrame(
        {
            "year": [2025] * 5,
            "region": ["AT111"] * 5,
            "carrier": [
                "residential rural heat",
                "residential urban decentral heat",
                "services rural heat",
                "services urban decentral heat",
                "urban central heat",
            ],
            "value": [8.0, 12.0, 16.0, 24.0, 40.0],
        }
    )

    pd.testing.assert_frame_equal(result.reset_index(drop=True), expected)


def test_allocate_heat_demand_clusters_heat_buses():
    demand = pd.DataFrame(
        {
            "year": [2025] * 4,
            "region": ["AT111"] * 4,
            "sector": ["households", "households", "services", "services"],
            "heating": ["central", "decentral"] * 2,
            "value": [10.0, 20.0, 30.0, 40.0],
        }
    )

    result = allocate(demand, pd.DataFrame({2025: [0.6]}, index=["AT111"]), True)

    expected = pd.DataFrame(
        {
            "year": [2025] * 3,
            "region": ["AT111"] * 3,
            "carrier": ["rural heat", "urban central heat", "urban decentral heat"],
            "value": [24.0, 40.0, 36.0],
        }
    )

    pd.testing.assert_frame_equal(result.reset_index(drop=True), expected)
