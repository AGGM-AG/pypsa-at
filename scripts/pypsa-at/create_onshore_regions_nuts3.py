# SPDX-FileCopyrightText: 2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""Generate onshore regions geopandas with AT in NUTS3 resolution."""
import geopandas as gpd
import logging

import pandas as pd

from scripts._helpers import configure_logging, set_scenario_config
from snakemake.script import Snakemake

logger = logging.getLogger(__name__)


def main(snakemake: Snakemake) -> None:
    """
    Create a geopandas frame of onshore regions with NUTS3 level for Austria

    Parameters
    ----------
    snakemake
        Snakemake object providing input, parameters and output.

    Returns
    -------
    :
        Writes output to snakemake output paths.
    """
    regions_df = gpd.read_file(
        snakemake.input.regions
    )
    crs = regions_df.crs

    shapes_df = gpd.read_file(
        snakemake.input.shapes
    ).to_crs(crs)

    out = pd.concat(
        [
            regions_df.query("~name.str.startswith('AT')"),
            shapes_df.query("country == 'AT'")[["level3", "geometry"]].rename(
                columns={"level3": "name"}
            ).drop_duplicates(),
        ]
    )
    out_gpd = gpd.GeoDataFrame(out, crs=crs)
    out_gpd.to_file(snakemake.output.regions_nuts3)

if __name__ == "__main__":
    if "snakemake" not in globals():
        from scripts._helpers import mock_snakemake

        snakemake = mock_snakemake("create_onshore_regions_nuts3", clusters="adm")

    configure_logging(snakemake)
    set_scenario_config(snakemake)
    main(snakemake)


