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


def view_demand_fed(
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
    fed = fed.swaplevel("carrier", "bus_carrier")
    fed.index.names = DataModel.YEAR_IDX_NAMES

    exporter = Exporter(
        statistics=[fed],
        view_config=config["view"],
    )
    exporter.defaults.plotly.chart = getattr(plots, config["view"]["chart"])
    exporter.defaults.plotly.xaxis_title = ""
    exporter.export(result_path, subdir=subdir)
