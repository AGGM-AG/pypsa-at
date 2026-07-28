# SPDX-FileCopyrightText: 2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
import logging
import re
import tempfile

import pandas as pd
from odf import teletype
from odf.opendocument import load
from odf.table import Table, TableCell
from snakemake.script import Snakemake

from mods.constants import NUTS2_CODES, TJ_PER_TWH
from scripts._helpers import configure_logging, set_scenario_config

logger = logging.getLogger(__name__)


# =============================================================================
# Configuration
# =============================================================================

REMOVE_COLUMNS = ["Nutzenergiekategorien insgesamt"]

REMOVE_ROWS = [
    "Sonstige ET",
    "Energieträger insgesamt",
    "Anteil der Nutzenergiekategorie in %",
]

SKIP_SECTORS = [
    "Wirtschaftsbereiche insgesamt",
    "Produzierender Bereich insgesamt",
    "Transport insgesamt",
    "Sonstige Wirtschaftsbereiche insgesamt",
]

SECTOR_TO_CATEGORY = {
    "Eisen- und Stahlerzeugung": "Produzierender Bereich",
    "Chemie und Petrochemie": "Produzierender Bereich",
    "Nicht-Eisen Metalle": "Produzierender Bereich",
    "Steine und Erden, Glas": "Produzierender Bereich",
    "Fahrzeugbau": "Produzierender Bereich",
    "Maschinenbau": "Produzierender Bereich",
    "Bergbau": "Produzierender Bereich",
    "Nahrungs- und Genußmittel, Tabak": "Produzierender Bereich",
    "Papier und Druck": "Produzierender Bereich",
    "Holzverarbeitung": "Produzierender Bereich",
    "Bau": "Produzierender Bereich",
    "Textil und Leder": "Produzierender Bereich",
    "Sonst. Produzierender Bereich": "Produzierender Bereich",
    "Eisenbahn": "Transport",
    "Sonstiger Landverkehr": "Transport",
    "Transport in Rohrfernleitungen": "Transport",
    "Binnenschiffahrt": "Transport",
    "Flugverkehr": "Transport",
    "Offentliche und Private Dienstleistungen": "Sonstige Wirtschaftsbereiche",
    "Private Haushalte": "Sonstige Wirtschaftsbereiche",
    "Landwirtschaft": "Sonstige Wirtschaftsbereiche",
}


# =============================================================================
# Small helper functions
# =============================================================================


def clean_text(value):
    if pd.isna(value):
        return ""

    value = str(value).replace("\n", " ")
    value = re.sub(r"\s+", " ", value).strip()
    value = re.sub(r"\s*([<>])\s*", r"\1", value)
    value = value.replace("° C", "°C")
    value = "0" if value == "." or value == "-" else value

    return value


def find_sector(table, header_row):
    """Get the sector"""
    title_row = header_row - 1
    value = table.iloc[title_row]
    return clean_text(value[0])


def clean_ods_errors(input_path, output_path):
    """
    Cleans file of DIV/0 errors

    Parameters
    ----------
    input_path
    output_path

    """
    doc = load(input_path)

    for table in doc.spreadsheet.getElementsByType(Table):
        for cell in table.getElementsByType(TableCell):
            if cell.getAttribute("valuetype") == "error":
                value = (
                    cell.getAttribute("stringvalue")
                    or teletype.extractText(cell)
                    or "#ERROR"
                )

                cell.setAttribute("valuetype", "string")
                cell.setAttribute("stringvalue", value)
                cell.setAttribute("value", None)

    doc.save(output_path)


# =============================================================================
# Read one workbook
# =============================================================================


def read_workbook(path, bundesland):

    with tempfile.NamedTemporaryFile(suffix=".ods") as tmp:
        clean_ods_errors(path, tmp.name)

        sheets = pd.read_excel(
            tmp.name,
            engine="odf",
            sheet_name=[f"NEA_{year}" for year in range(2005, 2025)],
            header=None,
            usecols="A:I",
        )

    workbook_data = []
    for sheet_name, table in sheets.items():
        year = int(sheet_name[4:])
        table = table.apply(lambda column: column.map(clean_text))

        # Find header rows
        header_rows = table.index[
            table.apply(
                lambda row: row.eq("Energieträger").any(),
                axis=1,
            )
        ].tolist()

        for position, header_row in enumerate(header_rows):
            next_header_row = (
                header_rows[position + 1]
                if position + 1 < len(header_rows)
                else len(table)
            )

            sector = find_sector(table, header_row)

            # Skip all aggregate Bereiche
            if sector in SKIP_SECTORS:
                continue

            category = SECTOR_TO_CATEGORY[sector]

            header = table.iloc[header_row]
            header_columns = header[~header.isin(REMOVE_COLUMNS)]

            block = table.iloc[
                header_row + 1 : next_header_row - 2,
                header_columns.index,
            ].copy()

            block.columns = header_columns

            # Convert the wide table into stacked format
            block = block.melt(
                id_vars="Energieträger",
                var_name="Nutzenergiekategorie",
                value_name="value_TJ",
            )

            # Keep only individual carriers from the configured list
            block = block[~block["Energieträger"].isin(REMOVE_ROWS)]

            block["value_TJ"] = pd.to_numeric(block["value_TJ"], errors="coerce")

            block["Bundesland"] = bundesland
            block["NUTS-2 Code"] = NUTS2_CODES[bundesland]
            block["year"] = year
            block["Bereich"] = sector
            block["Kategorie"] = category
            block["value_TWh"] = block["value_TJ"] / TJ_PER_TWH

            workbook_data.append(
                block[
                    [
                        "Bundesland",
                        "NUTS-2 Code",
                        "year",
                        "Kategorie",
                        "Bereich",
                        "Nutzenergiekategorie",
                        "Energieträger",
                        "value_TWh",
                    ]
                ]
            )

    return workbook_data


def main(snakemake: Snakemake) -> None:
    records = []

    for bundesland, path in snakemake.input.items():
        records.append(
            read_workbook(
                path=path,
                bundesland=bundesland,
            )
        )

    result = pd.concat(records, ignore_index=True).sort_values(
        [
            "Bundesland",
            "year",
            "Kategorie",
            "Bereich",
            "Energieträger",
            "Nutzenergiekategorie",
        ]
    )

    result.to_csv(
        snakemake.output.nea_at,
        index=False,
    )
    logging.info(
        f"Wrote combined NEA at file to {snakemake.output.nea_at}",
    )


if __name__ == "__main__":
    if "snakemake" not in globals():
        from scripts._helpers import mock_snakemake

        snakemake = mock_snakemake("build_nea_at")

    configure_logging(snakemake)
    set_scenario_config(snakemake)
    main(snakemake)
