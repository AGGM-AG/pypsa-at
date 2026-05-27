# SPDX-FileCopyrightText: 2023-2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""
PEMMDB trajectory band overwrites for the ``modify_prenetwork`` step.

Applies p_nom_min / p_nom_max trajectory bands from the TYNDP investment
dataset to all carriers present in the trajectories CSV.  Profiles and p_nom
values are out of scope — they are derived from atlite or optimised by the
solver.

Bus mapping
-----------
TYNDP country nodes are translated to PyPSA-AT NUTS codes via the explicit
``_TYNDP_TO_PYPSA_BUS`` dictionary.  Key rules:

- AT and DE are intentionally absent from the mapping and are never touched.
- Sub-national TYNDP zones follow the island-splitting in
  ``mods.clustering.apply_custom_clustering``: Italian Sicily → ``IT1``,
  Sardinia → ``IT2``; Danish Sjaelland → ``DK1``; Northern Ireland → ``GB1``;
  Balearic Islands → ``ES1`` (no TYNDP node in current dataset).
- When multiple TYNDP buses collapse to the same NUTS zone their p_nom_min
  and p_nom_max are summed and a warning is logged.
- When a NUTS zone has more than one PyPSA bus the trajectory cannot be
  disaggregated: a warning is logged and that zone is skipped.
