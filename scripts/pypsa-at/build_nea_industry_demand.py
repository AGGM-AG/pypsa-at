# SPDX-FileCopyrightText: 2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""Build model-region industry totals from the NEA dataset."""

import logging

import pandas as pd
from snakemake.script import Snakemake

from scripts._helpers import configure_logging, set_scenario_config

logger = logging.getLogger(__name__)

# Possible Keys:
#       'Iron and steel', 'Cement', 'Refineries', 'Paper and printing',
#       'Chemical industry', 'Glass', 'Non-ferrous metals',
#       'Non-metallic mineral products', 'Other non-classified', 'population',
#       'EAF', 'DRI + EAF', 'Integrated steelworks', 'Ammonia'

SECTOR_DISTRIBUTION_KEYS = {
    "Eisen- und Stahlerzeugung": "Iron and steel",
    "Chemie und Petrochemie": "Chemical industry",
    "Nicht-Eisen Metalle": "Non-ferrous metals",
    "Papier und Druck": "Paper and printing",
    "Bau": "Other non-classified",
    "Bergbau": "Other non-classified",
    "Fahrzeugbau": "Other non-classified",
    "Holzverarbeitung": "Other non-classified",
    "Maschinenbau": "Other non-classified",
    "Nahrungs- und Genußmittel, Tabak": "Other non-classified",
    "Sonst. Produzierender Bereich": "Other non-classified",
    "Steine und Erden, Glas": "Other non-classified",
    "Textil und Leder": "Other non-classified",
}

CARRIER_MAPPING = {
    "Elektrische Energie": "electricity",
    "Strom": "electricity",
    "Erdgas": "methane",
    "Gichtgas": "methane",
    "Kokereigas": "methane",
    "Wasserstoff": "hydrogen",
    "Biogene Brenn- und Treibstoffe": "solid biomass",
    "Scheitholz": "solid biomass",
    "Brennbare Abfälle": "solid biomass",
    "Fernwärme": "low-temperature heat",
    "Umgebungswärme etc.": "low-temperature heat",
    "Steinkohle": "coal",
    "Braunkohle": "coal",
    "Brenntorf": "coal",
    "Petrolkoks": "coal",
    "Koks": "coke",
    "Benzin": "naphtha",
    "Diesel": "naphtha",
    "Flüssiggas": "naphtha",
    "Gasöl für Heizzwecke": "naphtha",
    "Heizöl": "naphtha",
    "Petroleum": "naphtha",
    "Methanol": "methanol",
    "Ammoniak": "ammonia",
}


def nuts2_parent(region: str) -> str:
    """
    Return the Austrian Bundesland code for a model region.

    Parameters
    ----------
    region
        Austrian NUTS2 or NUTS3 region code.

    Returns
    -------
    :
        Austrian NUTS2 code used as the Bundesland identifier.
    """
    if region == "AT333":
        return "AT33"
    if region.startswith("AT"):
        return region[:4]
    raise ValueError(f"Cannot determine Bundesland for model region {region!r}.")


def allocate_to_regions(
    parent_totals: pd.DataFrame, distribution_keys: pd.DataFrame
) -> pd.DataFrame:
    """
    Allocate Bundesland totals to model regions.

    Parameters
    ----------
    parent_totals
        Bundesland totals with their selected distribution-key columns.
    distribution_keys
        Regional industrial and population distribution keys.

    Returns
    -------
    :
        Regional annual demand totals.
    """
    keys = distribution_keys.loc[distribution_keys.index.str.startswith("AT")]
    keys = keys / keys.groupby(keys.index.map(nuts2_parent)).transform("sum")
    keys = keys.mask(keys.isna(), keys["population"], axis=0)
    keys_long = keys.stack().reset_index()
    keys_long.columns = ["region", "distribution_key", "key_value"]
    keys_long["parent"] = keys_long["region"].map(nuts2_parent)
    merged = parent_totals.merge(
        keys_long, on=["parent", "distribution_key"], how="left"
    )
    merged["value_TWh"] *= merged["key_value"]
    return merged[["year", "region", "sector", "carrier", "value_TWh"]]


def build_demand(
    nea: pd.DataFrame,
    distribution_keys: pd.DataFrame,
    target_years: list[int],
    source_years: dict,
    source_category: str,
) -> pd.DataFrame:
    """
    Transform NEA rows into regional model-carrier totals.

    Parameters
    ----------
    nea
        Prepared NEA data in long format.
    distribution_keys
        Regional industrial and population distribution keys.
    target_years
        Model years to create.
    source_years
        Mapping from model years to NEA source years.
    source_category
        NEA category to include in the output.

    Returns
    -------
    :
        Annual demand totals by year, region, sector, and carrier.
    """
    nea = nea.loc[nea["Kategorie"].eq(source_category)].copy()
    nea["carrier"] = nea["Energieträger"].map(CARRIER_MAPPING)
    nea["sector"] = "industry"
    nea["distribution_key"] = (
        nea["Bereich"].map(SECTOR_DISTRIBUTION_KEYS).fillna("population")
    )

    totals = []
    for target_year in target_years:
        source_year = source_years[target_year]
        source = nea[nea["year"].eq(source_year)]
        parent_totals = (
            source.groupby(
                [
                    "NUTS-2 Code",
                    "Bereich",
                    "sector",
                    "carrier",
                    "distribution_key",
                ],
                as_index=False,
                dropna=False,
            )["value_TWh"]
            .sum()
            .rename(columns={"NUTS-2 Code": "parent"})
        )
        parent_totals["year"] = target_year
        allocated = allocate_to_regions(parent_totals, distribution_keys)
        allocated = allocated.groupby(
            ["year", "region", "sector", "carrier"], as_index=False
        )["value_TWh"].sum()
        totals.append(allocated)

    return pd.concat(totals, ignore_index=True)


def main(snakemake: Snakemake) -> None:
    """
    Read NEA inputs and write regional annual industry totals.

    Parameters
    ----------
    snakemake
        Snakemake workflow object providing inputs, parameters, and outputs.

    Returns
    -------
    :
        Writes the regional annual demand CSV.
    """
    result = build_demand(
        pd.read_csv(snakemake.input.nea_at),
        pd.read_csv(snakemake.input.industrial_distribution_key, index_col=0),
        [int(year) for year in snakemake.params.target_years],
        snakemake.params.source_years,
        snakemake.params.source_category,
    )
    result.to_csv(snakemake.output.industrial_demand_overrides, index=False)
    logger.info("Wrote %d annual regional industry totals", len(result))


if __name__ == "__main__":
    if "snakemake" not in globals():
        from scripts._helpers import mock_snakemake

        snakemake = mock_snakemake(
            "build_industrial_demand_overrides_at", run="AT_KN2040", clusters="adm"
        )
    configure_logging(snakemake)
    set_scenario_config(snakemake)
    main(snakemake)
