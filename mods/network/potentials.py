# SPDX-FileCopyrightText: 2023-2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""
Austrian KLIEN regional capacity potential overwrites for the ``modify_prenetwork`` step.

Caps extendable AT generator ``p_nom_max`` values by the regional potentials of
the Austrian KLIEN study (ground PV, building PV, onshore wind), following a
brownfield-deduction pattern so the bounds represent the *additional* capacity
still available to the solver.

* :func:`apply_klien_potential_limits` — entry point called from
  :func:`mods.network.modify_prenetwork`; reads the pre-processed KLIEN
  potential CSVs, aggregates them to the network clustering, and writes the
  remaining headroom into ``p_nom_max``.

TYNDP PEMMDB trajectory bands follow the same pattern but live in
:mod:`mods.network.trajectories`.
"""

from collections import defaultdict
from logging import getLogger
from pathlib import Path

import pandas as pd
import pypsa
from snakemake.script import Snakemake

from mods.clustering.utils import combine_regions_by_clustering

logger = getLogger(__name__)


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