"""

from logging import getLogger

import pandas as pd
import pypsa
from snakemake.script import Snakemake

from mods.constants import PROXIES, TYNDP_TO_PYPSA_LOCATION

logger = getLogger(__name__)


def aggregate_by_cluster_and_country(
    trajectories: pd.DataFrame,
    skip_countries: list[str] | None = None,
) -> pd.DataFrame:
    """
    Aggregate TYNDP trajectory data to PyPSA-AT cluster regions and country codes.

    Maps raw TYNDP bus codes to PyPSA-AT location codes via ``TYNDP_TO_PYPSA_LOCATION``,
    sums ``p_nom_min`` / ``p_nom_max`` per ``(location, pypsa_eur_carrier)`` pair, and
    additionally aggregates to two-letter country codes so that country-level clustering
    configurations (e.g. Italy as a single node) still find a matching trajectory.

    Parameters
    ----------
    trajectories:
        Raw trajectory DataFrame with at minimum the columns ``bus``,
        ``pypsa_eur_carrier``, ``p_nom_min``, and ``p_nom_max``.
    skip_countries:
        Two-letter ISO country codes (e.g. ``["AT", "DE"]``) whose locations
        are excluded from the output.  ``None`` skips no countries.

    Returns
    -------
    pd.DataFrame
        MultiIndex DataFrame indexed by ``(location, pypsa_eur_carrier)`` with
        columns ``p_nom_min`` and ``p_nom_max``.  Contains both sub-national
        cluster codes (e.g. ``IT1``) and country-level codes (e.g. ``IT``),
        with country-level entries derived by summing the cluster entries.

    Raises
    ------
    ValueError
        If any ``bus`` value in *trajectories* is absent from
        ``TYNDP_TO_PYPSA_LOCATION``.
    """
    df = trajectories.copy()  # to prevent mutating input
    df["location"] = df["bus"].map(TYNDP_TO_PYPSA_LOCATION)

    # make sure clustering is as expected
    unmapped = df.loc[df["location"].isna(), "bus"].unique()
    if len(unmapped):
        raise ValueError(
            f"TYNDP bus codes not in _TYNDP_TO_PYPSA_LOCATION mapping, skipping: "
            f"{sorted(unmapped)}"
        )

    if skip_countries:
        df = df[~df["location"].str[:2].isin(skip_countries)]

    # sum p_nom_min/max per cluster region
    traj_location = df.groupby(["location", "pypsa_eur_carrier"])[
        ["p_nom_min", "p_nom_max"]
    ].sum()

    # also sum per country for flexible clustering config:
    # Like this it's possible to cluster IT at country level.
    to_country_codes = {loc: loc[:2] for loc in traj_location.index.unique("location")}
    traj_countries = (
        traj_location.rename(to_country_codes, level="location")
        .groupby(traj_location.index.names)
        .sum()
    )

    # trajectories with both: clustered locations and country codes
    result = traj_location.combine_first(traj_countries).sort_index()

    # # Need to drop some countries: They are not modeled in PyPSA-AT
    # result = result.drop(index=["CY"], level="location")

    return result


def apply_trajectories(
    n, c, traj, carrier, skip_countries, is_myopic_year: bool, at_port: int = 0
):
    """
    Write trajectory ``p_nom_min`` / ``p_nom_max`` bounds onto a single carrier.

    For each non-skipped location that hosts an extendable component of *carrier*,
    the function:

    1. Looks up the pre-aggregated trajectory bounds from *traj*.
    2. Subtracts existing brownfield capacity (planning horizons > 2025 only) so
       that the bounds represent *additional* capacity still available to the solver.
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

    # Sum up p_nom of all assets. End-of-life assets have been
    # removed during add_brownfield(...)
    brownfield_capacities = n.statistics.installed_capacity(
        groupby=["location", "carrier"],
        components=c,
        carrier=carrier,
        aggregate_across_components=True,
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
        else:
            # Let's fail for KeyErrors to reveal broken assumptions
            p_nom_min, p_nom_max = traj.loc[PROXIES.get(loc, loc), carrier]

        # reduce total boundaries by already built and still existing capacities
        if is_myopic_year:
            p_nom_min = max(0, p_nom_min - existing_brownfield)
            p_nom_max = max(0, p_nom_max - existing_brownfield)

        # some trajectories are given for bus1 output capacities
        if at_port == 1:
            eff = comp.loc[idx, "efficiency"].item()
            p_nom_min = p_nom_min / eff
            p_nom_max = p_nom_max / eff
        elif at_port != 0:
            raise NotImplementedError(f"Value for 'at_port' {at_port} not implemented.")

        # Sanity check for calculated boundaries
        if (p_nom_max - p_nom_min) < 0:
            raise ValueError(
                f"Sanity check failed: lower bound is larger than upper bound for "
                f"component {c} for {idx} to {p_nom_min} - {p_nom_max} "
            )

        # directly set on network components --> avoids setting attributes on a copy
        n.components[c].static.loc[idx, "p_nom_max"] = p_nom_max
        if is_myopic_year:  # want to keep p_nom_min for base years
            n.components[c].static.loc[idx, "p_nom_min"] = p_nom_min

        logger.info(f"Setting p_nom_min/max for {c} {idx} to {p_nom_min} - {p_nom_max}")


def overwrite_pemmdb_capacities(n: pypsa.Network, snakemake: Snakemake) -> None:
    """
    Apply TYNDP trajectory ``p_nom_min`` / ``p_nom_max`` bands from PEMMDB data.

    Entry point called from ``mods/network_updates.py`` during the ``modify``
    DAG phase.  Reads the trajectory CSV pointed to by
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

    skip_countries = cfg["skip_countries"]
    pyear = int(snakemake.wildcards.planning_horizons)
    base_year = int(sorted(n.meta["scenario"]["planning_horizons"])[0])
    is_myopic_year = pyear != base_year

    trajectories = pd.read_csv(snakemake.input.tyndp_trajectories).query(
        "pyear == @pyear"
    )

    if trajectories.empty:
        raise ValueError(f"No trajectory data for horizon {pyear}.")

    traj_clustered = aggregate_by_cluster_and_country(trajectories, skip_countries)

    techs = [
        ("Generator", "onwind", 0),
        ("Generator", "solar rooftop", 0),
        ("Link", "H2 Electrolysis", 0),
        ("Link", "battery discharger", 1),
        ("Link", "home battery discharger", 1),
    ]

    # The Open-TYNDP carrier "solar-pv-utility" in the trajectories data frame
    # stands for combined "solar" and "solar-hsat" in PyPSA-AT. Their combined
    # trajectories are handled in a custom constraint in the pypsa-at mods constraints
    # module. That's why it is not included in the `techs` list.
    for c, carrier, port in techs:
        apply_trajectories(
            n, c, traj_clustered, carrier, skip_countries, is_myopic_year, at_port=port
        )

    logger.info(f"PEMMDB trajectory bands applied for horizon {pyear}.")
