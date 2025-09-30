# SPDX-FileCopyrightText: 2023-2025 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
from pathlib import Path

from evals.constants import DataModel as DM
from evals.fileio import Exporter
from evals.statistic import collect_myopic_statistics
from evals.utils import (
    get_heat_loss_factor,
    split_urban_central_heat_losses_and_consumption,
)
from evals.views.common import (
    get_energy_for_heat_production,
    simple_bus_balance,
)


def view_balance_carbon(
    result_path: str | Path,
    networks: dict,
    config: dict,
) -> None:
    """
    Evaluate and export the carbon balance showing CO2 flows in the energy system.

    This function analyzes CO2 emissions, sequestration, and storage by calculating
    the balance of carbon flows across the network. It delegates to the simple_bus_balance
    function to collect and export supply and withdrawal statistics for CO2 buses.

    Parameters
    ----------
    result_path
        Path where the evaluation results will be saved.
    networks
        Dictionary containing PyPSA network objects, typically keyed by year or scenario.
    config
        Configuration dictionary containing view settings including bus_carrier specification,
        chart type, and export parameters.
    """
    simple_bus_balance(networks, config, result_path)


def view_balance_electricity(
    result_path: str | Path,
    networks: dict,
    config: dict,
) -> None:
    """
    Evaluate and export electricity production and demand by country and year.

    This function calculates the electricity balance showing generation sources and
    consumption patterns across the network. It delegates to the simple_bus_balance
    function to collect and export supply and withdrawal statistics for electricity buses.

    Parameters
    ----------
    result_path
        Path where the evaluation results will be saved.
    networks
        Dictionary containing PyPSA network objects, typically keyed by year or scenario.
    config
        Configuration dictionary containing view settings including bus_carrier specification,
        chart type, and export parameters.

    Notes
    -----
    Balances do not add up to zero, because of domestic transmission losses.
    """
    simple_bus_balance(networks, config, result_path)


def view_balance_heat(
    result_path: str | Path,
    networks: dict,
    config: dict,
) -> None:
    """
    Evaluate and export the heat balance showing heat production and consumption.

    This function calculates the heat balance for specified heat bus carriers (urban central,
    urban decentral, rural heat) by analyzing link energy flows and load withdrawals. Heat
    supply is determined from link energy balance data, showing the input energy carriers
    feeding heat production. Heat demand includes consumption loads, with central heat losses
    separated from actual consumption. The function exports both supply and demand data with
    appropriate chart formatting based on the configured chart type.

    Parameters
    ----------
    result_path
        Path where the evaluation results will be saved.
    networks
        Dictionary containing PyPSA network objects, typically keyed by year or scenario.
    config
        Configuration dictionary containing view settings including bus_carrier specification,
        chart type, and export parameters. Must specify heat bus carriers in config["view"]["bus_carrier"].

    Notes
    -----
    Heat supply is calculated from link energy balances, excluding CO2 flows. For urban
    central heat, distribution losses are separated from consumption using heat loss factors.
    The function supports both ESMGroupedBarChart (preserving individual bus carriers) and
    ESMBarChart (aggregating bus carriers) visualization modes.
    """
    bus_carrier = config["view"]["bus_carrier"]

    heat_mix = get_energy_for_heat_production(networks, drop_regex=None)
    heat_mix = heat_mix.swaplevel(DM.CARRIER, DM.BUS_CARRIER)
    heat_mix.index.names = DM.YEAR_IDX_NAMES

    generator_supply = collect_myopic_statistics(
        networks,
        statistic="supply",
        comps="Generator",
        bus_carrier=bus_carrier,
    )

    heat_loss_factor = get_heat_loss_factor(networks)
    demand = (
        collect_myopic_statistics(
            networks,
            statistic="withdrawal",
            bus_carrier=bus_carrier,
        )
        .pipe(split_urban_central_heat_losses_and_consumption, heat_loss_factor)
        .mul(-1)
    )

    exporter = Exporter(
        statistics=[heat_mix, demand, generator_supply], view_config=config["view"]
    )
    exporter.export(result_path, config["global"]["subdir"])


def view_balance_hydrogen(
    result_path: str | Path,
    networks: dict,
    config: dict,
) -> None:
    """
    Evaluate and export the hydrogen balance showing H2 production and consumption.

    This function analyzes hydrogen flows in the energy system, including production
    from electrolyzers and other sources, as well as consumption from fuel cells,
    industrial processes, and other hydrogen-using technologies. It delegates to the
    simple_bus_balance function to collect and export supply and withdrawal statistics
    for hydrogen buses.

    Parameters
    ----------
    result_path
        Path where the evaluation results will be saved.
    networks
        Dictionary containing PyPSA network objects, typically keyed by year or scenario.
    config
        Configuration dictionary containing view settings including bus_carrier specification,
        chart type, and export parameters.
    """
    simple_bus_balance(networks, config, result_path)


def view_balance_methane(
    result_path: str | Path,
    networks: dict,
    config: dict,
) -> None:
    """
    Evaluate and export the methane balance showing natural gas and biogas flows.

    This function analyzes methane (CH4) flows in the energy system, including natural gas
    supply from pipelines and storage, biogas production, methanation processes, and
    consumption in gas boilers, combined heat and power plants, and other gas-consuming
    technologies. It delegates to the simple_bus_balance function to collect and export
    supply and withdrawal statistics for methane buses.

    Parameters
    ----------
    result_path
        Path where the evaluation results will be saved.
    networks
        Dictionary containing PyPSA network objects, typically keyed by year or scenario.
    config
        Configuration dictionary containing view settings including bus_carrier specification,
        chart type, and export parameters.
    """
    simple_bus_balance(networks, config, result_path)


def view_balance_biomass(
    result_path: str | Path,
    networks: dict,
    config: dict,
) -> None:
    """
    Evaluate and export the solid biomass balance showing biomass supply and consumption.

    This function analyzes solid biomass flows in the energy system, including biomass
    supply from forestry and agriculture, biomass imports, and consumption in biomass
    boilers, combined heat and power plants, and other biomass-using technologies. It
    delegates to the simple_bus_balance function to collect and export supply and
    withdrawal statistics for solid biomass buses.

    Parameters
    ----------
    result_path
        Path where the evaluation results will be saved.
    networks
        Dictionary containing PyPSA network objects, typically keyed by year or scenario.
    config
        Configuration dictionary containing view settings including bus_carrier specification,
        chart type, and export parameters.
    """
    simple_bus_balance(networks, config, result_path)


def view_balance_fuels(
    result_path: str | Path,
    networks: dict,
    config: dict,
) -> None:
    # show balances for coal, lignite, oil, waste, solid biomass, and other fuels
    # (any fuel that goes in to thermal powerplants or CHPs) in a grouped barchart
    # exclude gas and hydrogen, they have separate balance views
    simple_bus_balance(networks, config, result_path)

    # supply, demand, trade_statistics = get_supply_demand_trade_energy(networks, config)
    # statistics = [supply, demand] + trade_statistics
    #
    # bus_carrier_groups = {
    #     "coal": "Coal",
    #     "lignite": "Coal",
    #     "non-sequestered HVC": "Waste",
    # }
    #
    # statistics = [
    #     rename_aggregate(stat, bus_carrier_groups, level=DM.BUS_CARRIER)
    #     for stat in statistics
    # ]
    #
    # exporter = Exporter(statistics=statistics, view_config=config["view"])
    # exporter.export(result_path, config["global"]["subdir"])
