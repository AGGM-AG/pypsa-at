# SPDX-FileCopyrightText: 2023-2025 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""Expose view functions from inside the `views` module."""

from evals.views.balances import (
    view_balance_biomass,
    view_balance_carbon,
    view_balance_electricity,
    view_balance_fuels,
    view_balance_heat,
    view_balance_hydrogen,
    view_balance_methane,
)
from evals.views.balances_timeseries import (
    view_residual_load_duration_curve,
    view_timeseries_carbon,
    view_timeseries_electricity,
    view_timeseries_hydrogen,
    view_timeseries_methane,
    view_timeseries_residual_load,
)
from evals.views.capacities import (
    view_capacity_electricity_demand,
    view_capacity_electricity_production,
    view_capacity_electricity_storage,
    view_capacity_gas_production,
    view_capacity_gas_storage,
    view_capacity_heat_production,
    view_capacity_hydrogen_production,
)
from evals.views.demand import (
    view_demand_fed_sectoral,
    view_demand_fed_total,
    view_demand_heat_system,
    view_demand_heat_total,
)
from evals.views.sankey import view_sankey

__all__ = [
    # demand
    "view_demand_heat_total",
    "view_demand_heat_system",
    "view_demand_fed_sectoral",
    "view_demand_fed_total",
    # capacities
    "view_capacity_gas_storage",
    "view_capacity_electricity_storage",
    "view_capacity_electricity_production",
    "view_capacity_electricity_demand",
    "view_capacity_hydrogen_production",
    "view_capacity_heat_production",
    "view_capacity_gas_production",
    # balances
    "view_balance_electricity",
    "view_balance_carbon",
    "view_balance_heat",
    "view_balance_hydrogen",
    "view_balance_methane",
    "view_balance_biomass",
    "view_balance_fuels",
    # timeseries
    "view_timeseries_hydrogen",
    "view_timeseries_methane",
    "view_timeseries_electricity",
    "view_timeseries_carbon",
    # energy flow
    "view_sankey",
    # residual load
    "view_timeseries_residual_load",
    "view_residual_load_duration_curve",
]
