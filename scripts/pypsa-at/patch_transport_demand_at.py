# SPDX-FileCopyrightText: 2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""Patch Austrian road transport demand data based on Statistik Austria Nutzenergieanalyse."""

import pandas as pd
import xarray as xr
from snakemake.script import Snakemake

from mods.constants import UNITS
from scripts._helpers import configure_logging, set_scenario_config
from scripts.prepare_sector_network import (
    define_spatial,
    get_temp_efficency,
)

NEA_TO_TECHNOLOGY_MAPPING = {
    "Benzin": "ice",
    "Biogene Brenn- und Treibstoffe": "ice",
    "Diesel": "ice",
    "Elektrische Energie": "bev",
    "Erdgas": "ice",
    "Flüssiggas": "ice",
}


def transform_nea_to_km(
    snakemake: Snakemake, nea_filtered: pd.DataFrame
) -> pd.DataFrame:
    """
    Transforms energy values in nea from MWh to 100 km driven using efficiencies from pypsa-eur per carrier.

    Parameters
    ----------
    snakemake
        The Snakemake workflow object providing inputs, params, and config
    nea_filtered
        Filtered nea data grouped by NUTS2 region and energy carrier

    Returns
    -------
    :
        Nea demand in 100km grouped by NUTS2 region.
    """

    options = snakemake.params.sector
    pop_layout = pd.read_csv(snakemake.input.clustered_pop_layout, index_col=0)
    spatial = define_spatial(pop_layout.index, options)
    temperature = xr.open_dataarray(snakemake.input.temp_air_total).to_pandas()[
        spatial.nodes
    ]

    nea_filtered["technology"] = nea_filtered["Energieträger"].map(
        NEA_TO_TECHNOLOGY_MAPPING
    )
    if (missing_technology := nea_filtered["technology"].isna()).any():
        raise ValueError(
            f"Unsupported NEA carriers: {nea_filtered.loc[missing_technology, 'Energieträger'].unique().tolist()}"
        )

    efficiencies = []
    for technology in set(NEA_TO_TECHNOLOGY_MAPPING.values()):
        if technology == "ice":
            car_efficiency = options["transport_ice_efficiency"]
            lower_degree_factor = options["ICE_lower_degree_factor"]
            upper_degree_factor = options["ICE_upper_degree_factor"]
        elif technology == "bev":
            car_efficiency = options["transport_electric_efficiency"]
            lower_degree_factor = options["EV_lower_degree_factor"]
            upper_degree_factor = options["EV_upper_degree_factor"]
        elif technology == "hydrogen":
            car_efficiency = options["transport_fuel_cell_efficiency"]
            lower_degree_factor = options["ICE_lower_degree_factor"]
            upper_degree_factor = options["ICE_upper_degree_factor"]
        else:
            raise ValueError(
                f"Unexpected value {technology} for road transport technology."
            )

        efficiency = get_temp_efficency(
            car_efficiency,
            temperature,
            options["transport_heating_deadband_lower"],
            options["transport_heating_deadband_upper"],
            lower_degree_factor,
            upper_degree_factor,
        )
        efficiency = transform_timeseries_to_long(efficiency)
        efficiency = efficiency[
            efficiency["NUTS-2 Code"].isin(nea_filtered["NUTS-2 Code"])
        ]
        efficiency = efficiency.groupby(["NUTS-2 Code"], as_index=False)["value"].mean()
        efficiency["technology"] = technology
        efficiency = efficiency.rename(columns={"value": "eff"})
        efficiencies.append(efficiency)
    efficiency = pd.concat(efficiencies)
    nea_filtered = nea_filtered.merge(
        efficiency, on=["NUTS-2 Code", "technology"], how="left"
    )
    if (missing_eff := nea_filtered["eff"].isna()).any():
        missing = sorted(nea_filtered.loc[missing_eff, "NUTS-2 Code"].unique())
        raise ValueError(
            f"No model region matches the NEA NUTS2 regions {missing}. Their NEA "
            "demand cannot be applied. Check the clustering configuration and the "
            "NEA region codes."
        )
    nea_filtered["value"] *= nea_filtered["eff"]
    return nea_filtered.groupby(["NUTS-2 Code"], as_index=False)["value"].sum()


