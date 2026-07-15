# SPDX-FileCopyrightText: 2023-2025 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""Collect package helper functions."""

import logging
import re
from itertools import product
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
from frozendict import frozendict
from pypsa import NetworkCollection
from pypsa.statistics import get_transmission_carriers

from evals.constants import (
    ALIAS_COUNTRY,
    ALIAS_REGION,
    ALIAS_REGION_AT10_CLUSTERING,
    ALIAS_REGION_AT35_CLUSTERING,
    ALIAS_REGION_DE5_CLUSTERING,
    ALIAS_REGION_DE16_CLUSTERING,
    COLOR_SCHEME_FILL,
    COLOUR_SCHEME,
    UNITS,
    BusCarrier,
    DataModel,
    Group,
    Regex,
    TradeTypes,
)

logger = logging.getLogger(__file__)


def insert_index_level(
    df: pd.DataFrame | pd.Series,
    value: str,
    index_name: str,
    axis: int = 0,
    pos: int = 0,
) -> pd.DataFrame | pd.Series:
    """
    Add an index level to the data frame.

    Parameters
    ----------
    df
        The data frame that will receive the new outer level index.
    value
        The new index values.
    index_name
        The new index level name.
    axis : optional
        The index axis. Pass 0 for row index and 1 for column index.
    pos : optional
        Move the new index name to this position. 0 is outer left,
        1 is the second, and so on.

    Returns
    -------
    :
        The data frame with the new index level.
    """
    result = pd.concat({value: df}, names=[index_name], axis=axis)
    if pos == 0:  # no need to reorder levels. We are done inserting.
        return result
    idx = df.index if axis == 0 else df.columns
    idx_names = list(idx.names)
    idx_names.insert(pos, index_name)
    if isinstance(result, pd.DataFrame):
        return result.reorder_levels(idx_names, axis=axis)
    return result.reorder_levels(idx_names)


def get_unit(s: str, ignore_suffix: bool = True) -> str:
    """
    Parse the unit from a string.

    The unit must be inside round parentheses. If multiple
    parenthesis are found in the input string, returns the last one.

    Parameters
    ----------
    s
        The input string that should contain a unit.
    ignore_suffix
        Whether to strip the suffix, e.g. `_th`, `_el`, `_LHV`, ...

    Returns
    -------
    :
        All characters inside the last pair of parenthesis without
        the enclosing parenthesis, or an empty string.
    """
    if matches := re.findall(Regex.unit, s):
        unit = matches[-1].strip("()")
        if ignore_suffix and "_" in unit:
            return "_".join(unit.split("_")[:-1])
        else:
            return matches[-1].strip("()")
    return ""


def get_trade_type(bus_a: str, bus_b: str) -> str:
    """
    Determine the trade type between two buses.

    Parameters
    ----------
    bus_a
        1st string that should start with a region substring.
    bus_b
        2nd string that should start with a region substring.

    Returns
    -------
    :
        The trade type. One of constants.TRADE_TYPES.
    """
    loc_a = re.findall(Regex.region, bus_a)[:1]
    loc_b = re.findall(Regex.region, bus_b)[:1]
    if not loc_a or not loc_b:  # no region(s) found
        return ""
    elif loc_a[0] == loc_b[0]:
        # transformation link in same region, e.g. heat
        return TradeTypes.LOCAL
    elif loc_a[0][:2] == loc_b[0][:2]:  # country codes match
        return TradeTypes.DOMESTIC
    else:
        return TradeTypes.FOREIGN


def trade_mask(
    comp: pd.DataFrame, scopes: str | tuple, buses: tuple = ("bus0", "bus1")
) -> pd.Series:
    """
    Get the mask for a given trade type.

    The logic only compares bus0 and bus1 in a given component.

    Parameters
    ----------
    comp
        The component data frame. Should be one a branch_component,
        i.e. 'Line', 'Link', or 'Transformer'.
    scopes
        The trade scope(s) to match. One or multiple of 'local',
        'domestic', 'foreign'.
    buses
        Two buses to determine the trade type from. The trade type will
        be 'local', 'domestic', or 'foreign', for same location, same
        country code, or different country code, respectively.

    Returns
    -------
    :
        A pandas Series with the same index as component index and 1
        or 0 as values for match or differ, respectively.

    Raises
    ------
    ValueError
        In case the passed trade type is not supported and to prevent
        unintended string matches.
    """
    scopes = (scopes,) if isinstance(scopes, str) else scopes
    if unknown_scopes := set(scopes).difference(
        {TradeTypes.LOCAL, TradeTypes.DOMESTIC, TradeTypes.FOREIGN}
    ):
        raise ValueError(f"Invalid trade scopes detected: {unknown_scopes}.")
    df = comp[[*buses]]
    trade = df.apply(lambda row: get_trade_type(row[buses[0]], row[buses[1]]), axis=1)
    return trade.isin(scopes)


