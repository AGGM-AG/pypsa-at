# SPDX-FileCopyrightText: Contributors to PyPSA-Eur <https://github.com/pypsa/pypsa-eur>
#
# SPDX-License-Identifier: MIT
"""
Creates plots from summary CSV files.
"""

import logging

import matplotlib.gridspec as gridspec
import matplotlib.pyplot as plt
import pandas as pd

from scripts._helpers import configure_logging, rename_techs, set_scenario_config
from scripts.prepare_sector_network import co2_emissions_year

logger = logging.getLogger(__name__)
plt.style.use("bmh")


# consolidate and rename

preferred_order = pd.Index(
    [
        "transmission lines",
        "hydroelectricity",
        "hydro reservoir",
        "run of river",
        "pumped hydro storage",
        "solid biomass",
        "biogas",
        "onshore wind",
        "offshore wind",
        "offshore wind (AC)",
        "offshore wind (DC)",
        "solar PV",
        "solar thermal",
        "solar rooftop",
        "solar",
        "building retrofitting",
        "ground heat pump",
        "air heat pump",
        "heat pump",
        "resistive heater",
        "power-to-heat",
        "gas-to-power/heat",
        "CHP",
        "OCGT",
        "gas boiler",
        "gas",
        "natural gas",
        "methanation",
        "ammonia",
        "hydrogen storage",
        "power-to-gas",
        "power-to-liquid",
        "battery storage",
        "hot water storage",
        "CO2 sequestration",
    ]
)


def plot_costs():
    cost_df = pd.read_csv(
        snakemake.input.costs, index_col=list(range(3)), header=list(range(n_header))
    )

    df = cost_df.groupby("carrier").sum()

    # convert to billions
    df = df / 1e9

    df = df.groupby(df.index.map(rename_techs)).sum()

    to_drop = df.index[df.max(axis=1) < snakemake.params.plotting["costs_threshold"]]

    logger.info(
        f"Dropping technology with costs below {snakemake.params['plotting']['costs_threshold']} EUR billion per year"
    )
    logger.debug(df.loc[to_drop])

    df = df.drop(to_drop)

    logger.info(f"Total system cost of {round(df.sum().iloc[0])} EUR billion per year")

    new_index = preferred_order.intersection(df.index).append(
        df.index.difference(preferred_order)
    )

    # new_columns = df.sum().sort_values().index

    fig, ax = plt.subplots(figsize=(12, 8))

    if df.empty:
        ax.bar([], [])
    else:
        df.loc[new_index].T.plot(
            kind="bar",
            ax=ax,
            stacked=True,
            color=[snakemake.params.plotting["tech_colors"][i] for i in new_index],
        )

    handles, labels = ax.get_legend_handles_labels()

    handles.reverse()
    labels.reverse()

    ax.set_ylim([0, snakemake.params.plotting["costs_max"]])

    ax.set_ylabel("System Cost [EUR billion per year]")

    ax.set_xlabel("")

    ax.grid(axis="x")

    ax.legend(
        handles, labels, ncol=1, loc="upper left", bbox_to_anchor=[1, 1], frameon=False
    )

    fig.savefig(snakemake.output.costs, bbox_inches="tight")
    plt.close(fig)


