import importlib

import pandas as pd

module = importlib.import_module("scripts.pypsa-at.recalibrate_heat_demand_at")
recalibrate = module.recalibrate_heat_demand
allocate = module.allocate_heat_demand
redistribute = module.redistribute_central_heat


def test_recalibrate_heat_demand_matches_nea_by_nuts2():
    heat_demand = pd.DataFrame(
        {
            "region": ["AT111", "AT112", "AT111", "AT112"],
            "year": [2025, 2025, 2030, 2030],
            "value": [100.0, 300.0, 120.0, 280.0],
        }
    )
    nea = pd.DataFrame(
        {
            "NUTS-2 Code": ["AT11", "AT11"],
            "year": [2024, 2024],
            "Bereich": ["Private Haushalte"] * 2,
            "Nutzenergiekategorie": ["Raumklima und Warmwasser"] * 2,
            "Energieträger": ["Fernwärme", "Erdgas"],
            "value_TWh": [0.1, 0.3],
        }
    )

    result = recalibrate(
        nea,
        heat_demand,
        pd.Series({"AT111": "AT11", "AT112": "AT11"}),
        {2025: 2024},
    )

    expected = pd.DataFrame(
        {
            "year": [2025] * 4 + [2030] * 4,
            "NUTS-2 Code": ["AT11"] * 8,
            "region": ["AT111", "AT111", "AT112", "AT112"] * 2,
            "sector": ["households"] * 8,
            "heating": ["central", "decentral"] * 4,
            "value": [
                25000.0,
                75000.0,
                75000.0,
                225000.0,
                30000.0,
                90000.0,
                70000.0,
                210000.0,
            ],
        }
    )

    pd.testing.assert_frame_equal(result.reset_index(drop=True), expected)


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
    urban_fraction = pd.DataFrame(
        {
            "year": [2025, 2025],
            "region": ["AT111", "AT111"],
            "sector": ["households", "services"],
            "urban_fraction": [0.6, 0.6],
        }
    )

    result = allocate(demand, urban_fraction, 2025)

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


def test_redistribute_central_heat_by_urban_weighted_demand():
    demand = pd.DataFrame(
        {
            "year": [2025] * 8,
            "NUTS-2 Code": ["AT11"] * 4 + ["AT12"] * 4,
            "region": [
                "AT111",
                "AT111",
                "AT112",
                "AT112",
                "AT121",
                "AT121",
                "AT122",
                "AT122",
            ],
            "sector": ["households"] * 8,
            "heating": ["central", "decentral"] * 4,
            "value": [10.0, 90.0, 20.0, 80.0, 5.0, 95.0, 25.0, 175.0],
        }
    )

    result, urban_fraction = redistribute(
        demand,
        pd.DataFrame(
            {2025: [0.5, 0.0, 0.0, 0.0]},
            index=["AT111", "AT112", "AT121", "AT122"],
        ),
        pd.Series(
            {
                "AT111": "AT11",
                "AT112": "AT11",
                "AT121": "AT12",
                "AT122": "AT12",
            }
        ),
    )

    central = result[result["heating"].eq("central")].set_index("region")["value"]
    pd.testing.assert_series_equal(
        central,
        pd.Series(
            {"AT111": 30.0, "AT112": 0.0, "AT121": 10.0, "AT122": 20.0},
            name="value",
        ).rename_axis("region"),
    )
    expected_urban_fraction = pd.DataFrame(
        {
            "sector": ["households"] * 4,
            "year": [2025] * 4,
            "region": ["AT111", "AT112", "AT121", "AT122"],
            "urban_fraction": [0.5, 0.0, 0.1, 0.1],
        }
    )
    pd.testing.assert_frame_equal(
        urban_fraction.reset_index(drop=True), expected_urban_fraction
    )
    assert result.groupby(["region", "sector"]).value.sum().to_dict() == {
        ("AT111", "households"): 100.0,
        ("AT112", "households"): 100.0,
        ("AT121", "households"): 100.0,
        ("AT122", "households"): 200.0,
    }
