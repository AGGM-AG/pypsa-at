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

from mods.clustering.utils import combine_regions_by_clustering
from mods.constants import PROXIES, TYNDP_TO_PYPSA_LOCATION

logger = getLogger(__name__)


def aggregate_by_cluster_and_country(
    trajectories: pd.DataFrame,
    skip_countries: tuple[str] | None = None,
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
    skip_countries: tuple[str],
    pyear: int,
) -> None:
    """
    Add one extendable nuclear Link per location so :func:`apply_trajectories` can bound it.

    Nuclear is a conventional carrier represented by one or more non-extendable
    *vintage* Links per location (``bus0="EU uranium"``, ``bus1`` = electricity
    bus, ``bus2="co2 atmosphere"``), all created by ``add_existing_baseyear``.
    Because no extendable variant exists, the trajectory bounds would have nothing
    to attach to.  This function creates that missing component — a single
    extendable Link per location whose newest vintage supplies the *full*
    attribute row (buses, efficiency, ``capital_cost``, ramp limits, ...), with
    ``p_nom`` reset to zero and ``build_year`` set to *pyear*.  Copying every
    attribute keeps new capacity consistent with the vintages and prevents future
    attributes from silently regressing to defaults.  The vintages are left
    untouched and carry the brownfield as a fixed floor; the actual ``p_nom_min``
    / ``p_nom_max`` bounds are then written by :func:`apply_trajectories` via the
    standard ``techs`` loop (``("Link", "nuclear", 1)``).

    To guarantee every created Link is bounded — an unbounded extendable Link
    would let the solver build unlimited nuclear — the function fails fast instead
    of leaving a stray component: it raises if no nuclear vintages exist, if a
    non-skipped nuclear location has no trajectory, or if the target name already
    exists.  Locations in *skip_countries* are dropped before these checks.

    Parameters
    ----------
    n:
        The PyPSA network object to modify in-place.
    traj:
        Aggregated trajectory DataFrame as returned by
        :func:`aggregate_by_cluster_and_country`, indexed by
        ``(location, pypsa_eur_carrier)``.  Used to verify that every nuclear
        location carries a trajectory.
    skip_countries:
        Two-letter ISO country codes (matched against the location prefix) whose
        locations are not touched.
    pyear:
        Current planning horizon, used as the new Link's build year and name suffix.

    Raises
    ------
    ValueError
        If the network contains no nuclear vintage Links, if a non-skipped
        nuclear location lacks trajectory data, or if the extendable Link's name
        collides with an existing component.
    """
    carrier = "nuclear"
    brownfield = n.statistics.installed_capacity(
        groupby=["location", "build_year"],
        # location and not country to prevent collapsing GB regions
        components="Link",
        carrier=carrier,
        at_port="1",  # fetches electricity locations instead of EU uranium
        nice_names=False,
        drop_zero=False,
    )
    if brownfield.empty:
        raise ValueError("Expected existing nuclear links but found none.")

    # skip_countries are two-letter country codes; match sub-national locations
    # (e.g. "AT1", "GB0") by prefix, mirroring apply_trajectories.
    country = brownfield.index.get_level_values("location").str[:2]
    brownfield = brownfield[~country.isin(skip_countries)]

    nuclear_trajectories = traj[
        traj.index.get_level_values("pypsa_eur_carrier") == carrier
    ]
    missing = brownfield.index.unique("location").difference(
        nuclear_trajectories.index.unique("location")
    )
    if not missing.empty:
        raise ValueError(
            f"Some model locations do not contain trajectories data at locations {missing} for carrier {carrier}."
        )

    newest = brownfield.sort_index().groupby(level="location").tail(1)
    for loc, year in newest.index:
        # check for unexpected collisions. Since nuclear is a conventional non-extendable
        # asset, no nuclear assets for pyear must exist. Let's check to be sure.
        name = f"{loc} {carrier}-{pyear}"
        if name in n.links.index:
            raise ValueError(f"The asset {name} already exists.")

        template = n.links.loc[f"{loc} {carrier}-{year}", :].copy()
        template["p_nom"] = 0.0
        template["p_nom_extendable"] = True
        template["build_year"] = pyear
        n.add("Link", name, **template)

    logger.info(
        f"Registered {len(newest)} extendable nuclear Links for "
        f"locations: {', '.join(sorted(newest.index.unique('location')))}."
    )


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

    skip_countries = tuple(cfg["skip_countries"])
    pyear = int(snakemake.wildcards.planning_horizons)
    base_year = min(n.meta["scenario"]["planning_horizons"])
    is_myopic_year = pyear != base_year

    trajectories_fn = snakemake.input.tyndp_trajectories
    trajectories = pd.read_csv(trajectories_fn).query("pyear == @pyear")

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

    # Nuclear stays non-extendable in the base year. The technology is a
    # "conventional" technology in PyPSA-Eur, which means that no extendable
    # assets are created for myopic years.
    if is_myopic_year:
        register_extendable_nuclear(n, traj_clustered, skip_countries, pyear)
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


# ---------------------------------------------------------------------------
# AT KLIEN regional potential limits
# ---------------------------------------------------------------------------

# Mapping from PyPSA carrier name to the KLIEN study CSV type.
# ``solar`` and ``solar-hsat`` share the ground-mounted CSV because they
# share the same land area; the model enforces a combined land-use
# constraint in ``solve_network``.
_PYPSA_TO_KLIEN_MAPPING = {
    "solar rooftop": "buildings",
    "solar": "ground",
    "solar-hsat": "ground",
    "onwind": "wind",
}

_KLIEN_TO_PYPSA_MAPPING = defaultdict(list)
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

    The NUTS3-level potential CSVs are always read and aggregated to the
    network's clustering resolution via
    :func:`mods.clustering.utils.combine_regions_by_clustering` (AT10 collapses
    NUTS3 -> NUTS2; AT35 keeps NUTS3).

    Supported carriers and their CSV source:

    * ``solar rooftop`` — ``nuts3_pv_buildings.csv``
    * ``solar``, ``solar-hsat`` — ``nuts3_pv_ground.csv`` (shared land area)
    * ``onwind`` — ``nuts3_wind.csv``

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
    which captures carry-over from previous myopic periods.
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

    # Always read the NUTS3-level KLIEN potentials and aggregate them to the
    # network's clustering resolution. For AT10 clusterings this collapses
    # NUTS3 -> NUTS2 (potentials are additive); for AT35 the NUTS3 regions are
    # kept as-is.
    clustering = snakemake.config["mods"]["modify_nuts3_shapes"]
    paths = {
        "buildings": snakemake.input.nuts3_buildings,
        "ground": snakemake.input.nuts3_ground,
        "wind": snakemake.input.nuts3_wind,
    }

    # Load each CSV type once; map each requested carrier to its potential dict.
    klien_types_needed = {_PYPSA_TO_KLIEN_MAPPING[t] for t in technologies}
    carrier_potential = {}
    for klien_type in klien_types_needed:
        df = pd.read_csv(Path(paths[klien_type]), index_col=0)
        potential_dict = combine_regions_by_clustering(df[col], clustering).to_dict()
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
