# SPDX-FileCopyrightText: 2023-2025 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
from pathlib import Path

import pandas as pd

from evals.constants import BusCarrier, DataModel
from evals.fileio import Exporter
from evals.plots import ESMBarChart
from evals.statistic import collect_myopic_statistics
from evals.utils import (
    calculate_input_share,
    drop_from_multtindex_by_regex,
    filter_by,
    filter_for_carrier_connected_to,
    rename_aggregate,
)


def calculate_decentral_heat_mix(load: pd.Series, heat_share: pd.Series) -> pd.Series:
    decentral_heat = load.filter(
        regex="decentral|rural"
    )  # .droplevel(DataModel.BUS_CARRIER)

    load = load.drop(decentral_heat.index)

    to_concat = [load]
    for (year, location, carrier), data in decentral_heat.groupby(
        [DataModel.YEAR, DataModel.LOCATION, DataModel.CARRIER]
    ):
        ratios = filter_by(heat_share, year=year, location=location)
        result = data.item() * ratios
        to_concat.append(rename_aggregate(result, carrier))

    return pd.concat(to_concat)


def view_final_energy_demand(
    result_path: str | Path,
    networks: dict,
    config: dict,
    subdir: str | Path = "evaluation",
) -> None:
    """
    Evaluate the final energy demand per country.

    The resulting chart displays energy demand per bus_carrier. Years
    are stacked bars with energy demands. The x-axis shows year groups per
    sector.

    Parameters
    ----------
    result_path
    networks
    config
    subdir

    Returns
    -------
    :
    """
    decentral_heat_bus_carrier = [
        BusCarrier.HEAT_RURAL,
        BusCarrier.HEAT_URBAN_DECENTRAL,
    ]
    # calculate the heat production share per bus_carrier
    heat_mix = (
        collect_myopic_statistics(networks, comps="Link", statistic="energy_balance")
        .drop(["co2", "co2 stored"], level=DataModel.BUS_CARRIER)
        .pipe(drop_from_multtindex_by_regex, "water tanks|water pits")
        .pipe(filter_for_carrier_connected_to, decentral_heat_bus_carrier)
        .pipe(calculate_input_share, decentral_heat_bus_carrier)
        .pipe(rename_aggregate, "heat_mix")
    )
    heat_mix = heat_mix[heat_mix > 0]
    heat_share = heat_mix / heat_mix.groupby(["year", "location"]).transform("sum")

    # loads bsed approach:
    # easy, but sometimes behind the meter demands.
    # need to add losses from Links, central heat distribution losses
    # need to find the emergy mix ratio for bus_carrier supplying the rural/(de)central heat buses
    loads = collect_myopic_statistics(networks, "withdrawal", comps="Load")
    # transport Loads are final energy
    transport = loads.filter(regex="transport|shipping|aviation")
    # # no need to harmonize V2g:
    # bev_load = filter_by(transport, bus_carrier="EV battery")
    # v2g_demand = collect_myopic_statistics(networks, "withdrawal", comps="Link", bus_carrier="EV battery")
    # bev_charger = collect_myopic_statistics(networks, "supply", comps="Link", bus_carrier="EV battery")
    # bev_charger.loc[("2050", "SE")].item() - v2g_demand.loc[("2050", "SE")].item()
    # bev_load.loc[("2050", "SE")].item()
    # # --> its the same

    # agriculture contains final energy Loads and useful energy Loads (heat)
    agriculture = loads.filter(regex="agriculture|NH3")
    agriculture = calculate_decentral_heat_mix(agriculture, heat_share)

    # industry contains FED and useful energy (low-temperature heat for industry)
    industry = loads.filter(regex="industry")
    industry = calculate_decentral_heat_mix(industry, heat_share)

    # electricity base load contains loads not split
    base_load = filter_by(loads, carrier="electricity")

    # heat for buildings
    heat = filter_by(
        loads, carrier=BusCarrier.heat_buses()
    )  # 'carrier' not 'bus_carrier' to prevent capturing agriculture or industry loads
    heat = calculate_decentral_heat_mix(heat, heat_share)

    # idx = (
    #     transport.index.union(agriculture.index)
    #     .union(industry.index)
    #     .union(base_load.index)
    #     .union(heat.index)
    # )
    # assert loads.drop(idx).empty
    # assert not (
    #     transport.index.append(agriculture.index)
    #     .append(industry.index)
    #     .append(base_load.index)
    #     .append(heat.index)
    # ).has_duplicates
    fed = pd.concat(
        [
            rename_aggregate(transport, "Transport"),
            rename_aggregate(industry, "Industry"),
            rename_aggregate(agriculture, "Agriculture"),
            rename_aggregate(base_load, "hh_service"),
            rename_aggregate(heat, "hh_serivice"),
        ]
    )

    # todo: base load load splitting
    # todo: reduce urban central loads by
    # loss_factor = get_heat_loss_factor(networks)

    # link_supply_rural_heat = (
    #     collect_myopic_statistics(
    #         networks,
    #         comps="Link",
    #         statistic="energy_balance",
    #     )
    #     .pipe(filter_for_carrier_connected_to, BusCarrier.HEAT_RURAL)
    #     .pipe(calculate_input_share, BusCarrier.HEAT_RURAL)
    # )
    #
    # generator_supply_rural_heat = collect_myopic_statistics(
    #     networks,
    #     comps="Generator",
    #     statistic="supply",
    #     bus_carrier=BusCarrier.HEAT_RURAL,
    # )
    #
    # load_withdrawal_urban_heat = collect_myopic_statistics(
    #     networks,
    #     "withdrawal",
    #     comps="Load",
    #     bus_carrier=[BusCarrier.HEAT_URBAN_CENTRAL, BusCarrier.HEAT_URBAN_DECENTRAL],
    # ).drop(
    #     Carrier.low_temperature_heat_for_industry,
    #     level=DataModel.CARRIER,
    # )
    #
    # # # The predecessor drops Italian urban heat technologies for unknown reasons.
    # # load_withdrawal_urban_heat = load_withdrawal_urban_heat.drop(["IT0", "IT1", "IT2"], level=DataModel.LOCATION)
    # # # todo: Is this correct? They probably had a good reason for that, but I just can't see it.
    #
    # loss_factor = get_heat_loss_factor(networks)
    # load_split_urban_heat = split_urban_central_heat_losses_and_consumption(
    #     load_withdrawal_urban_heat, loss_factor
    # )
    #
    # fed_homes_and_trade = collect_myopic_statistics(
    #     networks, statistic="ac_load_split"
    # ).pipe(filter_by, carrier=Carrier.domestic_homes_and_trade)

    # todo: need to map carrier names to sector names in grouped barchart
    exporter = Exporter(
        statistics=[fed],
        view_config=config["view"],
    )

    # view specific static settings:
    exporter.defaults.plotly.chart = ESMBarChart
    exporter.defaults.excel.pivot_index = [
        DataModel.LOCATION,
        DataModel.BUS_CARRIER,
    ]
    exporter.defaults.plotly.plot_category = DataModel.BUS_CARRIER
    exporter.defaults.plotly.pivot_index = [
        DataModel.YEAR,
        DataModel.LOCATION,
        DataModel.BUS_CARRIER,
    ]

    exporter.export(result_path, subdir=subdir)
