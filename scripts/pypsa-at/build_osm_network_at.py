# SPDX-FileCopyrightText: Contributors to PyPSA-AT <https://github.com/AGGM-AG/pypsa-at>
#
# SPDX-License-Identifier: MIT

"""
Post-process the ``build_osm_network`` CSV outputs for the Austrian AT dataset.

This script applies AT-specific filtering to the network produced by the
PyPSA-Eur ``build_osm_network`` rule and writes a cleaned copy to
``resources/osm/build-at/``.

Precondition check
------------------
* Raises ``ValueError`` if 110 kV is not listed in
  ``config.electricity.voltages``, because building the AT OSM dataset only
  makes sense with the 110 kV level included.
"""

import logging
from csv import QUOTE_NONNUMERIC
from pathlib import Path

import pandas as pd

from scripts._helpers import configure_logging, set_scenario_config

logger = logging.getLogger(Path(__file__).stem)


def drop_cross_border_lines_lv(
    lines: pd.DataFrame,
    buses: pd.DataFrame,
    max_voltage: float = 220.0,
) -> pd.DataFrame:
    """
    Remove cross-border lines with voltage < *max_voltage* kV.

    A line is considered cross-border when exactly one of its endpoints
    (``bus0`` / ``bus1``) belongs to Austria.

    Parameters
    ----------
    lines:
        Lines DataFrame (index = ``line_id``) with columns ``bus0``, ``bus1``,
        ``voltage`` (kV).
    buses:
        Buses DataFrame (index = ``bus_id``) with column ``country``.
    max_voltage:
        Exclusive upper voltage threshold in kV.  Lines with
        ``voltage < max_voltage`` that cross the Austrian border are removed.
        Default is 220 kV, which targets all 110 kV (and lower) cross-border
        lines given the voltage levels present in the AT OSM dataset.

    Returns
    -------
    pd.DataFrame
        Copy of *lines* with the matching cross-border entries removed.
    """
    at_bus_ids = set(buses[buses["country"] == "AT"].index)

    xb_mask = lines["bus0"].isin(at_bus_ids) != lines["bus1"].isin(at_bus_ids)
    drop_mask = xb_mask & (lines["voltage"] < max_voltage)

    n_dropped = int(drop_mask.sum())
    if n_dropped:
        logger.info(
            f"Dropping {n_dropped} cross-border lines with voltage < {max_voltage:.2f} kV."
        )
        logger.debug(f"Dropped line IDs: {lines.index[drop_mask].tolist()}")
    else:
        logger.info(f"No cross-border lines with voltage < {max_voltage:.2f} kV found.")

    return lines[~drop_mask].copy()


if __name__ == "__main__":
    if "snakemake" not in globals():
        from scripts._helpers import mock_snakemake

        snakemake = mock_snakemake("build_osm_network_at")

    configure_logging(snakemake)
    set_scenario_config(snakemake)

    voltages_config = snakemake.config["electricity"]["voltages"]
    if 110.0 not in voltages_config:
        raise ValueError(
            "110.0 kV is not listed in config.electricity.voltages "
            f"(found: {voltages_config}). "
            "Building the AT OSM dataset requires the 110 kV voltage level."
        )

    buses = pd.read_csv(snakemake.input.buses, index_col=0, quotechar="'")
    lines = pd.read_csv(snakemake.input.lines, index_col=0, quotechar="'")
    links = pd.read_csv(snakemake.input.links, index_col=0, quotechar="'")
    converters = pd.read_csv(snakemake.input.converters, index_col=0, quotechar="'")
    transformers = pd.read_csv(snakemake.input.transformers, index_col=0, quotechar="'")

    logger.info(
        f"Loaded network: {len(buses)} buses, {len(lines)} lines, {len(links)} links."
    )

    # Drop all international buses and lines below 220 kV, because they
    # are not validated against ground truth.
    buses = buses.query("country == 'AT' or voltage >= 220")
    at_buses = buses.query("country == 'AT'").index
    lines = lines.query(
        "bus0.isin(@at_buses) or bus1.isin(@at_buses) or voltage >= 220"
    )

    # drop all cross border 110 kV Lines in Austria
    lines = drop_cross_border_lines_lv(lines, buses, max_voltage=220.0)

    to_csv_kwargs = dict(quotechar="'", quoting=QUOTE_NONNUMERIC)
    buses.to_csv(snakemake.output.buses, **to_csv_kwargs)
    lines.to_csv(snakemake.output.lines, **to_csv_kwargs)
    links.to_csv(snakemake.output.links, **to_csv_kwargs)
    converters.to_csv(snakemake.output.converters, **to_csv_kwargs)
    transformers.to_csv(snakemake.output.transformers, **to_csv_kwargs)

    logger.info(
        f"Wrote filtered AT OSM network to {Path(snakemake.output.buses).parent}."
    )