def plot_energy():
    energy_df = pd.read_csv(
        snakemake.input.energy, index_col=list(range(2)), header=list(range(n_header))
    )

    df = energy_df.groupby("carrier").sum()

    # convert MWh to TWh
    df = df / 1e6

    df = df.groupby(df.index.map(rename_techs)).sum()

    to_drop = df.index[
        df.abs().max(axis=1) < snakemake.params.plotting["energy_threshold"]
    ]

    logger.info(
        f"Dropping all technology with energy consumption or production below {snakemake.params['plotting']['energy_threshold']} TWh/a"
    )
    logger.debug(df.loc[to_drop])

    df = df.drop(to_drop)

    logger.info(f"Total energy of {round(df.sum().iloc[0])} TWh/a")

    if df.empty:
        fig, ax = plt.subplots(figsize=(12, 8))
        fig.savefig(snakemake.output.energy, bbox_inches="tight")
        plt.close(fig)
        return

    new_index = preferred_order.intersection(df.index).append(
        df.index.difference(preferred_order)
    )

    # new_columns = df.columns.sort_values()

    fig, ax = plt.subplots(figsize=(12, 8))

    logger.debug(df.loc[new_index])

    df.loc[new_index].T.plot(
        kind="bar",
        ax=ax,
        stacked=True,
        color=[snakemake.params.plotting["tech_colors"][i] for i in new_index],
    )

    handles, labels = ax.get_legend_handles_labels()

    handles.reverse()
    labels.reverse()

    ax.set_ylim(
        [
            snakemake.params.plotting["energy_min"],
            snakemake.params.plotting["energy_max"],
        ]
    )

    ax.set_ylabel("Energy [TWh/a]")

    ax.set_xlabel("")

    ax.grid(axis="x")

    ax.legend(
        handles, labels, ncol=1, loc="upper left", bbox_to_anchor=[1, 1], frameon=False
    )

    fig.savefig(snakemake.output.energy, bbox_inches="tight")
    plt.close(fig)


def plot_balances():
    co2_carriers = ["co2", "co2 stored", "process emissions"]

    balances_df = pd.read_csv(
        snakemake.input.balances, index_col=list(range(3)), header=list(range(n_header))
    )

    balances = {k: df for k, df in balances_df.groupby("bus_carrier")}
    balances["energy"] = balances_df.groupby(["component", "carrier"]).sum()

    for bus_carrier, df in balances.items():
        df = df.groupby("carrier").sum()

        # convert MWh to TWh
        df = df / 1e6

        df = df.groupby(df.index.map(rename_techs)).sum()

        to_drop = df.index[
            df.abs().max(axis=1) < snakemake.params.plotting["energy_threshold"] / 10
        ]

        units = "MtCO2/a" if bus_carrier in co2_carriers else "TWh/a"
        logger.debug(
            f"Dropping technology energy balance smaller than {snakemake.params['plotting']['energy_threshold'] / 10} {units}"
        )
        logger.debug(df.loc[to_drop])

        df = df.drop(to_drop)

        logger.debug(
            f"Total energy balance for {bus_carrier} of {round(df.sum().iloc[0], 2)} {units}"
        )

        if df.empty:
            continue

        new_index = preferred_order.intersection(df.index).append(
            df.index.difference(preferred_order)
        )

        new_columns = df.columns.sort_values()

        fig, ax = plt.subplots(figsize=(12, 8))

        df.loc[new_index, new_columns].T.plot(
            kind="bar",
            ax=ax,
            stacked=True,
            color=[snakemake.params.plotting["tech_colors"][i] for i in new_index],
        )

        handles, labels = ax.get_legend_handles_labels()

        handles.reverse()
        labels.reverse()

        if bus_carrier in co2_carriers:
            ax.set_ylabel("CO2 [MtCO2/a]")
        else:
            ax.set_ylabel("Energy [TWh/a]")

        ax.set_xlabel("")

        ax.grid(axis="x")

        ax.legend(
            handles,
            labels,
            ncol=1,
            loc="upper left",
            bbox_to_anchor=[1, 1],
            frameon=False,
        )

        fig.savefig(
            snakemake.output.balances[:-10] + bus_carrier + ".svg", bbox_inches="tight"
        )
        plt.close(fig)


