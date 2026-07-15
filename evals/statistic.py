# SPDX-FileCopyrightText: 2023-2025 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""Collect statistics for evaluations."""  # noqa: A005

import logging
import warnings
from collections.abc import Callable, Sequence
from inspect import getmembers
from itertools import product

import pandas as pd
import pypsa
from pypsa import Network, NetworkCollection
from pypsa.common import (
    MethodHandlerWrapper,
    deprecated_kwargs,
    pass_empty_series_if_keyerror,
)
from pypsa.descriptors import nominal_attrs
from pypsa.statistics import (
    StatisticsAccessor,
    get_transmission_carriers,
    groupers,
)
from pypsa.statistics.expressions import (
    StatisticHandler,
    port_efficiency,
    resolve_at_port,
)

from evals.constants import (
    BusCarrier,
    DataModel,
    Group,
)
from evals.utils import (
    add_grid_lines,
    align_edge_directions,
    filter_by,
    get_trade_type,
    insert_index_level,
    split_location_carrier,
    trade_mask,
)

logger = logging.getLogger(__file__)


def _port_location(n: Network, c: str, port: str = "") -> pd.Series:
    """
    Return the location of the bus at the given port.

    Parameters
    ----------
    n
        The network to evaluate.
    c
        The component name, e.g. "Line", "Link", "Transformer".
    port
        The port to look up the bus for, e.g. "0" or "1".

    Returns
    -------
    :
        Series with the location of the bus at this specific port.
    """
    bus = f"bus{port}"
    return groupers._map_with_multiindex(
        n.c[c].static[bus], n.c["Bus"].static["location"]
    ).rename("location")


def collect_myopic_statistics(
    nc: NetworkCollection,
    statistic: str,
    aggregate_components: str | None = "sum",
    drop_zeros: bool = True,
    drop_unit: bool = True,
    allow_missing: dict = None,
    **kwargs: object,
) -> pd.DataFrame | pd.Series:
    """
    Build a myopic statistic from loaded networks.

    This method calls ESMStatisticsAccessor methods. It calls the
    statistics method for every year and optionally aggregates
    components, e.g. Links and Lines often should become summed up.

    Parameters
    ----------
    nc
        The loaded networks as a NetworkCollection, with the year as index.
    statistic
        The name of the metric to build.
    aggregate_components
        The aggregation function to combine components by.
    drop_zeros
        Whether to drop rows from the returned statistic that have
        only zeros as values.
    drop_unit
        Whether to drop the unit index level from the returned statistic.
    allow_missing
        A dictionary with years as keys and a list of bus_carrier to drop
        for values. This is needed to allow bus_carrier to be missing in
        certain years.
    **kwargs
        Any key word argument accepted by the statistics function.

    Returns
    -------
    :
        The built statistic with the year as the outermost index level.

    Raises
    ------
    ValueError
        In case a non-existent statistics function was requested.
    """
    kwargs = kwargs or {}

    pypsa_statistics = [m[0] for m in getmembers(pypsa.statistics.StatisticsAccessor)]

    if statistic in pypsa_statistics:  # register a default to reduce verbosity
        kwargs.setdefault("groupby", ["location", "carrier", "bus_carrier", "unit"])

    year_statistics = []
    for year, n in nc.networks.items():
        func = getattr(n.statistics, statistic)
        if not func:
            raise AttributeError(
                f"Statistic '{statistic}' not found. "
                f"Available statistics are: "
                f"'{[m[0] for m in getmembers(n.statistics)]}'."
            )
        func_args = kwargs.copy()
        if allow_missing and year in allow_missing and "bus_carrier" in kwargs:
            func_args["bus_carrier"] = [
                bc for bc in kwargs["bus_carrier"] if bc not in allow_missing[year]
            ]

        year_statistic = func(**func_args)
        year_statistic = insert_index_level(year_statistic, year, DataModel.YEAR)
        if not year_statistic.empty:
            year_statistics.append(year_statistic)

    statistic = pd.concat(year_statistics, axis=0, sort=True)
    if DataModel.LOCATION in statistic.index.names:
        if "EU" in statistic.index.unique(DataModel.LOCATION):
            logger.debug(
                f"EU node found in statistic:\n"
                f"{filter_by(statistic, location='EU')}"
                f"\n\nPlease check if this is intentional!"
            )

    if aggregate_components and "component" in statistic.index.names:
        _names = statistic.index.droplevel("component").names
        statistic = statistic.groupby(_names).agg(aggregate_components)

    if kwargs.get("aggregate_time") is False:
        statistic.columns.name = DataModel.SNAPSHOTS

    if drop_zeros:
        if isinstance(statistic, pd.Series):
            statistic = statistic.loc[statistic != 0]
        elif isinstance(statistic, pd.DataFrame):
            statistic = statistic.loc[(statistic != 0).any(axis=1)]
        else:
            raise TypeError(f"Unknown statistic type '{type(statistic)}'")

    # assign the correct unit the statistic if possible
    if "unit" in statistic.index.names and drop_unit:
        if not statistic.empty:
            try:
                statistic.attrs["unit"] = statistic.index.unique("unit").item()
            except ValueError:
                logger.debug(
                    f"Mixed units detected in statistic: {statistic.index.unique('unit')}."
                )
        statistic = statistic.droplevel("unit")

    return statistic.sort_index()


