# SPDX-FileCopyrightText: Contributors to Open-TYNDP <https://github.com/open-energy-transition/open-tyndp>
# SPDX-FileCopyrightText: Contributors to PyPSA-AT
#
# SPDX-License-Identifier: MIT
"""
Open-TYNDP helpers vendored into PyPSA-AT.

These functions originate from ``open-tyndp/scripts/_helpers.py``. They are kept
in this dedicated module (rather than the upstream ``scripts/_helpers.py``) so
the upstream PyPSA-Eur file stays pristine. Import them via
``from scripts._tyndp_helpers import ...``.
"""

import logging
from bisect import bisect_right
from collections.abc import Callable

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

SCENARIO_DICT = {
    "Distributed Energy": "DE",
    "Global Ambition": "GA",
    r"National Trends\s*\+": "NT",
    r"NT\s*\+": "NT",
    "National Trends": "NT",
}

ENERGY_UNITS = {"TWh", "GWh", "MWh", "kWh"}
POWER_UNITS = {"GW", "MW", "kW"}
PRICE_UNITS = {"EUR/MWh", "EUR/MWh_e", "EUR/MWh_H2"}


def make_index(
    c, cname0="bus0", cname1="bus1", prefix="", connector="->", suffix="", separator=" "
):
    idx = [prefix, c[cname0], connector, c[cname1], suffix]
    idx = [i for i in idx if i]
    return separator.join(idx)


def safe_pyear(
    year: int | str,
    available_years: list[int] = [2030, 2040, 2050],
    source: str = "TYNDP",
    verbose: bool = True,
) -> int:
    """
    Checks and adjusts whether a given pyear is in the available years of a given data source. If not, it
    falls back to the previous available year.

    Parameters
    ----------
    year : int
        Planning horizon year which will be checked and possibly adjusted to previous available year.
    available_years : list[int], optional
        List of available years. Defaults to [2030, 2040, 2050].
    source : str, optional
        Source of the data for which availability will be checked. For logging purpose only. Defaults to "TYNDP".
    verbose : bool, optional
        Whether to activate verbose logging. Defaults to True.

    Returns
    -------
    year_new : int
        Safe pyear adjusted for available years
    """

    if not available_years:
        raise ValueError(
            "No `available_years` provided. Expected a non-empty list of years."
        )
    if not isinstance(year, int):
        year = int(year)
    if year not in available_years:
        year_new = available_years[
            bisect_right(sorted(available_years), year, lo=1) - 1
        ]
        if verbose:
            logger.warning(
                f"{source} data unavailable for planning horizon {year}. Falling back to previous available year {year_new}."
            )
    else:
        year_new = year

    return year_new


