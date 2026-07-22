# SPDX-FileCopyrightText: Contributors to PyPSA-AT <https://github.com/AGGM-AG/pypsa-at>
#
# SPDX-License-Identifier: MIT

"""
Apply the AT 110 kV corridor rules to the OSM lines before ``base_network``.

Thin Snakemake wrapper around :func:`mods.filter_inter_regional_lines`; see
that module for the rule definitions. The filtered ``lines.csv`` replaces the
archive lines as ``base_network`` input, and the per-line report documents the
rule and reason for every line, kept or dropped.
"""

import logging
from csv import QUOTE_NONNUMERIC
from pathlib import Path

import geopandas as gpd
import pandas as pd

from mods import filter_inter_regional_lines
from scripts._helpers import configure_logging, set_scenario_config

logger = logging.getLogger(Path(__file__).stem)

if __name__ == "__main__":
    if "snakemake" not in globals():
        from scripts._helpers import mock_snakemake

        snakemake = mock_snakemake("filter_osm_lines_at")

    configure_logging(snakemake)
    set_scenario_config(snakemake)

    lines = pd.read_csv(
        snakemake.input.lines, index_col=0, quotechar="'", low_memory=False
    )
    buses = pd.read_csv(
        snakemake.input.buses, index_col=0, quotechar="'", low_memory=False
    )
    nuts3_shapes = gpd.read_file(snakemake.input.nuts3_shapes)
    overrides = pd.read_csv(snakemake.input.electricity_network_overrides)

    kept, report = filter_inter_regional_lines(lines, buses, nuts3_shapes, overrides)

    kept.to_csv(snakemake.output.lines, quotechar="'", quoting=QUOTE_NONNUMERIC)
    report.to_csv(snakemake.output.report, quotechar="'", quoting=QUOTE_NONNUMERIC)

    logger.info(
        f"Wrote {len(kept)}/{len(lines)} lines to {snakemake.output.lines}; "
        f"per-line report at {snakemake.output.report}."
    )
