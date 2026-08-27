import importlib
from types import SimpleNamespace

import pandas as pd
import pytest

kfz = importlib.import_module("scripts.pypsa-at.build_kfz_bestand_at")


@pytest.fixture
def source_input():
    vehicle_columns = [
        "Pkw",
        "Lkw",
        "Motorräder",
        "Busse",
        "Zugmaschinen",
        "Anhänger",
        "Mopeds",
        "Sonstige 1",
        "Sonstige 2",
    ]

    districts = [
        "Österreich",
        "Burgenland insgesamt",
        " Wien ",
        "Graz",
        "Post",
        "Bahn",
        "Polizei, Justizwache, Finanzverwaltung",
        "Q: Quelle",
        None,
    ]

    data = {
        "Bundesland und Zulassungsbezirk": districts,
    }

    for column in vehicle_columns:
        data[column] = [
            1000,
            500,
            100,
            300,
            40,
            20,
            40,
            999,
            777,
        ]

    # Also test replacing "-" with zero.
    data["Motorräder"] = [
        1000,
        500,
        "-",
        100,
        10,
        5,
        5,
        999,
        777,
    ]

    return pd.DataFrame(data)


@pytest.fixture
def source_file(tmp_path, source_input):
    path = tmp_path / "vehicle_stock.ods"

    # read_source uses header=1, so the table starts on the second row.
    with pd.ExcelWriter(path, engine="odf") as writer:
        source_input.to_excel(
            writer,
            sheet_name="tab_7",
            index=False,
            startrow=1,
        )

    return path


def test_read_source(source_file):
    expected = pd.DataFrame(
        {
            "Pkw": [125.0, 375.0],
            "Lkw": [125.0, 375.0],
            "Motorräder": [0.0, 120.0],
            "Busse": [125.0, 375.0],
            "Zugmaschinen": [125.0, 375.0],
            "Anhänger": [125.0, 375.0],
            "Mopeds": [125.0, 375.0],
            "Sonstige 1": [125.0, 375.0],
            "Sonstige 2": [125.0, 375.0],
        },
        index=pd.Index(["Wien", "Graz"], name="district"),
    )

    result = kfz.read_source(source_file)

    pd.testing.assert_frame_equal(
        result, expected, check_dtype=False, check_index_type=False
    )


def test_map_special_districts():
    district_mapping = pd.DataFrame(
        {
            "district_name": [
                "Sankt Pölten(Stadt)",
                "Wiener Neustadt(Stadt)",
                "Land,Bregenz",
                "Eisenstadt(Stadt)",
                "Rust(Stadt)",
                "Klosterneuburg",
                "Tulln",
                "Bruck an der Leitha",
                "Leoben",
                "Leoben",
                "Liezen",
                "Liezen",
            ],
            "district_name_judicial": [
                "",
                "",
                "",
                "",
                "",
                "",
                "Klosterneuburg",
                "Schwechat",
                "",
                "",
                "",
                "",
            ],
            "municipality_name": [
                "Municipality A",
                "Municipality B",
                "Municipality C",
                "Eisenstadt",
                "Rust",
                "Klosterneuburg",
                "Municipality D",
                "Municipality E",
                "Leoben",
                "Trofaiach",
                "Gröbming",
                "Altaussee",
            ],
        }
    )

    expected = district_mapping.assign(
        district_vehicles=[
            "St. Pölten (Stadt)",
            "Wr. Neustadt (Stadt)",
            "Bregenz (Bezirk)",
            "Eisenstadt (Stadt inkl. Rust)",
            "Eisenstadt (Stadt inkl. Rust)",
            "Klosterneuburg (BH Tulln)",
            "Klosterneuburg (BH Tulln)",
            "Schwechat",
            "Leoben (Stadt)",
            "Leoben (Land)",
            "Pol. Exp. Gröbming",
            "Bad Aussee (Liezen)",
        ]
    )

    result = kfz._map_special_districts(district_mapping.copy())

    pd.testing.assert_frame_equal(result, expected)