def filter_by(
    df: pd.DataFrame | pd.Series, exclude: bool = False, **kwargs: object
) -> pd.DataFrame | pd.Series:
    """
    Filter a data frame by key value pairs.

    Constructs a pandas query using the pandas.Index.isin() method.
    Since the pandas query API is only available for data frames,
    any passed pandas Series is converted to frame and reset to
    series.

    Parameters
    ----------
    df
        The data frame or Series to filter.
    exclude
        Set to True to exclude the filter result from the original
        data set, and return the difference.
    **kwargs
        Key=value pairs, used in the filter expression. Valid keys are
        index level names or column labels.

    Returns
    -------
    :
        The filtered data frame in the same format as the input
        dataframe.
    """
    if df.empty:
        return df  # to prevent key errors

    if was_series := isinstance(df, pd.Series):
        df = df.to_frame()

    where_clauses = []
    for key, vals in kwargs.items():
        vals = [vals] if np.isscalar(vals) else vals
        where_clauses.append(f"{key} in {vals}")

    expression = " & ".join(where_clauses)
    result = df.query(expression)

    if exclude:
        result = df.drop(result.index)

    # squeeze(axis=1) to preserve index even for single rows
    return result.squeeze(axis=1) if was_series else result


def split_location_carrier(index: pd.MultiIndex, names: list) -> pd.MultiIndex:
    r"""
    Split location and carrier in the index.

    The location must be encoded in the string and match the regex
    '^[A-Z]{2}\\d\\s\\d'. Subsequent characters become the carrier
    name. The location defaults to an emtpy string if the regex
    does not match.

    Parameters
    ----------
    index
        A pandas Multiindex with the innermost level to split.
    names
        The list of output Multiindex names.

    Returns
    -------
    :
        The resulting Multiindex with one additional
        level due to the splitting.
    """
    idx_split = []
    for *prefixes, loc_category in index:
        matches = re.match(Regex.region, loc_category)
        location = matches.group().strip() if matches else ""
        technology = loc_category.removeprefix(location).strip()
        idx_split.append((*prefixes, location, technology))

    return pd.MultiIndex.from_tuples(idx_split, names=names)


def rename_aggregate(
    df: pd.DataFrame | pd.Series,
    mapper: dict | str,
    level: str = DataModel.CARRIER,
    agg: str = "sum",
) -> pd.Series | pd.DataFrame:
    """
    Rename index values and aggregate duplicates.

    In case the supplied mapper is a string, all values in the
    supplied level are replaced by this string.

    Parameters
    ----------
    df
        The input data frame.
    mapper
        A Dictionary with key-value pairs to rename index values, or
        a string used to replace all values in the given level.
    level
        The index level name.
    agg
        The aggregation method for duplicated index values after
        renaming.

    Returns
    -------
    :
        A data frame with renamed index values and aggregated values.

    Notes
    -----
    Support for column axis mapping was removed, because the groupby
    operation along axis=1 removes column level names and does not
    work correctly.
    """
    if isinstance(mapper, str):
        mapper = dict.fromkeys(df.index.unique(level=level), mapper)
    renamed = df.rename(mapper, level=level)
    return renamed.groupby(df.index.names).agg(agg)


def apply_cutoff(df: pd.DataFrame, limit: float, drop: bool = True) -> pd.DataFrame:
    """
    Replace small absolute values with NaN.

    The limit boundary is not inclusive, i.e. the limit value itself
    will not be replaced by NaN.

    Parameters
    ----------
    df
        The data frame to remove values from.
    limit
        Absolute values smaller than the limit will be dropped.
    drop
        Whether to drop all NaN rows from the returned data frame.

    Returns
    -------
    :
        A data frame without values that are smaller than the limit.
    """
    result = df.mask(cond=df.abs() < abs(limit), other=pd.NA)
    if drop:
        result = result.dropna(how="all", axis=0)
    return result


