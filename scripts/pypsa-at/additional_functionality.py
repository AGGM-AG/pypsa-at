# SPDX-FileCopyrightText: 2023-2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""
PyPSA-AT entry point for ``solving.options.custom_extra_functionality``.

Delegates to the upstream PyPSA-DE ``additional_functionality`` first, then
appends PyPSA-AT specific constraints via :func:`mods.pypsa_at_constraints`.

The function name must equal the module basename — ``scripts/solve_network.py``
loads the configured script with ``getattr(module, module_name)``.
"""

import logging
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from mods import (
    constraint_combined_solar_trajectories,
    constraint_national_co2_budgets,
    constraint_net_zero_electricity,
    constraint_ntc_flow_limits,
    constraint_production_targets,
)
from mods.constraints.trajectories import constraint_generic_trajectories

logger = logging.getLogger(__name__)

# Load the upstream PyPSA-DE module via spec to avoid mutating sys.path and
# to sidestep the hyphenated ``scripts/pypsa-de/`` directory not being a valid
# Python package name.
_scripts_dir = Path(__file__).resolve().parent.parent
_UPSTREAM_PATH = _scripts_dir / "pypsa-de" / "additional_functionality.py"
_spec = spec_from_file_location("pypsa_de_additional_functionality", _UPSTREAM_PATH)
_pypsa_de_additional_functionality = module_from_spec(_spec)
_spec.loader.exec_module(_pypsa_de_additional_functionality)


def additional_functionality(n, snapshots, snakemake):
    """Run upstream PyPSA-DE additional functionality, then PyPSA-AT constraints."""
    _pypsa_de_additional_functionality.additional_functionality(n, snapshots, snakemake)

    investment_year = int(snakemake.wildcards.planning_horizons)
    constraint_national_co2_budgets(n, snakemake, investment_year)
    constraint_ntc_flow_limits(n, snakemake, investment_year)
    constraint_net_zero_electricity(n, snakemake, investment_year)
    constraint_combined_solar_trajectories(n, snakemake, investment_year)
    constraint_generic_trajectories(n, snakemake, investment_year)
    constraint_production_targets(n, snakemake, investment_year)
