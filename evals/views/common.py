# SPDX-FileCopyrightText: 2023-2025 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
from pathlib import Path

import pandas as pd

from evals.constants import BusCarrier, DataModel, Group, TradeTypes
from evals.constants import DataModel as DM
from evals.fileio import Exporter
from evals.statistic import collect_myopic_statistics
from evals.utils import (
    calculate_input_share,
    drop_from_multtindex_by_regex,
    filter_by,
    filter_for_carrier_connected_to,
    get_storage_carriers,
    get_transmission_techs,
    regionalize_statistics,
    rename_aggregate,
)


def simple_bus_balance(
    networks: dict,
    config: dict,
    result_path,
) -> None:
    """
    Calculate and export simple bus balance statistics for energy supply and demand.

    This function computes the energy balance for specified bus carriers by collecting
    supply and withdrawal statistics, filtering out transmission components, and handling
    storage links. It also calculates trade statistics for both foreign and domestic
    imports and exports, then exports all data according to the view configuration.

    Parameters
    ----------
    networks
        Dictionary containing PyPSA network objects, typically keyed by year or scenario.
    config
        Configuration dictionary containing view settings including bus_carrier, storage_links,
        and export parameters.
    result_path
        Path where the evaluation results will be saved.

    Notes
    -----
    Supply values are positive and represent energy production or imports.
    Demand values are negated to show as negative for visualization purposes.
    The function exports data via Exporter using configured format settings.
    """
    (
        bus_carrier,
        transmission_comps,
        transmission_carrier,
        storage_carrier,
        storage_links,
    ) = _parse_view_config_items(networks, config)

    supply = collect_myopic_statistics(
        networks,
        statistic="supply",
        bus_carrier=bus_carrier,
        aggregate_components=None,
    ).pipe(
        filter_by,
        component=transmission_comps,
        carrier=transmission_carrier,
        exclude=True,
    )
    storage_supply = filter_by(
        supply, component=("Store", "StorageUnit"), carrier=storage_carrier
    )
    supply = pd.concat(
        [
            supply.drop(storage_supply.index),
            rename_aggregate(storage_supply, Group.storage_out),
        ]
    ).droplevel(DM.COMPONENT)

    # quick fix to allow mixed bus_carrier units
    if supply.attrs["unit"] == "carrier dependent":
        supply.attrs["unit"] = "MWh"

    demand = (
        collect_myopic_statistics(
            networks,
            statistic="withdrawal",
            bus_carrier=bus_carrier,
            aggregate_components=None,
        )
        .pipe(
            filter_by,
            component=transmission_comps,
            carrier=transmission_carrier,
            exclude=True,
        )
        # .pipe(rename_aggregate, dict.fromkeys(storage_links, Group.storage_in))
        .mul(-1)
        # .droplevel(DM.COMPONENT)
    )
    storage_demand = filter_by(
        demand, component=("Store", "StorageUnit"), carrier=storage_carrier
    )
    demand = pd.concat(
        [
            demand.drop(storage_demand.index),
            rename_aggregate(storage_demand, Group.storage_in),
        ]
    ).droplevel(DM.COMPONENT)

    if demand.attrs["unit"] == "carrier dependent":
        demand.attrs["unit"] = supply.attrs["unit"]

    regional_trade = [
        regionalize_statistics(supply, demand, bus_carrier).droplevel(
            DataModel.COMPONENT
        )
        for bus_carrier in BusCarrier.eu_buses()
    ]
    # drop all supply with EU location. They are in regional_trade.
    supply = filter_by(supply, location="EU", exclude=True)
    demand = filter_by(demand, location="EU", exclude=True)

    trade_statistics = []
    for scope, direction, alias in [
        (TradeTypes.FOREIGN, "import", Group.import_foreign),
        (TradeTypes.FOREIGN, "export", Group.export_foreign),
        (TradeTypes.DOMESTIC, "import", Group.import_domestic),
        (TradeTypes.DOMESTIC, "export", Group.export_domestic),
    ]:
        trade = (
            collect_myopic_statistics(
                networks,
                statistic="trade_energy",
                scope=scope,
                direction=direction,
                bus_carrier=bus_carrier,
                aggregate_components=None,
            )
            # the trade statistic finds transmission between EU -> country buses.
            # Those are dropped by the filter_by statement.
            .pipe(
                filter_by,
                component=transmission_comps,
                carrier=transmission_carrier,
            )
            .pipe(rename_aggregate, alias)
            .droplevel(DM.COMPONENT)
        )
        trade.attrs["unit"] = supply.attrs["unit"]
        trade_statistics.append(trade)

    # group bus carriers by groups defined in config.toml
    statistics = [supply, demand] + trade_statistics + regional_trade
    if bus_carrier_groups := config["view"].get("bus_carrier_groups", {}):
        statistics = [
            rename_aggregate(stat, bus_carrier_groups, level=DM.BUS_CARRIER)
            for stat in statistics
        ]

    exporter = Exporter(statistics=statistics, view_config=config["view"])
    exporter.export(result_path, config["global"]["subdir"])


