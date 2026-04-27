# SPDX-FileCopyrightText: 2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""AT PV potential overrides for the ``modify_prenetwork`` step."""

from logging import getLogger
from pathlib import Path

import pandas as pd
import pypsa
from snakemake.script import Snakemake

logger = getLogger(__name__)


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

    Raises
    ------
    ValueError
        If the given ``p_nom_max``, is smaller than the configured ``p_nom_min`` for the component.
    """
    gen_p_nom_max = n.generators.loc[gen_idx, "p_nom_max"]
    p_nom_max_value = min(p_nom_max, gen_p_nom_max)
    gen_p_nom_min = n.generators.loc[gen_idx, "p_nom_min"]
    if gen_p_nom_min > p_nom_max_value:
        raise ValueError(f"PV potential is below minimum for {gen_idx}")
    p_nom_max_value = max(gen_p_nom_min, p_nom_max_value)
    n.generators.loc[gen_idx, "p_nom_max"] = p_nom_max_value


def apply_pv_potential_limits(n: pypsa.Network, snakemake: Snakemake) -> None:
    """
    Cap extendable AT solar generator ``p_nom_max`` by regional PV potential.

    Reads pre-processed capacity potential CSVs (in MW) for buildings (rooftop)
    and ground-mounted solar, subtracts already-committed brownfield capacity,
    and writes the remaining headroom into ``p_nom_max`` for every extendable
    AT solar generator.

    Only generators on buses whose index starts with ``"AT"`` are affected.
    Non-AT generators (e.g. DE, CH) are left unchanged.  The function is
    not executed when the ``pv_potential_limits_enable`` param is false.

    When ``pv_potential_limits_use_technical_potentials`` is true, the column
    ``C_technical_potential`` is used regardless of ``year``, ``ambition``, or
    ``climate_scenario``.

    Supported carriers:

    * ``solar-rooftop`` — limited by ``{resolution}_pv_buildings.csv``
    * ``solar``, ``solar-hsat`` — limited by ``{resolution}_pv_ground.csv``
      (shared land area; individual ``p_nom_max`` applied since the model
      applies a constraint for a combined limit in solve_network)

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
        If ``climate_scenario``, ``year``, or ``ambition`` are unrecognised.
    KeyError
        If the requested scenario column is absent from the potential CSV.

    Notes
    -----
    Brownfield capacity is estimated via ``n.statistics.installed_capacity()``,
    which captures both carry-over from previous myopic periods.  Unsupported
    AT clustering levels emit a warning and cause an early return rather
    than raising.
    """
    if not snakemake.params["pv_potential_limits_enable"]:
        logger.info("PV potential limits: disabled — skipping.")
        return

    use_technical_potentials = snakemake.params[
        "pv_potential_limits_use_technical_potentials"
    ]
    climate_scenario = snakemake.params["pv_potential_limits_climate_scenario"]
    year = snakemake.params["pv_potential_limits_year"]
    ambition = snakemake.params["pv_potential_limits_ambition"]

    valid_climate = {"wocc", "mocc", "stcc"}
    valid_years = {2030, 2040}
    valid_ambitions = {"low", "medium", "high"}

    if climate_scenario not in valid_climate:
        raise ValueError(
            f"pv_potential_limits.climate_scenario={climate_scenario!r} is not valid. "
            f"Choose from {valid_climate}."
        )
    if year not in valid_years:
        raise ValueError(
            f"pv_potential_limits.year={year!r} is not valid. "
            f"Choose from {valid_years}."
        )
    if ambition not in valid_ambitions:
        raise ValueError(
            f"pv_potential_limits.ambition={ambition!r} is not valid. "
            f"Choose from {valid_ambitions}."
        )

    at_level = snakemake.config["clustering"]["administrative"]["AT"]
    if at_level == 2:
        buildings_path = snakemake.input.at10_buildings
        ground_path = snakemake.input.at10_ground
    elif at_level == 3:
        buildings_path = snakemake.input.nuts3_buildings
        ground_path = snakemake.input.nuts3_ground
    else:
        logger.warning(
            f"Unsupported clustering level AT={at_level!r}. Expected 2 or 3. — Skipping PV potential limits."
        )
        return

    df_buildings = pd.read_csv(Path(buildings_path), index_col=0)
    df_ground = pd.read_csv(Path(ground_path), index_col=0)

    col = (
        "C_technical_potential"
        if use_technical_potentials
        else f"C_{year}_{ambition}_{climate_scenario}"
    )
    if col not in df_buildings.columns:
        raise KeyError(
            f"Column {col!r} not found in {buildings_path}. "
            f"Available columns: {list(df_buildings.columns)}"
        )
    if col not in df_ground.columns:
        raise KeyError(
            f"Column {col!r} not found in {ground_path}. "
            f"Available columns: {list(df_ground.columns)}"
        )

    buildings_potential = df_buildings[col].to_dict()
    ground_potential = df_ground[col].to_dict()

    brownfield_solar = n.statistics.installed_capacity(
        groupby=["location", "carrier"],
        components="Generator",
        carrier=["solar rooftop", "solar", "solar-hsat"],
        aggregate_across_components=True,
        nice_names=False,
        drop_zero=False,
    )
    brownfield_at = brownfield_solar[
        brownfield_solar.index.get_level_values("location").str.startswith("AT")
    ]
    planning_horizon = int(snakemake.wildcards.planning_horizons)

    for (location, carrier), brownfield_value in brownfield_at.items():
        potential = (
            buildings_potential[location]
            if carrier == "solar rooftop"
            else ground_potential[location]
        )
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
    logger.info("AT PV potential limits applied.")
