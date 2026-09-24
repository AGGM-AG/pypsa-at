# SPDX-FileCopyrightText: 2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""Tests for the ERA5 runoff profile build."""

import atlite
import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
import xarray as xr
from build_inflow_profile import build_inflow_profile
from shapely.geometry import box


@pytest.fixture
def cutout(tmp_path) -> atlite.Cutout:
    """
    A 2 x 2 degree cutout covering 2012-12-31 to 2013-12-31 with continuous runoff.

    The western column carries a hundred times less runoff than the eastern
    one, so a global quantile threshold would blank it.
    """
    time = pd.date_range("2012-12-31", "2013-12-31 23:00", freq="h")
    x = np.array([10.25, 10.75, 11.25, 11.75])
    y = np.array([47.25, 47.75])
    hours = np.arange(len(time))
    seasonal = 1.0 + np.sin(2 * np.pi * hours / len(time))  # never below zero
    runoff = np.ones((len(time), len(y), len(x))) * seasonal[:, None, None]
    runoff[:, :, :2] *= 0.01
    ds = xr.Dataset(
        {
            "runoff": (("time", "y", "x"), runoff),
            "height": (("y", "x"), np.full((len(y), len(x)), 500.0)),
        },
        coords={"time": time, "y": y, "x": x},
    )
    ds.attrs["module"] = "era5"
    return atlite.Cutout(str(tmp_path / "test.nc"), data=ds)


@pytest.fixture
def regions() -> gpd.GeoSeries:
    return gpd.GeoSeries(
        {"WEST": box(10.0, 47.0, 11.0, 48.0), "EAST": box(11.0, 47.0, 12.0, 48.0)},
        crs="EPSG:4326",
    )


def test_profile_sums_to_one_per_region_over_the_weather_year(cutout, regions):
    time = pd.date_range("2013-01-01", "2013-12-31 23:00", freq="h")

    profile = build_inflow_profile(cutout, regions, time)

    assert profile.dims == ("countries", "time") or set(profile.dims) == {
        "countries",
        "time",
    }
    assert list(profile.coords["countries"].values) == ["WEST", "EAST"]
    assert pd.DatetimeIndex(profile.time.values).equals(time)
    assert profile.sum("time").values == pytest.approx([1.0, 1.0])


def test_profile_keeps_low_runoff_regions_without_zero_hours(cutout, regions):
    time = pd.date_range("2013-01-01", "2013-12-31 23:00", freq="h")

    profile = build_inflow_profile(cutout, regions, time)

    # no global quantile threshold: the dry region keeps every hour
    assert (profile.sel(countries="WEST") > 0).all()
    # the profiles carry timing only; both regions have the same shape
    west = profile.sel(countries="WEST").values
    east = profile.sel(countries="EAST").values
    assert west == pytest.approx(east, rel=1e-6)


def test_profile_restricts_to_the_snapshots(cutout, regions):
    time = pd.date_range("2013-03-01", "2013-03-31 23:00", freq="h")

    profile = build_inflow_profile(cutout, regions, time)

    assert len(profile.time) == len(time)
    # normalised over the whole year, so March holds only part of it
    assert 0 < float(profile.sel(countries="EAST").sum("time")) < 1