def map_tyndp_carrier_names(
    df: pd.DataFrame,
    carrier_mapping_fn: str,
    on_columns: list[str],
    drop_on_columns=False,
):
    """
    Map external carriers to available tyndp_carrier names based on an input mapping. Optionally drop merged on columns.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame with external carriers to map
    carrier_mapping_fn : str
        Path to file with mapping from external carriers to available tyndp_carrier names.
    on_columns : list[str]
        Columns to merge on between the external carriers and tyndp_carriers.
    drop_on_columns : bool, optional
        Whether to drop merge columns and rename `open_tyndp_carrier` and `open_tyndp_index` to `carrier`
        and `index_carrier`. Defaults to False.

    Returns
    -------
    pd.DataFrame
        Input DataFrame with external carriers mapped to available tyndp_carriers and index_carriers.
    """

    # Read TYNDP carrier mapping
    carrier_mapping = (
        pd.read_csv(carrier_mapping_fn)[
            on_columns
            + [
                "pypsa_eur_carrier",
                "open_tyndp_carrier",
                "open_tyndp_index",
                "open_tyndp_type",
            ]
        ]
    ).dropna()

    # Map the carriers
    df = df.merge(carrier_mapping, on=on_columns, how="left")

    # If the carrier is DSR or Other Non-RES, the different price bands are too diverse for a robust external
    # mapping. Instead, we will combine the carrier and type information.
    if "pemmdb_carrier" in on_columns:

        def normalize_carrier(s):
            return s.lower().replace(" ", "-").replace("other-non-res", "chp")

        # Other Non-RES are assumed to represent CHP plants (according to TYNDP 2024 Methodology report p.37)
        df = df.assign(
            open_tyndp_carrier=lambda x: np.where(
                x["pemmdb_carrier"].isin(["DSR", "Other Non-RES"]),
                x["pemmdb_carrier"].apply(normalize_carrier),
                x["open_tyndp_carrier"],
            ),
            open_tyndp_index=lambda x: np.where(
                x["pemmdb_carrier"].isin(["DSR", "Other Non-RES"]),
                x["open_tyndp_carrier"]
                + "-"
                + x["pemmdb_type"].apply(normalize_carrier),
                x["open_tyndp_index"],
            ),
        )

    if not drop_on_columns:
        return df

    # Otherwise drop merge columns and rename to new "carrier" and "index_carrier" column
    df = df.drop(on_columns, axis="columns").rename(
        columns={
            "open_tyndp_carrier": "carrier",
            "open_tyndp_index": "index_carrier",
        }
    )

    # Move "carrier" and "index_carrier" to the front
    cols = ["carrier", "index_carrier"] + [
        col for col in df.columns if col not in ["carrier", "index_carrier"]
    ]

    return df[cols]


def convert_units(
    df: pd.DataFrame,
    unit_col: str = "unit",
    value_col: str = "value",
    invert: bool = False,
) -> pd.DataFrame:
    """
    Convert values to standardized units based on unit type.

    Energy values are converted to MWh, power values to MW:
    - Energy units (TWh, GWh, MWh, kWh) → MWh
    - Power units (GW, MW, kW) → MW

    When invert=False (default):
        - Values are converted from unit_col units to standard units (MWh/MW)
        - The "unit" column is updated to reflect the standardized unit

    When invert=True:
        - Values are converted from standard units (MWh/MW) back to unit_col units
        - The "unit" column is NOT modified
        - Useful for reverting previously standardized data

    Parameters
    ----------
    df : pd.DataFrame
        Long-format DataFrame containing values to convert.
    unit_col : str, default "unit"
        Name of the column containing the unit information.
        When invert=False: contains source units to convert from.
        When invert=True: contains target units to convert to.
    value_col : str, default "value"
        Name of the column containing values to convert.
    invert : bool, default False
        If False, convert to standard units and update "unit" column.
        If True, convert from standard units using inverse factors without modifying "unit" column.

    Returns
    -------
    pd.DataFrame
        DataFrame with converted values.
    """
    df = df.copy()

    unit_conversion = {
        "TWh": 1000000,
        "GWh": 1000,
        "MWh": 1,
        "GW": 1000,
        "MW": 1,
        "kW": 0.001,
    }

    if invert:
        # Inverse conversion factor to revert unit
        unit_conversion = {k: 1 / v for k, v in unit_conversion.items()}

    # Convert values using conversion factors
    conversion_factors = df[unit_col].map(unit_conversion)
    df[value_col] = pd.to_numeric(df[value_col], errors="coerce") * conversion_factors

    # Update unit column
    if not invert:
        df["unit"] = df[unit_col].apply(
            lambda x: "MWh" if x in ENERGY_UNITS else "MW" if x in POWER_UNITS else x
        )

    return df


def check_cyear(cyear: int, scenario: str) -> int:
    """Check if the climatic year is valid for the given scenario."""

    valid_years = {
        "NT": [1995, 2008, 2009],
        "DE": [1995, 2008, 2009],
        "GA": [1995, 2008, 2009],
    }

    if cyear not in valid_years[scenario]:
        logger.warning(
            f"Snapshot year {cyear} doesn't match available TYNDP data. Falling back to 2009."
        )
        cyear = 2009

    return cyear