def historical_emissions(countries):
    """
    Read historical emissions to add them to the carbon budget plot.
    """
    # https://www.eea.europa.eu/data-and-maps/data/national-emissions-reported-to-the-unfccc-and-to-the-eu-greenhouse-gas-monitoring-mechanism-16
    # downloaded 201228 (modified by EEA last on 201221)
    df = pd.read_csv(snakemake.input.co2, encoding="latin-1", low_memory=False)
    df.loc[df["Year"] == "1985-1987", "Year"] = 1986
    df["Year"] = df["Year"].astype(int)
    df = df.set_index(
        ["Year", "Sector_name", "Country_code", "Pollutant_name"]
    ).sort_index()

    e = pd.Series()
    e["electricity"] = "1.A.1.a - Public Electricity and Heat Production"
    e["residential non-elec"] = "1.A.4.b - Residential"
    e["services non-elec"] = "1.A.4.a - Commercial/Institutional"
    e["rail non-elec"] = "1.A.3.c - Railways"
    e["road non-elec"] = "1.A.3.b - Road Transportation"
    e["domestic navigation"] = "1.A.3.d - Domestic Navigation"
    e["international navigation"] = "1.D.1.b - International Navigation"
    e["domestic aviation"] = "1.A.3.a - Domestic Aviation"
    e["international aviation"] = "1.D.1.a - International Aviation"
    e["total energy"] = "1 - Energy"
    e["industrial processes"] = "2 - Industrial Processes and Product Use"
    e["agriculture"] = "3 - Agriculture"
    e["LULUCF"] = "4 - Land Use, Land-Use Change and Forestry"
    e["waste management"] = "5 - Waste management"
    e["other"] = "6 - Other Sector"
    e["indirect"] = "ind_CO2 - Indirect CO2"
    e["other LULUCF"] = "4.H - Other LULUCF"

    pol = ["CO2"]  # ["All greenhouse gases - (CO2 equivalent)"]
    if "GB" in countries:
        countries.remove("GB")
        countries.append("UK")

    year = df.index.levels[0][df.index.levels[0] >= 1990]

    missing = pd.Index(countries).difference(df.index.levels[2])
    if not missing.empty:
        logger.warning(
            f"The following countries are missing and not considered when plotting historic CO2 emissions: {missing}"
        )
        countries = pd.Index(df.index.levels[2]).intersection(countries)

    idx = pd.IndexSlice
    co2_totals = (
        df.loc[idx[year, e.values, countries, pol], "emissions"]
        .unstack("Year")
        .rename(index=pd.Series(e.index, e.values))
    )

    co2_totals = (1 / 1e6) * co2_totals.groupby(level=0, axis=0).sum()  # Gton CO2

    co2_totals.loc["industrial non-elec"] = (
        co2_totals.loc["total energy"]
        - co2_totals.loc[
            [
                "electricity",
                "services non-elec",
                "residential non-elec",
                "road non-elec",
                "rail non-elec",
                "domestic aviation",
                "international aviation",
                "domestic navigation",
                "international navigation",
            ]
        ].sum()
    )

    emissions = co2_totals.loc["electricity"]
    if options["transport"]:
        emissions += co2_totals.loc[[i + " non-elec" for i in ["rail", "road"]]].sum()
    if options["heating"]:
        emissions += co2_totals.loc[
            [i + " non-elec" for i in ["residential", "services"]]
        ].sum()
    if options["industry"]:
        emissions += co2_totals.loc[
            [
                "industrial non-elec",
                "industrial processes",
                "domestic aviation",
                "international aviation",
                "domestic navigation",
                "international navigation",
            ]
        ].sum()
    return emissions


