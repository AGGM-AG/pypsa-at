# SPDX-FileCopyrightText: 2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""
Prepares custom cost resource file based on costs config.

If costs.use_list is true then combines files given in costs.custom_cost_fn_list. If entries occur multiple times
the first occurrence is kept.
If costs.use_list is false custom_cost_fn is exported
"""

import logging
import shutil

import pandas as pd
from snakemake.script import Snakemake

from scripts._helpers import configure_logging, set_scenario_config

logger = logging.getLogger(__name__)

def main(snakemake: Snakemake):
    costs = snakemake.params.costs
    if costs["use_list"]:
        file_list = costs["custom_cost_fn_list"]
        index_cols = ["planning_horizon", "technology", "parameter"]
        cost_dfs = [
            pd.read_csv(path).set_index(index_cols) for path in file_list
        ]
        combined = pd.concat(cost_dfs)

        # Keep the first occurrence according to the order of `paths`.
        # This also handles duplicate indices within an individual file.
        combined = combined[~combined.index.duplicated(keep="first")]
        pd.to_csv(snakemake.output.custom_cost_fn)

    else:
        shutil.copyfile(costs["custom_cost_fn"], snakemake.output.custom_cost_fn)


if __name__ == "__main__":
    if "snakemake" not in globals():
        from scripts._helpers import mock_snakemake

        snakemake = mock_snakemake("build_custom_cost_fn")

    configure_logging(snakemake)
    set_scenario_config(snakemake)
    main(snakemake)
