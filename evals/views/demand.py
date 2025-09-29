# SPDX-FileCopyrightText: 2023-2025 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
from pathlib import Path

import pandas as pd

from evals import plots as plots
from evals.constants import BusCarrier, DataModel
from evals.fileio import Exporter
from evals.statistic import collect_myopic_statistics
from evals.utils import (
    calculate_input_share,
    drop_from_multtindex_by_regex,
    filter_by,
    filter_for_carrier_connected_to,
    get_heat_loss_factor,
    rename_aggregate,
)


def get_energy_for_heat_production(networks: dict) -> pd.Series:
    """
    Calculate the energy input share for heat production across all heat bus carriers.

    This function analyzes the energy balance of link components connected to heat buses
    to determine the input energy carrier mix used for heat production. It processes
    energy balance data by filtering for heat-related carriers and calculating input
    shares for each heat bus carrier type.

    Parameters
    ----------
    networks
        Dictionary containing PyPSA network objects, typically keyed by year or scenario.
        Each network should contain Link components with energy balance data.

    Returns
    -------
    :
        Series containing energy input shares for heat production, indexed by year,
        location, and bus carrier. Only positive values are included. The series has
        'MWh_th' units set in attrs.

    Notes
    -----
    The function excludes CO2 and CO2 storage carriers, as well as water storage
    components (tanks and pits) from the analysis. It focuses specifically on
    energy carriers that directly contribute to heat production.
    """
    energy_balance = (
        collect_myopic_statistics(networks, comps="Link", statistic="energy_balance")
        .drop(["co2", "co2 stored"], level=DataModel.BUS_CARRIER)
        .pipe(drop_from_multtindex_by_regex, "water tanks|water pits")
        .pipe(filter_for_carrier_connected_to, BusCarrier.heat_buses())
    )
    heat_mix = pd.concat(
        [
            calculate_input_share(energy_balance, bc).pipe(rename_aggregate, bc)
            for bc in BusCarrier.heat_buses()
        ]
    )
    heat_mix = heat_mix[heat_mix > 0]  # supply only
    heat_mix.attrs["unit"] = "MWh_th"  # overwrite mixed units

    return heat_mix


def view_demand_heat(
    result_path: str | Path,
    networks: dict,
    config: dict,
    subdir: str | Path = "evaluation",
) -> None:
    """
    Evaluate and export energy required for heat production and generation.

    This function analyzes the energy input mix used for heat production by combining
    data from both link components (for heat production technologies like heat pumps,
    boilers) and generator components (for direct heat generation). Results are grouped
    by bus_carrier rather than carrier to show the input energy carrier mix for each
    type of heat bus. The output includes charts and Excel exports showing the energy
    balance for heat production across different heat technologies and carriers.

    Parameters
    ----------
    result_path
        Path where the evaluation results (plots and data files) will be saved.
    networks
        Dictionary containing PyPSA network objects, typically keyed by year or scenario.
        Each network should contain Link and Generator components with energy data.
    config
        Configuration dictionary containing view settings and chart specifications.
        Must include 'view' key with chart type and other plotting parameters.
    subdir
        Subdirectory name within result_path where outputs will be saved.

    Notes
    -----
    The function combines two data sources:
    1. Energy input for heat production from Link components (from get_energy_for_heat_production)
    2. Direct heat supply from Generator components connected to heat buses

    The data is organized by bus_carrier (heat bus types) rather than the usual carrier
    grouping to provide insight into the energy mix feeding different heat systems
    (urban central, urban decentral, rural heat). Index levels are swapped between
    carrier and bus_carrier to facilitate plotting with the specified chart class.
    """
    fed_for_heat = get_energy_for_heat_production(networks)

    generator_supply = collect_myopic_statistics(
        networks,
        statistic="supply",
        comps="Generator",
        bus_carrier=BusCarrier.heat_buses(),
    )
    # swap index levels to keep carrier information during plotting
    generator_supply = generator_supply.swaplevel(
        DataModel.CARRIER, DataModel.BUS_CARRIER
    )
    generator_supply.index.names = DataModel.YEAR_IDX_NAMES

    exporter = Exporter(
        statistics=[fed_for_heat, generator_supply],
        view_config=config["view"],
    )

    # view specific static settings:
    chart_class = getattr(plots, config["view"]["chart"])
    exporter.defaults.plotly.chart = chart_class

    exporter.defaults.excel.pivot_index = [DataModel.LOCATION, DataModel.BUS_CARRIER]
    exporter.defaults.plotly.plot_category = DataModel.BUS_CARRIER
    exporter.defaults.plotly.pivot_index = [
        DataModel.YEAR,
        DataModel.LOCATION,
        DataModel.BUS_CARRIER,
    ]

    exporter.export(result_path, subdir=subdir)