def interpolate_demand(
    available_years: list[int],
    pyear: int,
    load_single_year_func: Callable,
    **load_kwargs,
) -> pd.DataFrame | pd.Series:
    """
    Interpolate demand between available years.

    Parameters
    ----------
    available_years : list[int]
        Sorted list of years for which data is available.
    pyear : int
        Planning year to interpolate demand for.
    load_single_year_func : Callable
        Function to load data for a single planning year.
    **load_kwargs
        Keyword arguments to pass to load_single_year_func. Must include 'pyear'
        as a parameter key, which will be overridden with interpolation boundary years.

    Returns
    -------
    pd.DataFrame | pd.Series
        Interpolated demand data.
    """
    # Currently, only interpolation is implemented, not extrapolation
    idx = bisect_right(available_years, pyear)
    if idx == 0:
        # Planning horizon is before all available years
        logger.warning(
            f"Year {pyear} is before the first available year {available_years[0]}. "
            f"Falling back to first available year."
        )
        year_lower = year_upper = available_years[0]
    elif idx == len(available_years):
        # Planning horizon is after all available years
        logger.warning(
            f"Year {pyear} is after the latest available year {available_years[-1]}. "
            f"Falling back to latest available year."
        )
        year_lower = year_upper = available_years[-1]
    else:
        year_lower = available_years[idx - 1]
        year_upper = available_years[idx]

    logger.debug(f"Interpolating {pyear} from {year_lower} and {year_upper}")

    kwargs_lower = {**load_kwargs, "pyear": year_lower}
    kwargs_upper = {**load_kwargs, "pyear": year_upper}

    df_lower = load_single_year_func(**kwargs_lower)
    df_upper = load_single_year_func(**kwargs_upper)

    # Check if data was loaded successfully
    if df_lower.empty and df_upper.empty:
        logger.error("Both years failed to load")
        return pd.DataFrame()
    elif df_lower.empty:
        logger.warning(
            f"Year {year_lower} failed to load. Filling with zeros for interpolation."
        )
        df_lower = pd.DataFrame(0, index=df_upper.index, columns=df_upper.columns)
    elif df_upper.empty:
        logger.warning(
            f"Year {year_upper} failed to load. Using data from lower year for interpolation."
        )
        df_upper = df_lower

    if year_upper == year_lower:
        return df_lower

    # Handle column mismatches for DataFrames (only relevant for DataFrame, not Series)
    if isinstance(df_lower, pd.DataFrame) and isinstance(df_upper, pd.DataFrame):
        missing_in_lower = df_upper.columns.difference(df_lower.columns)
        missing_in_upper = df_lower.columns.difference(df_upper.columns)

        if len(missing_in_lower) > 0 or len(missing_in_upper) > 0:
            logger.warning(
                f"Column mismatch between {year_lower} and {year_upper}. "
                f"Missing columns filled with zeros. "
                f"Missing in {year_lower}: {list(missing_in_lower)}, "
                f"Missing in {year_upper}: {list(missing_in_upper)}"
            )
        df_lower_aligned, df_upper_aligned = df_lower.align(
            df_upper, join="outer", axis=1, fill_value=0
        )
    else:
        # For Series, just align
        df_lower_aligned, df_upper_aligned = df_lower.align(
            df_upper, join="outer", fill_value=0
        )

    # Perform linear interpolation
    weight = (pyear - year_lower) / (year_upper - year_lower)
    result = df_lower_aligned * (1 - weight) + df_upper_aligned * weight

    return result


def align_demand_to_snapshots(
    demand: pd.DataFrame, snapshots: pd.DatetimeIndex, format: str = None
) -> pd.DataFrame:
    """
    Convert demand index to DatetimeIndex, adjust year to match snapshots,
    and reindex to snapshots.
    """

    demand.index = pd.to_datetime(demand.index, format=format)
    target_year = snapshots[0].year
    demand.index = demand.index.map(lambda x: x.replace(year=target_year))

    return demand.reindex(snapshots)
