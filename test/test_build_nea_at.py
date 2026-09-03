import build_nea_at as bna
import pandas as pd
import pytest

CATEGORIES = [
    "Raumheizung und Klimaanlagen",
    "Dampferzeugung",
    "Industrieöfen",
    "Standmotoren",
    "Traktion",
    "Beleuchtung und EDV",
    "Elektrochemische Zwecke",
]


@pytest.fixture
def input_dataframe():
    header = [
        "Energieträger",
        *CATEGORIES,
        "Nutzenergiekategorien insgesamt",
    ]
    blank = [None] * 8
    footer = ["Fußzeile", *blank]

    return pd.DataFrame(
        [
            ["Wirtschaftsbereiche insgesamt", *blank],
            header,
            ["Kohle", *([3600] * 7), 25200],
            footer,
            footer,
            ["Eisen- und Stahlerzeugung", *blank],
            header,
            ["Strom", 3600, 7200, 10800, 14400, 18000, 21600, 25200, 100800],
            ["Erdgas", ".", 1800, 3600, 5400, 7200, 9000, 10800, 37800],
            ["Sonstige ET", *([3600] * 7), 25200],
            ["Energieträger insgesamt", *([3600] * 7), 25200],
            ["Anteil der Nutzenergiekategorie in %", *([10] * 7), 70],
            footer,
            ["Eisenbahn", *blank],
            header,
            ["Diesel", 7200, 14400, 21600, 28800, 36000, 43200, 50400, 201600],
            ["Strom", 3600, 7200, 10800, 14400, 18000, 21600, 25200, 100800],
            ["Sonstige ET", *([3600] * 7), 25200],
            ["Energieträger insgesamt", *([3600] * 7), 25200],
            ["Anteil der Nutzenergiekategorie in %", *([10] * 7), 70],
            footer,
            footer,
        ]
    )


@pytest.fixture
def workbook(tmp_path, input_dataframe):
    path = tmp_path / "nea.ods"

    with pd.ExcelWriter(path, engine="odf") as writer:
        pd.DataFrame([["Must be skipped"]]).to_excel(
            writer,
            sheet_name="Deckblatt",
            header=False,
            index=False,
        )
        input_dataframe.to_excel(
            writer,
            sheet_name="NEA_2020",
            header=False,
            index=False,
        )

    return path


@pytest.fixture
def expected_dataframe():
    sectors = [
        (
            "Eisen- und Stahlerzeugung",
            "Produzierender Bereich",
            {
                "Strom": [1, 2, 3, 4, 5, 6, 7],
                "Erdgas": [0, 0.5, 1, 1.5, 2, 2.5, 3],
            },
        ),
        (
            "Eisenbahn",
            "Transport",
            {
                "Diesel": [2, 4, 6, 8, 10, 12, 14],
                "Strom": [1, 2, 3, 4, 5, 6, 7],
            },
        ),
    ]

    return pd.DataFrame(
        [
            {
                "Bundesland": "Wien",
                "NUTS-2 Code": "AT13",
                "year": 2020,
                "Kategorie": category,
                "Bereich": sector,
                "Nutzenergiekategorie": useful_energy_category,
                "Energieträger": carrier,
                "value_TWh": values[category_index],
            }
            for sector, category, carriers in sectors
            for category_index, useful_energy_category in enumerate(CATEGORIES)
            for carrier, values in carriers.items()
        ]
    )


def test_read_workbook_end_to_end(workbook, expected_dataframe):
    result = pd.concat(bna.read_workbook(workbook, "Wien"), ignore_index=True)

    pd.testing.assert_frame_equal(result, expected_dataframe)
