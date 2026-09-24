# SPDX-FileCopyrightText: 2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""
Existing Austrian biogas-to-power plants as brownfield ``biogas CHP`` Links.

PyPSA-DE used to split small bioenergy power plants into a ``biogas``
carrier inside ``add_existing_baseyear``. That heuristic is gone upstream,
so the Anlagenregister plants prepared by ``overwrite_powerplants_at`` are
turned into Links here, in the base year only. ``add_brownfield`` carries
them into later horizons and retires them via ``build_year`` + ``lifetime``.
"""

from logging import getLogger

import numpy as np
import pandas as pd
import pypsa
from snakemake.script import Snakemake

logger = getLogger(__name__)

CARRIER = "biogas CHP"
"""Carrier of the Links, named like the PyPSA-DE MaStR biogas CHPs."""

COST_KEY = "central solid biomass CHP"
"""Technology-data row used for efficiency, cost and lifetime, like upstream."""


def aggregate_biogas_plants(
    plants: pd.DataFrame,
    grouping_years: list[int],
    lifetime: float,
    base_year: int,
    threshold_capacity: float,
) -> pd.DataFrame:
    """
    Sum plant capacities per node and grouping year.

    Mirrors the vintage handling of ``add_existing_baseyear``: plants are
    binned into ``grouping_years`` by ``DateIn``, retired at
    ``DateIn + lifetime`` and dropped per node and vintage when the summed
    capacity does not exceed ``threshold_capacity``.

    Parameters
    ----------
    plants
        One row per plant with ``bus``, ``Capacity`` (MW) and ``DateIn``.
    grouping_years
        Vintage bin edges (``existing_capacities: grouping_years_power``).
    lifetime
        Technical lifetime in years, used for every plant.
    base_year
        First planning horizon; plants retired before it are dropped.
    threshold_capacity
        Minimum summed capacity (MW) per node and vintage.

    Returns
    -------
    :
        Indexed by ``bus`` and ``grouping_year`` with the summed ``capacity``
        (MW) and the capacity-weighted remaining ``lifetime`` (years).

    Raises
    ------
    ValueError
        If a plant has no ``DateIn`` or was commissioned after the last
        grouping year, as both would silently drop capacity.
    """
    df = plants.copy()

    if df["DateIn"].isna().any():
        raise ValueError("Biogas plants without DateIn cannot be binned into vintages.")
    if (df["DateIn"] > max(grouping_years)).any():
        raise ValueError(
            f"Biogas plants commissioned after the last grouping year "
            f"{max(grouping_years)} would be dropped. Extend grouping_years_power."
        )

    df["DateOut"] = df["DateIn"] + lifetime
    df = df[df["DateOut"] >= base_year]

    df["grouping_year"] = pd.cut(
        df["DateIn"],
        bins=grouping_years,
        labels=grouping_years[1:],
        right=True,
        include_lowest=True,
    ).astype(int)
    # +1 because the phase-out happens at the end of the year, like upstream
    df["lifetime"] = df["DateOut"] - df["grouping_year"] + 1

    grouped = df.groupby(["bus", "grouping_year"])
    aggregated = pd.DataFrame(
        {
            "capacity": grouped["Capacity"].sum(),
            "lifetime": grouped.apply(
                lambda g: np.average(g["lifetime"], weights=g["Capacity"]),
                include_groups=False,
            ),
        }
    )

    return aggregated[aggregated["capacity"] > threshold_capacity]


def build_biogas_chp_links(
    aggregated: pd.DataFrame, costs: pd.DataFrame
) -> pd.DataFrame:
    """
    Build the static Link table from aggregated capacities.

    The Links take biogas from the node's biogas bus and feed the node's
    electricity bus, with the technology parameters of ``COST_KEY`` as in the
    former upstream implementation. ``p_nom`` is the biogas input capacity,
    so ``p_nom * efficiency`` recovers the electric capacity.

    Parameters
    ----------
    aggregated
        Output of :func:`aggregate_biogas_plants`.
    costs
        Processed technology data for the planning horizon.

    Returns
    -------
    :
        Static Link attributes indexed by ``{bus} biogas CHP-{grouping_year}``.
    """
    efficiency = costs.at[COST_KEY, "efficiency"]
    bus = aggregated.index.get_level_values("bus")
    grouping_year = aggregated.index.get_level_values("grouping_year")

    links = pd.DataFrame(
        {
            "bus0": bus + " biogas",
            "bus1": bus,
            "carrier": CARRIER,
            "location": bus,
            "p_nom": aggregated["capacity"].to_numpy() / efficiency,
            "p_nom_extendable": False,
            # custom attribute of PyPSA-Eur; NaN would break the solve constraints
            "reversed": False,
            "efficiency": efficiency,
            # NB: costs are per MWel, Link capacities are per MW of biogas input
            "capital_cost": costs.at[COST_KEY, "capital_cost"] * efficiency,
            "onight_cost": costs.at[COST_KEY, "investment"] * efficiency,
            "marginal_cost": costs.at[COST_KEY, "VOM"] * efficiency,
            "build_year": grouping_year.astype(int),
            "lifetime": aggregated["lifetime"].to_numpy(),
        },
        index=pd.Index(bus + f" {CARRIER}-" + grouping_year.astype(str), name="name"),
    )

    return links


def add_existing_biogas_chp_at(
    n: pypsa.Network, snakemake: Snakemake, costs: pd.DataFrame
) -> None:
    """
    Add the Austrian Anlagenregister biogas plants as ``biogas CHP`` Links.

    Runs in the base year only; later horizons receive the Links through
    ``add_brownfield``. Returns early when
    ``mods: existing_capacities: add_biogas_to_power_plants_AT`` is false.

    Parameters
    ----------
    n
        The pre-network to modify in place.
    snakemake
        The Snakemake workflow object providing the prepared plants CSV
        (``input.biogas_plants_at``), the ``existing_capacities`` and
        ``planning_horizons`` params and the planning-horizon wildcard.
    costs
        Processed technology data for the planning horizon.

    Returns
    -------
    :
        Network is modified in place.

    Raises
    ------
    ValueError
        If the feature is enabled but no plants were prepared, if a biogas
        bus is missing, or if a Link of the same name already exists.
    """
    if not snakemake.params.add_biogas_to_power_plants_AT:
        logger.info(
            "Skipping Austrian biogas CHPs: add_biogas_to_power_plants_AT is false."
        )
        return

    year = int(snakemake.wildcards.planning_horizons)
    if year != min(snakemake.params.planning_horizons):
        return  # add_brownfield carries the base-year Links forward

    plants = pd.read_csv(snakemake.input.biogas_plants_at)
    if plants.empty:
        raise ValueError(
            f"No Austrian biogas plants in {snakemake.input.biogas_plants_at}, "
            "although add_biogas_to_power_plants_AT is enabled."
        )

    existing_capacities = snakemake.params.existing_capacities
    aggregated = aggregate_biogas_plants(
        plants,
        grouping_years=existing_capacities["grouping_years_power"],
        lifetime=costs.at[COST_KEY, "lifetime"],
        base_year=year,
        threshold_capacity=existing_capacities["threshold_capacity"],
    )
    links = build_biogas_chp_links(aggregated, costs)

    missing_buses = links["bus0"][~links["bus0"].isin(n.buses.index)]
    if not missing_buses.empty:
        raise ValueError(f"Biogas buses missing in network: {missing_buses.tolist()}.")
    duplicates = links.index.intersection(n.links.index)
    if not duplicates.empty:
        raise ValueError(f"Biogas CHP Links already exist: {duplicates.tolist()}.")

    if CARRIER not in n.carriers.index:
        color = snakemake.config["plotting"]["tech_colors"].get(CARRIER, "")
        n.add("Carrier", CARRIER, color=color)

    n.add("Link", links.index, **links.to_dict("series"))

    logger.info(
        f"Added {len(links)} '{CARRIER}' Links with "
        f"{aggregated['capacity'].sum():.1f} MW electric capacity from "
        f"{len(plants)} Austrian Anlagenregister plants."
    )
