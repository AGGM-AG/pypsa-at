# SPDX-FileCopyrightText: 2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""Annual renewable electricity production constraints."""

import logging

import pandas as pd
import pypsa

from mods.constants import UNITS

logger = logging.getLogger(__name__)

GENERATOR_CARRIERS = {
    "solar": ["solar", "solar-hsat", "solar rooftop"],
    "wind": ["onwind", "offwind-ac", "offwind-dc", "offwind-float"],
    "hydro": ["hydro inflow", "ror", "PHS inflow"],
}
LINK_CARRIERS = {
    "biomass": (
        ["solid biomass", "biogas", "renewable gas"],
        ["AC", "low voltage"],
    )
}
LINK_EAG_ADDITIONS = {"biomass": (["gas"], [])}

ELECTRICITY_CARRIERS = ["AC", "low voltage"]


def inflow_turbine_weights(n: pypsa.Network, generators: pd.Index) -> pd.Series:
    """
    Weight generators on store buses by the efficiency of their turbine link.

    The hydro inflow generators (``hydro inflow``, ``PHS inflow``) feed a
    store bus, and their energy reaches the grid only through the discharger
    link of that store, whose efficiency is below one. A production target
    stated in delivered electricity (E-Control counts generation at the
    terminals) therefore weights such a generator by that efficiency.
    Generators on an electricity bus (``ror``, wind, solar) get weight one.

    Parameters
    ----------
    n
        Network with buses, links and generators.
    generators
        Generator names to weight.

    Returns
    -------
    :
        Weights indexed by generator name (index named ``Generator``).

    Raises
    ------
    ValueError
        If a generator sits on a non-electricity bus without a turbine link
        into an electricity bus, so its energy could never reach the grid.
    """
    electricity_buses = n.buses.index[n.buses.carrier.isin(ELECTRICITY_CARRIERS)]
    turbines = n.links[n.links.bus1.isin(electricity_buses)]
    turbine_efficiency = turbines.groupby("bus0")["efficiency"].mean()
    weights = pd.Series(1.0, index=pd.Index(generators, name="Generator"))
    on_store = ~n.generators.loc[generators, "bus"].isin(electricity_buses)
    store_buses = n.generators.loc[generators[on_store], "bus"]
    missing = store_buses[~store_buses.isin(turbine_efficiency.index)]
    if not missing.empty:
        raise ValueError(
            "Generators on a store bus without a turbine link into an "
            f"electricity bus: {missing.index.tolist()}."
        )
    weights[on_store.to_numpy()] = store_buses.map(turbine_efficiency).to_numpy()
    return weights


def _production_expression(n: pypsa.Network, source: str, region: str):
    """
    Build a snapshot-weighted production expression.

    Parameters
    ----------
    n
        Network with an attached optimization model.
    source
        Production source to constrain.
    region
        Region prefix used to select components.

    Returns
    -------
    :
        Weighted production expression, or ``None`` for unsupported sources.

    Notes
    -----
    Time-varying link efficiencies are ignored. Generators on store buses
    (the hydro inflow generators) are weighted by the efficiency of the
    turbine link of that store, see :func:`inflow_turbine_weights`.
    """
    weightings = n.snapshot_weightings.generators

    if source in GENERATOR_CARRIERS:
        generators = n.generators[
            n.generators.bus.str.startswith(region)
            & n.generators.carrier.isin(GENERATOR_CARRIERS[source])
            & n.generators.active
        ].index
        weights = inflow_turbine_weights(n, generators)
        return (
            n.model["Generator-p"].loc[:, generators].mul(weights).mul(weightings).sum()
        )
    elif source in LINK_CARRIERS:
        from_carriers, to_carriers = LINK_CARRIERS[source]
        from_buses = n.buses[
            n.buses.carrier.isin(from_carriers) & n.buses.index.str.startswith(region)
        ].index
        to_buses = n.buses[
            n.buses.carrier.isin(to_carriers) & n.buses.index.str.startswith(region)
        ].index
        links = pd.concat(
            [
                n.links.loc[
                    n.links.bus0.isin(from_buses)
                    & n.links[f"bus{port}"].isin(to_buses)
                    & n.links.active
                    & (n.links[f"efficiency{port if port > 1 else ''}"] > 0),
                    f"efficiency{port if port > 1 else ''}",
                ]
                for port in range(1, 5)
            ]
        )

        return n.model["Link-p"].loc[:, links.index].mul(links).mul(weightings).sum()
    else:
        return None


def _add_eag_entries(eag_enabled: bool) -> None:
    """
    Modify LINK_CARRIERS to contain eag relevant carriers if applicable

    Parameters
    ----------
    eag_enabled
        Config parameter indicating if eag constraints are enabled

    Returns
    -------
    :
        Modifies LINK_CARRIERS inplace.
    """
    if eag_enabled:
        for eag_key, eag_tuple in LINK_EAG_ADDITIONS.items():
            link_tuple = LINK_CARRIERS[eag_key]
            LINK_CARRIERS[eag_key] = (
                [*link_tuple[0], *eag_tuple[0]],
                [*link_tuple[1], *eag_tuple[1]],
            )


def constraint_production_targets(
    n: pypsa.Network, snakemake, investment_year: int
) -> None:
    """
    Add annual production lower and upper bounds.

    Parameters
    ----------
    n
        Network with an attached optimization model.
    snakemake
        Snakemake workflow object with solving constraints.
    investment_year
        Planning horizon year.

    Returns
    -------
    :
        Constraints are added to the model in place.
    """
    _add_eag_entries(snakemake.config["mods"]["net_zero_electricity"]["enable"])
    constraints = snakemake.params.solving["constraints"]
    maximums = constraints.get("limits_volume_max", {})
    minimums = constraints.get("limits_volume_min", {})

    for sense, limits, suffix in [("<=", maximums, "upper"), (">=", minimums, "lower")]:
        for source, region_dict in limits.items():
            for region, year_dict in region_dict.items():
                years = year_dict.keys()
                if investment_year not in years:
                    continue
                limit = year_dict[investment_year]
                lhs = _production_expression(n, source, region)
                if lhs is None or lhs.empty:
                    continue
                limit *= UNITS["TWh"]

                cname = f"production_limit_{suffix}-{source}-{region}"
                if cname in n.global_constraints.index:
                    logger.warning(
                        f"Global constraint {cname} already exists. Dropping and adding it again."
                    )
                    n.global_constraints.drop(cname, inplace=True)
                n.model.add_constraints(
                    lhs, sense, limit, name=f"GlobalConstraint-{cname}"
                )
                n.add(
                    "GlobalConstraint",
                    cname,
                    constant=limit,
                    sense=sense,
                    type="",
                    carrier_attribute="",
                )
                logger.info(
                    f"Limiting {source} production in {region} to "
                    f"{limit / 1e6} TWh/a ({sense})."
                )
