# SPDX-FileCopyrightText: 2023-2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""
TYNDP PEMMDB trajectory overwrites for the ``modify_prenetwork`` step.

Writes TYNDP PEMMDB trajectory ``p_nom_min`` / ``p_nom_max`` bands onto
extendable components for multiple carriers across all modelled countries,
following a brownfield-deduction pattern so the bounds represent the
*additional* capacity still available to the solver.

* :func:`apply_pemmdb_trajectories` — entry point called from
  :func:`mods.network.modify_prenetwork`; reads the trajectory CSV, aggregates
  it to PyPSA-AT cluster regions, and delegates per-carrier bound writes.
"""

from logging import getLogger

import pandas as pd
import pypsa
from snakemake.script import Snakemake

from mods.constants import PROXIES
from mods.utils import resolve_tyndp_locations

logger = getLogger(__name__)


def aggregate_by_cluster_and_country(
    trajectories: pd.DataFrame,
    location_mapping: dict,
    skip_countries: tuple[str] | None = None,
) -> pd.DataFrame:
    """
    Aggregate TYNDP trajectory data to PyPSA-AT cluster regions and country codes.

    Maps raw TYNDP bus codes to PyPSA-AT location codes via the resolved
    location mapping, sums ``p_nom_min`` / ``p_nom_max`` per
    ``(location, pypsa_eur_carrier)`` pair.

    Parameters
    ----------
    trajectories:
        Raw trajectory DataFrame with at minimum the columns ``bus``,
        ``pypsa_eur_carrier``, ``p_nom_min``, and ``p_nom_max``.
    location_mapping:
        The TYNDP location mapping resolved for the clustering
        configuration, see
        :func:`mods.constants.resolve_tyndp_locations`.
    skip_countries:
        Two-letter ISO country codes (e.g. ``["AT", "DE"]``) whose locations
        are excluded from the output.  ``None`` skips no countries.

    Returns
    -------
    pd.DataFrame
        MultiIndex DataFrame indexed by ``(location, pypsa_eur_carrier)`` with
        columns ``p_nom_min`` and ``p_nom_max``.

    Raises
    ------
    ValueError
        If any ``bus`` value in *trajectories* is absent from
        the location mapping.
    """
    df = trajectories.copy()  # to prevent mutating input
    df["location"] = df["bus"].map(location_mapping)

    # make sure clustering is as expected
    unmapped = df.loc[df["location"].isna(), "bus"].unique()
    if len(unmapped):
        raise ValueError(
            f"TYNDP bus codes not in the location mapping: {sorted(unmapped)}"
        )

    if skip_countries:
        df = df[~df["location"].str[:2].isin(skip_countries)]

    # sum p_nom_min/max per cluster region
    result = df.groupby(["location", "pypsa_eur_carrier"])[
        ["p_nom_min", "p_nom_max"]
    ].sum()

    return result


def apply_trajectories(
    n, c, traj, carrier, skip_countries, is_myopic_year: bool, at_port: int = 0
):
    """
    Write trajectory ``p_nom_min`` / ``p_nom_max`` bounds onto a single carrier.

    For each non-skipped location that hosts an extendable component of *carrier*,
    the function:

    1. Looks up the pre-aggregated trajectory bounds from *traj*.
    2. Subtracts existing brownfield capacity (myopic horizons only) so that the
       bounds represent *additional* capacity still available to the solver.
       The brownfield is measured at the same port as the trajectory: bus-1 units
       (``p_nom × efficiency``) when ``at_port=1``, bus-0 units otherwise.
    3. Converts bus-1 output capacity bounds to bus-0 input bounds when
       ``at_port=1`` by dividing by component efficiency.
    4. Writes the final bounds directly to ``n.components[c].static``.

    Parameters
    ----------
    n:
        The PyPSA network object to modify in-place.
    c:
        Component class name, e.g. ``"Generator"`` or ``"Link"``.
    traj:
        Aggregated trajectory DataFrame as returned by
        :func:`aggregate_by_cluster_and_country`, indexed by
        ``(location, pypsa_eur_carrier)``.
    carrier:
        PyPSA carrier string to match against the network components and
        the trajectory index level ``pypsa_eur_carrier``.
    skip_countries:
        Two-letter ISO country codes whose locations are not touched.
    is_myopic_year:
        True if current planning horizon is not the first planning horizon.
    at_port:
        Port index used to identify the bus column (``"bus"`` for port 0,
        ``"bus1"`` for port 1) and, when set to ``1``, to convert output
        capacity bounds to input capacity bounds via component efficiency.
        Only ``0`` and ``1`` are supported.

    Raises
    ------
    ValueError
        If no extendable locations are found for *carrier*, or if the
        computed ``p_nom_min`` exceeds ``p_nom_max`` after brownfield
        subtraction.
    NotImplementedError
        If ``at_port`` is neither ``0`` nor ``1``.
    """
    comp = n.components[c].static.query("carrier == @carrier & p_nom_extendable")

    # use model locations for lookup. All model except 'skip_countries' locations
    # must be found in trajectories.
    locations = [
        name[0]
        for name in comp.index.str.split(" ")
        if name[0][:2] not in skip_countries
    ]

    # Sum up p_nom of all assets in the same port units as the trajectory.
    # For at_port=1 carriers (battery discharger, home battery discharger) the
    # trajectory p_nom_max is expressed in bus1 (output) MW, so the brownfield
    # deduction must also be in bus1 units (p_nom * efficiency). End-of-life
    # assets have been removed during add_brownfield(...)
    brownfield_capacities = n.statistics.installed_capacity(
        groupby=["location", "carrier"],
        components=c,
        carrier=carrier,
        at_port=str(at_port),
        nice_names=False,
        drop_zero=False,
    )

    if not locations:
        raise ValueError(f"Empty Locations detected for carrier {carrier}.")

    for loc in locations:
        # cannot use query, because some assets have empty no locations assigned
        bus_col = "bus" if c == "Generator" else f"bus{at_port}"
        idx = comp[comp[bus_col].str.startswith(loc)].index.item()
        existing_brownfield = brownfield_capacities.loc[loc].item()

        # Some trajectories are missing in open-tyndp upstream data set:
        if loc == "GB1" and carrier == "H2 Electrolysis":
            # Effectively negates H2 Electrolysis on Northern Ireland
            p_nom_min, p_nom_max = 0, 0
        else:  # fail for KeyErrors to reveal broken assumptions
            p_nom_min, p_nom_max = traj.loc[PROXIES.get(loc, loc), carrier]

        # reduce total boundaries by already built and still existing capacities.
        # Only in myopic years: in the base year the existing capacity is the
        # extendable component's own (non-zero) p_nom, which the optimiser already
        # accounts for as its starting point, so deducting it would double-count.
        if is_myopic_year:
            p_nom_min = max(0, p_nom_min - existing_brownfield)

        # For wind and solar, add_land_use_constraint() in solve_network.py subtracts
        # existing non-extendable p_nom from p_nom_max during the solve step.
        # Deducting here too would cause the brownfield to be subtracted twice.
        # solar-utility is not affected, because a constraint directly sets p_nom_opt
        # ceilings for combined solar + solar-hsat technologies.
        if is_myopic_year and carrier not in ("onwind", "solar rooftop"):
            p_nom_max = max(0, p_nom_max - existing_brownfield)

        # some trajectories are given for bus1 output capacities
        if at_port == 1:
            eff = comp.loc[idx, "efficiency"].item()
            p_nom_min = p_nom_min / eff
            p_nom_max = p_nom_max / eff
        elif at_port != 0:
            raise NotImplementedError(f"Value for 'at_port' {at_port} not implemented.")

        # Keep existing brownfield capacities as lower boundary for
        # base years to prevent model infeasibility
        if not is_myopic_year:
            installed = comp.loc[idx, "p_nom_min"].item()
            if p_nom_max < installed:
                logger.warning(
                    f"Trajectory p_nom_max {p_nom_max:.2f} for {c} {idx} is below the "
                    f"installed capacity {installed:.2f}. Raising p_nom_max to the "
                    f"installed capacity."
                )
                p_nom_max = installed

        # Sanity check for calculated boundaries
        if (p_nom_max - p_nom_min) < 0:
            raise ValueError(
                f"Sanity check failed: lower bound is larger than upper bound for "
                f"component {c} for {idx} to {p_nom_min} - {p_nom_max} "
            )

        # directly set on network components to avoid setting attributes on a copy
        n.components[c].static.loc[idx, "p_nom_max"] = p_nom_max
        if is_myopic_year:  # want to keep p_nom_min for base years
            n.components[c].static.loc[idx, "p_nom_min"] = p_nom_min

        logger.info(
            f"Setting p_nom_min/max for {c} {idx} to {p_nom_min:.2f} - {p_nom_max:.2f}"
        )


def register_extendable_nuclear(
    n: pypsa.Network,
    traj: pd.DataFrame,
    pyear: int,
    costs: pd.DataFrame,
) -> None:
    """
    Add one extendable nuclear Link per location so :func:`apply_trajectories` can bound it.

    Nuclear is a conventional carrier represented by one or more non-extendable
    *vintage* Links per location (``bus0="EU uranium"``, ``bus1`` = electricity
    bus, ``bus2="co2 atmosphere"``), all created by ``add_existing_baseyear``.
    Because no extendable variant exists, the trajectory bounds would have nothing
    to attach to.  This function creates that missing component — a single
    extendable Link per location that carries a non-zero nuclear trajectory band.
    An arbitrary existing nuclear Link acts as the schema donor (buses, ramp
    limits, custom PyPSA-Eur columns, ...), while the meaningful attributes
    (``efficiency``, ``capital_cost``, ``marginal_cost``, ``lifetime``) are taken
    from *costs*, ``p_nom`` is reset to zero and ``build_year`` set to *pyear*.
    The vintages are left untouched and carry the brownfield as a fixed floor;
    the actual ``p_nom_min`` / ``p_nom_max`` bounds are then written by
    :func:`apply_trajectories` via the standard ``techs`` loop
    (``("Link", "nuclear", 1)``).

    Locations whose nuclear bands are all zero (or absent) receive no extendable
    Link.  If a Link named ``{location} nuclear-{pyear}`` already exists with
    ``p_nom > 0``, it is an existing brownfield vintage and no extendable Link
    is added for that location.

    Parameters
    ----------
    n:
        The PyPSA network object to modify in-place.  Must contain at least one
        nuclear Link to act as the schema donor.
    traj:
        Aggregated trajectory DataFrame as returned by
        :func:`aggregate_by_cluster_and_country`, indexed by
        ``(location, pypsa_eur_carrier)``.
    pyear:
        Current planning horizon, used as the new Link's build year and name suffix.
    costs:
        The processed costs CSV data.

    Raises
    ------
    ValueError
        If a Link named ``{location} nuclear-{pyear}`` already exists with
        ``p_nom == 0``.
    IndexError
        If the network contains no nuclear Links at all (no schema donor).
    """
    carrier = "nuclear"

    where_carrier_non_zero = (
        "pypsa_eur_carrier == @carrier & (p_nom_min > 0 | p_nom_max > 0)"
    )
    nuclear_trajectories = traj.query(where_carrier_non_zero).droplevel(
        "pypsa_eur_carrier"
    )

    # Schema donor: an existing nuclear Link whose row supplies valid defaults
    # for all (incl. custom PyPSA-Eur) columns. All meaningful attributes are
    # overwritten below, so any nuclear Link is an equivalent donor.
    efficiency = costs.at[carrier, "efficiency"]
    template = n.links[n.links.carrier == carrier].iloc[0].copy()
    template["bus0"] = "EU uranium"
    template["bus2"] = "co2 atmosphere"
    template["p_nom"] = 0.0
    template["p_nom_extendable"] = True
    template["build_year"] = pyear
    template["efficiency"] = efficiency
    template["efficiency2"] = costs.at["uranium", "CO2 intensity"]
    template["capital_cost"] = efficiency * costs.at[carrier, "capital_cost"]
    template["marginal_cost"] = efficiency * costs.at[carrier, "VOM"]
    template["lifetime"] = costs.at[carrier, "lifetime"]

    for loc in nuclear_trajectories.index:
        name = f"{loc} {carrier}-{pyear}"
        if name in n.links.index:
            if n.links.at[name, "p_nom"] == 0:
                raise ValueError(
                    f"Unexpected empty vintage detected for {name} "
                    f"with p_nom {n.links.at[name, 'p_nom']:.2f}."
                )
            continue  # The brownfield asset already exists with a p_nom larger zero.

        link = template.copy()
        link["bus1"] = loc  # AC bus
        n.add("Link", name, **link)
        logger.info(f"Registered extendable nuclear Link: {name}.")


def apply_pemmdb_trajectories(n: pypsa.Network, snakemake: Snakemake, costs) -> None:
    """
    Apply TYNDP trajectory ``p_nom_min`` / ``p_nom_max`` bands from PEMMDB data.

    Entry point called from :func:`mods.network.modify_prenetwork` during the
    ``modify`` DAG phase.  Reads the trajectory CSV pointed to by
    ``snakemake.input.tyndp_trajectories``, filters it to the current planning
    horizon, aggregates it to PyPSA-AT cluster regions, and delegates per-carrier
    bound writes to :func:`apply_trajectories`.

    Only trajectory bands are applied; generator profiles and optimised ``p_nom``
    values are out of scope.

    The function is a no-op when ``mods.PEMMDB_trajectories.enable`` is ``false``
    in ``config.at.yaml``.

    Parameters
    ----------
    n:
        The PyPSA network object to modify in-place.
    snakemake:
        Snakemake proxy object providing ``config``, ``input``, and
        ``wildcards.planning_horizons``.

    Raises
    ------
    ValueError
        If the trajectory CSV contains no rows for the current planning horizon.
    """
    cfg = snakemake.config["mods"]["PEMMDB_trajectories"]
    if not cfg["enable"]:
        logger.info("PEMMDB trajectory overwrites disabled. Skipping.")
        return

    skip_countries = tuple(cfg["skip_countries"])
    pyear = int(snakemake.wildcards.planning_horizons)
    base_year = min(n.meta["scenario"]["planning_horizons"])
    is_myopic_year = pyear != base_year

    trajectories_fn = snakemake.input.tyndp_trajectories
    trajectories = pd.read_csv(trajectories_fn).query("pyear == @pyear")

    if trajectories.empty:
        raise ValueError(f"No trajectory data for horizon {pyear}.")

    location_mapping = resolve_tyndp_locations(
        snakemake.params.admin_levels,
        snakemake.params.custom_clustering,
    )
    traj_clustered = aggregate_by_cluster_and_country(
        trajectories, location_mapping, skip_countries
    )

    # Edge case (CI test config only): the reduced at10 test network models just
    # AT and its neighbours, while the TYNDP trajectories cover all of Europe.
    # Drop trajectory locations absent from the model so that
    # register_extendable_nuclear does not attach Links to non-existent buses.
    if n.meta["run"]["prefix"] == "test-sector-myopic-at10":
        model_locations = n.buses.location.unique()
        traj_clustered = traj_clustered[
            traj_clustered.index.get_level_values("location").isin(model_locations)
        ]

    techs = [
        ("Generator", "onwind", 0),
        ("Generator", "solar rooftop", 0),
        ("Link", "H2 Electrolysis", 0),
        ("Link", "battery discharger", 1),
        ("Link", "home battery discharger", 1),
    ]

    # Nuclear stays non-extendable in the base year. Capacities that do not exist today
    # (2025) should not be added by the optimizer. Nuclear plants take a very long time.
    if is_myopic_year:
        register_extendable_nuclear(n, traj_clustered, pyear, costs)
        techs.append(("Link", "nuclear", 1))

    # The Open-TYNDP carrier "solar-pv-utility" in the trajectories data frame
    # stands for combined "solar" and "solar-hsat" in PyPSA-AT. Their combined
    # trajectories are handled in a custom constraint in the pypsa-at mods constraints
    # module. That's why it is not included in the `techs` list.
    for c, carrier, port in techs:
        apply_trajectories(
            n, c, traj_clustered, carrier, skip_countries, is_myopic_year, at_port=port
        )
        # fail-fast: no extendable trajectory asset among techs may be left unbounded.
        # skip_country assets (e.g. AT, DE) are intentionally excluded — they receive
        # their bounds from the PyPSA-AT/-DE calibrations, not from TYNDP.
        unbounded = (
            n.components[c]
            .static.query(
                "carrier == @carrier"
                " & p_nom_extendable"
                " & not name.str.startswith(@skip_countries)"
                " & p_nom_max == inf"
            )
            .index
        )
        if not unbounded.empty:
            raise ValueError(
                f"Extendable {carrier} assets left without a finite p_nom_max: "
                f"{list(unbounded)}"
            )

    logger.info(f"PEMMDB trajectory bands applied for horizon {pyear}.")
