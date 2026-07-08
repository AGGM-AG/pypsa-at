# SPDX-FileCopyrightText: 2023-2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""TYNDP-driven constraints: cross-border NTC flow limits and solar utility trajectory bands."""

import logging

import pandas as pd
import pypsa

from mods.network.trajectories import aggregate_by_cluster_and_country
from mods.utils import get_relevant_links_and_lines

logger = logging.getLogger(__name__)


def constraint_ntc_flow_limits(
    n: pypsa.Network, snakemake, investment_year: int
) -> None:
    """
    Add TYNDP NTC-style net cross-border flow limit constraints per snapshot.

    Reads the TYNDP transmission trajectory CSV for ``investment_year`` and
    adds two per-snapshot linopy constraints to ``n.model`` for each
    corridor: one limiting net flow in the direct direction and one limiting
    net flow in the indirect direction.

    Net flow from location A to location B is defined as:

    .. code-block:: none

        sum(Line-s for lines with bus0_tyndp == A, bus1_tyndp == B)
        − sum(Line-s for lines with bus0_tyndp == B, bus1_tyndp == A)
        + sum(efficiency × Link-p for DC links with bus0_tyndp == A, bus1_tyndp == B)
        − sum(Link-p for DC links with bus0_tyndp == B, bus1_tyndp == A)

    Parameters
    ----------
    n : pypsa.Network
        PyPSA network with a linopy model attached (``n.model``).
    snakemake
        Snakemake workflow object. Must expose
        ``snakemake.input.tyndp_transmission_trajectories`` — path to a CSV
        with columns ``from_node``, ``to_node``, ``direct_capacity``,
        ``indirect_capacity``, and ``year``.  ``direct_capacity`` is the
        capacity in the ``from_node → to_node`` direction (MW);
        ``indirect_capacity`` is the capacity in the reverse direction (MW).
    investment_year : int
        Planning horizon year used to filter the CSV.

    Raises
    ------
    ValueError
        If the CSV contains no rows for ``investment_year``.

    Notes
    -----
    * The ``enable`` guard (``mods.tyndp_cross_border_flow_limits.enable``) is
      handled by the caller; this function does not check it.
    * DC Links are **included** in the NTC constraint alongside AC Lines: direct
      links contribute ``efficiency × link_p`` (power received at bus1); indirect
      links contribute raw ``link_p`` (power dispatched from their grid).
    * Constraint names follow the pattern
      ``tyndp_ntc_flow_dir-{A}-{B}-{year}`` (direct) and
      ``tyndp_ntc_flow_indir-{B}-{A}-{year}`` (indirect).
    * Corridors with no matching active AC Lines or DC Links in the network
      are skipped with a warning (no constraint is added).
    * Constraints are time-varying (one inequality per snapshot) and are
      therefore **not** registered as ``GlobalConstraint`` network objects.
    """
    years_with_ntcs = snakemake.config["mods"]["tyndp_lower_bounds"]["years"]
    if investment_year not in years_with_ntcs:
        logger.info(
            f"Skip setting electricity transmission "
            f"lower bounds from NTCs for {investment_year}."
        )
        return
    df = pd.read_csv(snakemake.input.tyndp_transmission_trajectories)
    df = df[df["year"] == investment_year]

    if df.empty:
        raise ValueError(
            f"No cross-border NTC limits defined for year {investment_year}."
        )

    logger.info(f"Adding cross-border flow limits for year {investment_year}")

    relevant_links, relevant_lines = get_relevant_links_and_lines(n)

    line_s = n.model["Line-s"]
    link_p = n.model["Link-p"]

    for row in df.itertuples():
        from_node: str = row.from_node
        to_node: str = row.to_node
        dir_cap: float = row.direct_capacity
        indir_cap: float = row.indirect_capacity

        links_dir_idx = relevant_links[
            (relevant_links["bus0_tyndp"] == from_node)
            & (relevant_links["bus1_tyndp"] == to_node)
        ].index
        links_indir_idx = relevant_links[
            (relevant_links["bus0_tyndp"] == to_node)
            & (relevant_links["bus1_tyndp"] == from_node)
        ].index

        lines_dir_idx = relevant_lines[
            (relevant_lines["bus0_tyndp"] == from_node)
            & (relevant_lines["bus1_tyndp"] == to_node)
        ].index
        lines_indir_idx = relevant_lines[
            (relevant_lines["bus0_tyndp"] == to_node)
            & (relevant_lines["bus1_tyndp"] == from_node)
        ].index

        if (
            links_dir_idx.empty
            and links_indir_idx.empty
            and lines_dir_idx.empty
            and lines_indir_idx.empty
        ):
            logger.warning(
                f"Ignoring constraints for border {from_node}->{to_node} in {investment_year}"
            )
            continue

        lines_lhs_dir = line_s.sel(name=lines_dir_idx).sum("name") - line_s.sel(
            name=lines_indir_idx
        ).sum("name")
        lines_lhs_indir = -1 * lines_lhs_dir

        eff_dir = n.links.loc[links_dir_idx, "efficiency"]
        eff_indir = n.links.loc[links_indir_idx, "efficiency"]

        links_lhs_dir = link_p.sel(name=links_dir_idx).mul(eff_dir).sum(
            "name"
        ) - link_p.sel(name=links_indir_idx).sum("name")

        links_lhs_indir = link_p.sel(name=links_indir_idx).mul(eff_indir).sum(
            "name"
        ) - link_p.sel(name=links_dir_idx).sum("name")

        cname_dir = f"tyndp_ntc_flow_dir-{from_node}-{to_node}-{investment_year}"
        cname_indir = f"tyndp_ntc_flow_indir-{to_node}-{from_node}-{investment_year}"

        n.model.add_constraints(
            lines_lhs_dir + links_lhs_dir <= dir_cap, name=cname_dir
        )
        n.model.add_constraints(
            lines_lhs_indir + links_lhs_indir <= indir_cap, name=cname_indir
        )

        logger.info(
            f"TYNDP NTC constraint added: {from_node}→{to_node} ≤ {dir_cap} MW, "
            f"{to_node}→{from_node} ≤ {indir_cap} MW."
        )