def filter_nea(
    nea_at: pd.DataFrame, base_year: int, source_years: dict[int, int]
) -> pd.DataFrame:
    """
    Filter Nutzenergieanalyse (nea) data to the configured source year and road transport data

    Parameters
    ----------
    nea_at
        Full nea at dataset
    base_year
        Model base year, i.e. the first planning horizon
    source_years
        Mapping from model base years to NEA source years from the
        ``demand: source_years:`` configuration

    Returns
    -------
    :
        Filtered nea data grouped by NUTS2 region and energy carrier

    Raises
    ------
    ValueError
        If no NEA source year is configured for ``base_year`` or the NEA
        dataset contains no road transport demand for the source year.
    """
    try:
        year = source_years[base_year]
    except KeyError as err:
        raise ValueError(
            f"No NEA source year configured for base year {base_year}. "
            f"Add it to 'demand: source_years:' (configured: {source_years})."
        ) from err
    nea_filtered = nea_at[
        (nea_at["year"] == year)
        & (nea_at["Bereich"] == "Sonstiger Landverkehr")
        & (nea_at["Nutzenergiekategorie"] == "Verkehr")
    ].copy()
    nea_filtered["value"] = nea_filtered["value_TWh"] * UNITS["TWh"]
    nea_filtered = nea_filtered.groupby(
        ["NUTS-2 Code", "Energieträger"], as_index=False
    )["value"].sum()
    nea_filtered = nea_filtered[nea_filtered["value"] != 0]
    if nea_filtered.empty:
        raise ValueError(
            f"The NEA dataset contains no road transport demand for source year "
            f"{year}. Available NEA years: {sorted(nea_at['year'].unique())}."
        )
    return nea_filtered


def transform_timeseries_to_long(df: pd.DataFrame):
    """
    Transform a given timeseries DataFrame to long format.

    Parameters
    ----------
    df
        Dataframe to transform. Assumes timestamps as index and model regions as columns

    Returns
    -------
    :
        Transformed DataFrame
    """
    df = df.stack().reset_index()
    df.columns = ["timestamp", "region", "value"]
    df["NUTS-2 Code"] = df["region"].map(lambda x: x[:4])
    return df


def apply_nea(transport_demand_long, nea_transformed):
    """
    Transform and apply the calculated nea demand in 100km to the existing demand dataset

    Parameters
    ----------
    transport_demand_long
        Existing total road demand per model region in 100km
    nea_transformed
        Nea demand in 100km grouped by NUTS2 region

    Returns
    -------
    :
        Updated total road demand dataset.
    """
    transport_demand_long["NUTS-2 sum"] = transport_demand_long.groupby("NUTS-2 Code")[
        "value"
    ].transform("sum")
    transport_demand_long = transport_demand_long.merge(
        nea_transformed.rename(columns={"value": "nea_value"}),
        on=["NUTS-2 Code"],
        how="left",
    )
    zero_baseline = transport_demand_long["nea_value"].notna() & transport_demand_long[
        "NUTS-2 sum"
    ].eq(0)
    if zero_baseline.any():
        regions = sorted(
            transport_demand_long.loc[zero_baseline, "NUTS-2 Code"].unique()
        )
        raise ValueError(
            f"The existing transport demand sums to zero in NUTS2 regions "
            f"{regions}, but the NEA prescribes demand there. The NEA target "
            "cannot be distributed onto a zero baseline."
        )
    transport_demand_long["factor"] = (
        transport_demand_long["nea_value"] / transport_demand_long["NUTS-2 sum"]
    )
    transport_demand_long.loc[~transport_demand_long["factor"].isna(), "value"] *= (
        transport_demand_long["factor"]
    )

    return transport_demand_long.pivot(
        index="timestamp", columns="region", values="value"
    )


def main(snakemake: Snakemake) -> None:
    """
    Build the patched road demand CSV

    Parameters
    ----------
    snakemake
        The Snakemake workflow object providing inputs, params, and config.

    Returns
    -------
    :
        Result is written to the snakemake output
    """
    transport_demand = pd.read_csv(
        snakemake.input.transport_demand, index_col=0, parse_dates=True
    )
    transport_demand_long = transform_timeseries_to_long(transport_demand)
    nea_at = pd.read_csv(snakemake.input.nea_at)
    nea_filtered = filter_nea(
        nea_at, snakemake.params.planning_horizons[0], snakemake.params.source_years
    )
    nea_transformed = transform_nea_to_km(snakemake, nea_filtered)
    transport_demand_patched = apply_nea(transport_demand_long, nea_transformed)
    transport_demand_patched.to_csv(snakemake.output.transport_demand_patched)


if __name__ == "__main__":
    if "snakemake" not in globals():
        from scripts._helpers import mock_snakemake

        snakemake = mock_snakemake(
            "patch_transport_demand_at", clusters="adm", run="AT_KN2040"
        )
    configure_logging(snakemake)
    set_scenario_config(snakemake)
    main(snakemake)