def simple_timeseries(
    networks: dict,
    config: dict,
    result_path: str | Path,
) -> None:
    """
    Calculate and export time series data for energy supply, demand, and trade balance.

    This function collects hourly time series statistics for supply and withdrawal,
    along with net trade saldo (imports minus exports) for specified bus carriers.
    Unlike simple_bus_balance, this function preserves temporal resolution and does
    not aggregate over time periods.

    Parameters
    ----------
    networks
        Dictionary containing PyPSA network objects, typically keyed by year or scenario.
    config
        Configuration dictionary containing view settings including bus_carrier, storage_links,
        and export parameters.
    result_path
        Path where the evaluation results will be saved.

    Notes
    -----
    Trade saldo combines both foreign and domestic trade into a single net balance.
    Time series data is not aggregated over time, preserving hourly or sub-hourly resolution.
    This function is useful for analyzing temporal patterns and system operation.
    """
    (
        bus_carrier,
        transmission_comps,
        transmission_carrier,
        storage_carrier,
        storage_links,
    ) = _parse_view_config_items(networks, config)

    supply = (
        collect_myopic_statistics(
            networks,
            statistic="supply",
            bus_carrier=bus_carrier,
            aggregate_time=False,
            aggregate_components=None,
        )
        .pipe(
            filter_by,
            component=transmission_comps,
            carrier=transmission_carrier,
            exclude=True,
        )
        .pipe(
            # combine all bus carrier to export netted technologies
            rename_aggregate,
            bus_carrier[0],
            level=DM.BUS_CARRIER,
        )
    )
    storage_supply = filter_by(
        supply, component=("Store", "StorageUnit"), carrier=storage_carrier
    )
    supply = pd.concat(
        [
            supply.drop(storage_supply.index),
            rename_aggregate(storage_supply, Group.storage_out),
        ]
    ).droplevel(DM.COMPONENT)

    demand = (
        collect_myopic_statistics(
            networks,
            statistic="withdrawal",
            bus_carrier=bus_carrier,
            aggregate_time=False,
            aggregate_components=None,
        )
        .pipe(
            filter_by,
            component=transmission_comps,
            carrier=transmission_carrier,
            exclude=True,
        )
        .pipe(
            # combine all bus carrier to export netted technologies
            rename_aggregate,
            bus_carrier[0],
            level=DM.BUS_CARRIER,
        )
        .mul(-1)
    )

    storage_demand = filter_by(
        demand, component=("Store", "StorageUnit"), carrier=storage_carrier
    )
    demand = pd.concat(
        [
            demand.drop(storage_demand.index),
            rename_aggregate(storage_demand, Group.storage_in),
        ]
    ).droplevel(DM.COMPONENT)

    if storage_links:
        supply = rename_aggregate(
            supply, dict.fromkeys(storage_links, Group.storage_out), level=DM.CARRIER
        )
        demand = rename_aggregate(
            demand, dict.fromkeys(storage_links, Group.storage_in), level=DM.CARRIER
        )

    # calculated netted storage time series for time series graphs
    storage_supply = filter_by(supply, carrier=Group.storage_out).pipe(
        rename_aggregate, "Storage"
    )
    supply = supply.drop(Group.storage_out, level=DataModel.CARRIER)
    storage_demand = filter_by(demand, carrier=Group.storage_in).pipe(
        rename_aggregate, "Storage"
    )
    demand = demand.drop(Group.storage_in, level=DataModel.CARRIER)
    storage_balance = storage_supply.add(storage_demand, fill_value=0)
    storage_in = rename_aggregate(
        storage_balance[storage_balance < 0], Group.storage_in
    )
    storage_out = rename_aggregate(
        storage_balance[storage_balance > 0], Group.storage_out
    )

    trade_saldo = (
        collect_myopic_statistics(
            networks,
            statistic="trade_energy",
            scope=(TradeTypes.FOREIGN, TradeTypes.DOMESTIC),
            direction="saldo",
            bus_carrier=bus_carrier,
            aggregate_time=False,
            aggregate_components=None,
        )
        .pipe(
            filter_by,
            component=transmission_comps,
            carrier=transmission_carrier,
        )
        .droplevel(DM.COMPONENT)
    )
    trade_saldo.attrs["unit"] = supply.attrs["unit"]
    trade_saldo = rename_aggregate(trade_saldo, trade_saldo.attrs["name"])

    exporter = Exporter(
        statistics=[supply, demand, trade_saldo, storage_in, storage_out],
        view_config=config["view"],
    )

    exporter.export(result_path, config["global"]["subdir"])


