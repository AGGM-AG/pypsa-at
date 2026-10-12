# SPDX-FileCopyrightText: 2023-2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""Cross-cutting network helpers: load clipping and resource meta-data attachment."""

from contextlib import ExitStack
from functools import cache
from importlib.util import module_from_spec, spec_from_file_location
from logging import getLogger
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

import pandas as pd
import pypsa
from snakemake.script import Snakemake

from mods.demand.annual import apply_annual_demand_overrides
from mods.demand.electricity import (
    BASE_LOAD_CARRIERS,
    apply_electricity_base_load,
    base_load_load_splitting,
)
from mods.demand.heat_demand import apply_heat_demand
from mods.demand.industrial_demand import apply_industrial_demand_profiles
from mods.network.biogas import add_existing_biogas_chp_at
from mods.network.biomass import apply_ch_biomass_split
from mods.network.electricity import apply_tyndp_transmission_lower_bounds
from mods.network.gas import (
    block_russian_gas_imports,
    check_retrofit_pairing,
    deduct_retrofitted_gas_capacity,
    fix_gas_grid_capacity,
    override_gas_storage_capacities,
    restore_asymmetric_pipeline_capacities,
    unravel_gas_import_and_production,
)
from mods.network.h2 import (
    add_h2_for_industry_bus,
    add_h2_imports,
    add_methane_pyrolysis_plasma,
)
from mods.network.hydro import process_hydro
from mods.network.onwind import apply_onwind_brownfield
from mods.network.potentials import (
    apply_klien_potential_limits,
    deduct_existing_capacities,
    raise_potentials_to_minimum,
)
from mods.network.trajectories import apply_pemmdb_trajectories

logger = getLogger(__name__)


def _raise_on_perfect_foresight(snakemake: Snakemake) -> None:
    """Fail early, PyPSA-AT does not support perfect foresight."""
    if snakemake.params.foresight == "perfect":
        raise NotImplementedError("PyPSA-AT does not support perfect foresight.")


def prepare_sector_network(
    n: pypsa.Network, snakemake: Snakemake, costs: pd.DataFrame, nyears: float
) -> None:
    """
    Apply all PyPSA-AT specific sector modifications during ``compose_network``.

    Must be called after the upstream sector components were added and
    after temporal aggregation. The node index, spatial namespace and
    population weighted energy totals are local to the upstream
    ``prepare_sector_network.main`` and are rebuilt here the same way.

    Parameters
    ----------
    n
        The composed network to be modified in place.
    snakemake
        The Snakemake workflow object providing inputs, params, and config.
    costs
        Processed cost DataFrame for the current planning horizon.
    nyears
        Number of modelled years (snapshot weightings sum / 8760).

    Returns
    -------
    :
        Modifies the network in place.

    Raises
    ------
    NotImplementedError
        If the workflow runs with perfect foresight.
    """
    from scripts.prepare_sector_network import define_spatial

    _raise_on_perfect_foresight(snakemake)

    options = snakemake.params.sector
    nodes = pd.read_csv(snakemake.input.clustered_pop_layout, index_col=0).index
    spatial = define_spatial(nodes, options)

    pop_weighted_energy_totals = (
        pd.read_csv(snakemake.input.pop_weighted_energy_totals, index_col=0) * nyears
    )
    if options["heating"]:
        pop_weighted_heat_totals = (
            pd.read_csv(snakemake.input.pop_weighted_heat_totals, index_col=0) * nyears
        )
        pop_weighted_energy_totals.update(pop_weighted_heat_totals)

    add_h2_for_industry_bus(n, nodes)
    add_methane_pyrolysis_plasma(n, snakemake, costs, nodes, spatial)
    process_hydro(n, snakemake, costs)
    base_load_load_splitting(n, pop_weighted_energy_totals)
    apply_annual_demand_overrides(n, snakemake)
    apply_industrial_demand_profiles(n, snakemake)


