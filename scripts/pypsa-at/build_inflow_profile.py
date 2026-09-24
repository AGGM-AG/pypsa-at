# SPDX-FileCopyrightText: 2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""
Build hydroelectric inflow profile time-series for each model region.

The profile is the ERA5 runoff of the cutout, smoothed by atlite, aggregated
over each model region and normalised so that every region's profile sums to
one over the weather year of the snapshots. It carries the timing of the
water only; the annual energy is attached later by ``build_inflows_per_region``.

atlite's ``lower_threshold_quantile`` is deliberately not applied: it zeroes
every value below one global quantile over all regions and hours, which at
NUTS3 resolution blanks thousands of hours in small low-runoff regions on
large rivers (Vienna on the Danube).

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

import atlite
import geopandas as gpd
import pandas as pd
import xarray as xr

from scripts._helpers import (
    configure_logging,
    get_snapshots,
    load_cutout,
    set_scenario_config,
)

logger = logging.getLogger(__name__)


def build_inflow_profile(
    cutout: atlite.Cutout, regions: gpd.GeoSeries, time: pd.DatetimeIndex
) -> xr.DataArray:
    """
    Normalised hourly runoff profile per model region for one weather year.

    Parameters
    ----------
    cutout
        atlite cutout with hourly runoff; only the weather year of ``time``
        is used.
    regions
        Model region polygons indexed by region name, in the cutout's CRS.
    time
        Snapshots of the run, all within one calendar year.

    Returns
    -------
    :
        DataArray with dimensions ``countries`` (the region names) and
        ``time``, restricted to ``time``; each region sums to one over the
        weather year before that restriction.
    """
    year = pd.DatetimeIndex(time).year.unique().item()
    cutout_time = pd.DatetimeIndex(cutout.coords["time"].values)
    cutout = cutout.sel(time=cutout_time[cutout_time.year == year])

    regions = regions.copy()
    regions.index.name = "countries"
    normalize_df = pd.DataFrame({year: [1]}, index=regions.index).T

    inflow = cutout.runoff(
        shapes=regions,
        smooth=True,
        lower_threshold_quantile=None,
        normalize_using_yearly=normalize_df,
    )
    return inflow.sel(time=time)


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
    regions = gpd.read_file(snakemake.input.regions).set_index("name")["geometry"]

    inflow = build_inflow_profile(cutout, regions, time)
    inflow.to_netcdf(snakemake.output.profile)
