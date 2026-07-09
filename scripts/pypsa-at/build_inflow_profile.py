# SPDX-FileCopyrightText: 2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""
Build hydroelectric inflow profile time-series for each model region.

Outputs
-------

- ``resources/profile_inflow_{clusters}.nc``:

    ===================  ================  =========================================================
    Field                Dimensions        Description
    ===================  ================  =========================================================
    inflow               countries, time   Inflow profile(normalized),
                                           e.g. due to river inflow in hydro reservoir.
    ===================  ================  =========================================================
"""

import logging

import geopandas as gpd
import pandas as pd

from scripts._helpers import (
    configure_logging,
    get_snapshots,
    load_cutout,
    set_scenario_config,
)

logger = logging.getLogger(__name__)

if __name__ == "__main__":
    if "snakemake" not in globals():
        from scripts._helpers import mock_snakemake

        snakemake = mock_snakemake(
            "build_inflow_profile", clusters="adm", run="AT_KN2040"
        )
    configure_logging(snakemake)
    set_scenario_config(snakemake)

    time = get_snapshots(snakemake.params.snapshots, snakemake.params.drop_leap_day)

    cutout = load_cutout(snakemake.input.cutout)

    year = pd.DatetimeIndex(time).year.unique().item()
    cutout_time = pd.DatetimeIndex(cutout.coords["time"].values)

    mask = [pd.Timestamp(t).year == year for t in cutout_time]
    cutout = cutout.sel(time=cutout_time[mask])

    regions = gpd.read_file(snakemake.input.regions).set_index("name")["geometry"]
    regions.index.name = "countries"

    normalize_df = pd.DataFrame({year: [1]}, index=regions.index).T

    inflow = cutout.runoff(
        shapes=regions,
        smooth=True,
        lower_threshold_quantile=True,
        normalize_using_yearly=normalize_df,
    )

    inflow = inflow.sel(time=time)

    inflow.to_netcdf(snakemake.output.profile)
