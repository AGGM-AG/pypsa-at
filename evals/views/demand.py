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
    filter_for_carrier_connected_to,
    rename_aggregate,
)


def view_demand_heat(
    result_path: str | Path,
    networks: dict,
    config: dict,
    subdir: str | Path = "evaluation",
) -> None:
    """
    Evaluate the energy required for heat production and generation.

    Results are grouped by bus_carrier and not by carrier
    as usual to show the input energy carrier mix.

    Returns
    -------
    :

    Notes
    -----
    See eval docstring for parameter description.
    """
    energy_balance = (
        collect_myopic_statistics(networks, comps="Link", statistic="energy_balance")
        .drop(["co2", "co2 stored"], level=DataModel.BUS_CARRIER)
        .pipe(drop_from_multtindex_by_regex, "water tanks|water pits")
        .pipe(filter_for_carrier_connected_to, BusCarrier.heat_buses())
    )
    energy_for_heat = pd.concat(
        [
            calculate_input_share(energy_balance, bc).pipe(rename_aggregate, bc)
            for bc in BusCarrier.heat_buses()
        ]
    )
    energy_for_heat = energy_for_heat[energy_for_heat > 0]
    # need to set energy balance unit
    energy_for_heat.attrs["unit"] = "MWh_th"

    generator_supply = collect_myopic_statistics(
        networks,
        statistic="supply",
        comps="Generator",
        bus_carrier=BusCarrier.heat_buses(),
    )
    # swap index levels to
    generator_supply = generator_supply.swaplevel(
        DataModel.CARRIER, DataModel.BUS_CARRIER
    )
    generator_supply.index.names = DataModel.YEAR_IDX_NAMES

    exporter = Exporter(
        statistics=[energy_for_heat, generator_supply],
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