def simple_optimal_capacity(
    networks: dict, config: dict, result_path: str | Path, kind: str = None
) -> None:
    """
    Calculate and export optimal capacity statistics for energy system components.

    This function collects optimal capacity data for components connected to specified
    bus carriers, filtering out transmission and storage links. The capacity data can be
    filtered to show only production capacities (positive values), demand capacities
    (negative values), or both.

    Parameters
    ----------
    networks
        Dictionary containing PyPSA network objects, typically keyed by year or scenario.
    config
        Configuration dictionary containing view settings including bus_carrier, storage_links,
        and export parameters.
    result_path
        Path where the evaluation results will be saved.
    kind
        Optional filter for capacity type. Use "production" for positive capacities only,
        "demand" for negative capacities only, or None for both.

    Notes
    -----
    The function corrects a known issue where optimal_capacity returns MWh units
    instead of MW units, by replacing the unit string accordingly.
    """
    (
        bus_carrier,
        transmission_comps,
        transmission_carrier,
        storage_carrier,
        storage_links,
    ) = _parse_view_config_items(networks, config)

    optimal_capacity = (
        collect_myopic_statistics(
            networks,
            statistic="optimal_capacity",
            bus_carrier=bus_carrier,
            aggregate_components=None,
        )
        .pipe(
            filter_by,
            component=transmission_comps,
            carrier=transmission_carrier,
            exclude=True,
        )
        .pipe(
            filter_by,
            component=("Store", "StorageUnit"),
            carrier=storage_carrier,
            exclude=True,
        )
        .pipe(
            filter_by,
            component=("Link", "Generator"),
            # Include Generator to drop heat vents
            carrier=storage_links,
            exclude=True,
        )
        .droplevel(DM.COMPONENT)
    )

    if kind == "production":
        optimal_capacity = optimal_capacity[optimal_capacity > 0]
    elif kind == "demand":
        optimal_capacity = optimal_capacity[optimal_capacity < 0]

    # 'optimal_capacity' wrongly returns MWh as a unit, but it is MW.
    optimal_capacity.attrs["unit"] = optimal_capacity.attrs["unit"].replace("MWh", "MW")

    exporter = Exporter(
        statistics=[optimal_capacity],
        view_config=config["view"],
    )

    # # view specific constant settings
    # chart_class = getattr(plots, config["view"]["chart"])
    # exporter.defaults.plotly.chart = chart_class
    #
    # if chart_class == plots.ESMGroupedBarChart:
    #     exporter.defaults.plotly.xaxis_title = ""
    # elif chart_class == plots.ESMBarChart:
    #     # combine bus carrier to export netted technologies, although
    #     # they have difference bus_carrier in index, e.g.
    #     # electricity distribution grid, (AC, low voltage)
    #     exporter.statistics = [
    #         rename_aggregate(s, bus_carrier[0], level=DM.BUS_CARRIER)
    #         for s in exporter.statistics
    #     ]

    exporter.export(result_path, config["global"]["subdir"])


def simple_storage_capacity(
    networks: dict, config: dict, result_path: str | Path
) -> None:
    """
    Calculate and export optimal storage capacity statistics.

    This function collects optimal capacity data specifically for storage components
    (stores and storage units) connected to specified bus carriers. It filters the
    results to include only carriers that match the configured storage_links list.

    Parameters
    ----------
    networks
        Dictionary containing PyPSA network objects, typically keyed by year or scenario.
    config
        Configuration dictionary containing view settings including bus_carrier, storage_links,
        and export parameters.
    result_path
        Path where the evaluation results will be saved.

    Notes
    -----
    The function sets cutoff_drop to False to prevent dropping empty years from the output,
    which is important for storage capacity evolution visualization across time periods.
    """
    (
        bus_carrier,
        _,
        _,
        storage_carrier,
        _,
    ) = _parse_view_config_items(networks, config)

    stores = collect_myopic_statistics(
        networks,
        statistic="optimal_capacity",
        bus_carrier=bus_carrier,
        storage=True,
    ).pipe(filter_by, carrier=storage_carrier)

    exporter = Exporter(
        statistics=[stores],
        view_config=config["view"],
    )

    exporter.defaults.plotly.cutoff_drop = False  # prevent dropping empty years
    exporter.export(result_path, config["global"]["subdir"])


