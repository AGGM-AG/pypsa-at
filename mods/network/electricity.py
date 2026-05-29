# SPDX-FileCopyrightText: 2023-2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""
Enforce absolute NTC floor values on cross-border transmission corridors.

For each corridor listed in the TYNDP transmission trajectories CSV, the module
filters to the current planning horizon year and computes the NTC target as
``max(direct_capacity, indirect_capacity)``.  It then calculates the installed
capacity of every Line and Link on the corridor, weighting each component by its
``s_max_pu`` / ``p_max_pu`` to obtain the effective active transfer limit.
Installed capacity is summed over both extendable components (contributing their
current lower bound ``s_nom_min`` / ``p_nom_min``) and non-extendable components
(contributing their fixed ``s_nom`` / ``p_nom``).

The shortfall ``target = NTC_target − installed_cap`` is derived.  When the
shortfall is positive (NTC not yet met), every extendable component on the
corridor has its lower bound scaled upward proportionally so that the summed
extendable lower bounds increase by exactly the shortfall.  When no extendable
capacity exists on a corridor, the raw lower bound per component is
``target / Σ(s_max_pu)`` for AC lines or ``target / Σ(p_max_pu)`` for DC
forward and reverse links respectively, so that the sum of effective capacities
equals the shortfall.
"""

import dataclasses
import logging
import math

import pandas as pd
import pypsa
from snakemake.script import Snakemake

from mods.utils import get_relevant_links_and_lines, sanity_check_links_and_lines

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class _CorridorComponents:
    """Classified Line and Link subsets for a single transmission corridor."""

    ac_ext: pd.DataFrame
    ac_nonext: pd.DataFrame
    dc_ext: pd.DataFrame
    dc_nonext: pd.DataFrame
    dc_indir_ext: pd.DataFrame

    @property
    def components(self) -> list[pd.DataFrame]:
        """All classified component subsets, for iteration over the corridor."""
        return [
            self.ac_ext,
            self.ac_nonext,
            self.dc_ext,
            self.dc_nonext,
            self.dc_indir_ext,
        ]


def _validate_dc_link_symmetry(relevant_links: pd.DataFrame) -> None:
    """
    Validate that cross-border DC Links are bidirectional and have symmetric lower bounds.

    Parameters
    ----------
    relevant_links : pd.DataFrame
        Active DC Links that cross a TYNDP border, as returned by
        ``get_relevant_links_and_lines``.  Must contain columns
        ``bus0``, ``bus1``, and ``p_nom_min``.

    Raises
    ------
    ValueError
        If any cross-border DC Link is not matched by a reverse link
        (i.e. links are not modelled as bidirectional pairs).
    ValueError
        If the summed ``p_nom_min`` of forward and reverse DC links on
        any corridor are not equal (asymmetric lower bounds).
    """
    # Explicit set comparison — easier to read than iterating the same DF twice.
    link_pairs = set(
        relevant_links[["bus0", "bus1"]].itertuples(index=False, name=None)
    )
    if link_pairs != {(b, a) for (a, b) in link_pairs}:
        raise ValueError("Found uni-directional cross-border links.")

    if not all(
        math.isclose(
            relevant_links.loc[
                (relevant_links["bus0"] == bus0) & (relevant_links["bus1"] == bus1),
                "p_nom_min",
            ].sum(),
            relevant_links.loc[
                (relevant_links["bus0"] == bus1) & (relevant_links["bus1"] == bus0),
                "p_nom_min",
            ].sum(),
        )
        for (bus0, bus1) in relevant_links[["bus0", "bus1"]].itertuples(
            index=False, name=None
        )
    ):
        raise ValueError("Found asymmetric cross-border links.")


def _classify_corridor(
    relevant_lines: pd.DataFrame,
    relevant_links: pd.DataFrame,
    from_node: str,
    to_node: str,
) -> _CorridorComponents:
    """
    Filter and split Lines and Links on a single corridor into extendable and non-extendable subsets.

    Parameters
    ----------
    relevant_lines : pd.DataFrame
        Active AC Lines crossing TYNDP borders, with ``bus0_tyndp`` and ``bus1_tyndp`` columns.
    relevant_links : pd.DataFrame
        Active DC Links crossing TYNDP borders, with ``bus0_tyndp`` and ``bus1_tyndp`` columns.
    from_node : str
        TYNDP location code for the corridor origin.
    to_node : str
        TYNDP location code for the corridor destination.

    Returns
    -------
    _CorridorComponents
        Classified subsets of Lines and Links for the corridor.
    """
    ac_curr = relevant_lines[
        (
            (relevant_lines["bus0_tyndp"] == from_node)
            & (relevant_lines["bus1_tyndp"] == to_node)
        )
        | (
            (relevant_lines["bus0_tyndp"] == to_node)
            & (relevant_lines["bus1_tyndp"] == from_node)
        )
    ]
    dc_dir_curr = relevant_links[
        (relevant_links["bus0_tyndp"] == from_node)
        & (relevant_links["bus1_tyndp"] == to_node)
    ]
    dc_indir_curr = relevant_links[
        (relevant_links["bus0_tyndp"] == to_node)
        & (relevant_links["bus1_tyndp"] == from_node)
    ]

    ac_nonext = ac_curr[~ac_curr["s_nom_extendable"]]
    ac_ext = ac_curr[ac_curr["s_nom_extendable"]]
    dc_nonext = dc_dir_curr[~dc_dir_curr["p_nom_extendable"]]
    dc_ext = dc_dir_curr[dc_dir_curr["p_nom_extendable"]]
    dc_indir_ext = dc_indir_curr[dc_indir_curr["p_nom_extendable"]]

    return _CorridorComponents(
        ac_ext=ac_ext,
        ac_nonext=ac_nonext,
        dc_ext=dc_ext,
        dc_nonext=dc_nonext,
        dc_indir_ext=dc_indir_ext,
    )


def apply_tyndp_transmission_lower_bounds(
    n: pypsa.Network,
    snakemake: Snakemake,
) -> None:
    """
    Set ``s_nom_min`` / ``p_nom_min`` so corridors meet the absolute TYNDP NTC floor.

    For each corridor in the TYNDP trajectories CSV the function filters to the
    current planning horizon year, computes ``installed_cap`` — the sum of all
    extendable and non-extendable Line/Link capacities on the corridor weighted
    by ``s_max_pu`` / ``p_max_pu`` — and derives the shortfall
    ``target = NTC_target − installed_cap``.  When the shortfall is positive,
    the extendable lower bounds are scaled proportionally by
    ``cap_factor = (total_ext_cap + target) / total_ext_cap`` so that their sum
    increases by exactly the shortfall.

    Parameters
    ----------
    n : pypsa.Network
        Pre-solve network to be modified in place.
    snakemake : Snakemake
        Snakemake workflow object.  Required attributes:

        * ``snakemake.input.tyndp_transmission_trajectories`` — path to a CSV
          with columns ``from_node``, ``to_node``, ``direct_capacity``,
          ``indirect_capacity``, ``year``.  The effective per-corridor NTC target
          is ``max(direct_capacity, indirect_capacity)`` — the larger of the two
          direction capacities is used intentionally to capture the dominant
          transfer direction.
        * ``snakemake.wildcards.planning_horizons`` — 4-digit year string
          (e.g. ``"2040"``).

    Returns
    -------
    None
        Modifies ``n.lines["s_nom_min"]`` and ``n.links["p_nom_min"]`` in place
        for extendable components on under-capacity corridors.

    Raises
    ------
    ValueError
        If cross-border DC Links are not modelled as bidirectional pairs.
    ValueError
        If forward and reverse DC link capacities on a corridor are asymmetric.

    Notes
    -----
    * The guard for which planning horizons trigger this function is enforced
      by the caller in ``mods.network.__init__``.
    * ``installed_cap`` sums both extendable components (using ``s_nom_min`` /
      ``p_nom_min`` as their current lower bound) and non-extendable components
      (using fixed ``s_nom`` / ``p_nom``), each weighted by ``s_max_pu`` /
      ``p_max_pu``.  Non-extendable components are never modified.
    * Only the forward DC direction is counted for ``installed_cap``; symmetry
      is validated by the asymmetry check before the corridor loop.
    * Corridors where ``target ≤ 0`` are skipped (NTC already met) and logged
      at INFO level.
    * The proportional scaling ``cap_factor = (total_ext_cap + target) / total_ext_cap``
      preserves the relative distribution of extendable capacity across parallel
      components on the same corridor.
    * When extendable capacity is zero (``ac_cap_ext == 0`` and ``dc_cap_ext == 0``),
      the raw lower bound per component is ``target / Σ(s_max_pu)`` for AC lines and
      ``target / Σ(p_max_pu)`` for DC forward and reverse links respectively, ensuring
      that the sum of effective capacities equals the shortfall.  A ``ValueError`` is
      raised if the relevant ``s_max_pu`` or ``p_max_pu`` sum is zero.
    """
    pyear = int(snakemake.wildcards.planning_horizons)
    if pyear not in snakemake.config["mods"]["tyndp_lower_bounds"]["years"]:
        return

    tyndp_traj = pd.read_csv(snakemake.input.tyndp_transmission_trajectories)

    # max(direct_capacity, indirect_capacity) is used as the effective corridor
    # NTC target — the larger of the two direction capacities captures the dominant
    # transfer direction and is intentional per the algorithm design.
    df = (
        tyndp_traj[tyndp_traj["year"] == pyear]
        .set_index(["from_node", "to_node"])
        .drop(columns=["year"])
        .max(axis=1)
        .rename("NTC_target")
        .reset_index()
    )

    relevant_links_curr, relevant_lines_curr = get_relevant_links_and_lines(n)
    sanity_check_links_and_lines(
        relevant_links=relevant_links_curr,
        relevant_lines=relevant_lines_curr,
        tyndp_transmission=df,
    )
    _validate_dc_link_symmetry(relevant_links_curr)

    for row in df.itertuples():
        node_from = row.from_node
        node_to = row.to_node
        from_to = f"{node_from}→{node_to}"

        corridor = _classify_corridor(
            relevant_lines_curr, relevant_links_curr, node_from, node_to
        )

        # Corridors present in the TYNDP CSV but entirely absent from the
        # (clustered) network are tolerated.
        if all(c.empty for c in corridor.components):
            logger.info(f"Corridor {from_to}: not modelled in network — skipping.")
            continue

        # Installed capacity: non-extendable components contribute fixed s_nom/p_nom;
        # extendable components contribute their current lower bound (s_nom_min/p_nom_min).
        # s_max_pu / p_max_pu weight converts apparent/rated capacity to effective active transfer limit.
        ac_cap_nonext = (
            corridor.ac_nonext["s_nom"] * corridor.ac_nonext["s_max_pu"]
        ).sum()
        ac_cap_ext = (corridor.ac_ext["s_nom_min"] * corridor.ac_ext["s_max_pu"]).sum()
        dc_cap_nonext = (
            corridor.dc_nonext["p_nom"] * corridor.dc_nonext["p_max_pu"]
        ).sum()
        dc_cap_ext = (corridor.dc_ext["p_nom_min"] * corridor.dc_ext["p_max_pu"]).sum()

        installed_cap = ac_cap_nonext + ac_cap_ext + dc_cap_nonext + dc_cap_ext

        target = row.NTC_target - installed_cap

        if target <= 0:
            logger.info(
                f"Corridor {from_to}: TYNDP target already met "
                f"(target={target:.1f} MW ≤ 0) — skipping."
            )
            continue

        if ac_cap_ext == 0 and dc_cap_ext == 0:
            # Zero-cap branch: extendable lower bounds are all zero; target is distributed so
            # that the total (summed) effective capacity equals the shortfall.
            if not corridor.ac_ext.empty:
                n.lines.loc[corridor.ac_ext.index, "s_nom_min"] = (
                    target / n.lines.loc[corridor.ac_ext.index, "s_max_pu"].sum()
                )
            elif not corridor.dc_ext.empty:
                n.links.loc[corridor.dc_ext.index, "p_nom_min"] = (
                    target / n.links.loc[corridor.dc_ext.index, "p_max_pu"].sum()
                )
                n.links.loc[corridor.dc_indir_ext.index, "p_nom_min"] = (
                    target / n.links.loc[corridor.dc_indir_ext.index, "p_max_pu"].sum()
                )
            else:
                # The corridor is modelled (non-extendable components exist) but
                # has no extendable capacity to scale up, so the NTC floor cannot
                # be met. This is a genuine inconsistency — fail fast.
                raise ValueError(
                    f"Corridor {from_to}: target={target:.1f} MW shortfall but "
                    f"only non-extendable lines or links found — cannot raise the "
                    f"lower bound to meet the TYNDP NTC floor."
                )
            logger.info(
                f"Corridor {from_to}: lower bounds set (zero-cap) — shortfall={target:.1f} MW."
            )
        else:
            total_ext_cap = ac_cap_ext + dc_cap_ext
            cap_factor = (total_ext_cap + target) / total_ext_cap

            n.lines.loc[corridor.ac_ext.index, "s_nom_min"] *= cap_factor
            n.links.loc[corridor.dc_ext.index, "p_nom_min"] *= cap_factor
            n.links.loc[corridor.dc_indir_ext.index, "p_nom_min"] *= cap_factor

            logger.info(
                f"Corridor {from_to}: lower bounds scaled — shortfall={target:.1f} MW "
                f"(cap_factor={cap_factor:.3f})."
            )