def scale(df: pd.DataFrame, to_unit: str) -> pd.DataFrame:
    """
    Scale metric values to the specified target unit.

    Multiplies all columns in the metric by a scaling factor.
    The scaling factor is calculated from the unit in the data frame
    columns and the given target unit. Also updates the unit
    names encoded in the data frame columns for time aggregated
    metrics.

    Parameters
    ----------
    df
        The input data frame with valid units in the column labels.
    to_unit
        The target unit. See constants.UNITS for possible
        units.

    Returns
    -------
    :
        The scaled data frame with replaced units in column labels.

    Raises
    ------
    raises KeyError
        If the 'to_unit' is not found in UNITS, or if the attrs
        dictionary has no unit field.
    raises ValueError
        If input units are inconsistent, i.e. mixed power and energy
        columns.
    """
    suffix = ""
    if to_unit.endswith(("_LHV", "_th", "_el")):
        to_unit, suffix = to_unit.split("_")

    if df.columns.name == DataModel.SNAPSHOTS:
        is_unit = df.attrs["unit"]
        scaling_factor = UNITS[is_unit] / UNITS[to_unit]
        result = df.mul(scaling_factor)
    else:
        scale_to = to_unit if isinstance(to_unit, float) else UNITS[to_unit]
        units_in = list(map(get_unit, df.columns))
        if to_unit.endswith("h") and not all(u.endswith("h") for u in units_in):
            raise ValueError("Denying to convert units from power to energy.")
        if to_unit.endswith("W") and not all(u.endswith("W") for u in units_in):
            raise ValueError("Denying to convert unit from energy to power.")
        scale_in = [UNITS[s] for s in units_in]
        scaling_factors = [x / scale_to for x in scale_in]

        result = df.mul(scaling_factors, axis=1)
        result.columns = result.columns.str.replace(
            "|".join(units_in), to_unit, regex=True
        )

    if suffix:
        result.attrs["unit"] = f"{to_unit}_{suffix}"
    else:
        result.attrs["unit"] = to_unit

    return result


def calculate_input_share(
    df: pd.DataFrame | pd.Series,
    bus_carrier: str | list,
    apply_scaling: bool = True,
) -> pd.DataFrame | pd.Series:
    """
    Calculate the withdrawal necessary to supply energy for requested bus_carrier.

    Each technology's demand rows are weighted by the output share that lands
    on the requested ``bus_carrier``.  An optional input/output scaling step
    converts those input-side magnitudes into the equivalent output-side
    magnitudes; see *apply_scaling* below.

    Parameters
    ----------
    df
        The input DataFrame or Series with a MultiIndex.
    bus_carrier
        Calculates the input energy for this bus_carrier.
    apply_scaling
        Whether to rescale each demand row by the technology's
        ``total_output / total_input`` ratio (default ``True``, preserving
        the legacy behaviour).

        - ``True``: the result is expressed in *output* magnitudes. For a
          fuel-to-power link this yields the electricity actually produced
          from the fuel (``elec_output``).  Heat-pump-like links (where
          output exceeds input) get a virtual ``ambient heat`` /
          ``latent heat`` surplus row so that input + surplus matches
          output.
        - ``False``: the scaling factor is skipped and the result is
          expressed in *input* magnitudes. For a fuel-to-power link this
          yields the fuel input attributable to electricity output
          (``fuel × electricity_fraction``).  The heat-pump surplus branch
          is irrelevant in this mode and is therefore skipped.

    Returns
    -------
    :
        The withdrawal amounts necessary to produce energy of `bus_carrier`,
        either in output-side magnitudes (``apply_scaling=True``) or in
        input-side magnitudes (``apply_scaling=False``).
    """

    def _input_share(_df):
        demand = _df[_df.lt(0)]
        supply = _df[_df.ge(0)]
        bus_carrier_supply = filter_by(supply, bus_carrier=bus_carrier).sum()
        # share takes multiple outputs into account
        with np.errstate(divide="ignore", invalid="ignore"):  # silently divide by zero
            share = bus_carrier_supply / supply.sum()
        if not apply_scaling:
            # Input-side magnitudes: skip the input/output scaling so the
            # result reflects ``demand × output_share`` (e.g. fuel input
            # attributable to electricity output).
            return demand * share
        # scaling takes into account that Link inputs and outputs are not equally large
        scaling = abs(supply.sum() / demand.sum())
        if scaling > 1.0:
            _carrier = _df.index.unique(DataModel.CARRIER).item()
            _bus_carrier = "ambient heat" if "heat pump" in _carrier else "latent heat"
            surplus = rename_aggregate(
                demand * (scaling - 1), _bus_carrier, level=DataModel.BUS_CARRIER
            )
            return pd.concat([demand, surplus]) * share
        else:
            return demand * scaling * share

    groups = [s for s in df.index.names if s != "bus_carrier"]
    return df.groupby(groups, group_keys=False).apply(_input_share).mul(-1)


