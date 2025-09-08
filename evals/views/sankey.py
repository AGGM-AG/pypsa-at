# SPDX-FileCopyrightText: 2023-2025 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""Plot sankey diagrams."""

from pathlib import Path

import pandas as pd

from evals import plots as plots
from evals.constants import DataModel as DM
from evals.constants import Group, TradeTypes
from evals.fileio import Exporter
from evals.statistic import collect_myopic_statistics
from evals.utils import (
    drop_from_multtindex_by_regex,
    filter_by,
    insert_index_level,
    rename_aggregate,
)
from evals.views.common import _parse_view_config_items

IDX = ["year", "component", "location", "carrier"]
pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 20)
pd.set_option("display.max_rows", 500)


def _process_single_input_link(
    supply: pd.Series,
    demand: pd.Series,
    bc_in: str,
):
    balance = supply.groupby(IDX).sum() + demand.groupby(IDX).sum()
    losses = balance[balance < 0]
    surplus = balance[balance > 0]
    # losses = insert_index_level(losses, bc_in, "bus_carrier", pos=4)
    losses = insert_index_level(losses, f"{bc_in} losses", "bus_carrier", pos=4).mul(-1)
    surplus = insert_index_level(surplus, "ambient heat", "bus_carrier", pos=4)
    # if not losses.empty:
    #     # need to rename the carrier to avoid mixing with supply
    #     carrier = losses.index.unique("carrier").item()
    #     losses = rename_aggregate(losses, f"{carrier} losses")
    return pd.concat([losses, surplus])


def collect_imbalances(supply, demand):
    bc_in = demand.index.unique("bus_carrier")
    # bc_out = supply.index.unique("bus_carrier")

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


def get_supply(networks, transmission_comps, transmission_carrier):
    supply = (
        collect_myopic_statistics(
            networks,
            statistic="supply",
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
                "hydro": "hydro supply",
                "PHS": "PHS supply",
                "H2 Store": "H2 Store supply",
                "gas": "gas Store supply",
            },
        )
    )
    supply.attrs["unit"] = "MWh"

    return supply


def get_demand(networks, transmission_comps, transmission_carrier, unit):
    withdrawal = collect_myopic_statistics(
        networks,
        statistic="withdrawal",
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
                "hydro": "hydro demand",
                "PHS": "PHS demand",
                "H2 Store": "H2 Store demand",
                "gas": "gas Store demand",
            },
        )
        .mul(-1)
    )

    result = pd.concat([demand, compressing])
    result.attrs["unit"] = unit

    return result


def net_distribution_grid_losses(supply, demand):
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


def get_trade_statistics(networks, transmission_comps, transmission_carrier, unit):
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
            # .abs()
        )
        trade.attrs["unit"] = unit
        trade_statistics.append(trade)

    return trade_statistics


def get_link_losses(supply, demand):
    link_losses = []
    link_supply_carrier = filter_by(supply, component="Link").index.unique("carrier")
    link_demand_carrier = filter_by(demand, component="Link").index.unique("carrier")
    link_carrier = link_supply_carrier.union(link_demand_carrier)
    for carrier in link_carrier:
        link_supply = filter_by(supply, carrier=carrier, component="Link")
        link_demand = filter_by(demand, carrier=carrier, component="Link")
        # balance = link_supply.droplevel("bus_carrier").add(link_demand.droplevel("bus_carrier")).groupby(["year", "component", "location", "carrier"]).sum()
        if link_supply.empty or link_demand.empty:
            print(f"Skipping carrier '{carrier}' due to empty supply or demand.")
            continue
        link_losses.append(collect_imbalances(link_supply, link_demand))
        # demand.drop(link_demand.index, inplace=True)

    return link_losses


def get_regional_trade(supply, demand, bus_carrier: str | list):
    regional_supply = (
        filter_by(supply, bus_carrier=bus_carrier).groupby(["year", "location"]).sum()
    )
    regional_demand = (
        filter_by(demand, bus_carrier=bus_carrier).groupby(["year", "location"]).sum()
    )
    regional_balance = (
        regional_supply.add(regional_demand, fill_value=0)
        .pipe(insert_index_level, "Link", "component", pos=1)
        .pipe(insert_index_level, bus_carrier, "bus_carrier", pos=3)
        .pipe(insert_index_level, "trade", "carrier", pos=3)
        .drop("EU", level="location", errors="ignore")
    )
    regional_import = rename_aggregate(
        regional_balance[regional_balance.le(0)], {"trade": "Import Foreign"}
    ).mul(-1)
    regional_export = rename_aggregate(
        regional_balance[regional_balance.gt(0)], {"trade": "Export Foreign"}
    ).mul(-1)

    return [regional_import, regional_export]


def view_sankey(
    result_path: str | Path,
    networks: dict,
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
    networks
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
        storage_links,
    ) = _parse_view_config_items(networks, config)

    supply = get_supply(networks, transmission_comps, transmission_carrier)
    demand = get_demand(
        networks, transmission_comps, transmission_carrier, unit=supply.attrs["unit"]
    )

    # todo:
    #  - calculate regional oil import from regional oil demand
    #  - calculate regional NH3 Load from regional NH3 production

    #  - assert all nodes balanced
    grid_losses = net_distribution_grid_losses(supply, demand)
    trade_statistics = get_trade_statistics(
        networks, transmission_comps, transmission_carrier, unit=supply.attrs["unit"]
    )
    link_losses = get_link_losses(supply, demand)

    regional_trade = [
        get_regional_trade(supply, demand, bus_carrier)
        for bus_carrier in ("oil", "coal", "lignite", "NH3")
    ]
    # for bus_carrier in ("oil", "coal", "lignite", "NH3"):
    #     regional_trade.extend(get_regional_trade(supply, demand, bus_carrier))

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

    chart_class = getattr(plots, config["view"]["chart"])
    exporter.defaults.plotly.chart = chart_class
    exporter.defaults.plotly.xaxis_title = ""
    exporter.defaults.plotly.plotby = [DM.YEAR, DM.LOCATION]
    exporter.defaults.plotly.pivot_index = [
        DM.COMPONENT,
        DM.YEAR,
        DM.LOCATION,
        DM.CARRIER,
        DM.BUS_CARRIER,
    ]
    exporter.export(result_path, config["global"]["subdir"])
