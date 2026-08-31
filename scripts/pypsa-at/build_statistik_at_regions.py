# SPDX-FileCopyrightText: 2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""Build a general Austrian municipality and regional register CSV."""

from pathlib import Path

import geopandas as gpd
import pandas as pd
from snakemake.script import Snakemake

from scripts._helpers import configure_logging, set_scenario_config

OUTPUT_COLUMNS = [
    "federal_state_code",
    "federal_state",
    "nuts2_code",
    "nuts3_code",
    "nuts3_name",
    "district_code",
    "district_name",
    "district_name_judicial",
    "municipality_code",
    "municipality_name",
    "postal_code",
    "population",
]


def read_municipalities(path: str | Path) -> pd.DataFrame:
    """
    Read municipality-level records from a Statistik Austria register.

    Parameters
    ----------
    path
        Path to a ``RegGemVz`` ODS workbook.

    Returns
    -------
    :
        Municipality records with English, machine-readable column names.
    """
    source = pd.read_excel(path, sheet_name="Gemeinden", engine="odf")
    source = source.ffill()[
        ~(
            source["Gerichtsbezirks kennziffer"].isna()
            | source["Gerichtsbezirks kennziffer"].str.contains(",")
        )
    ]
    source = source.rename(
        columns={
            "Bundeslandkennziffer": "federal_state_code",
            "Bundesland": "federal_state",
            "NUTS3-Code": "nuts3_code",
            "NUTS3": "nuts3_name",
            "Kennziffer Bezirk": "district_code",
            "Name Bezirk": "district_name",
            "Gerichtsbezirksname": "district_name_judicial",
            "Gemeinde kennziffer": "municipality_code",
            "Gemeindename": "municipality_name",
            "PLZ Gemeindeamt": "postal_code",
            "Bevölkerungszahl 01.01.2025": "population",
        }
    )
    source["population"] = pd.to_numeric(source["population"], errors="raise")
    return source


def add_nuts2_code(
    municipalities: pd.DataFrame, nuts3_shapes: str | Path
) -> pd.DataFrame:
    """
    Add the model-compatible NUTS2 code from the final NUTS3 shapes.

    Parameters
    ----------
    municipalities
        Municipality records containing ``nuts3_code``.
    nuts3_shapes
        Final project NUTS3 GeoJSON. Its ``level2`` column contains the
        model-compatible NUTS2 assignment.

    Returns
    -------
    :
        Municipality records with a validated ``nuts2_code`` column.
    """
    shapes = gpd.read_file(nuts3_shapes)[["level3", "level2"]].rename(
        columns={"level3": "nuts3_code", "level2": "nuts2_code"}
    )
    result = municipalities.merge(
        shapes.drop_duplicates(),
        on="nuts3_code",
        how="left",
    )
    if result["nuts2_code"].isna().any():
        missing = sorted(result.loc[result["nuts2_code"].isna(), "nuts3_code"].unique())
        raise ValueError(f"Missing NUTS2 assignments for NUTS3 codes: {missing}")
    return result


def main(snakemake: Snakemake) -> None:
    """
    Build the general regional register CSV.

    Parameters
    ----------
    snakemake
        The Snakemake workflow object providing inputs, params, and config.

    Returns
    -------
    :
        Result is written to the snakemake output
    """
    base_year = snakemake.params.planning_horizons[0]
    if base_year != 2025:
        raise NotImplementedError(
            f"Base year {base_year} is not supported: the Statistik Austria "
            "register is read with the hardcoded population column "
            "'Bevölkerungszahl 01.01.2025', which is only valid for base "
            "year 2025."
        )
    municipalities = read_municipalities(snakemake.input.ods)
    result = add_nuts2_code(municipalities, snakemake.input.nuts3_shapes)
    result[OUTPUT_COLUMNS].to_csv(snakemake.output.regional_data, index=False)


if __name__ == "__main__":
    if "snakemake" not in globals():
        from scripts._helpers import mock_snakemake

        snakemake = mock_snakemake("build_statistik_at_regions")
    configure_logging(snakemake)
    set_scenario_config(snakemake)
    main(snakemake)
