# SPDX-FileCopyrightText: 2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""Annual renewable electricity production constraints."""

import logging

import pypsa
import pandas as pd

from mods.constants import UNITS

logger = logging.getLogger(__name__)

GENERATOR_CARRIERS = {
    "solar": ["solar", "solar-hsat", "solar rooftop"],
    "wind": ["onwind", "offwind-ac", "offwind-dc", "offwind-float"],
    "hydro": ["hydro inflow", "ror", "PHS inflow"],
}
LINK_CARRIERS = {
    "biomass": (["solid biomass", "biogas", "gas", "renewable gas"], ["AC", "low voltage"])
}


def _production_expression(n: pypsa.Network, source: str, region: str):
    """Build a snapshot-weighted production expression.

    Parameters
    ----------
    n : pypsa.Network
        Network with an attached optimization model.
    source : str
        Production source to constrain.
    region : str
        Region prefix used to select components.

    Returns
    -------
    :
        Weighted production expression, or ``None`` for unsupported sources.

    Notes
    -----
    Time-varying link efficiencies are ignored.
    """
    weightings = n.snapshot_weightings.generators

    if source in GENERATOR_CARRIERS:
        generators = n.generators[
            n.generators.bus.str.startswith(region)
            & n.generators.carrier.isin(GENERATOR_CARRIERS[source])
            & n.generators.active
        ].index
        return n.model["Generator-p"].loc[:, generators].mul(weightings).sum()
    elif source in LINK_CARRIERS:
        from_carriers, to_carriers = LINK_CARRIERS[source]
        from_buses = n.buses[
            n.buses.carrier.isin(from_carriers) & n.buses.index.str.startswith(region)
        ].index
        to_buses = n.buses[
            n.buses.carrier.isin(to_carriers) & n.buses.index.str.startswith(region)
        ].index
        links = pd.concat([n.links.loc[
            n.links.bus0.isin(from_buses)
            & n.links[f"bus{port}"].isin(to_buses)
            & n.links.active
            & (n.links[f"efficiency{port if port > 1 else ''}"] > 0), f"efficiency{port if port > 1 else ''}"
        ] for port in range(1,5)])

        return n.model["Link-p"].loc[:, links.index].mul(links).mul(weightings).sum()
    else:
        return None



def constraint_production_targets(
    n: pypsa.Network, snakemake, investment_year: int
) -> None:
    """Add annual production lower and upper bounds.

    Parameters
    ----------
    n : pypsa.Network
        Network with an attached optimization model.
    snakemake
        Snakemake workflow object with solving constraints.
    investment_year : int
        Planning horizon year.

    Returns
    -------
    :
        Constraints are added to the model in place.
    """
    constraints = snakemake.params.solving["constraints"]
    maximums = constraints.get("limits_volume_max", {})
    minimums = constraints.get("limits_volume_min", {})

    for sense, limits, suffix in [("<=", maximums, "upper"),(">=", minimums, "lower")]:
        for source, region_dict in limits.items():
            for region, year_dict in region_dict.items():
                years = year_dict.keys()
                if investment_year not in years:
                    continue
                limit = year_dict[investment_year]
                lhs = _production_expression(n, source, region)
                if lhs is None:
                    continue
                limit *= UNITS["TWh"]

                cname = f"production_limit_{suffix}-{source}-{region}"
                n.model.add_constraints(
                    lhs, sense, limit, name=f"GlobalConstraint-{cname}"
                )

                if cname in n.global_constraints.index:
                    logger.warning(
                        f"Global constraint {cname} already exists. Dropping and adding it again."
                    )
                    n.global_constraints.drop(cname, inplace=True)
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
