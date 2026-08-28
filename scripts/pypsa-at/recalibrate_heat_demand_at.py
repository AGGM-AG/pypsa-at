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
    base_year: int,
) -> pd.DataFrame:
    """
    Scale regional heat demand to NEA household and service totals.

    Parameters
    ----------
    nea
        NEA heat-demand data in long format.
    heat_demand
        Unsplit regional heat-demand data in MWh.
    region_to_nuts2
        Mapping from NUTS3 region codes to NUTS2 codes.
    source_years
        Mapping from target years to NEA source years.
    base_year
        Heat-demand year used to calculate the scaling factors.

    Returns
    -------
    :
        Recalibrated demand by year, NUTS-2 region, region, sector, and
        heating type.
    """
    nea = nea.loc[
        nea["year"].eq(source_years[base_year])
        & nea["Bereich"].isin(SECTORS.keys())
        & nea["Nutzenergiekategorie"].isin(USES)
    ].copy()
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
    return result[
        ["year", "NUTS-2 Code", "region", "sector", "heating", "value"]
    ].sort_values(["year", "NUTS-2 Code", "region", "sector", "heating"])


def redistribute_central_heat(
    result: pd.DataFrame,
    urban_fraction: pd.DataFrame,
    region_to_nuts2: pd.Series,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Redistribute central heat by urban-weighted regional demand.

    Central heat is preserved per NUTS2 region and sector. Decentral heat is
    adjusted so total heat demand per region and sector remains unchanged.

    If all urban fractions in a NUTS-2 sector group are zero, the
    central-demand share is used as the fallback allocation fraction.

    Parameters
    ----------
    result
        Recalibrated demand.
    urban_fraction
        Wide urban fractions indexed by region.
    region_to_nuts2
        Mapping from regional codes to NUTS-2 codes.

    Returns
    -------
    :
        Adjusted demand and long urban fractions.
    """
    fractions = urban_fraction.rename_axis(index="region", columns="year")
    fractions = fractions.stack().rename("urban_fraction").reset_index()
    weights = result.groupby(["year", "region", "sector"], as_index=False)[
        "value"
    ].sum()
    weights = weights.rename(columns={"value": "sectoral_totals"})
    weights["NUTS-2 Code"] = weights["region"].map(region_to_nuts2)
    weights["nuts2_totals"] = weights.groupby(
        ["year", "NUTS-2 Code", "sector"], as_index=False
    )["sectoral_totals"].transform("sum")

    weights["share"] = weights["sectoral_totals"] / weights["nuts2_totals"]

    weights = weights.merge(fractions, on=["year", "region"], how="left")

    central_mask = result["heating"].eq("central")
    regional_sector_totals = result.groupby(["year", "region", "sector"])["value"].sum()
    central_totals = (
        result.loc[central_mask]
        .groupby(["year", "NUTS-2 Code", "sector"], as_index=False)["value"]
        .sum()
        .rename(columns={"value": "central_total"})
    )
    central_totals = central_totals.merge(
        weights[
            [
                "year",
                "NUTS-2 Code",
                "region",
                "sector",
                "nuts2_totals",
                "share",
                "urban_fraction",
            ]
        ],
        on=["year", "sector", "NUTS-2 Code"],
    )
    central_totals["nuts2_urban_fraction"] = central_totals.groupby(
        ["year", "NUTS-2 Code", "sector"]
    )["urban_fraction"].transform("sum")
    central_totals.loc[
        central_totals["nuts2_urban_fraction"] == 0, "urban_fraction"
    ] = (
        central_totals.loc[central_totals["nuts2_urban_fraction"] == 0, "central_total"]
        / central_totals.loc[
            central_totals["nuts2_urban_fraction"] == 0, "nuts2_totals"
        ]
    )
    urban_fraction_unstacked = central_totals[
        ["sector", "year", "region", "urban_fraction"]
    ].copy()
    central_totals["weight"] = (
        central_totals["share"] * central_totals["urban_fraction"]
    )
    central_totals["weight"] /= central_totals.groupby(
        ["year", "NUTS-2 Code", "sector"]
    )["weight"].transform("sum")

    central_totals["target_central"] = (
        central_totals["central_total"] * central_totals["weight"]
    )
    central_keys = ["year", "region", "sector"]
    central_totals = central_totals.sort_values(central_keys)
    target_central = central_totals.set_index(central_keys)["target_central"]

    central_rows = result.loc[central_mask, central_keys]
    central_values = target_central.reindex(pd.MultiIndex.from_frame(central_rows))
    result.loc[central_mask, "value"] = central_values.to_numpy()

    target_decentral = regional_sector_totals - target_central.reindex(
        regional_sector_totals.index, fill_value=0
    )
    if (target_decentral < 0).any():
        logger.warning(
            "Clipping below zero decentral heating values resulting in inconsistent demand."
        )
    target_decentral = target_decentral.clip(lower=0)

    decentral_mask = result["heating"].eq("decentral")
    decentral_rows = result.loc[decentral_mask, central_keys]
    decentral_values = target_decentral.reindex(
        pd.MultiIndex.from_frame(decentral_rows)
    )
    result.loc[decentral_mask, "value"] = decentral_values.to_numpy()

    return result.drop(columns="NUTS-2 Code"), urban_fraction_unstacked


def allocate_heat_demand(
    demand: pd.DataFrame,
    urban_fraction: pd.DataFrame,
    cluster_heat_buses: bool,
) -> pd.DataFrame:
    """
    Allocate recalibrated demand to urban, rural, and central heat carriers.

    Parameters
    ----------
    demand
        Recalibrated demand by year, region, sector, and heating type.
    urban_fraction
        Long urban fractions.
    cluster_heat_buses
        Merge residential and services carriers into shared heat carriers.

    Returns
    -------
    :
        Demand by year, region, carrier, and value.
    """
    demand = demand.merge(urban_fraction, on=["region", "year", "sector"])

    central = (
        demand.loc[demand["heating"].eq("central")]
        .groupby(["year", "region"], as_index=False)["value"]
        .sum()
        .assign(carrier="urban central heat")
    )

    decentral = demand.loc[demand["heating"].eq("decentral")].copy()
    urban = decentral.assign(
        value=decentral["value"] * decentral["urban_fraction"],
        carrier=decentral["sector"].map(
            {
                "households": "residential urban decentral heat",
                "services": "services urban decentral heat",
            }
        ),
    )
    rural = decentral.assign(
        value=decentral["value"] * (1 - decentral["urban_fraction"]),
        carrier=decentral["sector"].map(
            {
                "households": "residential rural heat",
                "services": "services rural heat",
            }
        ),
    )

    result = pd.concat([central, urban, rural], ignore_index=True)[
        ["year", "region", "carrier", "value"]
    ]

    if cluster_heat_buses:
        result.loc[:, "carrier"] = result["carrier"].replace(
            {
                "residential rural heat": "rural heat",
                "services rural heat": "rural heat",
                "residential urban decentral heat": "urban decentral heat",
                "services urban decentral heat": "urban decentral heat",
            }
        )
        result = result.groupby(
            ["year", "region", "carrier"], as_index=False
        ).value.sum()
    return result.sort_values(["year", "region", "carrier"])


def main(snakemake: Snakemake) -> None:
    """
    Read inputs, recalibrate heat demand, and write the output file.

    Parameters
    ----------
    snakemake : Snakemake
        Snakemake input, output, and parameter collections.

    Returns
    -------
    :
        Writes recalibrated carrier-level heat demand and Austrian urban
        fractions to the configured outputs.
    """
    shapes = gpd.read_file(snakemake.input.nuts3_shapes)
    modify_nuts3_shapes = snakemake.params.modify_nuts3_shapes
    region_idx = "level3" if modify_nuts3_shapes.startswith("AT35") else "level2"
    shapes[f"{region_idx}_values"] = shapes[region_idx].copy()
    region_to_nuts2 = (
        shapes.loc[shapes["country"].eq("AT"), [region_idx, f"{region_idx}_values"]]
        .drop_duplicates()
        .set_index(region_idx)[f"{region_idx}_values"]
    )
    region_to_nuts2 = region_to_nuts2.map(lambda x: x[:4])

    result = recalibrate_heat_demand(
        pd.read_csv(snakemake.input.nea_at),
        pd.read_csv(snakemake.input.heat_demand),
        region_to_nuts2,
        snakemake.params.source_years,
        base_year=snakemake.params.planning_horizons[0],
    )
    urban_fraction = pd.concat(
        [
            pd.read_csv(path, index_col=0)["urban fraction"]
            for path in snakemake.input.urban_fraction
        ],
        axis=1,
        keys=snakemake.params.planning_horizons,
    )
    result, urban_fraction_unstacked = redistribute_central_heat(
        result, urban_fraction, region_to_nuts2
    )
    result = allocate_heat_demand(
        result,
        urban_fraction_unstacked,
        snakemake.params.cluster_heat_buses,
    )
    urban_fraction_at = (
        urban_fraction_unstacked.groupby(["year", "region"], as_index=False)[
            "urban_fraction"
        ]
        .mean()
        .pivot(index="region", columns="year", values="urban_fraction")
    )
    urban_fraction_at.to_csv(snakemake.output.urban_fraction_at)
    result.to_csv(snakemake.output.heat_demand, index=False)
    logger.info("Wrote recalibrated heat-demand")


if __name__ == "__main__":
    if "snakemake" not in globals():
        from scripts._helpers import mock_snakemake

        snakemake = mock_snakemake(
            "recalibrate_heat_demand_at",
            run="AT_KN2040",
            clusters="adm",
        )
    configure_logging(snakemake)
    main(snakemake)
