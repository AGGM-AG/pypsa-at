# SPDX-FileCopyrightText: 2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""AT KLIEN potential overrides for the ``modify_prenetwork`` step."""

from logging import getLogger

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

LAND_USE_CONSTRAINT_CARRIER = (
    "onwind",
    "solar rooftop",
    "solar",
    "solar-hsat",
    "offwind-ac",
    "offwind-dc",
    "offwind-float",
)


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

    file_paths = {
        "buildings": snakemake.input.nuts3_buildings,
        "ground": snakemake.input.nuts3_ground,
        "wind": snakemake.input.nuts3_wind,
    }

    # DataFrame: index=NUTS3 region, columns=technology. solar and solar-hsat
    # share the ground CSV, so both columns carry identical values.
    to_concat = []
    for tech in technologies:
        file_path = file_paths[_PYPSA_TO_KLIEN_MAPPING[tech]]
        to_concat.append(pd.read_csv(file_path, index_col=0)[col].rename(tech))

    carrier_potential = pd.concat(to_concat, axis=1)

    c = "Generator"
    brownfield = n.statistics.installed_capacity(
        groupby=["location", "carrier"],
        components=c,
        carrier=list(technologies),
        nice_names=False,
        drop_zero=False,
    )
    brownfield_at = brownfield[
        brownfield.index.get_level_values("location").str.startswith("AT")
    ]

    for (location, carrier), brownfield_value in brownfield_at.items():
        _nuts3 = carrier_potential.index.get_level_values("nuts3")
        location_mask = _nuts3.str.startswith(location)
        potential = carrier_potential.loc[location_mask, carrier]

        comp = n.components[c].static
        extendable_mask = (
            comp.index.str.startswith(location + " ")
            & (comp["carrier"] == carrier)
            & comp["p_nom_extendable"]
        )

        # edge case east tyrol: AT333 starts with AT33 but needs to be kept outside AT33 sum
        if location == "AT33" and "AT333" in potential.index:
            potential.pop("AT333")
            extendable_mask &= ~comp.index.str.startswith("AT333 ")

        # n.components[c].static breaks df.query()
        extendable_idx = comp[extendable_mask].index

        if len(extendable_idx) == 0:
            # conventional assets e.g. nuclear are non-extendable
            continue
        elif len(extendable_idx) != 1:
            # There must not be more than one extendable asset for above query
            raise ValueError(
                f"Multiple extendable assets for the same component {c}, "
                f"location {location} and carrier {carrier} detected."
            )

        if carrier not in LAND_USE_CONSTRAINT_CARRIER:
            raise NotImplementedError(
                f"Missing brownfield deduction logic for "
                f"carrier {carrier} not covered by add_land_use_constraint() "
                f"during solve_network."
            )

        # Make sure that the upper limit can always be reached
        limit_upper = max(0.0, potential.sum(), brownfield_value)
        limit_lower = comp.loc[extendable_idx, "p_nom_min"].item()

        if limit_lower > limit_upper:
            # Happens due to issues in wind distribution for the base year
            logger.warning(f"KLIEN potential is below minimum for {extendable_idx}.")

        # assign new limits to network component
        comp.loc[extendable_idx, "p_nom_max"] = max(limit_lower, limit_upper)

    logger.info(f"AT KLIEN potential limits applied for: {list(technologies)}.")