class ESMStatistics(StatisticsAccessor):
    """
    Provides additional statistics for ESM evaluations.

    Extends the StatisticsAccessor with additional metrics.

    Note, that the __call__ method of the base class is not
    updated. Metrics registered with this class need to
    be called explicitly and are not included in the output
    of n.statistics().

    The actual patching is done directly after reading in the
    network files in read_networks(). This means, that
    io.read_networks() must be used to load networks, or the
    statistics will not be available under n.statistics().

    Parameters
    ----------
    n
        The loaded postnetwork.
    """

    def __init__(self, n: pypsa.Network) -> None:
        super().__init__(n)

    def phs_split(
        self, aggregate_time: str = "sum", drop_hydro_cols: bool = True
    ) -> pd.DataFrame:
        """
        Split energy amounts for StorageUnits.

        This is done to properly separate primary energy and energy
        storage, i.e. to separate the natural inflow (primary energy)
        from storage dispatch (secondary energy).

        Parameters
        ----------
        aggregate_time
            The aggregation function used to aggregate time steps.

        drop_hydro_cols
            Whether, or not to drop 'hydro' carriers from the result.
            This is required to stay consistent with the old predecessor
            implementation.

        Returns
        -------
        :
            A DataFrame containing the split energy amounts for
            PHS and hydro.

        Notes
        -----
        Not needed if all PHS are implemeted as closed loops. The method is kept
        if open loop PHS is available.

        .. deprecated::
            ``phs_split`` is deprecated and will be removed in a future release.
        """
        warnings.warn(
            "phs_split is deprecated and will be removed in a future release.",
            DeprecationWarning,
            stacklevel=2,
        )
        n = self._n

        idx = n.static("StorageUnit").index
        phs = pd.DataFrame(index=idx)
        for time_series in ("p_dispatch", "p_store", "spill", "inflow"):
            p = n.pnl("StorageUnit")[time_series].reindex(columns=idx, fill_value=0)
            # weights = get_weightings(n, "StorageUnit")
            weights = n.snapshot_weightings["stores"]
            phs[time_series] = n.statistics._aggregate_timeseries(
                p, weights, agg=aggregate_time
            )

        # calculate the potential dispatch energy for storages
        stored_energy = phs["p_store"] * n.static("StorageUnit")["efficiency_dispatch"]
        share_inflow = phs["inflow"] / (phs["inflow"] + stored_energy)

        phs["Dispatched Power from Inflow"] = phs["p_dispatch"] * share_inflow
        phs["Dispatched Power from Stored"] = phs["p_dispatch"] * (1 - share_inflow)
        phs["Spill from Inflow"] = phs["spill"] * share_inflow
        phs["Spill from Stored"] = phs["spill"] * (1 - share_inflow)

        mapper = {
            "p_dispatch": "Dispatched Power",
            "p_store": "Stored Power",
            "inflow": "Inflow",
            "spill": "Spill",
        }
        phs = phs.rename(mapper, axis=1)

        ser = phs.stack()
        ser.index = ser.index.swaplevel(0, 1)
        ser.index = split_location_carrier(ser.index, names=DataModel.IDX_NAMES)

        # merge 'carrier' with 'bus_carrier' level and keep original
        # bus_carrier. Needed to stay consistent with the old predecessor
        # naming conventions.
        ser.index = pd.MultiIndex.from_tuples(
            [(r[1], f"{r[2]} {r[0]}", r[2]) for r in ser.index],
            names=DataModel.IDX_NAMES,
        )
        ser = ser.rename(
            index={"PHS": BusCarrier.AC, "hydro": BusCarrier.AC},
            level=DataModel.BUS_CARRIER,
        )

        ser.attrs["name"] = "PHS&Hydro"
        ser.attrs["unit"] = "MWh"

        if drop_hydro_cols:
            cols = [
                "hydro Dispatched Power from Inflow",
                "hydro Dispatched Power from Stored",
                "hydro Spill from Inflow",
                "hydro Spill from Stored",
            ]
            ser = ser.drop(cols, level=DataModel.CARRIER)

        return ser.sort_index()

    def phs_hydro_operation(self) -> pd.DataFrame:
        """
        Calculate Hydro- and Pumped Hydro Storage unit statistics.

        Returns
        -------
        :
            Cumulated or constant time series for storage units.

        .. deprecated::
            ``phs_hydro_operation`` is deprecated and will be removed in a future release.
        """
        warnings.warn(
            "phs_hydro_operation is deprecated and will be removed in a future release.",
            DeprecationWarning,
            stacklevel=2,
        )
        n = self._n
        ts_efficiency_name_agg = [
            ("p_dispatch", "efficiency_dispatch", Group.turbine_cum, "cumsum"),
            ("p_store", "efficiency_store", Group.pumping_cum, "cumsum"),
            ("spill", None, Group.spill_cum, "cumsum"),
            ("inflow", None, Group.inflow_cum, "cumsum"),
            ("state_of_charge", None, Group.soc, None),
        ]

        # weights = get_weightings(n, "StorageUnit")
        weights = n.snapshot_weightings["stores"]

        su = n.static("StorageUnit").query("carrier in ['PHS', 'hydro']")

        results = []
        for time_series, efficiency, index_name, agg in ts_efficiency_name_agg:
            df = n.pnl("StorageUnit")[time_series].filter(su.index, axis=1)
            if agg:
                df = df.mul(weights, axis=0).agg(agg)
            if efficiency == "efficiency_dispatch":
                df = df / su[efficiency]
            elif efficiency == "efficiency_store":
                df = df * su[efficiency]
            # The actual bus carrier is "AC" for both, PHS and hydro.
            # Since only PHS and hydro are considered, we can use the
            # bus_carrier level to track groups.
            result = insert_index_level(df, index_name, DataModel.BUS_CARRIER, axis=1)
            results.append(result.T)

        # broadcast storage volume to time series (not quite the
        # same as utils.scalar_to_time_series, because it's a series)
        volume = su["p_nom_opt"] * su["max_hours"]
        volume_ts = pd.concat([volume] * len(n.snapshots), axis=1)
        volume_ts.columns = n.snapshots
        volume_ts = insert_index_level(volume_ts, Group.soc_max, DataModel.BUS_CARRIER)
        results.append(volume_ts)

        statistic = pd.concat(results)
        statistic.index = split_location_carrier(
            statistic.index,
            names=[DataModel.BUS_CARRIER, DataModel.LOCATION, DataModel.CARRIER],
        )
        statistic = statistic.reorder_levels(DataModel.IDX_NAMES)

        statistic.columns.names = [DataModel.SNAPSHOTS]
        statistic.attrs["name"] = "StorageUnit Operation"
        statistic.attrs["unit"] = "MWh"

        return statistic

    def trade_energy(
        self,
        scope: str | tuple,
        direction: str = "saldo",
        bus_carrier: str = None,
        aggregate_time: str = "sum",
    ) -> pd.DataFrame:
        """
        Calculate energy amounts exchanged between locations.

        Returns positive values for 'import' (supply) and negative
        values for 'export' (withdrawal).

        Parameters
        ----------
        scope
            The scope of energy exchange. Must be one of "foreign",
            "domestic", or "local".

        direction
            The direction of the trade. Can be one of "saldo", "export",
            or "import".

        bus_carrier
            The bus carrier for which to calculate the energy exchange.
            Defaults to using all bus carrier.

        aggregate_time
            The method of aggregating the energy exchange over time.
            Can be one of "sum", "mean", "max", "min".

        Returns
        -------
        :
            A DataFrame containing the calculated energy exchange
            between locations.
        """
        n = self._n
        results_comp = []

        buses = n.static("Bus").reset_index()
        if bus_carrier:
            _bc = [bus_carrier] if isinstance(bus_carrier, str) else bus_carrier
            buses = buses.query("carrier in @_bc")

        carrier = get_transmission_carriers(n, bus_carrier).unique("carrier")  # Noqa: F841
        comps = get_transmission_carriers(n, bus_carrier).unique("component")

        for port, c in product((0, 1), comps):
            mask = trade_mask(n.static(c), scope).to_numpy()
            comp = n.static(c)[mask].reset_index()

            p = buses.merge(
                comp.query("carrier.isin(@carrier)"),
                left_on="name",
                right_on=f"bus{port}",
                suffixes=("_bus", ""),
            ).merge(n.pnl(c).get(f"p{port}").T, on="name")

            _location = (
                DataModel.LOCATION + "_bus"
                if "location" in comp
                else DataModel.LOCATION
            )
            p = p.set_index([_location, DataModel.CARRIER, "carrier_bus", "unit"])
            p.index.names = DataModel.IDX_NAMES + ["unit"]
            # branch components have reversed sign
            p = p.filter(n.snapshots, axis=1).mul(-1)
            if direction == "export":
                p = p.clip(upper=0)  # keep negative values (withdrawal)
            elif direction == "import":
                p = p.clip(lower=0)  # keep positive values (supply)
            elif direction != "saldo":
                raise ValueError(f"Direction '{direction}' not supported.")

            results_comp.append(insert_index_level(p, c, "component"))

        if not results_comp:
            return pd.DataFrame()

        result = pd.concat(results_comp)

        if aggregate_time:
            weights = n.snapshot_weightings["objective"]
            result = result.multiply(weights, axis=1)
            result = result.agg(aggregate_time, axis=1)

        name = " & ".join(scope) if isinstance(scope, tuple) else scope
        result.attrs["name"] = f"{name} {direction}"
        result.attrs["unit"] = "MWh"

        return result.sort_index()

    def trade_capacity(
        self,
        scope: str,
        bus_carrier: str = "",
    ) -> pd.DataFrame:
        """
        Calculate exchange capacity between locations.

        Parameters
        ----------
        scope
            The scope of energy exchange. Must be one of
            constants.TRADE_TYPES.
        bus_carrier
            The bus carrier for which to calculate the energy exchange.
            Defaults to using all bus carrier.

        Returns
        -------
        :
            Energy exchange capacity between locations.
        """
        n = self._n

        capacity = self.optimal_capacity(
            comps=n.branch_components,
            bus_carrier=bus_carrier,
            groupby=["bus0", "bus1", "carrier", "bus_carrier"],
            nice_names=False,
        ).to_frame()
        trade_type = capacity.apply(
            lambda row: get_trade_type(row.name[1], row.name[2]), axis=1
        )

        trade_capacity = capacity[trade_type == scope]

        # duplicate capacities to list them for source and destination
        # locations. For example, the trade capacity for AT -> DE gas
        # pipeline will be shown in location AT and in location DE.
        df_list = []
        for bus in ("bus0", "bus1"):
            df = trade_capacity.droplevel(bus)
            df.index.names = [DataModel.COMPONENT] + DataModel.IDX_NAMES
            df_list.append(df)

        trade_capacity = pd.concat(df_list).drop_duplicates()

        return trade_capacity.squeeze()

    def grid_capacity(
        self,
        comps: list = None,
        groupby: list = None,
        bus_carrier: list = None,
        carrier: list = None,
        append_grid: bool = True,
        align_edges: bool = True,
    ) -> pd.DataFrame:
        """
        Return transmission grid capacities.

        Parameters
        ----------
        comps
            The network components to consider, defaults to all
            pypsa.Networks.branch_components.
        bus_carrier
            The bus carrier to consider.
        carrier
            The carrier to consider, defaults to all
            transmission carriers in the network.
        append_grid
            Whether to add the grid lines to the result.
        align_edges
            Whether to adjust edges between the same nodes but in
            reversed direction. For example, AC and DC grids have
            edges between IT0 0 and FR0 0 as IT->FR and FR->IT,
            respectively. If enabled, both will have the same bus0 and
            bus1.

        Returns
        -------
        :
            The optimal capacity for transmission technologies between
            nodes.

        Notes
        -----
        The "pypsa.statistics.transmission" statistic does not work here
        because it returns energy the amounts whereas this statistic returns
        the optimal capacity.

        .. deprecated::
            ``grid_capacity`` is deprecated and will be removed in a future release.
        """
        warnings.warn(
            "grid_capacity is deprecated and will be removed in a future release.",
            DeprecationWarning,
            stacklevel=2,
        )
        n = self._n
        carrier = carrier or list(
            get_transmission_carriers(n, bus_carrier).unique("carrier")
        )
        capacities = n.statistics.optimal_capacity(
            components=comps or n.branch_components,
            groupby=groupby or ["bus0", "bus1", "carrier", "bus_carrier"],
            bus_carrier=bus_carrier,
            # carrier=carrier,
        )
        # result = filter_by(capacities, carrier=list(carrier))
        result = capacities

        result.attrs["name"] = "Capacity"
        result.attrs["unit"] = "MW"
        result.name = f"{result.attrs['name']} ({result.attrs['unit']})"

        if align_edges:
            result = align_edge_directions(result)

        if append_grid:
            result = add_grid_lines(n.static("Bus"), result)

        return result.sort_index()

    def grid_flow(
        self,
        comps: list = None,
        bus_carrier: list = None,
        carrier: list = None,
        aggregate_time: str = "sum",
        append_grid: bool = True,
    ) -> pd.DataFrame:
        """
        Return the transmission grid energy flow.

        Parameters
        ----------
        comps
            The network components to consider, defaults to all
            pypsa.Networks.branch_components.
        bus_carrier
            The bus carrier to consider.
        carrier
            The carrier to consider, defaults to all
            transmission carrier in the network.
        aggregate_time
            The aggregation function aggregate by.
        append_grid
            Whether to add the grid lines to the result.

        Returns
        -------
        :
            The amount of energy transfer for transmission technologies
            between nodes.

        .. deprecated::
            ``grid_flow`` is deprecated and will be removed in a future release.
        """
        warnings.warn(
            "grid_flow is deprecated and will be removed in a future release.",
            DeprecationWarning,
            stacklevel=2,
        )
        n = self._n
        carrier = carrier or get_transmission_carriers(n, bus_carrier).unique("carrier")
        comps = comps or n.branch_components

        energy_transmission = n.statistics.transmission(
            comps=comps,
            groupby=["bus0", "bus1", "carrier", "bus_carrier"],
            bus_carrier=bus_carrier,
            aggregate_time=False,
        )
        energy_transmission = filter_by(energy_transmission, carrier=carrier)

        # split directions:
        # positive values are from bus0 to bus1, i.e. bus1 supply
        bus0_to_bus1 = energy_transmission.clip(lower=0)

        # negative values are from bus1 to bus0, i.e. bus0 supply
        idx_names = list(energy_transmission.index.names)
        bus1_to_bus0 = energy_transmission.clip(upper=0).mul(-1)
        # reverse the node index levels to show positive values and
        # have a consistent way of interpreting the energy flow
        bus1_to_bus0 = bus1_to_bus0.swaplevel("bus0", "bus1")
        pos0, pos_1 = idx_names.index("bus0"), idx_names.index("bus1")
        idx_names[pos_1], idx_names[pos0] = idx_names[pos0], idx_names[pos_1]
        bus1_to_bus0.index.names = idx_names

        result = pd.concat([bus0_to_bus1, bus1_to_bus0])
        result = result.groupby(idx_names).sum()

        assert aggregate_time, "Time Series is not supported."
        unit = "MW"
        if aggregate_time in ("max", "min"):
            result = result.agg(aggregate_time, axis=1)
        elif aggregate_time:  # mean, median, etc.
            # weights = get_weightings(n, comps)
            weights = n.snapshot_weightings[comps]
            result = result.mul(weights, axis=1).agg(aggregate_time, axis=1)
            unit = "MWh"

        result.attrs["name"] = "Energy"
        result.attrs["unit"] = unit
        result.name = f"{result.attrs['name']} ({result.attrs['unit']})"

        if append_grid:
            result = add_grid_lines(n.static("Bus"), result)

        return result.sort_index()

    @MethodHandlerWrapper(handler_class=StatisticHandler, inject_attrs={"n": "_n"})
    @deprecated_kwargs(
        deprecated_in="1.0",
        removed_in="2.0",
        comps="components",
        aggregate_groups="groupby_method",
        aggregate_time="groupby_time",
    )
    def remaining_capacity(  # noqa: D417
        self,
        components: str | Sequence[str] | None = None,
        groupby_method: Callable | str = "sum",
        aggregate_across_components: bool = False,
        groupby: str | Sequence[str] | Callable = "carrier",
        at_port: str | None = None,
        carrier: str | Sequence[str] | None = None,
        bus_carrier: str | Sequence[str] | None = None,
        nice_names: bool | None = None,
        drop_zero: bool | None = None,
        round: int | None = None,
        storage: bool = False,
    ) -> pd.DataFrame:
        """
        Calculate the **remaining buildable capacity** in MW.

        Returns ``p_nom_max - p_nom`` for extendable components in the current investment
        period, and zero for non-extendable (already-built) components. This
        represents how much additional capacity could still be installed on top of
        the current ``installed_capacity``.

        Note
        ----
        In brownfield myopic networks, ``p_nom`` for extendable components is
        typically zero while ``p_nom_min`` holds a committed floor (from
        brownfield carry-over, PEMMDB contracted additions, or other sources).
        The formula ``p_nom_max - p_nom`` therefore intentionally includes this
        committed capacity (``p_nom_min - p_nom``), ensuring that
        ``technical_potential = installed_capacity + remaining_capacity``
        algebraically reduces to ``p_nom_max`` (the raw trajectory ceiling).

        Parameters
        ----------
        components : str | Sequence[str] | None, default=None
            Components to include. If None, includes all one-port and branch
            components.
        groupby_method : Callable | str, default="sum"
            Aggregation function for groups.
        aggregate_across_components : bool, default=False
            Whether to aggregate across components.
        groupby : str | Sequence[str] | Callable, default="carrier"
            How to group components.
        at_port : str | None, default=None
            Which ports to consider.
        carrier : str | Sequence[str] | None, default=None
            Filter by carrier.
        bus_carrier : str | Sequence[str] | None, default=None
            Filter by carrier of connected buses.
        nice_names : bool | None, default=None
            Whether to use carrier nice names.
        drop_zero : bool | None, default=None
            Whether to drop zero values from the result.
        round : int | None, default=None
            Number of decimal places to round to.

        Other Parameters
        ----------------
        storage : bool, default=False
            Whether to consider only storage capacities.

        Returns
        -------
        pd.DataFrame
            Remaining buildable capacity in MW.

        See Also
        --------
        installed_capacity : Already installed capacity.
        technical_potential : Total ceiling (installed + remaining).
        """
        if storage:
            components = ("Store", "StorageUnit")
        resolved_at_port = resolve_at_port(at_port, bus_carrier)

        @pass_empty_series_if_keyerror
        def func(n: Network, c: str, port: str) -> pd.Series:
            efficiency = port_efficiency(n, c, port=port)
            if n.c[c]._as_ports(resolved_at_port) == [0]:
                efficiency = abs(efficiency)
            static = n.c[c].static
            col = (
                (static[f"{nominal_attrs[c]}_max"] - static[nominal_attrs[c]])
                .where(static[f"{nominal_attrs[c]}_extendable"], 0)
                .mul(efficiency)
            )
            if storage and (c == "StorageUnit"):
                col = col * static.max_hours
            return col

        df = self._aggregate_components(
            func,
            components=components,
            agg=groupby_method,
            aggregate_across_components=aggregate_across_components,
            groupby=groupby,
            at_port=at_port,
            carrier=carrier,
            bus_carrier=bus_carrier,
            nice_names=nice_names,
            drop_zero=drop_zero,
            round=round,
        )
        df.attrs["name"] = "Remaining Capacity"
        df.attrs["unit"] = "MW"
        return df

    @MethodHandlerWrapper(handler_class=StatisticHandler, inject_attrs={"n": "_n"})
    @deprecated_kwargs(
        deprecated_in="1.0",
        removed_in="2.0",
        comps="components",
        aggregate_groups="groupby_method",
        aggregate_time="groupby_time",
    )
    def technical_potential(  # noqa: D417
        self,
        components: str | Sequence[str] | None = None,
        groupby_method: Callable | str = "sum",
        aggregate_across_components: bool = False,
        groupby: str | Sequence[str] | Callable = "carrier",
        at_port: str | None = None,
        carrier: str | Sequence[str] | None = None,
        bus_carrier: str | Sequence[str] | None = None,
        nice_names: bool | None = None,
        drop_zero: bool | None = None,
        round: int | None = None,
        storage: bool = False,
    ) -> pd.DataFrame:
        """
        Calculate the **technical potential** (total capacity ceiling) in MW.

        Returns the absolute upper bound on how much capacity a region could
        ever have installed: already-built capacity from all past investment
        periods plus the maximum additionally buildable capacity in the current
        period.

        Computed as ``installed_capacity + remaining_capacity``.

        Parameters
        ----------
        components : str | Sequence[str] | None, default=None
            Components to include. If None, includes all one-port and branch
            components.
        groupby_method : Callable | str, default="sum"
            Aggregation function for groups.
        aggregate_across_components : bool, default=False
            Whether to aggregate across components.
        groupby : str | Sequence[str] | Callable, default="carrier"
            How to group components.
        at_port : str | None, default=None
            Which ports to consider.
        carrier : str | Sequence[str] | None, default=None
            Filter by carrier.
        bus_carrier : str | Sequence[str] | None, default=None
            Filter by carrier of connected buses.
        nice_names : bool | None, default=None
            Whether to use carrier nice names.
        drop_zero : bool | None, default=None
            Whether to drop zero values from the result.
        round : int | None, default=None
            Number of decimal places to round to.

        Other Parameters
        ----------------
        storage : bool, default=False
            Whether to consider only storage capacities.

        Returns
        -------
        pd.DataFrame
            Technical potential in MW.

        See Also
        --------
        installed_capacity : Already installed capacity.
        remaining_capacity : Capacity still buildable in the current period.
        """
        shared = dict(
            components=components,
            groupby_method=groupby_method,
            aggregate_across_components=aggregate_across_components,
            groupby=groupby,
            at_port=at_port,
            carrier=carrier,
            bus_carrier=bus_carrier,
            nice_names=nice_names,
            drop_zero=False,
            round=None,
            storage=storage,
        )
        installed = self.installed_capacity(**shared)
        remaining = self.remaining_capacity(**shared)
        df = installed.add(remaining, fill_value=0)
        if drop_zero is None:
            drop_zero = True
        if drop_zero:
            df = df[df != 0]
        if round is not None:
            df = df.round(round)
        df.attrs["name"] = "Technical Potential"
        df.attrs["unit"] = "MW"
        return df

    @MethodHandlerWrapper(handler_class=StatisticHandler, inject_attrs={"n": "_n"})
    @deprecated_kwargs(
        deprecated_in="1.0",
        removed_in="2.0",
        comps="components",
        aggregate_groups="groupby_method",
        aggregate_time="groupby_time",
    )
    def loss(  # noqa: D417
        self,
        components: str | Sequence[str] | None = None,
        groupby_method: Callable | str = "sum",
        aggregate_across_components: bool = False,
        groupby: str | Sequence[str] | Callable | None = None,
        carrier: str | Sequence[str] | None = None,
        bus_carrier: str | Sequence[str] | None = None,
        nice_names: bool | None = None,
        drop_zero: bool | None = None,
        round: int | None = None,
    ) -> pd.DataFrame:
        """
        Calculate the **loss** of two-port components at each snapshot.

        For every branch (default: Link, Line, Transformer), the loss is
        ``p0 + p1`` at the port from which power is flowing into the branch
        (i.e. the port whose power is non-negative); the other port is set
        to zero for that snapshot. This makes the attribution direction
        aware: loss is assigned to the location of the bus that is
        supplying power to the branch, rather than being double counted or
        assigned to a fixed port. Time is **not** aggregated: the result
        keeps snapshots as columns.

        Parameters
        ----------
        components : str | Sequence[str] | None, default=None
            Components to include. If None, includes all one-port and branch
            components.
        groupby_method : Callable | str, default="sum"
            Aggregation function for groups.
        aggregate_across_components : bool, default=False
            Whether to aggregate across components.
        groupby : str | Sequence[str] | Callable, default="carrier"
            How to group components.
        carrier : str | Sequence[str] | None, default=None
            Filter by carrier.
        bus_carrier : str | Sequence[str] | None, default=None
            Filter by carrier of connected buses.
        nice_names : bool | None, default=None
            Whether to use carrier nice names.
        drop_zero : bool | None, default=None
            Whether to drop zero values from the result.
        round : int | None, default=None
            Number of decimal places to round to.


        Returns
        -------
        :
            Loss of components in the network, with the grouping
            keys (e.g. component, location, carrier, bus_carrier) as rows and
            snapshots as columns.

        """
        components = components if components else ["Link", "Line", "Transformer"]
        groupby = groupby if groupby else ["location", "carrier", "bus_carrier"]

        @pass_empty_series_if_keyerror
        def loss_func(n: Network, c: str, port: str) -> pd.Series:
            dynamic = n.c[c].dynamic
            own = dynamic[f"p{port}"]
            other = dynamic[f"p{'1' if port == '0' else '0'}"]
            loss = (own + other).where(own >= 0, 0).clip(lower=0)
            return loss.T

        # substitute a port-aware "location" grouper (see _port_location)
        # so that bus0/bus1 resolve to different locations, regardless
        # of what is currently registered under the "location" name.
        loss_groupby = groupby
        if isinstance(loss_groupby, str):
            loss_groupby = [loss_groupby]
        if not callable(loss_groupby):
            loss_groupby = [
                _port_location if g == DataModel.LOCATION else g for g in loss_groupby
            ]

        df = self._aggregate_components(
            loss_func,
            components=components,
            agg=groupby_method,
            aggregate_across_components=aggregate_across_components,
            groupby=loss_groupby,
            at_port=[0, 1],
            carrier=carrier,
            bus_carrier=bus_carrier,
            nice_names=nice_names,
            drop_zero=drop_zero,
            round=round,
        )

        df.attrs["name"] = "Loss"
        df.attrs["unit"] = "MWh_el"
        return df