def filter_for_carrier_connected_to(df: pd.DataFrame, bus_carrier: str | list):
    """
    Return a subset with technologies connected to a bus carrier.

    Parameters
    ----------
    df
        The input DataFrame or Series with a MultiIndex.
    bus_carrier
        The bus carrier to filter for.

    Returns
    -------
    :
        A subset of the input data that contains all location + carrier
        combinations that have at least one connection to the requested
        bus_carrier.
    """
    carrier_connected_to_bus_carrier = []
    locations_connected_to_bus_carrier = []

    # hotfix to support country groupers
    location_or_country = DataModel.LOCATION
    if "country" in df.index.names:
        location_or_country = "country"

    for (loc, carrier), data in df.groupby([location_or_country, DataModel.CARRIER]):
        if filter_by(data, bus_carrier=bus_carrier).any():
            carrier_connected_to_bus_carrier.append(carrier)
            locations_connected_to_bus_carrier.append(loc)

    kwargs = {
        "carrier": carrier_connected_to_bus_carrier,
        location_or_country: locations_connected_to_bus_carrier,
    }

    return filter_by(df, **kwargs)


def split_urban_central_heat_losses_and_consumption(
    df: pd.DataFrame | pd.Series, heat_loss: int
) -> pd.DataFrame:
    """
    Split urban heat amounts by a heat loss factor.

    Amounts for urban central heat contain distribution losses.
    However, the evaluation shows final demands
    in the results. Therefore, heat network distribution losses need
    to be separated from the total amounts because grid distribution
    losses do not arrive at the metering endpoint.

    Parameters
    ----------
    df
        The input data frame with values for urban central heat
        technologies.
    heat_loss
        The heat loss factor from the configuration file.

    Returns
    -------
    :
        The data frame with split heat amounts for end user demand
        (urban dentral heat), distribution grid losses (urban dentral
        heat losses) and anything else from the input data frame
        (not urban central heat).
    """
    loss_factor = heat_loss / (1 + heat_loss)
    urban_heat_bus_carrier = [BusCarrier.HEAT_URBAN_CENTRAL]

    urban_heat = filter_by(df, bus_carrier=urban_heat_bus_carrier)
    rest = filter_by(df, bus_carrier=urban_heat_bus_carrier, exclude=True)
    consumption = urban_heat.mul(1 - loss_factor)
    losses = urban_heat.mul(loss_factor)
    losses_mapper = dict.fromkeys(urban_heat_bus_carrier, "urban central heat losses")
    losses = losses.rename(losses_mapper, level=DataModel.CARRIER)

    return pd.concat([rest, consumption, losses]).sort_index()


def get_heat_loss_factor(nc: NetworkCollection) -> int:
    """
    Return the heat loss factor for district heating from the config.

    Parameters
    ----------
    nc
        The loaded networks.

    Returns
    -------
    The heat loss factor for district heating networks.
    """
    heat_loss_factors = {
        n.meta["sector"]["district_heating"]["district_heating_loss"] for n in nc
    }
    assert len(heat_loss_factors) == 1, "Varying loss factors are not supported."
    return heat_loss_factors.pop()


def drop_from_multtindex_by_regex(
    df: pd.DataFrame, pattern: str, level: str = DataModel.CARRIER
) -> pd.DataFrame | pd.Series:
    """
    Drop all rows that match the regex in the index level.

    This function is needed, because pandas.DataFrame.filter cannot
    be applied to MultiIndexes.

    Parameters
    ----------
    df
        The input data frame with a multi index.
    pattern
        The regular expression pattern as a raw string.
    level
        The multi index level to match the regex to.

    Returns
    -------
    :
        The input data where the regular expression does not match.
    """
    if not pattern:
        return df

    mask = df.index.get_level_values(level).str.contains(pattern, regex=True)
    return df[~mask]


def custom_sort(
    df: pd.DataFrame, by: str, values: tuple, ascending: bool = False
) -> pd.DataFrame:
    """
    Sort a data frame by the first appearance in *values*.

    Parameters
    ----------
    df
        The dataframe to sort.
    by
        The column name to find values in.
    values
        The values to sort by.  The order in this collection defines
        the sort result.
    ascending
        Whether to reverse the result (Plotly inserts legend items from
        top down).

    Returns
    -------
    :
        The sorted data frame.
    """
    if not values:
        return df

    def _custom_order(ser: pd.Series) -> pd.Series:
        order = {s: i for i, s in enumerate(values)}
        return ser.apply(lambda x: order.get(x, 1000))

    return df.sort_values(by=by, key=_custom_order, ascending=ascending)