def modify_prenetwork(n: pypsa.Network, snakemake: Snakemake) -> None:
    """
    Apply all PyPSA-AT specific modifications to the pre-network.

    This is the single entry point for all AT-specific modifications in
    ``compose_network``. It runs as late as possible, after the upstream
    cost and potential adjustments. It first applies the PyPSA-DE
    modifications and then the AT modifications, so that AT modifications
    take precedence. It orchestrates the individual modification functions
    and encapsulates the conditional logic for when each modification
    applies.

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

    Raises
    ------
    NotImplementedError
        If the workflow runs with perfect foresight.
    """
    from scripts._helpers import load_costs

    _raise_on_perfect_foresight(snakemake)

    costs = load_costs(snakemake.input.tech_costs)

    _apply_pypsa_de_modifications(n, snakemake, costs)

    # AT potentials overwrite p_nom_max after upstream deducted the existing
    # capacities, see deduct_existing_capacities
    p_nom_max_before = n.generators.p_nom_max.copy()

    unravel_gas_import_and_production(n, snakemake, costs)
    block_russian_gas_imports(n, snakemake)
    fix_gas_grid_capacity(n, snakemake)
    restore_asymmetric_pipeline_capacities(n, snakemake)
    deduct_retrofitted_gas_capacity(n, snakemake)
    check_retrofit_pairing(n)

    apply_pemmdb_trajectories(n, snakemake, costs)
    apply_onwind_brownfield(n, snakemake)
    add_existing_biogas_chp_at(n, snakemake, costs)
    override_gas_storage_capacities(n, snakemake)
    apply_klien_potential_limits(n, snakemake)
    apply_ch_biomass_split(n, snakemake)
    apply_tyndp_transmission_lower_bounds(n, snakemake)
    add_h2_imports(n, snakemake)
    apply_heat_demand(n, snakemake)
    apply_electricity_base_load(n, snakemake)

    deduct_existing_capacities(n, p_nom_max_before, int(snakemake.wildcards.horizon))
    raise_potentials_to_minimum(n)

    # Apply Load clipping just before the solve step
    clip_negative_loads_for_edge_cases(n, snakemake)


def _skip_pypsa_de_function(*args, **kwargs) -> None:
    """Replace a PyPSA-DE modification that must not run for PyPSA-AT."""


# PyPSA-DE functions in ``scripts/pypsa-de/modify_prenetwork.py`` that are
# skipped for PyPSA-AT. PyPSA-AT models the gas network explicitly, and
# unravelling the carbonaceous fuels and the gas bus is not possible with it.
SKIPPED_PYPSA_DE_FUNCTIONS = ("unravel_carbonaceous_fuels", "unravel_gasbus")


@cache
def _load_pypsa_de_modify_prenetwork() -> ModuleType:
    """
    Load ``scripts/pypsa-de/modify_prenetwork.py`` as a module.

    The hyphenated directory is not an importable package, hence the file
    based import. The module is cached so that every call patches and runs
    the same module object.
    """
    path = Path(__file__).parents[2] / "scripts" / "pypsa-de" / "modify_prenetwork.py"
    spec = spec_from_file_location("pypsa_de_modify_prenetwork", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load the PyPSA-DE modifications from {path}")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _apply_pypsa_de_modifications(
    n: pypsa.Network, snakemake: Snakemake, costs: pd.DataFrame
) -> None:
    """
    Apply the PyPSA-DE modifications without the functions PyPSA-AT skips.

    Calls ``main`` of ``scripts/pypsa-de/modify_prenetwork.py`` with every
    function in ``SKIPPED_PYPSA_DE_FUNCTIONS`` patched to a no-op. The patch
    only lasts for this call. If upstream renames one of the functions,
    ``patch.object`` raises an ``AttributeError`` instead of letting the
    function run silently.

    Parameters
    ----------
    n
        The composed network to be modified in place.
    snakemake
        The Snakemake workflow object of the ``compose_network`` rule.
    costs
        Processed cost DataFrame for the current planning horizon.

    Returns
    -------
    :
        Updates the :class:`pypsa.Network` in place.
    """
    pypsa_de_module = _load_pypsa_de_modify_prenetwork()
    with ExitStack() as stack:
        for name in SKIPPED_PYPSA_DE_FUNCTIONS:
            stack.enter_context(
                patch.object(pypsa_de_module, name, _skip_pypsa_de_function)
            )
        logger.info(
            f"PyPSA-AT: skipping PyPSA-DE functions {SKIPPED_PYPSA_DE_FUNCTIONS}."
        )
        pypsa_de_module.main(
            n,
            snakemake.input,
            snakemake.params,
            costs,
            int(snakemake.wildcards.horizon),
        )


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

    investment_year = int(snakemake.wildcards.horizon)
    averaging = cfg["clustering"]["temporal"]["averaging"]
    resolution = (
        int(pd.Timedelta(averaging) / pd.Timedelta(hours=1)) if averaging else 1
    )
    clustering = cfg["mods"]["modify_nuts3_shapes"]
    # the rebuilt Austrian base load (apply_electricity_base_load) has no
    # negative hours, so the Austrian edge cases only apply without it
    skip_at = cfg["mods"]["electricity_base_load"]["enable"]

    def _clip_static(carrier: str) -> None:
        idx = n.loads.index[n.loads["carrier"] == carrier]
        negatives = idx[n.loads.loc[idx, "p_set"] < 0]
        if negatives.empty:
            raise RuntimeError(f"Expected negative '{carrier}' Loads.")
        n.loads.loc[negatives, "p_set"] = 0

    def _clip_electricity(location: str) -> None:
        # the base load is split into sectoral Loads (see
        # base_load_load_splitting), so negative hours from the electric
        # heating deduction sit proportionally in all of them
        if skip_at and location.startswith("AT"):
            return
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
