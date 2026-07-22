# SPDX-FileCopyrightText: 2023-2025 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""
Sankey diagram generation for energy system visualization.

This module provides functions to create comprehensive Sankey diagrams from PyPSA
network data, showing energy flows including supply/demand balances, transmission
losses, trade statistics, and regional energy exchanges. The diagrams are exported
as interactive Plotly visualizations with accompanying CSV data files.

The main entry point is `view_sankey.py` which processes PyPSA networks and generates
Sankey diagrams aggregated by year, component, location, and carrier.
"""

import logging
from pathlib import Path

import pandas as pd
from pypsa import NetworkCollection

from evals import plots as plots
from evals.constants import BusCarrier, Group, TradeTypes
from evals.constants import DataModel as DM
from evals.fileio import Exporter
from evals.stats import collect_myopic_statistics
from evals.utils import (
    drop_from_multtindex_by_regex,
    filter_by,
    insert_index_level,
    regionalize_statistics,
    rename_aggregate,
)
from evals.views.common import _parse_view_config_items

logger = logging.getLogger(__file__)

IDX = ["year", "component", "location", "carrier"]
pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 20)
pd.set_option("display.max_rows", 500)


def _process_single_input_link(
    supply: pd.Series,
    demand: pd.Series,
    bc_in: str,
) -> pd.DataFrame:
    """
    Process energy balance for a single bus carrier link.

    Calculates energy losses and surplus heat from supply-demand imbalances
    for a specific bus carrier, labeling losses appropriately and treating
    positive surpluses as ambient heat recovery.

    Parameters
    ----------
    supply
        Supply statistics for the bus carrier.
    demand
        Demand statistics for the bus carrier.
    bc_in
        Bus carrier identifier used for labeling losses.

    Returns
    -------
    :
        Combined series of losses (negative values made positive) and
        surplus heat labeled as ambient heat.
    """
    balance = supply.groupby(IDX).sum() + demand.groupby(IDX).sum()
    losses = balance[balance < 0]
    surplus = balance[balance > 0]
    losses = insert_index_level(losses, f"{bc_in} losses", "bus_carrier", pos=4).mul(-1)
    surplus = insert_index_level(surplus, "ambient heat", "bus_carrier", pos=4)

    return pd.concat([losses, surplus])


def collect_imbalances(supply: pd.Series, demand: pd.Series) -> pd.DataFrame:
    """
    Collect energy imbalances from link connections.

    Processes supply and demand imbalances for multi-carrier links by
    proportionally distributing supply based on demand shares and
    calculating losses for each bus carrier type.

    Parameters
    ----------
    supply
        Link supply statistics across all bus carriers.
    demand
        Link demand statistics across all bus carriers.

    Returns
    -------
    :
        Concatenated series of imbalances including losses and
        carrier-specific supply flows.
    """
    bc_in = demand.index.unique("bus_carrier")

    if len(bc_in) > 1:
        to_concat = []
        for _bc in bc_in:
            demand_bc = filter_by(demand, bus_carrier=_bc)
            demand_share = demand_bc.sum() / demand.sum()
            supply_bc = supply * demand_share
            to_concat.append(_process_single_input_link(supply_bc, demand_bc, _bc))
            mapper = {
                v: f"{v} from {_bc}" for v in supply_bc.index.unique("bus_carrier")
            }
            to_concat.append(rename_aggregate(supply_bc, mapper, level="bus_carrier"))
        return pd.concat(to_concat)

    return _process_single_input_link(supply, demand, bc_in.item())


def get_supply(
    nc: NetworkCollection, transmission_comps: list, transmission_carrier: list
) -> pd.Series:
    """
    Extract and process supply statistics from PyPSA networks.

    Collects supply statistics excluding transmission components, filters out
    CO2 and process emissions, and renames storage components for clarity.

    Parameters
    ----------
    nc
        Dictionary of PyPSA network objects.
    transmission_comps
        List of transmission components to exclude from analysis.
    transmission_carrier
        List of transmission carriers to exclude from analysis.

    Returns
    -------
    :
        Supply statistics series with unit attribute set to MWh.
    """
    supply = (
        collect_myopic_statistics(
            nc,
            "supply",
            aggregate_components=None,
        )
        .pipe(
            filter_by,
            component=transmission_comps,
            carrier=transmission_carrier,
            exclude=True,
        )
        .pipe(
            drop_from_multtindex_by_regex, "co2|process emissions", level="bus_carrier"
        )
        .pipe(
            rename_aggregate,
            {
                "hydro discharger": "hydro supply",
                "PHS discharger": "PHS supply",
                "H2 Store": "H2 Store supply",
                "gas": "gas Store supply",
            },
        )
    )
    supply.attrs["unit"] = "MWh"

    return supply


def get_demand(
    nc: NetworkCollection,
    transmission_comps: list,
    transmission_carrier: list,
    unit: str,
) -> pd.DataFrame:
    """
    Extract and process demand statistics from PyPSA networks.

    Collects withdrawal statistics excluding transmission components,
    includes pipeline compression loads, and processes storage demands.

    Parameters
    ----------
    nc
        Dictionary of PyPSA network objects.
    transmission_comps
        List of transmission components to exclude from analysis.
    transmission_carrier
        List of transmission carriers to exclude from analysis.
    unit
        Unit string for the returned series attributes.

    Returns
    -------
    :
        Demand statistics series including compression loads with
        specified unit attribute.
    """
    withdrawal = collect_myopic_statistics(
        nc,
        "withdrawal",
        aggregate_components=None,
    )
    compressing = (
        withdrawal.to_frame()
        .query("carrier.str.contains('pipeline') and bus_carrier == 'AC'")
        .squeeze()
    )
    demand = (
        filter_by(
            withdrawal,
            component=transmission_comps,
            carrier=transmission_carrier,
            exclude=True,
        )
        .pipe(
            drop_from_multtindex_by_regex, "co2|process emissions", level="bus_carrier"
        )
        .pipe(
            rename_aggregate,
            {
                "PHS charger": "PHS demand",
                "H2 Store": "H2 Store demand",
                "gas": "gas Store demand",
            },
        )
        .mul(-1)
    )

    result = pd.concat([demand, compressing])
    result.attrs["unit"] = unit

    return result


def net_distribution_grid_losses(supply: pd.Series, demand: pd.DataFrame) -> pd.Series:
    """
    Calculate net electricity distribution grid losses.

    Computes grid losses from electricity distribution by summing supply
    and demand for distribution grid carriers, then removes these carriers
    from the input series to avoid double counting.

    Parameters
    ----------
    supply
        Supply statistics series (modified in-place).
    demand
        Demand statistics series (modified in-place).

    Returns
    -------
    :
        Grid losses series with 'losses' bus carrier label.

    Notes
    -----
    This function modifies the input supply and demand series by removing
    'electricity distribution grid' carrier entries.
    """
    grid_losses = (
        filter_by(supply, carrier="electricity distribution grid")
        .groupby(IDX)
        .sum()
        .add(
            filter_by(demand, carrier="electricity distribution grid")
            .groupby(IDX)
            .sum()
        )
    )
    grid_losses = insert_index_level(grid_losses, "losses", "bus_carrier", pos=4)
    supply.drop("electricity distribution grid", level="carrier", inplace=True)
    demand.drop("electricity distribution grid", level="carrier", inplace=True)

    return grid_losses


def get_trade_statistics(
    nc: NetworkCollection,
    transmission_comps: list,
    transmission_carrier: list,
    unit: str,
) -> list[pd.Series]:
    """
    Extract energy trade statistics for foreign and domestic exchanges.

    Collects import/export statistics for both foreign and domestic trade,
    filtering out CO2 emissions and applying appropriate grouping labels.

    Parameters
    ----------
    nc
        Dictionary of PyPSA network objects.
    transmission_comps
        List of transmission components to include in trade analysis.
    transmission_carrier
        List of transmission carriers to include in trade analysis.
    unit
        Unit string for the returned series attributes.

    Returns
    -------
    :
        List of trade statistics series for foreign imports/exports
        and domestic imports/exports.
    """
    trade_statistics = []
    for scope, direction, alias in [
        (TradeTypes.FOREIGN, "import", Group.import_foreign),
        (TradeTypes.FOREIGN, "export", Group.export_foreign),
        (TradeTypes.DOMESTIC, "import", Group.import_domestic),
        (TradeTypes.DOMESTIC, "export", Group.export_domestic),
    ]:
        trade = (
            collect_myopic_statistics(
                nc,
                "trade_energy",
                scope=scope,
                direction=direction,
                aggregate_components=None,
            )
            # the trade statistic finds transmission between EU -> country buses.
            # Those are dropped by the filter_by statement.
            .pipe(
                filter_by,
                component=transmission_comps,
                carrier=transmission_carrier,
            )
            .pipe(drop_from_multtindex_by_regex, "co2", level="bus_carrier")
            .pipe(rename_aggregate, alias)
        )
        trade.attrs["unit"] = unit
        trade_statistics.append(trade)

    return trade_statistics


def get_link_losses(supply: pd.Series, demand: pd.DataFrame) -> list[pd.Series]:
    """
    Calculate losses from Link components.

    Processes each carrier type in Link components to identify conversion
    losses and energy imbalances between supply and demand sides.

    Parameters
    ----------
    supply
        Supply statistics including Link components.
    demand
        Demand statistics including Link components.

    Returns
    -------
    :
        List of imbalance series for each Link carrier type.
        Empty carriers are skipped with a logged warning.
    """
    link_losses = []
    link_supply_carrier = filter_by(supply, component="Link").index.unique("carrier")
    link_demand_carrier = filter_by(demand, component="Link").index.unique("carrier")
    link_carrier = link_supply_carrier.union(link_demand_carrier)
    for carrier in link_carrier:
        link_supply = filter_by(supply, carrier=carrier, component="Link")
        link_demand = filter_by(demand, carrier=carrier, component="Link")
        if link_supply.empty or link_demand.empty:
            logger.warning(
                f"Skipping carrier '{carrier}' due to empty supply or demand."
            )
            continue
        link_losses.append(collect_imbalances(link_supply, link_demand))

    return link_losses


def view_sankey(
    result_path: str | Path,
    nc: NetworkCollection,
    config: dict,
) -> None:
    """
    Generate Sankey diagrams for energy flow visualization.

    Creates comprehensive Sankey diagrams showing energy flows, including supply/demand
    balances, transmission losses, trade statistics, and regional energy exchanges.
    The function processes PyPSA network data to extract energy flows and exports
    them as interactive visualizations.

    Parameters
    ----------
    result_path
        Path where the generated Sankey diagrams and data will be saved.
    nc
        Dictionary of PyPSA network objects containing the energy system data
        to be analyzed and visualized.
    config
        Configuration dictionary containing view settings, chart specifications,
        transmission components to exclude, and export parameters.

    Returns
    -------
    :
        Exports Sankey diagrams and underlying energy flow data to the specified
        result path. Generated files include interactive Plotly visualizations
        and CSV data files containing the processed statistics.

    Notes
    -----
    The function processes several types of energy flows:
    - Supply and demand statistics (excluding transmission components)
    - Grid losses from electricity distribution
    - Trade statistics (foreign and domestic imports/exports)
    - Link losses and conversion inefficiencies
    - Regional trade balances for specific carriers (oil, coal, lignite, NH3)

    All statistics are aggregated by year, component, location, and carrier.
    """
    (
        _,
        transmission_comps,
        transmission_carrier,
        _,
        _,
    ) = _parse_view_config_items(nc, config)

    supply = get_supply(nc, transmission_comps, transmission_carrier)
    demand = get_demand(
        nc, transmission_comps, transmission_carrier, unit=supply.attrs["unit"]
    )

    grid_losses = net_distribution_grid_losses(supply, demand)
    trade_statistics = get_trade_statistics(
        nc, transmission_comps, transmission_carrier, unit=supply.attrs["unit"]
    )
    link_losses = get_link_losses(supply, demand)

    regional_trade = [
        regionalize_statistics(supply, demand, bus_carrier)
        for bus_carrier in BusCarrier.eu_buses()
    ]

    exporter = Exporter(
        statistics=[
            supply,
            demand,
            grid_losses,
        ]
        + trade_statistics
        + regional_trade
        + link_losses,
        view_config=config["view"],
    )

    exporter.defaults.xaxis_title = ""
    exporter.defaults.plotby = [DM.YEAR, DM.LOCATION]
    exporter.defaults.pivot_index = [
        DM.COMPONENT,
        DM.YEAR,
        DM.LOCATION,
        DM.CARRIER,
        DM.BUS_CARRIER,
    ]
    exporter.export(result_path, config["global"]["subdir"])