def test_build_district_weights():
    district_mapping = pd.DataFrame(
        {
            "district_vehicles": [
                "District A",
                "District A",
                "District A",
                "District B",
                "District B",
            ],
            "nuts2_code": [
                "AT11",
                "AT11",
                "AT11",
                "AT12",
                "AT21",
            ],
            "nuts3_code": [
                "AT111",
                "AT111",
                "AT112",
                "AT121",
                "AT211",
            ],
            "population": [30, 20, 50, 25, 75],
        }
    )

    expected_nuts3 = pd.DataFrame(
        {
            "district": [
                "District A",
                "District A",
                "District B",
                "District B",
            ],
            "region": [
                "AT111",
                "AT112",
                "AT121",
                "AT211",
            ],
            "weight": [0.5, 0.5, 0.25, 0.75],
        }
    )

    expected_nuts2 = pd.DataFrame(
        {
            "district": [
                "District A",
                "District B",
                "District B",
            ],
            "region": [
                "AT11",
                "AT12",
                "AT21",
            ],
            "weight": [1.0, 0.25, 0.75],
        }
    )

    result_nuts3 = kfz.build_district_weights(
        district_mapping,
        clustering="adm",
    )
    result_nuts2 = kfz.build_district_weights(
        district_mapping,
        clustering="AT10",
    )

    pd.testing.assert_frame_equal(
        result_nuts3,
        expected_nuts3,
    )
    pd.testing.assert_frame_equal(
        result_nuts2,
        expected_nuts2,
    )


def test_build_kfz_data():
    car_stock = pd.DataFrame(
        {
            "district": [
                "District A",
                "District B",
            ],
            "Pkw": [100, 200],
            "Lkw": [10, 20],
        }
    )

    weights = pd.DataFrame(
        {
            "district": [
                "District A",
                "District A",
                "District B",
                "District B",
            ],
            "region": [
                "Region 1",
                "Region 2",
                "Region 1",
                "Region 2",
            ],
            "weight": [0.25, 0.75, 0.5, 0.5],
        }
    )

    expected = pd.DataFrame(
        {
            "Pkw": [125.0, 175.0],
            "Lkw": [12.5, 17.5],
        },
        index=pd.Index(
            ["Region 1", "Region 2"],
            name="region",
        ),
    )

    result = kfz.build_kfz_data(
        car_stock,
        weights,
    )

    pd.testing.assert_frame_equal(result, expected)


def test_transform_transport_data(tmp_path):
    weighted_data = pd.DataFrame(
        {
            "Pkw": [125.0, 175.0],
        },
        index=pd.Index(
            ["AT11", "AT12"],
            name="region",
        ),
    )

    transport_data = pd.DataFrame(
        {
            "country": ["AT", "AT", "DE"],
            "year": [2023, 2022, 2023],
            "number cars": [999.0, 888.0, 500.0],
            "description": [
                "updated",
                "other year",
                "other country",
            ],
        }
    )
    transport_file = tmp_path / "transport_data.csv"
    transport_data.to_csv(transport_file, index=False)

    expected = pd.DataFrame(
        {
            "country": ["AT11", "AT12", "AT", "DE"],
            "year": [2023, 2023, 2022, 2023],
            "number cars": [125.0, 175.0, 888.0, 500.0],
            "description": [
                "updated",
                "updated",
                "other year",
                "other country",
            ],
        }
    )

    result = kfz.transform_transport_data(
        weighted_data,
        transport_file,
        energy_totals_year=2023,
    )

    pd.testing.assert_frame_equal(result, expected)


def test_main(tmp_path, source_file):
    regional_data = pd.DataFrame(
        {
            "district_name": ["Wien", "Graz"],
            "district_name_judicial": ["", ""],
            "municipality_name": ["Wien", "Graz"],
            "nuts2_code": ["AT13", "AT22"],
            "nuts3_code": ["AT130", "AT221"],
            "population": [100, 300],
        }
    )
    regional_file = tmp_path / "regional_data.csv"
    regional_data.to_csv(regional_file, index=False)

    transport_data = pd.DataFrame(
        {
            "country": ["AT"],
            "year": [2023],
            "number cars": [999.0],
            "description": ["cars"],
        }
    )
    transport_input_file = tmp_path / "transport_input.csv"
    transport_data.to_csv(transport_input_file, index=False)

    output_file = tmp_path / "transport_output.csv"

    snakemake = SimpleNamespace(
        input=SimpleNamespace(
            ods=source_file,
            regional_data=regional_file,
            transport_data_in=transport_input_file,
        ),
        params=SimpleNamespace(
            clustering="adm",
            energy_totals_year=2023,
        ),
        output=SimpleNamespace(
            transport_data_out=output_file,
        ),
    )

    expected = pd.DataFrame(
        {
            "country": ["AT130", "AT221"],
            "year": [2023, 2023],
            "number cars": [125.0, 375.0],
            "description": ["cars", "cars"],
        }
    )

    kfz.main(snakemake)
    result = pd.read_csv(output_file)

    pd.testing.assert_frame_equal(result, expected)
