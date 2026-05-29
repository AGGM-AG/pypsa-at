# SPDX-FileCopyrightText: 2023-2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""
Capacity potential overwrites for the ``modify_prenetwork`` step.

Two complementary p_nom_max writers share this module because both source their
bounds from external capacity studies and follow the same brownfield-deduction
pattern:

* :func:`overwrite_pemmdb_capacities` — TYNDP PEMMDB trajectory bands for
  multiple carriers across all modelled countries.
* :func:`apply_klien_potential_limits` — Austrian KLIEN study regional
  potentials (ground PV, building PV, onshore wind).
"""

from collections import defaultdict
from logging import getLogger
from pathlib import Path

import pandas as pd
import pypsa
from snakemake.script import Snakemake

from mods.constants import PROXIES, TYNDP_TO_PYPSA_LOCATION

logger = getLogger(__name__)

# ---------------------------------------------------------------------------
# PEMMDB trajectory overwrites
# ---------------------------------------------------------------------------
#
# Applies p_nom_min / p_nom_max trajectory bands from the TYNDP investment
# dataset to all carriers present in the trajectories CSV. Profiles and p_nom
# values are out of scope — they are derived from atlite or optimised by the
# solver.
#
# Bus mapping
# -----------
# TYNDP country nodes are translated to PyPSA-AT NUTS codes via the explicit
# ``TYNDP_TO_PYPSA_LOCATION`` dictionary in ``mods.constants``. Key rules:
#
# - AT and DE are intentionally absent from the mapping and are never touched.
# - Sub-national TYNDP zones follow the island-splitting in
#   ``mods.clustering.apply_custom_clustering``: Italian Sicily → ``IT1``,
#   Sardinia → ``IT2``; Danish Sjaelland → ``DK1``; Northern Ireland → ``GB1``;
#   Balearic Islands → ``ES1`` (no TYNDP node in current dataset).
# - When multiple TYNDP buses collapse to the same NUTS zone their p_nom_min
#   and p_nom_max are summed and a warning is logged.
# - When a NUTS zone has more than one PyPSA bus the trajectory cannot be
#   disaggregated: a warning is logged and that zone is skipped.


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


# ---------------------------------------------------------------------------
# AT KLIEN regional potential limits
# ---------------------------------------------------------------------------

# Mapping from PyPSA carrier name to the KLIEN study CSV type.
# ``solar`` and ``solar-hsat`` share the ground-mounted CSV because they
# share the same land area; the model enforces a combined land-use
# constraint in ``solve_network``.
_PYPSA_TO_KLIEN_MAPPING: dict[str, str] = {
    "solar rooftop": "buildings",
    "solar": "ground",
    "solar-hsat": "ground",
    "onwind": "wind",
}

_KLIEN_TO_PYPSA_MAPPING: dict[str, list[str]] = defaultdict(list)
for _k, _v in _PYPSA_TO_KLIEN_MAPPING.items():
    _KLIEN_TO_PYPSA_MAPPING[_v].append(_k)


def _set_p_nom_max(
    n: pypsa.Network,
    gen_idx: str,
    p_nom_max: float,
) -> None:
    """
    Set ``p_nom_max`` for one extendable generator, capped to ``p_nom_min``.

    Parameters
    ----------
    n
        The network whose generator table is modified in place.
    gen_idx
        Row label of the generator in ``n.generators``.
    p_nom_max
        The new upper bound on nominal capacity (MW). Clamped to
        ``p_nom_min`` if the value is below it.

    """
    gen_p_nom_min = n.generators.loc[gen_idx, "p_nom_min"]
    if gen_p_nom_min > p_nom_max:
        # Happens due to issues in wind distribution for the base year
        logger.warning(f"KLIEN potential is below minimum for {gen_idx}")
        p_nom_max = gen_p_nom_min
    n.generators.loc[gen_idx, "p_nom_max"] = p_nom_max


def _resolve_scenario_column(snakemake: Snakemake) -> str:
    """
    Validate scenario parameters and return the KLIEN CSV column name.

    Reads the following keys from ``snakemake.params``:

    * ``klien_potential_limits_use_technical_potentials``: when ``True``,
      returns ``"C_technical_potential"`` regardless of the other parameters
      (which are still validated).
    * ``klien_potential_limits_year``: study year; must be 2030 or 2040.
    * ``klien_potential_limits_ambition``: scenario ambition level; must be
      ``"low"``, ``"medium"``, or ``"high"``.
    * ``klien_potential_limits_climate_scenario``: climate scenario code; must
      be ``"wocc"``, ``"mocc"``, or ``"stcc"``.

    Parameters
    ----------
    snakemake
         Snakemake workflow object providing ``snakemake.params``.

    Returns
    -------
    :
        The column name to look up in the KLIEN potential CSV.

    Raises
    ------
    ValueError
         If any of ``climate_scenario``, ``year``, or ``ambition`` is invalid.
    """
    use_technical_potentials = snakemake.params[
        "klien_potential_limits_use_technical_potentials"
    ]
    year = snakemake.params["klien_potential_limits_year"]
    ambition = snakemake.params["klien_potential_limits_ambition"]
    climate_scenario = snakemake.params["klien_potential_limits_climate_scenario"]

    valid_climate = {"wocc", "mocc", "stcc"}
    valid_years = {2030, 2040}
    valid_ambitions = {"low", "medium", "high"}

    if climate_scenario not in valid_climate:
        raise ValueError(
            f"klien_potential_limits.climate_scenario={climate_scenario} is not valid. "
            f"Choose from {valid_climate}."
        )
    if year not in valid_years:
        raise ValueError(
            f"klien_potential_limits.year={year} is not valid. "
            f"Choose from {valid_years}."
        )
    if ambition not in valid_ambitions:
        raise ValueError(
            f"klien_potential_limits.ambition={ambition} is not valid. "
            f"Choose from {valid_ambitions}."
        )
    if use_technical_potentials:
        return "C_technical_potential"
    return f"C_{year}_{ambition}_{climate_scenario}"


def _paths_for_at_level(at_level: int, snakemake: Snakemake) -> dict[str, str]:
    """
    Return a mapping from CSV type to file path for the given AT clustering level.

    Parameters
    ----------
    at_level
        Integer NUTS level for Austria (2 = AT10, 3 = NUTS3).
        snakemake: Snakemake workflow object providing ``snakemake.input``.

    Returns
    -------
    :
        Dict mapping ``"buildings"``, ``"ground"``, ``"wind"`` to absolute file paths,
        or an empty dict when ``at_level`` is unsupported.
    """
    if at_level == 2:
        return {
            "buildings": snakemake.input.at10_buildings,
            "ground": snakemake.input.at10_ground,
            "wind": snakemake.input.at10_wind,
        }
    if at_level == 3:
        return {
            "buildings": snakemake.input.nuts3_buildings,
            "ground": snakemake.input.nuts3_ground,
            "wind": snakemake.input.nuts3_wind,
        }
    return {}


def apply_klien_potential_limits(n: pypsa.Network, snakemake: Snakemake) -> None:
    """
    Cap extendable AT generator ``p_nom_max`` values by regional KLIEN study potentials.

    Reads pre-processed capacity potential CSVs (in MW) produced by
    ``build_klien_potentials``, subtracts already-committed brownfield capacity,
    and writes the remaining headroom into ``p_nom_max`` for every extendable
    AT generator whose carrier appears in ``klien_potential_limits.technologies``.

    Only generators on buses whose index starts with ``"AT"`` are affected.
    Non-AT generators (e.g. DE, CH) are left unchanged.  The function skips
    silently when ``klien_potential_limits.technologies`` is an empty list.

    When ``klien_potential_limits.use_technical_potentials`` is true, the column
    ``C_technical_potential`` is used regardless of ``year``, ``ambition``, or
    ``climate_scenario``.

    Supported carriers and their CSV source:

    * ``solar rooftop`` — ``{resolution}_pv_buildings.csv``
    * ``solar``, ``solar-hsat`` — ``{resolution}_pv_ground.csv`` (shared land area)
    * ``onwind`` — ``{resolution}_wind.csv``

    Parameters
    ----------
    n
        The pre-network to be modified in place.
    snakemake
        Snakemake workflow object; config is read via ``snakemake.params`` and
        file paths via ``snakemake.input``.

    Raises
    ------
    ValueError
        If any entry in ``technologies`` is not a recognised carrier, or if
        ``climate_scenario``, ``year``, or ``ambition`` are unrecognised.
    KeyError
        If the requested scenario column is absent from a potential CSV.

    Notes
    -----
    Brownfield capacity is estimated via ``n.statistics.installed_capacity()``,
    which captures carry-over from previous myopic periods.  Unsupported AT
    clustering levels emit a warning and cause an early return rather than raising.
    """
    technologies = snakemake.params["klien_potential_limits_technologies"]
    if not technologies:
        logger.info("KLIEN potential limits: technologies list is empty — skipping.")
        return

    unknown = set(technologies) - set(_PYPSA_TO_KLIEN_MAPPING.keys())
    if unknown:
        raise ValueError(
            f"Unknown technologies in klien_potential_limits.technologies: {unknown}. "
            f"Valid options: {list(_PYPSA_TO_KLIEN_MAPPING.keys())}."
        )

    col = _resolve_scenario_column(snakemake)

    at_level = snakemake.config["clustering"]["administrative"]["AT"]
    paths = _paths_for_at_level(at_level, snakemake)
    if not paths:
        logger.warning(
            f"Unsupported clustering level AT={at_level!r}. Expected 2 or 3. "
            "— Skipping KLIEN potential limits."
        )
        return

    # Load each CSV type once; map each requested carrier to its potential dict.
    klien_types_needed = {_PYPSA_TO_KLIEN_MAPPING[t] for t in technologies}
    carrier_potential: dict[str, dict] = {}
    for klien_type in klien_types_needed:
        df = pd.read_csv(Path(paths[klien_type]), index_col=0)
        potential_dict = df[col].to_dict()
        for tech in _KLIEN_TO_PYPSA_MAPPING[klien_type]:
            carrier_potential[tech] = potential_dict

    brownfield = n.statistics.installed_capacity(
        groupby=["location", "carrier"],
        components="Generator",
        carrier=list(technologies),
        aggregate_across_components=True,
        nice_names=False,
        drop_zero=False,
    )
    brownfield_at = brownfield[
        brownfield.index.get_level_values("location").str.startswith("AT")
    ]

    for (location, carrier), brownfield_value in brownfield_at.items():
        potential = carrier_potential[carrier][location]

        mask_ext = (
            (n.generators.index.str.startswith(f"{location} "))
            & (n.generators["carrier"] == carrier)
            & (n.generators["p_nom_extendable"])
        )

        if not any(mask_ext):
            continue

        # Make sure that the upper limit can always be reached
        new_upper_limit = max(0.0, potential, brownfield_value)

        for gen_idx in n.generators.index[mask_ext]:
            _set_p_nom_max(n, gen_idx, new_upper_limit)

    logger.info(f"AT KLIEN potential limits applied for: {list(technologies)}.")
