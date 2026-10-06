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

        snakemake = mock_snakemake("build_inflow_profile", run="AT_KN2040")
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

    # atlite can only normalize to yearly totals with (almost) a full year of data
    full_year_available = sum(mask) > 8700

    if full_year_available:
        normalize_df = pd.DataFrame({year: [1]}, index=regions.index).T

        inflow = cutout.runoff(
            shapes=regions,
            smooth=True,
            lower_threshold_quantile=True,
            normalize_using_yearly=normalize_df,
        )
    else:
        # e.g. short test cutouts in CI: normalize over the available period and
        # scale to its share of the year, assuming the period is representative
        logger.warning(
            f"Cutout does not cover a full year of {year}. Normalizing the inflow "
            "profile over the available period instead of the full year."
        )
        inflow = cutout.runoff(
            shapes=regions,
            smooth=True,
            lower_threshold_quantile=True,
        )
        hours_in_year = pd.Timestamp(f"{year}-12-31").dayofyear * 24
        share_of_year = inflow.sizes["time"] / hours_in_year
        # regions without runoff in the cutout receive a flat profile
        inflow = (inflow / inflow.sum("time")).fillna(
            1 / inflow.sizes["time"]
        ) * share_of_year

    inflow = inflow.sel(time=time)

    inflow.to_netcdf(snakemake.output.profile)