def view_demand_heat_system(
    result_path: str | Path,
    networks: dict,
    config: dict,
    subdir: str | Path = "evaluation",
) -> None:
    """
    Evaluate and export heat system energy flows with carrier-focused visualization.

    This function analyzes the complete heat system by combining energy input for heat
    production from Link components with direct heat generation from Generator components
    (specifically solar thermal). Unlike view_demand_heat(), this function organizes
    results by carrier rather than bus_carrier to provide insight into the energy
    sources feeding the heat system. Solar heat generation is specifically aggregated
    and labeled for clear identification in the output.

    Parameters
    ----------
    result_path
        Path where the evaluation results (plots and data files) will be saved.
    networks
        Dictionary containing PyPSA network objects, typically keyed by year or scenario.
        Each network should contain Link and Generator components with energy data.
    config
        Configuration dictionary containing view settings and chart specifications.
        Must include 'view' key with chart type and other plotting parameters.
    subdir
        Subdirectory name within result_path where outputs will be saved.

    Notes
    -----
    The function combines two data sources:
    1. Energy input for heat production from Link components (from get_energy_for_heat_production)
    2. Solar heat generation from Generator components, aggregated as "solar heat"

    Key differences from view_demand_heat():
    - Results organized by carrier (energy source) rather than bus_carrier (heat bus type)
    - Generator supply specifically renamed to "solar heat" for clarity
    - Index levels swapped to prioritize carrier information during visualization
    - Simplified chart configuration without specific pivot settings

    This view is particularly useful for understanding the overall energy source mix
    feeding the heat system across all heat bus types.
    """
    fed_for_heat = get_energy_for_heat_production(networks)
    # swap index levels to keep carrier information during plotting
    fed_for_heat = fed_for_heat.swaplevel(DataModel.CARRIER, DataModel.BUS_CARRIER)
    fed_for_heat.index.names = DataModel.YEAR_IDX_NAMES
    generator_supply = collect_myopic_statistics(
        networks,
        statistic="supply",
        comps="Generator",
        bus_carrier=BusCarrier.heat_buses(),
    ).pipe(rename_aggregate, "solar heat")

    exporter = Exporter(
        statistics=[fed_for_heat, generator_supply],
        view_config=config["view"],
    )

    exporter.defaults.plotly.chart = getattr(plots, config["view"]["chart"])
    exporter.defaults.plotly.xaxis_title = ""
    exporter.export(result_path, subdir=subdir)


