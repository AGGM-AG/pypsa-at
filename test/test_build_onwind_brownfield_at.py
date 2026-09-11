import importlib
from types import SimpleNamespace

import pandas as pd

wind = importlib.import_module("scripts.pypsa-at.build_onwind_brownfield_at")


def test_extrapolate_production():
    source = pd.DataFrame(
        {
            "Jahr": [2001, 2002, 2003],
            "Burgenland in GWh": [20, 31, 34],
        }
    )
    regions = pd.DataFrame({"federal_state": ["Burgenland"], "nuts2_code": ["AT11"]})

    result = wind.extrapolate_production(source, 6, regions, errors="ignore")
    expected = pd.DataFrame(
        {
            "region": ["AT11"] * 6,
            "year": [1998, 1999, 2000, 2001, 2002, 2003],
            "production": [0.0, 0.0, 9.0, 20.0, 31.0, 34.0],
        }
    )
    pd.testing.assert_frame_equal(result, expected)


def test_create_buildup():
    production = pd.DataFrame(
        {
            "region": ["AT11"] * 10,
            "year": [2000, 2001, 2002, 2003, 2004, 2020, 2021, 2022, 2023, 2024],
            "production": [100, 110, 100, 115, 130, 130, 140, 135, 150, 170],
        }
    )

    result = wind.create_buildup(production)
    expected = pd.DataFrame(
        {
            "region": ["AT11", "AT11", "AT11", "AT11"],
            "year": [2000, 2005, 2020, 2025],
            "buildup": [0.0, 40 / 85, 0.0, 45 / 85],
        }
    )
    pd.testing.assert_frame_equal(result, expected)


def test_prepare_potentials():
    potentials = pd.DataFrame(
        {"nuts3": ["AT111", "AT112", "AT333"], "C_current": [10, 20, 5]}
    )

    result_at35 = wind.prepare_potentials(potentials, {"AT": 3})
    result_at10 = wind.prepare_potentials(potentials, {"AT": 2})
    expected_at35 = pd.DataFrame(
        {"region": ["AT111", "AT112", "AT333"], "capacity": [10, 20, 5]}
    )
    expected_at10 = pd.DataFrame({"region": ["AT11", "AT333"], "capacity": [30, 5]})
    pd.testing.assert_frame_equal(result_at35, expected_at35)
    pd.testing.assert_frame_equal(result_at10, expected_at10)


def test_create_brownfield():
    capacities = pd.DataFrame({"region": ["AT11", "AT333"], "capacity": [100.0, 20.0]})
    buildup = pd.DataFrame(
        {
            "region": ["AT11", "AT11", "AT33", "AT33"],
            "year": [2005, 2025, 2005, 2025],
            "buildup": [0.25, 0.75, 0.25, 0.75],
        }
    )

    result = wind.create_brownfield(capacities, buildup)
    expected = pd.DataFrame(
        {
            "region": ["AT11", "AT11", "AT333", "AT333"],
            "year": [2005, 2025, 2005, 2025],
            "capacity": [25.0, 75.0, 5.0, 15.0],
        }
    )
    pd.testing.assert_frame_equal(result, expected)


def test_main(tmp_path):
    wind_file = tmp_path / "wind.xlsx"
    pd.DataFrame(
        {
            "Jahr": [2022, 2023, 2024],
            "Burgenland in GWh": [10, 20, 40],
            "Tirol in GWh": [0, 0, 10],
        }
    ).to_excel(wind_file, sheet_name="Sheet1", index=False)
    potentials_file = tmp_path / "potentials.csv"
    pd.DataFrame({"nuts3": ["AT111", "AT333"], "C_current": [10, 5]}).to_csv(
        potentials_file, index=False
    )
    regions_file = tmp_path / "regions.csv"
    pd.DataFrame(
        {"federal_state": ["Burgenland", "Tirol"], "nuts2_code": ["AT11", "AT33"]}
    ).to_csv(regions_file, index=False)
    costs_file = tmp_path / "costs.csv"
    pd.DataFrame({"technology": ["onwind"], "lifetime": [3]}).to_csv(
        costs_file, index=False
    )
    output_file = tmp_path / "brownfield.csv"
    snakemake = SimpleNamespace(
        input=SimpleNamespace(
            costs=costs_file,
            wind_production=wind_file,
            nuts3_wind=potentials_file,
            at_regions=regions_file,
        ),
        params=SimpleNamespace(admin_levels={"AT": 2}),
        output=SimpleNamespace(wind_brownfield=output_file),
    )

    wind.main(snakemake, errors="ignore")
    result = pd.read_csv(output_file)
    expected = pd.DataFrame(
        {"region": ["AT11", "AT333"], "year": [2025, 2025], "capacity": [10.0, 5.0]}
    )
    pd.testing.assert_frame_equal(result, expected)
