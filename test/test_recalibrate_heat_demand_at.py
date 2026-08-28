import importlib
import json
from types import SimpleNamespace

import pandas as pd

module = importlib.import_module("scripts.pypsa-at.recalibrate_heat_demand_at")
recalibrate = module.recalibrate_heat_demand
allocate = module.allocate_heat_demand
redistribute = module.redistribute_central_heat
main = module.main


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
        2025,
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

    result = allocate(demand, urban_fraction, False)

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


def test_main_writes_recalibrated_heat_demand(tmp_path):
    shapes_path = tmp_path / "nuts3_shapes.geojson"
    nea_path = tmp_path / "nea.csv"
    heat_demand_path = tmp_path / "heat_demand.csv"
    urban_fraction_path = tmp_path / "urban_fraction.csv"
    output_heat_demand_path = tmp_path / "recalibrated_heat_demand.csv"
    output_urban_fraction_path = tmp_path / "urban_fraction_at.csv"

    shapes_path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {
                            "country": "AT",
                            "level3": "AT111",
                        },
                        "geometry": {
                            "type": "Point",
                            "coordinates": [16.0, 48.0],
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    pd.DataFrame(
        {
            "NUTS-2 Code": ["AT11"] * 4,
            "year": [2024] * 4,
            "Bereich": [
                "Private Haushalte",
                "Private Haushalte",
                "Offentliche und Private Dienstleistungen",
                "Offentliche und Private Dienstleistungen",
            ],
            "Nutzenergiekategorie": ["Raumklima und Warmwasser"] * 4,
            "Energieträger": [
                "Fernwärme",
                "Erdgas",
                "Fernwärme",
                "Erdgas",
            ],
            "value_TWh": [0.04, 0.12, 0.06, 0.18],
        }
    ).to_csv(nea_path, index=False)

    pd.DataFrame(
        {
            "region": ["AT111"],
            "year": [2025],
            "value": [400.0],
        }
    ).to_csv(heat_demand_path, index=False)

    pd.DataFrame(
        {"urban fraction": [0.5]},
        index=pd.Index(["AT111"], name="region"),
    ).to_csv(urban_fraction_path)

    snakemake = SimpleNamespace(
        input=SimpleNamespace(
            nuts3_shapes=shapes_path,
            nea_at=nea_path,
            heat_demand=heat_demand_path,
            urban_fraction=[urban_fraction_path],
        ),
        output=SimpleNamespace(
            heat_demand=output_heat_demand_path,
            urban_fraction_at=output_urban_fraction_path,
        ),
        params=SimpleNamespace(
            modify_nuts3_shapes="AT35DE5",
            source_years={2025: 2024},
            planning_horizons=[2025],
            cluster_heat_buses=False,
        ),
    )

    main(snakemake)

    result = pd.read_csv(output_heat_demand_path)
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
            "value": [
                60_000.0,
                60_000.0,
                90_000.0,
                90_000.0,
                100_000.0,
            ],
        }
    )
    pd.testing.assert_frame_equal(result, expected)

    result_urban_fraction = pd.read_csv(
        output_urban_fraction_path,
        index_col=0,
    )
    expected_urban_fraction = pd.DataFrame(
        {"2025": [0.5]},
        index=pd.Index(["AT111"], name="region"),
    )
    pd.testing.assert_frame_equal(
        result_urban_fraction,
        expected_urban_fraction,
    )