def _parse_view_config_items(networks: dict, config: dict) -> tuple:
    """
    Parse and extract view configuration items for statistics collection.

    This internal helper function extracts and processes configuration parameters needed
    for collecting energy statistics from PyPSA networks. It identifies bus carriers,
    transmission components, and storage links that should be filtered or aggregated.

    Parameters
    ----------
    networks
        Dictionary containing PyPSA network objects, used to identify transmission
        technologies and storage carriers.
    config
        Configuration dictionary containing view settings. Must include a "view" key
        with optional "bus_carrier" and "storage_links" parameters.

    Returns
    -------
    :
        Tuple containing (bus_carrier, transmission_comps, transmission_carrier, storage_links).
        bus_carrier is the configured bus carrier filter or None for all carriers.
        transmission_comps is a list of transmission component names to filter.
        transmission_carrier is a list of transmission carrier names to filter.
        storage_carrier is a list of storage carrier names for aggregation.
        storage_links is a list of storage Link carrier names for aggregation.

    Notes
    -----
    TOML configuration files cannot represent None values, so empty strings are
    converted to None for bus_carrier filtering.
    """
    bus_carrier = (
        config["view"]["bus_carrier"] or None
    )  # replace '' by None because TOML has no None type
    transmission_techs = get_transmission_techs(networks, bus_carrier)
    transmission_comps = [comp for comp, carr in transmission_techs]
    transmission_carrier = [carr for comp, carr in transmission_techs]
    storage_carrier = get_storage_carriers(networks)
    storage_links = config["view"].get("storage_links", [])

    return (
        bus_carrier,
        transmission_comps,
        transmission_carrier,
        storage_carrier,
        storage_links,
    )


def get_energy_for_heat_production(
    networks: dict, drop_regex: str = "water tanks|water pits"
) -> pd.Series:
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
    drop_regex
        A regular expression to exclude certain carriers from analysis.

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
        .pipe(drop_from_multtindex_by_regex, drop_regex)
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


# def get_supply_demand_trade_energy(networks: dict, config: dict):
#     """
#     Calculate and return supply, demand, and trade energy statistics without exporting.
#
#     This function is similar to simple_bus_balance but returns the statistics as a tuple
#     instead of exporting them directly. It computes energy supply, withdrawal (demand),
#     and trade statistics for foreign and domestic imports and exports. This is useful
#     when the statistics need to be further processed before export.
#
#     Parameters
#     ----------
#     networks
#         Dictionary containing PyPSA network objects, typically keyed by year or scenario.
#     config
#         Configuration dictionary containing view settings including bus_carrier, storage_links,
#         and export parameters.
#
#     Returns
#     -------
#     :
#         Tuple containing (supply, demand, trade_statistics).
#         supply is a Series with positive energy production values.
#         demand is a Series with negative energy consumption values.
#         trade_statistics is a list of Series containing import and export data for
#         both foreign and domestic trade.
#
#     Notes
#     -----
#     Demand values are multiplied by -1 to represent energy consumption as negative values.
#     This function is typically used internally by view functions that need to combine
#     or further process statistics before exporting.
#     """
#     (
#         bus_carrier,
#         transmission_comps,
#         transmission_carrier,
#         storage_links,
#     ) = _parse_view_config_items(networks, config)
#
#     supply = (
#         collect_myopic_statistics(
#             networks,
#             statistic="supply",
#             bus_carrier=bus_carrier,
#             aggregate_components=None,
#         )
#         .pipe(
#             filter_by,
#             component=transmission_comps,
#             carrier=transmission_carrier,
#             exclude=True,
#         )
#         .pipe(rename_aggregate, dict.fromkeys(storage_links, Group.storage_out))
#         .droplevel(DM.COMPONENT)
#     )
#
#     demand = (
#         collect_myopic_statistics(
#             networks,
#             statistic="withdrawal",
#             bus_carrier=bus_carrier,
#             aggregate_components=None,
#         )
#         .pipe(
#             filter_by,
#             component=transmission_comps,
#             carrier=transmission_carrier,
#             exclude=True,
#         )
#         .pipe(rename_aggregate, dict.fromkeys(storage_links, Group.storage_in))
#         .mul(-1)
#         .droplevel(DM.COMPONENT)
#     )
#
#     trade_statistics = []
#     for scope, direction, alias in [
#         (TradeTypes.FOREIGN, "import", Group.import_foreign),
#         (TradeTypes.FOREIGN, "export", Group.export_foreign),
#         (TradeTypes.DOMESTIC, "import", Group.import_domestic),
#         (TradeTypes.DOMESTIC, "export", Group.export_domestic),
#     ]:
#         trade = (
#             collect_myopic_statistics(
#                 networks,
#                 statistic="trade_energy",
#                 scope=scope,
#                 direction=direction,
#                 bus_carrier=bus_carrier,
#                 aggregate_components=None,
#             )
#             # the trade statistic finds transmission between EU -> country buses.
#             # Those are dropped by the filter_by statement.
#             .pipe(
#                 filter_by,
#                 component=transmission_comps,
#                 carrier=transmission_carrier,
#             )
#             .pipe(rename_aggregate, alias)
#             .droplevel(DM.COMPONENT)
#         )
#         trade.attrs["unit"] = supply.attrs["unit"]
#         trade_statistics.append(trade)
#
#         return supply, demand, trade_statistics