def view_demand_fed(
    result_path: str | Path,
    networks: dict,
    config: dict,
    subdir: str | Path = "evaluation",
) -> None:
    """
    Evaluate and export final energy demand (FED) by sector and location.

    This function calculates final energy demand across different sectors including
    transport, industry, agriculture, and households & services. It processes load
    data from PyPSA networks, applies heat mix calculations for decentral heating,
    accounts for distribution losses in central heat systems, and aggregates results
    by sector. The output includes charts and Excel exports showing energy demand
    per bus carrier with years as stacked bars grouped by sector.

    Parameters
    ----------
    result_path
        Path where the evaluation results (plots and data files) will be saved.
    networks
        Dictionary containing PyPSA network objects, typically keyed by year or scenario.
        Each network should contain Load and Link components with energy data.
    config
        Configuration dictionary containing view settings and chart specifications.
        Must include 'view' key with chart type and other plotting parameters.
    subdir
        Subdirectory name within result_path where outputs will be saved.

    Notes
    -----
    The function processes several energy sectors:
    - Transport: Includes shipping, aviation, and land transport (including EVs)
    - Industry: Industrial loads and low-temperature heat, including NH3 production
    - Agriculture: Agricultural loads with heat mix applied to decentral heating
    - HH & Service: Household and service loads including building heat and base electricity

    Central heat loads are reduced by distribution losses since these losses are not
    counted as final energy demand. Decentral heat buses (rural and urban decentral)
    use calculated heat mix ratios to determine the input energy carrier breakdown.

    The function exports results using the Exporter class with GroupedBarChart
    visualization where carrier and bus_carrier index levels are swapped for
    simplified plotting.
    """
    decentral_heat_bus_carrier = [
        BusCarrier.HEAT_RURAL,
        BusCarrier.HEAT_URBAN_DECENTRAL,
    ]
    # calculate the heat production share per bus_carrier. Cannot use
    # get_energy_for_heat_production() because it calculates for all bus_carrier
    decentral_production = (
        collect_myopic_statistics(networks, comps="Link", statistic="energy_balance")
        .drop(["co2", "co2 stored"], level=DataModel.BUS_CARRIER)
        .pipe(drop_from_multtindex_by_regex, "water tanks|water pits")
        .pipe(filter_for_carrier_connected_to, decentral_heat_bus_carrier)
        .pipe(calculate_input_share, decentral_heat_bus_carrier)
        .pipe(rename_aggregate, "heat_mix")
    )
    decentral_production = decentral_production[decentral_production > 0]

    decentral_generation = (
        collect_myopic_statistics(
            networks,
            "supply",
            comps="Generator",
            bus_carrier=decentral_heat_bus_carrier,
        )
        .pipe(rename_aggregate, "heat_mix")
        .pipe(rename_aggregate, "solar heat", level=DataModel.BUS_CARRIER)
    )

    decentral_heat_mix = pd.concat([decentral_production, decentral_generation])

    heat_share = decentral_heat_mix / decentral_heat_mix.groupby(
        [DataModel.YEAR, DataModel.LOCATION]
    ).transform("sum")

    loads = collect_myopic_statistics(networks, "withdrawal", comps="Load")

    # reduce central heat loads by distribution losses. Distribution losses
    # are not metered and do not count as final energy demand
    loss_factor = get_heat_loss_factor(networks)
    central_heat_loads = filter_by(loads, bus_carrier="urban central heat")
    loads.loc[central_heat_loads.index] = central_heat_loads / (1 + loss_factor)

    # transport Loads are final energy
    transport = loads.filter(regex="transport|shipping|aviation")
    # no need to harmonize V2g:
    # bev_load = filter_by(transport, bus_carrier="EV battery")
    # v2g_demand = collect_myopic_statistics(networks, "withdrawal", comps="Link", bus_carrier="EV battery")
    # bev_charger = collect_myopic_statistics(networks, "supply", comps="Link", bus_carrier="EV battery")
    # bev_charger.loc[("2050", "SE")].item() - v2g_demand.loc[("2050", "SE")].item()
    # bev_load.loc[("2050", "SE")].item()
    # --> they are equal, and we simply use the load

    # agriculture contains final energy Loads and useful energy Loads (heat)
    agriculture = loads.filter(regex="agriculture")
    agriculture = apply_heat_mix_to_decentral_heat_buses(agriculture, heat_share)

    # industry contains FED and useful energy (low-temperature heat for industry)
    industry = loads.filter(regex="industry|NH3")
    industry = apply_heat_mix_to_decentral_heat_buses(industry, heat_share)
    # todo: include methane losses due to `gas for industry CC`

    # electricity base load contains loads not split
    base_load = filter_by(loads, carrier="electricity")
    # todo: base load splitting

    # heat for buildings
    heat = filter_by(loads, carrier=BusCarrier.heat_buses())
    # filter by 'carrier' not 'bus_carrier' to prevent capturing agriculture or industry loads
    heat = apply_heat_mix_to_decentral_heat_buses(heat, heat_share)

    fed = pd.concat(
        [
            rename_aggregate(transport, "Transport"),
            rename_aggregate(industry, "Industry"),
            rename_aggregate(agriculture, "Agriculture"),
            rename_aggregate(base_load, "HH & Service"),
            rename_aggregate(heat, "HH & Service"),
        ]
    )
    fed.attrs["unit"] = "MWh"
    fed.attrs["name"] = "FED"

    # swap carrier and bus_carrier to simplify plotting with GroupedBarChart
    fed = fed.swaplevel(DataModel.CARRIER, DataModel.BUS_CARRIER)
    fed.index.names = DataModel.YEAR_IDX_NAMES

    exporter = Exporter(
        statistics=[fed],
        view_config=config["view"],
    )
    exporter.defaults.plotly.chart = getattr(plots, config["view"]["chart"])
    exporter.defaults.plotly.xaxis_title = ""
    exporter.export(result_path, subdir=subdir)


def apply_heat_mix_to_decentral_heat_buses(
    load: pd.Series, heat_share: pd.Series
) -> pd.Series:
    """

    Parameters
    ----------
    load
    heat_share

    Returns
    -------
    :
    """
    decentral_heat = load.filter(regex="decentral|rural")

    load = load.drop(decentral_heat.index)

    to_concat = [load]
    for (year, location, carrier), data in decentral_heat.groupby(
        [DataModel.YEAR, DataModel.LOCATION, DataModel.CARRIER]
    ):
        ratios = filter_by(heat_share, year=year, location=location)
        result = data.item() * ratios
        to_concat.append(rename_aggregate(result, carrier))

    return pd.concat(to_concat)
