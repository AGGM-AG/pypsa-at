# SPDX-FileCopyrightText: 2023-2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""Cross-cutting network helpers: load clipping and resource meta-data attachment."""

from logging import getLogger

import pypsa
from snakemake.script import Snakemake

from mods.demand.annual import apply_annual_demand_overrides
from mods.demand.electricity import BASE_LOAD_CARRIERS, base_load_load_splitting
from mods.demand.heat_demand import apply_heat_demand
from mods.demand.industrial_demand import apply_industrial_demand_profiles
from mods.network.electricity import apply_tyndp_transmission_lower_bounds
from mods.network.gas import (
    block_russian_gas_imports,
    make_gas_pipelines_unextendable,
    override_gas_storage_capacities,
    unravel_gas_import_and_production,
)
from mods.network.h2 import (
    add_h2_for_industry_bus,
    add_h2_imports,
    add_methane_pyrolysis_plasma,
)
from mods.network.hydro import process_hydro
from mods.network.potentials import apply_klien_potential_limits
from mods.network.trajectories import apply_pemmdb_trajectories

logger = getLogger(__name__)


def prepare_sector_network(
    n, snakemake, nodes, costs, spatial, pop_weighted_energy_totals
):
    """
    Apply all PyPSA-AT specific modifications during ``prepare_sector_network``.

    Parameters
    ----------
    n
        The pre-network to be modified in place.
    snakemake
        The Snakemake workflow object providing inputs, params, and config.
    costs
        Processed cost DataFrame for the current planning horizon.
    nodes
        Clustered node index (``pop_layout.index``).
    spatial
        Spatial namespace produced by ``define_spatial``.
    pop_weighted_energy_totals
        Population weighted energy totals per node in TWh per calendar
        year, used to split the electricity base load into sectoral
        Loads.

    Returns
    -------
    :
        Modifies the network in place.
    """
    add_h2_for_industry_bus(n, nodes)
    add_methane_pyrolysis_plasma(n, snakemake, costs, nodes, spatial)
    process_hydro(n, snakemake, costs)
    base_load_load_splitting(n, pop_weighted_energy_totals)
    apply_annual_demand_overrides(n, snakemake)
    apply_industrial_demand_profiles(n, snakemake)


def modify_prenetwork(n: pypsa.Network, snakemake: Snakemake) -> None:
    """
    Apply all PyPSA-AT specific modifications to the pre-network.

    This is the single entry point for all AT-specific modifications during
    the ``modify_prenetwork`` Snakemake step. It orchestrates the individual
    modification functions and encapsulates the conditional logic for when
    each modification applies.

    Parameters
    ----------
    n
        The pre-network to be modified in place.
    snakemake
        The Snakemake workflow object providing inputs, params, config,
        and wildcards.

    Returns
    -------
    :
        Updates the :class:`pypsa.Network` in place.
    """
    from scripts.add_electricity import load_costs

    costs = load_costs(snakemake.input.costs)

    unravel_gas_import_and_production(n, snakemake, costs)
    block_russian_gas_imports(n, snakemake)
    make_gas_pipelines_unextendable(n, snakemake)

    apply_pemmdb_trajectories(n, snakemake, costs)
    override_gas_storage_capacities(n, snakemake)
    apply_klien_potential_limits(n, snakemake)
    apply_tyndp_transmission_lower_bounds(n, snakemake)
    add_h2_imports(n, snakemake)
    apply_heat_demand(n, snakemake)

    # Apply Load clipping just before the solve step
    clip_negative_loads_for_edge_cases(n, snakemake)


def clip_negative_loads_for_edge_cases(n: pypsa.Network, snakemake: Snakemake) -> None:
    """
    Clip negative Loads for selected edge cases.

    This is neccessary, because some electricity demands are calculated
    from heuristics. For example, ``heat for electricity`` from
    ``energy_totals`` and population share is deducted from
    regional ``base load``. This can lead to negative Loads if
    heuristics yield larger values than input data sets. However,
    there are many examples where this may happen.

    Parameters
    ----------
    n
        The network before solve step.
    snakemake
        The Snakemake workflow object providing inputs, params,
        config, and outputs.

    Returns
    -------
    :
        Updates network in place.

    Raises
    ------
    RunTimeError
        If expected edge cases could not be found.

    """
    cfg = snakemake.config

    investment_year = int(snakemake.wildcards.planning_horizons)
    resolution = int(cfg["clustering"]["temporal"]["resolution_sector"].rstrip("H"))
    clustering = cfg["mods"]["modify_nuts3_shapes"]

    def _clip_static(carrier: str):
        idx = n.loads.index[n.loads["carrier"] == carrier]
        negatives = idx[n.loads.loc[idx, "p_set"] < 0]
        if negatives.empty:
            raise RuntimeError(f"Expected negative '{carrier}' Loads.")
        n.loads.loc[negatives, "p_set"] = 0

    def _clip_electricity(location: str):
        # the base load is split into sectoral Loads (see
        # base_load_load_splitting), so negative hours from the electric
        # heating deduction sit proportionally in all of them
        at_location = n.loads.index.str.startswith(f"{location} ")
        is_split = n.loads["carrier"].isin(BASE_LOAD_CARRIERS).to_numpy()
        p_set = n.loads_t["p_set"]
        columns = p_set.columns.intersection(n.loads.index[at_location & is_split])
        if not p_set[columns].lt(0).any().any():
            raise RuntimeError(f"Expected negative electricity Loads for {location}.")
        p_set[columns] = p_set[columns].clip(lower=0)

    # In the reduced at10 test network a few "H2 for industry" negative
    if cfg["run"]["prefix"] == "test-sector-myopic-at10":
        if investment_year < 2030:
            _clip_static("H2 for industry")
        return  # skip any other clipping

    # Edge case: electricity for heat is larger than base load in AT126
    if resolution == 365 and clustering.startswith("AT35"):
        _clip_electricity("AT126")

    # For 120H runs IT1 always has negative electricity Loads
    if resolution == 120:
        _clip_electricity("IT1")

    if resolution == 3:
        for loc in ("AL", "AT111", "AT112", "AT126", "IT1", "IT2"):
            _clip_electricity(loc)

    if resolution == 24:
        for loc in ("AT126", "IT1", "IT2"):
            _clip_electricity(loc)

    # Edge case: runs contain negative H2 for industry Loads until including 2030
    if investment_year <= 2030:
        _clip_static("H2 for industry")
