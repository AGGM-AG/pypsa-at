# SPDX-FileCopyrightText: 2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""
Combine or export custom cost CSV files for energy system optimization.

This script prepares a unified custom cost resource file based on the configuration.
It supports two modes:

1. **List mode** (``costs.use_list=true``): Combines multiple CSV files specified in
   ``costs.custom_cost_fn_list``. When duplicate index entries exist (same
   ``planning_horizon``, ``technology``, and ``parameter``), the first occurrence
   is retained. This priority order respects the order of files in the config list.

2. **Single file mode** (``costs.use_list=false``): Exports the single file specified
   in ``costs.custom_cost_fn``.

**Input format:**
Each CSV file must have the following columns:
- ``planning_horizon``: Year or horizon identifier (e.g. 2025, 2030, 2050)
- ``technology``: Technology name (e.g. 'solar', 'methane pyrolysis plasma')
- ``parameter``: Cost parameter (e.g. 'capital_cost', 'marginal_cost')
- Additional columns: cost values and metadata

**Output:**
A single CSV file at ``resources/custom_cost_fn.csv`` with deduplicated entries.
"""

import logging

import pandas as pd
from snakemake.script import Snakemake

from scripts._helpers import configure_logging, set_scenario_config

logger = logging.getLogger(__name__)


def main(snakemake: Snakemake) -> None:
    """
    Combine multiple custom cost CSV files or export a single file.

    When combining files (``costs.use_list=true``), concatenates all CSV files
    specified in ``snakemake.input.custom_cost_files``, then deduplicates by
    index (planning_horizon, technology, parameter), retaining the first occurrence.
    This ensures earlier files in the list take priority over later ones.

    Parameters
    ----------
    snakemake
        Snakemake object

    Returns
    -------
    :
        Writes the deduplicated combined CSV to ``snakemake.output.custom_cost_fn``.

    """
    file_list = snakemake.input.custom_cost_files
    index_cols = ["planning_horizon", "technology", "parameter"]

    logger.info(f"Loading {len(file_list)} custom cost file(s)...")

    cost_dfs = [pd.read_csv(path).set_index(index_cols) for path in file_list]

    combined = pd.concat(cost_dfs)

    # Remove duplicates, keeping the first occurrence. This respects the order
    # of files in the input list: earlier files have higher priority.
    # The keep="first" parameter also handles duplicates within individual files.
    combined = combined[~combined.index.duplicated(keep="first")]

    logger.info(f"Writing custom cost file to {snakemake.output.custom_cost_fn}.")

    combined.to_csv(snakemake.output.custom_cost_fn)


if __name__ == "__main__":
    if "snakemake" not in globals():
        from scripts._helpers import mock_snakemake

        snakemake = mock_snakemake("build_custom_cost_fn")

    configure_logging(snakemake)
    set_scenario_config(snakemake)
    main(snakemake)