def prettify_number(x: float) -> str:
    """
    Format a float for display on trace hover actions.

    Parameters
    ----------
    x
        The imprecise value to format.

    Returns
    -------
    :
        The formatted number as a string with 1 or 0 decimal places,
        depending on the magnitude of the input value.
    """
    if abs(x) >= 10:
        return f"{int(round(x, 0)):d}"
    else:
        return f"{round(x, 1):.1f}"


def add_grid_lines(buses: pd.DataFrame, statistic: pd.Series) -> pd.DataFrame:
    """
    Add a column with gridlines to a statistic.

    Parameters
    ----------
    buses
        The Bus component data frame from a pypsa network.

    statistic
        A pandas object with a multiindex. There must be a "bus0" and
        a "bus1" multiindex level, that hold the node names.

    Returns
    -------
    :
        A data frame with an additional "line" column that holds x/y
        coordinate pairs between the respective bus0 and bus1 locations.
    """
    if isinstance(statistic, pd.Series):
        statistic = statistic.to_frame()

    bus0 = statistic.index.get_level_values("bus0").str.strip()
    bus1 = statistic.index.get_level_values("bus1").str.strip()
    ac_buses = filter_by(buses, carrier="AC")[["x", "y"]]

    def _get_bus_lines(_nodes: tuple[str]) -> np.ndarray:
        """
        Draw a line between buses using AC bus coordinates.

        Note, that only AC buses have coordinates assigned.

        Parameters
        ----------
        _nodes
            The start node name and the end node name in a tuple.

        Returns
        -------
        :
            A one dimensional array with lists of coordinate pairs,
            i.e. grid lines.
        """
        return ac_buses.loc[[*_nodes]][["y", "x"]].values.tolist()

    # generate lines [(x0, y0), (x1,y1)] between buses for every
    # row in grid and store it in a new column
    statistic["line"] = [*map(_get_bus_lines, zip(bus0, bus1, strict=True))]

    return statistic


def align_edge_directions(
    df: pd.DataFrame, lvl0: str = "bus0", lvl1: str = "bus1"
) -> pd.DataFrame:
    """
    Align the directionality of edges between two nodes.

    Parameters
    ----------
    df
        The input data frame with a multiindex.
    lvl0
        The first MultiIndex level name to swap values.
    lvl1
        The second MultiIndex level name to swap values.

    Returns
    -------
    :
        The input data frame with aligned edge directions between the
        nodes in lvl1 and lvl0.
    """
    seen = []

    def _reverse_values_if_seen(df_slice: pd.DataFrame) -> pd.DataFrame:
        """
        Reverse index levels if they have a duplicated permutation.

        Parameters
        ----------
        df_slice
            A slice of a data frame with the bus0 and bus1 index level.

        Returns
        -------
        :
            The slice with exchanged level values if the combination of
            lvl1 and lvl2 is not unique and the original slice
            otherwise.
        """
        buses = {df_slice.index.unique(lvl0)[0], df_slice.index.unique(lvl1)[0]}
        if buses in seen:
            reversed_slice = df_slice.swaplevel(lvl0, lvl1)
            # keep original names since we only want to swap values
            reversed_slice.index.names = df_slice.index.names
            return reversed_slice
        else:
            seen.append(buses)
            return df_slice

    return df.groupby([lvl0, lvl1], group_keys=False).apply(
        _reverse_values_if_seen,
    )