def plot_carbon_budget_distribution(input_eurostat, options):
    """
    Plot historical carbon emissions in the EU and decarbonization path.
    """
    import seaborn as sns

    sns.set()
    sns.set_style("ticks")
    plt.rcParams["xtick.direction"] = "in"
    plt.rcParams["ytick.direction"] = "in"
    plt.rcParams["xtick.labelsize"] = 20
    plt.rcParams["ytick.labelsize"] = 20

    emissions_scope = snakemake.params.emissions_scope
    input_co2 = snakemake.input.co2

    # historic emissions
    countries = snakemake.params.countries
    e_1990 = co2_emissions_year(
        countries,
        input_eurostat,
        options,
        emissions_scope,
        input_co2,
        year=1990,
    )
    emissions = historical_emissions(countries)
    # add other years https://sdi.eea.europa.eu/data/0569441f-2853-4664-a7cd-db969ef54de0
    emissions.loc[2019] = 3.414362
    emissions.loc[2020] = 3.092434
    emissions.loc[2021] = 3.290418
    emissions.loc[2022] = 3.213025

    if snakemake.config["foresight"] == "myopic":
        path_cb = "results/" + snakemake.params.RDIR + "/csvs/"
        co2_cap = pd.read_csv(path_cb + "carbon_budget_distribution.csv", index_col=0)[
            ["cb"]
        ]
        co2_cap *= e_1990
    else:
        supply_energy = pd.read_csv(
            snakemake.input.balances, index_col=[0, 1, 2], header=[0, 1, 2, 3]
        )
        co2_cap = (
            supply_energy.loc["co2"].droplevel(0).drop("co2").sum().unstack().T / 1e9
        )
        co2_cap.rename(index=lambda x: int(x), inplace=True)

    plt.figure(figsize=(10, 7))
    gs1 = gridspec.GridSpec(1, 1)
    ax1 = plt.subplot(gs1[0, 0])
    ax1.set_ylabel("CO$_2$ emissions \n [Gt per year]", fontsize=22)
    # ax1.set_ylim([0, 5])
    ax1.set_xlim([1990, snakemake.params.planning_horizons[-1] + 1])

    ax1.plot(emissions, color="black", linewidth=3, label=None)

    # plot committed and under-discussion targets
    # (notice that historical emissions include all countries in the
    # network, but targets refer to EU)
    ax1.plot(
        [2020],
        [0.8 * emissions[1990]],
        marker="*",
        markersize=12,
        markerfacecolor="black",
        markeredgecolor="black",
    )

    ax1.plot(
        [2030],
        [0.45 * emissions[1990]],
        marker="*",
        markersize=12,
        markerfacecolor="black",
        markeredgecolor="black",
    )

    ax1.plot(
        [2030],
        [0.6 * emissions[1990]],
        marker="*",
        markersize=12,
        markerfacecolor="black",
        markeredgecolor="black",
    )

    ax1.plot(
        [2050, 2050],
        [x * emissions[1990] for x in [0.2, 0.05]],
        color="gray",
        linewidth=2,
        marker="_",
        alpha=0.5,
    )

    ax1.plot(
        [2050],
        [0.0 * emissions[1990]],
        marker="*",
        markersize=12,
        markerfacecolor="black",
        markeredgecolor="black",
        label="EU committed target",
    )

    for col in co2_cap.columns:
        ax1.plot(co2_cap[col], linewidth=3, label=col)

    ax1.legend(
        fancybox=True, fontsize=18, loc=(0.01, 0.01), facecolor="white", frameon=True
    )

    plt.grid(axis="y")
    path = snakemake.output.balances.split("balances")[0] + "carbon_budget.svg"
    plt.savefig(path, bbox_inches="tight")
    plt.close()


if __name__ == "__main__":
    if "snakemake" not in globals():
        from scripts._helpers import mock_snakemake

        snakemake = mock_snakemake("plot_summary", run="KN2045_Mix")

    configure_logging(snakemake)
    set_scenario_config(snakemake)

    n_header = 3

    plot_costs()

    plot_energy()

    plot_balances()

    co2_budget = snakemake.params["co2_budget"]
    if (
        isinstance(co2_budget, str) and co2_budget.startswith("cb")
    ) or snakemake.params["foresight"] == "perfect":
        options = snakemake.params.sector
        plot_carbon_budget_distribution(snakemake.input.eurostat, options)
