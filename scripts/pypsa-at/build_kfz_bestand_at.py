# SPDX-FileCopyrightText: 2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""Build regional Austrian vehicle-stock data from Statistik Austria ODS files."""

import pandas as pd
from snakemake.script import Snakemake

from scripts._helpers import configure_logging, set_scenario_config

SPECIAL_DISTRICTS = {"Polizei, Justizwache, Finanzverwaltung", "Post", "Bahn"}


def read_source(path: str) -> pd.DataFrame:
    """
    Read the district level car stock data and redistribute unassignable categories.

    Parameters
    ----------
    path
        Path to the Statistik Austria workbook on car stock data.

    Returns
    -------
    :
        Number of registered cars per district
    """
    table = pd.read_excel(
        path, sheet_name="tab_7", header=1, usecols="A:J", engine="odf"
    ).rename(columns={"Bundesland und Zulassungsbezirk": "district"})
    table["district"] = table["district"].astype("string").str.strip()
    table = table.loc[
        table["district"].notna() & ~table["district"].str.startswith("Q:")
    ].set_index("district")

    table = table.replace({"-": 0})
    rows = table.loc[
        ~((table.index == "Österreich") | table.index.str.endswith("insgesamt"))
    ]
    special = rows.loc[rows.index.isin(SPECIAL_DISTRICTS)]
    geographic = rows.loc[~rows.index.isin(SPECIAL_DISTRICTS)]

    factor = (geographic.sum() + special.sum()) / geographic.sum()
    geographic *= factor
    return geographic


def _map_special_districts(district_mapping: pd.DataFrame) -> pd.DataFrame:
    """
    Manually create entries where vehicle registration districts deviate from normal district naming.

    Parameters
    ----------
    district_mapping
        Mapping of districts to NUTS regions with population number

    Returns
    -------
    :
        District mapping with extra district_vehicles column to represent vehicle registration districts.
    """
    district_mapping["district_vehicles"] = district_mapping["district_name"]
    district_mapping["district_vehicles"] = (
        district_mapping["district_vehicles"]
        .str.replace("Sankt", "St.")
        .str.replace("Wiener", "Wr.")
        .str.replace("(", " (")
        .str.replace(".*,", "", regex=True)
        .str.replace("Bregenz", "Bregenz (Bezirk)")
    )
    district_mapping["district_vehicles"] = district_mapping[
        "district_vehicles"
    ].replace(
        {
            "Eisenstadt (Stadt)": "Eisenstadt (Stadt inkl. Rust)",
            "Rust (Stadt)": "Eisenstadt (Stadt inkl. Rust)",
            "Klosterneuburg": "Klosterneuburg (BH Tulln)",
        }
    )
    district_mapping.loc[
        district_mapping["district_name_judicial"] == "Klosterneuburg",
        "district_vehicles",
    ] = "Klosterneuburg (BH Tulln)"
    district_mapping.loc[
        district_mapping["district_name_judicial"] == "Schwechat", "district_vehicles"
    ] = "Schwechat"
    district_mapping.loc[
        district_mapping["municipality_name"] == "Leoben", "district_vehicles"
    ] = "Leoben (Stadt)"
    district_mapping.loc[
        district_mapping["municipality_name"] == "Gröbming", "district_vehicles"
    ] = "Pol. Exp. Gröbming"
    district_mapping.loc[
        district_mapping["municipality_name"].isin(
            ["Altaussee", "Bad Aussee", "Bad Mitterndorf", "Grundlsee"]
        ),
        "district_vehicles",
    ] = "Bad Aussee (Liezen)"
    district_mapping.loc[
        (district_mapping["municipality_name"] != "Leoben")
        & (district_mapping["district_vehicles"] == "Leoben"),
        "district_vehicles",
    ] = "Leoben (Land)"
    return district_mapping


def build_district_weights(
    district_mapping: pd.DataFrame, clustering: str
) -> pd.DataFrame:
    """
    Build weights for the mapping of vehicle registration districts to model regions given a clustering

    Parameters
    ----------
    district_mapping
        Mapping of vehicle registration districts to NUTS regions with population number
    clustering
        The config string modify_nuts3_shapes to indicate AT clustering variant

    Returns
    -------
    :
        A mapping of vehicle registration districts to model regions with a corresponding weight
    """
    region = "nuts2_code" if clustering.startswith("AT10") else "nuts3_code"
    weights = (
        district_mapping.groupby(["district_vehicles", region], as_index=False)[
            "population"
        ]
        .sum()
        .rename(columns={"district_vehicles": "district", region: "region"})
    )
    weights["weight"] = weights["population"] / weights.groupby("district")[
        "population"
    ].transform("sum")

    return weights[["district", "region", "weight"]]


def build_kfz_data(
    car_stock: pd.DataFrame,
    weights: pd.DataFrame,
) -> pd.DataFrame:
    """
    Apply district weights to car stock data.

    Parameters
    ----------
    car_stock
        Number of registered cars per registration district
    weights
        A mapping of vehicle registration districts to model regions with a corresponding weight

    Returns
    -------
    :
        Number of registered cars per model region
    """
    if missing := sorted(set(car_stock["district"]) - set(weights["district"])):
        raise ValueError(f"Unmapped vehicle districts: {missing}")
    merged = car_stock.merge(weights, on="district", how="inner").set_index("region")
    return (
        merged.drop(columns=["district", "weight"])
        .mul(merged["weight"], axis=0)
        .groupby(level="region")
        .sum()
    )


def transform_transport_data(
    weighted_data: pd.DataFrame, transport_data_in: str, energy_totals_year: int
) -> pd.DataFrame:
    """
    Transform and apply the calculated AT car stock numbers to the existing transport data

    Parameters
    ----------
    weighted_data
        Number of registered cars per AT model region
    transport_data_in
        Existing transport data numbers for all model regions
    energy_totals_year
        Year used for energy totals

    Returns
    -------
    :
        Modified transport data
    """
    transport_data = pd.read_csv(transport_data_in)
    cols = transport_data.columns
    data_export = weighted_data[["Pkw"]]
    data_export["year"] = energy_totals_year
    data_export["country"] = weighted_data.index.map(lambda x: x[:2])
    transport_data = transport_data.merge(
        data_export.reset_index(), on=["country", "year"], how="left"
    )
    transport_data["number cars"] = transport_data["Pkw"].fillna(
        transport_data["number cars"]
    )
    transport_data["country"] = transport_data["region"].fillna(
        transport_data["country"]
    )
    return transport_data[cols]


def main(snakemake: Snakemake) -> None:
    """
    Build the configured regional vehicle-stock CSV per node.

    Parameters
    ----------
    snakemake
        The Snakemake workflow object providing inputs, params, and config.

    Returns
    -------
    :
        Result is written to the snakemake output
    """
    car_stock = read_source(snakemake.input.ods).reset_index()
    district_mapping = pd.read_csv(snakemake.input.regional_data)
    district_mapping = _map_special_districts(district_mapping)
    weights = build_district_weights(district_mapping, snakemake.params.clustering)
    weighted_data = build_kfz_data(car_stock, weights)
    transport_data_out = transform_transport_data(
        weighted_data,
        snakemake.input.transport_data_in,
        snakemake.params.energy_totals_year,
    )

    transport_data_out.to_csv(snakemake.output.transport_data_out, index=False)


if __name__ == "__main__":
    if "snakemake" not in globals():
        from scripts._helpers import mock_snakemake

        snakemake = mock_snakemake(
            "build_kfz_bestand_at", clusters="adm", run="AT_KN2040"
        )
    configure_logging(snakemake)
    set_scenario_config(snakemake)
    main(snakemake)
