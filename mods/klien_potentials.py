# SPDX-FileCopyrightText: 2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""AT KLIEN potential overrides for the ``modify_prenetwork`` step."""

from collections import defaultdict
from logging import getLogger
from pathlib import Path

import pandas as pd
import pypsa
from snakemake.script import Snakemake

logger = getLogger(__name__)

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
    gen_p_nom_max = n.generators.loc[gen_idx, "p_nom_max"]
    p_nom_max_value = min(p_nom_max, gen_p_nom_max)
    gen_p_nom_min = n.generators.loc[gen_idx, "p_nom_min"]
    if gen_p_nom_min > p_nom_max_value:
        # Happens due to issues in wind distribution for the base year
        logger.warning(f"KLIEN potential is below minimum for {gen_idx}")
        p_nom_max_value = gen_p_nom_min
    n.generators.loc[gen_idx, "p_nom_max"] = p_nom_max_value


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

    Args:
        snakemake: Snakemake workflow object providing ``snakemake.params``.

    Returns:
        The column name to look up in the KLIEN potential CSV.

    Raises:
        ValueError: If any of ``climate_scenario``, ``year``, or ``ambition`` is invalid.
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

    Args:
        at_level: Integer NUTS level for Austria (2 = AT10, 3 = NUTS3).
        snakemake: Snakemake workflow object providing ``snakemake.input``.

    Returns:
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
    technologies: list[str] = snakemake.params["klien_potential_limits_technologies"]
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
    planning_horizon = int(snakemake.wildcards.planning_horizons)

    for (location, carrier), brownfield_value in brownfield_at.items():
        potential = carrier_potential[carrier][location]
        if planning_horizon > 2025:
            potential -= brownfield_value

        mask_ext = (
            (n.generators.index.str.startswith(location))
            & (n.generators["carrier"] == carrier)
            & (n.generators["p_nom_extendable"])
        )

        if not any(mask_ext):
            continue

        new_upper_limit = max(0.0, potential)

        for gen_idx in n.generators.index[mask_ext]:
            _set_p_nom_max(n, gen_idx, new_upper_limit)

    logger.info(f"AT KLIEN potential limits applied for: {list(technologies)}.")