def _aggregate_eu(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calculate the EU region as the sum of all country regions.

    Cross-border trade carriers (import/export net, foreign, domestic)
    sum to zero across all countries and are therefore renamed to
    'Transmission Losses' to avoid double-counting at EU level.
    Non-EU imports (e.g. 'global import') are kept as-is.

    Parameters
    ----------
    df
        DataFrame with a MultiIndex level named ``location``.
        Expected to contain region-level rows (e.g. 'AT1', 'DE2').

    Returns
    -------
    :
        Single-location DataFrame with location set to 'EU'.
    """
    df_no_eu = df.query(f"{DataModel.LOCATION} not in ['EU', '']")
    europe = rename_aggregate(df_no_eu, "EU", level=DataModel.LOCATION)
    eu_trade_to_losses = dict.fromkeys(
        [
            Group.import_net,
            Group.export_net,
            Group.import_foreign,
            Group.export_foreign,
            Group.import_domestic,
            Group.export_domestic,
        ],
        "Transmission Losses",
    )
    return rename_aggregate(europe, eu_trade_to_losses)


def _aggregate_locations(
    df: pd.DataFrame,
    keep_regions: tuple = ("AT",),
    nice_names: bool = True,
) -> pd.DataFrame:
    """
    Aggregate cluster-level data to countries, add EU total, keep sub-national regions.

    Parameters
    ----------
    df
        DataFrame with a MultiIndex location level containing cluster
        codes such as 'AT1', 'FR0', 'DE2'.
    keep_regions
        Country-code prefixes whose original cluster rows are preserved
        in the output alongside the aggregated country rows.
    nice_names
        Replace ISO-2 country/region codes with human-readable names
        via :func:`get_location_alias`.

    Returns
    -------
    :
        DataFrame with rows for every aggregated country, all EU
        sub-national regions listed in *keep_regions*, and one EU row.
    """
    country_codes = {loc: loc[:2] for loc in df.index.unique(DataModel.LOCATION)}
    if "EU" in country_codes.values():
        logger.warning(
            "Values for 'EU' node found in input data frame. "
            "This can lead to value duplication during location aggregation.",
        )
    countries = rename_aggregate(df, country_codes, level=DataModel.LOCATION)
    # Domestic trade nets to zero after country-level aggregation; rename to
    # transmission losses to avoid double-counting.
    mapper_losses = dict.fromkeys(
        [Group.import_domestic, Group.export_domestic], "Transmission Losses"
    )
    countries = rename_aggregate(countries, mapper_losses)

    europe = _aggregate_eu(df)

    mask = df.index.get_level_values(DataModel.LOCATION).str.startswith(keep_regions)
    regions = df.loc[mask, :]
    result = pd.concat([countries, regions, europe]).sort_index(axis=0)

    if nice_names:
        mapper = get_location_alias(result.index.unique(DataModel.LOCATION))
        result = result.rename(index=mapper, level=DataModel.LOCATION)

    return result


def _split_trade_saldo_to_netted_import_export(df: pd.DataFrame) -> pd.DataFrame:
    """
    Split the trade saldo carrier into netted import and export rows.

    Must be called *after* location aggregation so that cross-regional
    netting is correct for multi-region countries (e.g. Germany).
    Positive saldo values become import; negative values become export.

    Parameters
    ----------
    df
        DataFrame that may contain rows whose carrier contains 'saldo'.

    Returns
    -------
    :
        DataFrame with saldo rows replaced by separate import-net and
        export-net rows.  Returns *df* unchanged when no saldo rows exist.
    """
    saldo = df.query("carrier.str.contains('saldo')")
    if saldo.empty:
        return df

    net_import = rename_aggregate(saldo.mul(saldo.gt(0)), Group.import_net)
    net_export = rename_aggregate(saldo.mul(saldo.le(0)), Group.export_net)
    saldo_carrier = saldo.index.unique("carrier")
    return pd.concat(
        [df.drop(saldo_carrier, level=DataModel.CARRIER), net_import, net_export]
    ).sort_index()


def combine_statistics(
    statistics: list,
    metric_name: str,
    is_unit: str,
    to_unit: str,
    keep_regions: tuple = ("AT", "GB", "ES", "FR", "DE", "IT"),
    region_nice_names: bool = True,
) -> pd.DataFrame:
    """
    Build the metric data frame from statistics.

    Parameters
    ----------
    statistics
        The statistics to combine.
    metric_name
        The metric name used in plot titles and column labels.
    is_unit
        The common unit of input statistics.
    to_unit
        The desired unit of the output metric.
    keep_regions
        A collection of country codes for which original input
        cluster codes will be included in the metric locations.
    region_nice_names
        Whether to replace location country codes with country/region
        names.

    Returns
    -------
    :
        The formatted metric in the desired unit and locations.
    """
    df = pd.concat(statistics)

    if was_series := isinstance(df, pd.Series):
        df = df.to_frame(f"{metric_name} ({is_unit})")

    df = _aggregate_locations(df, keep_regions, region_nice_names)

    df.attrs["name"] = metric_name
    df.attrs["unit"] = to_unit

    df.columns.name = DataModel.METRIC if was_series else DataModel.SNAPSHOTS
    if df.columns.name == DataModel.SNAPSHOTS:
        df.columns = pd.to_datetime(df.columns, errors="raise")

    if to_unit and (is_unit != to_unit):
        df = scale(df, to_unit=to_unit)

    df = _split_trade_saldo_to_netted_import_export(df)

    return df


def get_storage_carriers(nc: NetworkCollection) -> list[str]:
    """
    Get the storage carriers from the networks.

    Parameters
    ----------
    nc
        The loaded networks.

    Returns
    -------
    :
        A list of storage carrier names.
    """
    storage_carriers = set()
    for n, c in product(nc, ("Store", "StorageUnit")):
        storage_carriers = storage_carriers.union(n.static(c)["carrier"].unique())

    return sorted(storage_carriers)


def get_transmission_techs(
    nc: NetworkCollection, bus_carrier: str | list = None
) -> list[str]:
    """
    Get the transmission technologies from the networks.

    Parameters
    ----------
    nc
        The loaded networks.
    bus_carrier
        The bus carrier to filter for.

    Returns
    -------
    :
        A list of transmission technology names.
    """
    transmission_techs = set()
    for n in nc:
        transmission_techs = transmission_techs.union(
            get_transmission_carriers(n, bus_carrier)
        )

    return sorted(transmission_techs)


def regionalize_statistics(
    supply: pd.Series, demand: pd.DataFrame, bus_carrier: str | list
) -> pd.Series:
    """
    Calculate regional balances for specific carriers.

    Computes regional import/export balances by comparing supply and demand
    for specific bus carriers (e.g., oil, coal, lignite, NH3) across locations.

    Parameters
    ----------
    supply
        Supply statistics series.
    demand
        Demand statistics series.
    bus_carrier
        Bus carrier name(s) to analyze for regional trade.

    Returns
    -------
    :
        List containing regional import and export series.
        Imports are negative balances (deficit), exports are positive (surplus).
    """
    year_loc = [DataModel.YEAR, DataModel.LOCATION]
    regional_supply = filter_by(supply, bus_carrier=bus_carrier).groupby(year_loc).sum()
    regional_demand = filter_by(demand, bus_carrier=bus_carrier).groupby(year_loc).sum()
    regional_balance = (
        regional_supply.add(regional_demand, fill_value=0)
        .pipe(insert_index_level, "Link", DataModel.COMPONENT, pos=1)
        .pipe(insert_index_level, bus_carrier, DataModel.BUS_CARRIER, pos=3)
        .pipe(insert_index_level, "trade", DataModel.CARRIER, pos=3)
        .drop("EU", level=DataModel.LOCATION, errors="ignore")
    )
    regional_import = rename_aggregate(
        regional_balance[regional_balance.le(0)], {"trade": "Global Import"}
    ).mul(-1)
    regional_export = rename_aggregate(
        regional_balance[regional_balance.gt(0)], {"trade": "Global Export"}
    ).mul(-1)

    return pd.concat([regional_import, regional_export])


def get_location_alias(locations: pd.Index) -> dict:
    """
    Return the location alias mapping depending on the clustering.

    Constructs a mapping dictionary from location codes to human-readable
    names based on the detected clustering configuration. Automatically
    detects DE5/16 and AT10/35 clustering levels by counting the
    number of regional locations in the index.

    Parameters
    ----------
    locations
        Index containing location codes (e.g., 'DE1', 'AT211', 'EU').

    Returns
    -------
    :
        Dictionary mapping location codes to human-readable names.
        Includes country, region, and clustering-specific aliases.

    Raises
    ------
    ValueError
        If the number of DE or AT regions doesn't match expected
        clustering configurations (DE5/16 or AT10/35).
    """
    de_regions = [loc for loc in locations if loc.startswith("DE")]
    if len(de_regions) == 6:  # DE5 clustering + Germany
        alias = ALIAS_COUNTRY | ALIAS_REGION | ALIAS_REGION_DE5_CLUSTERING
    elif len(de_regions) == 17:  # 16 Bundesländer + Germany
        alias = ALIAS_COUNTRY | ALIAS_REGION | ALIAS_REGION_DE16_CLUSTERING
    else:
        logger.warning(f"Unexpected number of locations for DE: {len(de_regions)}.")
        alias = ALIAS_COUNTRY

    at_regions = [loc for loc in locations if loc.startswith("AT")]
    if len(at_regions) == 11:  # AT10 + Austria
        alias = alias | ALIAS_REGION_AT10_CLUSTERING
    elif len(at_regions) == 36:  # AT35 + Austria
        alias = alias | ALIAS_REGION_AT35_CLUSTERING
    else:
        logger.warning(f"Unexpected number of locations for AT: {len(at_regions)}.")

    return frozendict(alias)


def get_energy_totals_domestic_share(
    energy_totals: pd.DataFrame, kind: str
) -> pd.Series:
    """
    Return the domestic share of energy totals for a given kind.

    Parameters
    ----------
    energy_totals
        The energy totals data frame filtered to one energy year.
    kind: {'aviation', 'navigation'}
        The kind of energy totals to calculate the factor for.

    Returns
    -------
    :
        The share of national aviation or navigation per country.
    """
    domestic = energy_totals[f"total domestic {kind}"]
    international = energy_totals[f"total international {kind}"]
    return domestic / (domestic + international)


def build_plot_config(global_cfg: dict) -> SimpleNamespace:
    """
    Build a plot configuration namespace from the TOML global config dict.

    All values are read directly from *global_cfg* without fallback defaults.
    If a required key is missing, a :class:`KeyError` is raised immediately so
    misconfigurations surface loudly rather than silently producing incorrect
    output.

    Complex values that cannot be expressed in TOML (chart class references,
    colour/pattern dicts, empty per-view dicts) are set here using Python
    constants. View-specific overrides (``plotby``, ``pivot_index``, etc.) are
    applied in the individual view functions after the namespace is constructed.

    Parameters
    ----------
    global_cfg
        The ``[global]`` section of the merged TOML configuration, as
        returned by :func:`~evals.fileio.read_views_config`.

    Returns
    -------
    :
        A :class:`~types.SimpleNamespace` with the same attribute names as
        the former ``PlotConfig`` dataclass.

    Raises
    ------
    KeyError
        If a required key is absent from *global_cfg*.
    """
    _pattern_keys = [
        Group.import_foreign,
        Group.export_foreign,
        Group.import_domestic,
        Group.export_domestic,
        Group.import_net,
        Group.export_net,
        Group.import_global,
    ]

    return SimpleNamespace(
        # --- title & file naming (overwritten by Exporter per view) ---
        title=None,
        file_name_template=global_cfg["file_name_template"],
        unit="",  # default is metric.df.attrs["unit"] at render time
        # --- database upload attributes (overwritten by Exporter per view) ---
        database_plot_type="",
        database_specifier="",
        database_bus_carrier="",
        # --- chart class (resolved to a class by Exporter.export()) ---
        chart=None,
        # --- data model / pivot defaults (overwritten in view code per view) ---
        plotby=[DataModel.LOCATION],
        pivot_index=list(DataModel.YEAR_IDX_NAMES),
        pivot_columns=[],
        plot_category=DataModel.CARRIER,
        plot_xaxis=DataModel.YEAR,
        facet_column=DataModel.BUS_CARRIER,
        # --- view-level overrides set per-view (empty by default) ---
        category_orders=(),
        fill=dict(COLOR_SCHEME_FILL),
        line_dash={},
        line_width={},
        # --- complex defaults from Python constants ---
        colors=dict(COLOUR_SCHEME),
        pattern=dict.fromkeys(_pattern_keys, "/"),
        # --- scalar / boolean defaults sourced from TOML [global] ---
        stacked=global_cfg["stacked"],
        line_shape=global_cfg["line_shape"],
        legend_header=global_cfg["legend_header"],
        xaxis_title=global_cfg["xaxis_title"],
        yaxis_color=global_cfg["yaxis_color"],
        footnotes=tuple(global_cfg["footnotes"]),
        cutoff=global_cfg.get(
            "cutoff", 0.0001
        ),  # overwritten per-view; toml has no view-level default
        cutoff_drop=global_cfg["cutoff_drop"],
        legend_font_size=global_cfg["legend_font_size"],
        title_font_size=global_cfg["title_font_size"],
        font_size=global_cfg["font_size"],
        xaxis_font_size=global_cfg["xaxis_font_size"],
        yaxes_showgrid=global_cfg["yaxes_showgrid"],
        yaxes_visible=global_cfg["yaxes_visible"],
    )


def get_latest_results_folder() -> Path:
    """Find the results folder with the latest file system timestamp."""
    results_root = Path("results")
    scenario_dirs = [
        scenario
        for prefix in results_root.iterdir()
        if prefix.is_dir()
        for scenario in prefix.iterdir()
        if scenario.is_dir()
    ]
    if not scenario_dirs:
        raise FileNotFoundError(
            f"No scenario directories found under {results_root.resolve()}"
        )

    # return largest system timestamp folder
    return max(scenario_dirs, key=lambda p: p.stat().st_mtime)