def constraint_combined_solar_trajectories(
    n: pypsa.Network,
    snakemake,
    investment_year: int,
) -> None:
    """
    Add joint solar utility trajectory floor/ceiling constraints.

    Enforces combined ``solar`` + ``solar-hsat`` capacity per modelled location
    against TYNDP ``solar-pv-utility`` trajectory bands, after deducting
    existing brownfield capacity.

    The constraint reads:

    .. code-block:: none

        p_nom_opt[solar @ loc] + p_nom_opt[solar-hsat @ loc]
            >= max(0, traj_p_nom_min[loc] - brownfield[loc])   # floor
        p_nom_opt[solar @ loc] + p_nom_opt[solar-hsat @ loc]
            <= max(0, traj_p_nom_max[loc] - brownfield[loc])   # ceiling

    Locations where both bounds equal 0 after brownfield deduction are skipped.

    Parameters
    ----------
    n
        The pypsa network with a linopy model attached (``n.model``).
    snakemake
        The snakemake workflow object.  Must expose
        ``snakemake.input.tyndp_trajectories`` and the config key
        ``mods.PEMMDB_trajectories``.
    investment_year
        The myopic planning horizon (e.g. 2030, 2040, 2050).

    Notes
    -----
    ``solar-pv-utility`` trajectories cover the *combined* deployment of
    ``solar`` (flat-panel) and ``solar-hsat`` (single-axis tracking).  They
    are intentionally skipped in ``overwrite_pemmdb_capacities`` and handled
    here as linopy constraints so that the solver can choose the mix freely.
    """
    cfg = snakemake.config["mods"]["PEMMDB_trajectories"]
    if not cfg.get("enable"):
        logger.info(
            "PEMMDB_trajectories disabled — skipping solar utility trajectory constraints."
        )
        return

    skip_countries = cfg["skip_countries"]

    trajectories = pd.read_csv(snakemake.input.tyndp_trajectories).query(
        "pyear == @investment_year"
    )
    traj_clustered = aggregate_by_cluster_and_country(trajectories, [])

    # solar-pv-utility rows carry pypsa_eur_carrier == "solar(-hsat)"
    traj_solar = traj_clustered.xs("solar(-hsat)", level="pypsa_eur_carrier")

    # Pre-compute brownfield: sum of installed solar + solar-hsat per location
    carrier = ["solar", "solar-hsat"]
    brownfield = n.statistics.installed_capacity(
        groupby=["location", "carrier"],
        carrier=carrier,
        aggregate_across_components=True,
        nice_names=False,
        drop_zero=False,
    )
    # Sum over the carrier level → single Series indexed by location
    brownfield_by_loc = brownfield.groupby(level="location").sum()

    for loc in brownfield_by_loc.index:
        if loc.startswith(tuple(skip_countries)):
            logger.info(f"Skipping solar trajectory constraint for {loc}.")
            continue

        # Kosovo "XK" has no TYNDP data. Always use RS trajectories instead. Note
        # that the location proxy is different from the missing p_nom_min/max
        # replacements further below. Here, we always want to replace values, not only
        # if they are zero.
        loc_proxy = "RS" if loc == "XK" else loc
        p_nom_min = traj_solar.at[loc_proxy, "p_nom_min"]
        p_nom_max = traj_solar.at[loc_proxy, "p_nom_max"]

        # some countries do not have trajectories for solar-utility. Want to
        # replace by trajectory values from a nearby country of similar size.
        if p_nom_min == 0.0 and p_nom_max == 0.0:
            traj_proxy = {"BE": "NL", "CH": "AT", "NO": "SE", "SI": "SK", "XK": "RS"}
            if loc not in traj_proxy:
                raise KeyError(
                    f"Unexpected missing trajectories detected for loc {loc} and {investment_year}."
                )
            # fetch trajectories again from updated locations
            p_nom_min = traj_solar.at[traj_proxy[loc], "p_nom_min"]
            p_nom_max = traj_solar.at[traj_proxy[loc], "p_nom_max"]

        # existing brownfield from the original country
        existing_brownfield = brownfield_by_loc.at[loc]

        # determine brownfield correction
        pyear = int(n.meta["wildcards"]["planning_horizons"])
        deduction = 0  # for base year 2025
        if pyear > 2025:
            # reduce total boundaries by already built and still existing
            # capacities from previous myopic optimizations
            deduction = existing_brownfield

        # apply brownfield correction
        rhs_min = max(0.0, p_nom_min - deduction)
        rhs_max = max(0.0, p_nom_max - deduction)

        # it is possible that extrapolated p_nom_max values are smaller than the existing
        # brownfield from powerplant-matching. The function add_existing_baseyear.py
        # automatically adds p_nom-lower >= existing_brownfield constraints. We cannot set
        # upper boundaries smaller than the lower limit, which is the existing capactiy.
        if pyear == 2025:
            rhs_max = max(rhs_max, existing_brownfield)

        # Collect extendable solar and solar-hsat generators at this location
        gens = n.generators.query(
            "carrier in @carrier and bus.str.startswith(@loc) and p_nom_extendable"
        ).index.tolist()
        if not gens:
            logger.debug(
                f"No extendable solar/solar-hsat generators at {loc} — skipping."
            )
            continue

        lhs = n.model["Generator-p_nom"].sel(name=gens).sum()

        cname_upper = f"tyndp-combined-solar-upper[{loc} solar(-hsat)-{pyear}]"
        cname_lower = f"tyndp-combined-solar-lower[{loc} solar(-hsat)-{pyear}]"

        # The model constraint must be prefixed with "GlobalConstraint-" so that
        # pypsa's assign_duals() can split the name into the GlobalConstraint
        # component and the matching index, and persist the shadow price as
        # ``mu`` on the network. See eag.py for the same pattern.
        model_cname_upper = f"GlobalConstraint-{cname_upper}"
        model_cname_lower = f"GlobalConstraint-{cname_lower}"

        if rhs_min == 0.0 and rhs_max == 0.0:
            # Brownfield fills the ceiling — lock new builds to zero.
            n.model.add_constraints(lhs <= 0.0, name=model_cname_upper)
            if cname_upper not in n.global_constraints.index:
                n.add(
                    "GlobalConstraint",
                    cname_upper,
                    constant=0.0,
                    sense="<=",
                    type="",
                    carrier_attribute="",
                )
            logger.info(
                f"Solar utility capacity locked at 0 for {loc}: "
                f"brownfield={existing_brownfield:.1f} MW fills trajectory ceiling of {rhs_max:.1f} MW."
            )
            continue

        # add constraints twice: once to model and once to the Network object
        # constraints are only persisted to output networks if they are appended
        # the network objects GlobalConstraint attribute.
        n.model.add_constraints(lhs <= rhs_max, name=model_cname_upper)
        if cname_upper not in n.global_constraints.index:
            n.add(
                "GlobalConstraint",
                cname_upper,
                constant=rhs_max,
                sense="<=",
                type="",
                carrier_attribute="",
            )

        n.model.add_constraints(lhs >= rhs_min, name=model_cname_lower)
        if cname_lower not in n.global_constraints.index:
            n.add(
                "GlobalConstraint",
                cname_lower,
                constant=rhs_min,
                sense=">=",
                type="",
                carrier_attribute="",
            )

        logger.info(
            f"Solar utility constraint added for {loc}: "
            f"floor={rhs_min:.1f} MW, ceiling={rhs_max:.1f} MW "
            f"(brownfield={deduction:.1f} MW deducted)"
        )
