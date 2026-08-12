# SPDX-FileCopyrightText: 2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""Recalibrate Austrian heat demand against NEA household and service data."""

import logging

import geopandas as gpd
import pandas as pd
from snakemake.script import Snakemake

from scripts._helpers import configure_logging

logger = logging.getLogger(__name__)

SECTORS = {
    "Private Haushalte": "households",
    "Offentliche und Private Dienstleistungen": "services",
}
USES = [
    "Raumklima und Warmwasser",
    "Prozesswärme<200 °C",
    "Prozesswärme>200 °C",
]


def recalibrate_heat_demand(
    nea: pd.DataFrame,
    heat_demand: pd.DataFrame,
    region_to_nuts2: pd.Series,
    source_years: dict[int, int],
    base_year: int = 2025,
) -> pd.DataFrame:
    """
    Scale regional heat demand to NEA household and service totals.

    Parameters
    ----------
    nea : pd.DataFrame
        NEA heat-demand data in long format.
    heat_demand : pd.DataFrame
        Unsplit regional heat-demand data in MWh.
    region_to_nuts2 : pd.Series
        Mapping from NUTS3 region codes to NUTS2 codes.
    source_years : dict[int, int]
        Mapping from target years to NEA source years.
    base_year : int, default=2025
        Heat-demand year used to calculate the scaling factors.

    Returns
    -------
    :
        Recalibrated demand by year, region, sector, and heating type.
    """
    nea = nea.loc[
        nea["year"].eq(source_years[base_year])
        & nea["Bereich"].isin(SECTORS.keys())
        & nea["Nutzenergiekategorie"].isin(USES)
    ]
    nea["heating"] = (
        nea["Energieträger"].eq("Fernwärme").map({True: "central", False: "decentral"})
    )
    nea = nea.rename(columns={"Bereich": "sector"})
    nea["sector"] = nea["sector"].replace(SECTORS)
    nea = nea.groupby(["NUTS-2 Code", "sector", "heating"], as_index=False)[
        "value_TWh"
    ].sum()

    demand = heat_demand.copy()
    demand["NUTS-2 Code"] = demand["region"].map(region_to_nuts2)
    base_demand = (
        demand.loc[demand["year"].eq(base_year)]
        .groupby("NUTS-2 Code")["value"]
        .sum()
        .rename("base_value")
    )

    factors = nea.merge(base_demand, on="NUTS-2 Code")
    factors["factor"] = factors["value_TWh"] * 1e6 / factors["base_value"]

    result = demand.merge(
        factors[["NUTS-2 Code", "sector", "heating", "factor"]],
        on="NUTS-2 Code",
    )
    result["value"] *= result["factor"]
    return result[["year", "region", "sector", "heating", "value"]].sort_values(
        ["year", "region", "sector", "heating"]
    )


def main(snakemake: Snakemake) -> None:
    """
    Read inputs, recalibrate heat demand, and write the output file.

    Parameters
    ----------
    snakemake : Snakemake
        Snakemake input, output, and parameter collections.
    """
    shapes = gpd.read_file(snakemake.input.nuts3_shapes)
    region_to_nuts2 = shapes.loc[shapes["country"].eq("AT")].set_index("level3")[
        "level2"
    ]
    result = recalibrate_heat_demand(
        pd.read_csv(snakemake.input.nea_at),
        pd.read_csv(snakemake.input.heat_demand),
        region_to_nuts2,
        snakemake.params.source_years,
        base_year=snakemake.params.base_year,
    )
    result.to_csv(snakemake.output.heat_demand, index=False)
    logger.info("Wrote %d recalibrated heat-demand values", len(result))


if __name__ == "__main__":
    if "snakemake" not in globals():
        from scripts._helpers import mock_snakemake

        snakemake = mock_snakemake(
            "recalibrate_heat_demand_at",
            run="AT_KN2040",
            cluster="adm",
        )
    configure_logging(snakemake)
    main(snakemake)
