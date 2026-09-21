import marimo

__generated_with = "0.20.4"
app = marimo.App(width="full")


@app.cell(hide_code=True)
def _():
    import sys

    import marimo as mo

    sys.path.insert(0, ".")
    return (mo,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    # Evals Walkthrough: Electricity Time Series

    This notebook walks step-by-step through the same data pipeline that
    `view_timeseries_electricity` executes, **without** calling the CLI or
    writing any files to disk.

    At each stage the intermediate result is displayed so the transformation is
    visible and can be inspected.

    | Step | What happens |
    |------|-------------|
    | 1 | Load `NetworkCollection` and view config |
    | 2 | Collect raw supply — `aggregate_time=False` keeps the full hourly shape |
    | 3 | Filter out transmission-only components |
    | 4 | Collapse all `bus_carrier` labels to a single value with `rename_aggregate` |
    | 5 | Separate storage contributions, collect demand and trade saldo |
    | 6 | Build `Exporter` — inspect `Exporter.df`, the combined metric DataFrame |
    | 7 | Apply the `categories` mapping via `rename_aggregate` |
    | 8 | Render the Plotly chart inline |
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ---
    ## Step 1 — Load NetworkCollection and config

    `read_networks` scans a results folder for `*.nc` files, loads each one as a
    `pypsa.Network`, and patches the `statistics` accessor with `ESMStatistics`.
    It returns a `NetworkCollection` keyed by planning year string.

    `read_views_config` reads `config.default.toml`, merges any local
    `config.override.toml` on top, and returns a dict with `"global"` and `"view"`
    sections — the view section is specific to the function you pass in.
    """)
    return


@app.cell
def _(mo):
    result_path = mo.ui.text(
        value="results/test-sector-myopic-at10/AT_KN2040",
        label="Result path",
        full_width=True,
    )
    result_path
    return (result_path,)


@app.cell
def _(result_path):
    from evals.fileio import read_networks, read_views_config
    from evals.views.balances_timeseries import view_timeseries_electricity

    nc = read_networks(result_path.value)
    config = read_views_config(view_timeseries_electricity)

    years = list(nc.networks.keys())
    bus_carrier = config["view"]["bus_carrier"] or None
    print(f"Years loaded : {years}")
    print(f"bus_carrier  : {bus_carrier}")
    return bus_carrier, config, nc


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ---
    ## Step 2 — Collect raw supply (time-resolved)

    `collect_myopic_statistics` iterates over every year in the `NetworkCollection`,
    calls `n.statistics.supply(**kwargs)` on each network, prepends a `year` index
    level, and concatenates the results.

    Two kwargs control the shape of the output:

    - **`aggregate_time=False`** — keeps snapshot timestamps as **columns** instead of
      summing them. The result is a `DataFrame` rather than a `Series`.
    - **`aggregate_components=None`** — preserves the `component` index level
      (Generator, Link, Store, …) so storage rows can be identified and relabelled
      before the component level is dropped.

    The default `groupby=["location", "carrier", "bus_carrier", "unit"]` produces a
    `MultiIndex` with those four levels plus the `component` level (when
    `aggregate_components=None`).
    """)
    return


@app.cell
def _(bus_carrier, config, nc):
    import pandas as pd
    from evals.statistic import collect_myopic_statistics

    from evals.utils import (
        filter_by,
        get_storage_carriers,
        get_transmission_techs,
        rename_aggregate,
    )

    allow_missing = config["view"].get("exclude", {})

    raw_supply = collect_myopic_statistics(
        nc,
        "supply",
        bus_carrier=bus_carrier,
        aggregate_time=False,
        aggregate_components=None,
        allow_missing=allow_missing,
    )

    print(f"shape         : {raw_supply.shape}")
    print(f"index levels  : {raw_supply.index.names}")
    print(f"snapshot cols : {raw_supply.shape[1]} timesteps")
    return (
        allow_missing,
        collect_myopic_statistics,
        filter_by,
        get_storage_carriers,
        get_transmission_techs,
        pd,
        raw_supply,
        rename_aggregate,
    )


@app.cell
def _(raw_supply):
    # show index and first 3 snapshot columns
    raw_supply.iloc[:, :3].head(14)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ---
    ## Step 3 — Filter transmission components

    Lines and Links that only move energy between buses (no conversion, no storage)
    appear in both supply **and** withdrawal simultaneously.  Including them would
    double-count every inter-node flow.

    `get_transmission_techs` finds these pairs and `filter_by(..., exclude=True)`
    removes them from the DataFrame.
    """)
    return


@app.cell
def _(bus_carrier, filter_by, get_transmission_techs, nc, raw_supply):
    transmission_techs = get_transmission_techs(nc, bus_carrier)
    transmission_comps = [c for c, _ in transmission_techs]
    transmission_carrier = [k for _, k in transmission_techs]

    supply_no_tx = raw_supply.pipe(
        filter_by,
        component=transmission_comps,
        carrier=transmission_carrier,
        exclude=True,
    )

    removed = len(raw_supply) - len(supply_no_tx)
    print(f"Removed {removed} transmission rows → {len(supply_no_tx)} remaining")
    print(f"Transmission components : {set(transmission_comps)}")
    return supply_no_tx, transmission_carrier, transmission_comps


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ---
    ## Step 4 — Collapse `bus_carrier` with `rename_aggregate`

    The view covers several bus carriers simultaneously (AC, low voltage, EV battery …).
    To treat them as one unified carrier for charting purposes, every `bus_carrier`
    label is overwritten with a single representative value — `bus_carrier[0]` — using
    `rename_aggregate`.

    **How `rename_aggregate` works:**

    ```
    rename_aggregate(df, mapper, level, agg="sum")
    ```

    1. If `mapper` is a **string**, every value in `level` is replaced by that string.
    2. If `mapper` is a **dict**, it maps old labels → new labels (missing keys keep the
       original label).
    3. After renaming, rows that now share the **same full index tuple** are **summed**
       via `groupby().agg(agg)`.

    Here, passing a string forces all bus_carrier values to `"AC"`.  Any row that was
    `(AT, land transport EV, EV battery)` becomes `(AT, land transport EV, AC)` and
    gets summed with any other row sharing that tuple.
    """)
    return


@app.cell
def _(bus_carrier, rename_aggregate, supply_no_tx):
    before_bc = supply_no_tx.index.unique("bus_carrier").tolist()

    supply_bc = supply_no_tx.pipe(
        rename_aggregate,
        bus_carrier[0],  # "AC" — target label for every bus_carrier
        level="bus_carrier",
    )

    after_bc = supply_bc.index.unique("bus_carrier").tolist()
    print(f"bus_carrier BEFORE collapse : {before_bc}")
    print(f"bus_carrier AFTER  collapse : {after_bc}")
    print(f"Rows reduced {len(supply_no_tx)} → {len(supply_bc)}  (duplicates summed)")
    return (supply_bc,)


@app.cell
def _(supply_bc):
    supply_bc.iloc[:, :3].head(10)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ---
    ## Step 5 — Separate storage, collect demand and trade saldo

    **Storage** (Store + StorageUnit components) must be handled separately:
    - Their supply rows are relabelled `"Storage Out"` with `rename_aggregate`.
    - Their demand rows are relabelled `"Storage In"`.
    - Supply and demand contributions are then **netted** per technology
      (net positive timesteps → "Storage Out", net negative → "Storage In").
      This prevents showing the same storage cycle as both positive and negative.

    **storage_links** (e.g. "BEV charger", "V2G") are Link carriers that act as
    storage from the electricity-bus perspective.  They are also relabelled to
    "Storage Out" / "Storage In" before the netting step.

    **Demand** follows the identical pipeline as supply but values are negated
    (withdrawal statistics are positive; the sign flip gives the conventional
    negative side on the chart).

    **Trade saldo** captures net cross-border and inter-regional energy flows
    (`scope=(FOREIGN, DOMESTIC), direction="saldo"`).  Positive saldo = net import,
    negative = net export.  `combine_statistics` (called by `Exporter.df`) later
    splits this into separate "Net Import" and "Net Export" bands.
    """)
    return


@app.cell
def _(
    allow_missing,
    bus_carrier,
    collect_myopic_statistics,
    config,
    filter_by,
    get_storage_carriers,
    nc,
    pd,
    rename_aggregate,
    supply_bc,
    transmission_carrier,
    transmission_comps,
):
    from evals.constants import DataModel as DM
    from evals.constants import Group, TradeTypes

    storage_carrier = get_storage_carriers(nc)
    storage_links = config["view"].get("storage_links", [])

    # ── supply: label storage rows, drop component level ──────────────────────
    _stor_sup = filter_by(
        supply_bc, component=("Store", "StorageUnit"), carrier=storage_carrier
    )
    supply = pd.concat(
        [
            supply_bc.drop(_stor_sup.index),
            rename_aggregate(_stor_sup, Group.storage_out),
        ]
    ).droplevel(DM.COMPONENT)

    if storage_links:
        supply = rename_aggregate(
            supply, dict.fromkeys(storage_links, Group.storage_out), level=DM.CARRIER
        )

    # ── demand: same pipeline, values negated ──────────────────────────────────
    _raw_demand = (
        collect_myopic_statistics(
            nc,
            "withdrawal",
            bus_carrier=bus_carrier,
            aggregate_time=False,
            aggregate_components=None,
            allow_missing=allow_missing,
        )
        .pipe(
            filter_by,
            component=transmission_comps,
            carrier=transmission_carrier,
            exclude=True,
        )
        .pipe(rename_aggregate, bus_carrier[0], level=DM.BUS_CARRIER)
        .mul(-1)
    )

    _stor_dem = filter_by(
        _raw_demand, component=("Store", "StorageUnit"), carrier=storage_carrier
    )
    demand = pd.concat(
        [
            _raw_demand.drop(_stor_dem.index),
            rename_aggregate(_stor_dem, Group.storage_in),
        ]
    ).droplevel(DM.COMPONENT)

    if storage_links:
        demand = rename_aggregate(
            demand, dict.fromkeys(storage_links, Group.storage_in), level=DM.CARRIER
        )

    # ── net storage balance ────────────────────────────────────────────────────
    _sup_stor = filter_by(supply, carrier=Group.storage_out).pipe(
        rename_aggregate, "Storage"
    )
    _dem_stor = filter_by(demand, carrier=Group.storage_in).pipe(
        rename_aggregate, "Storage"
    )
    _balance = _sup_stor.add(_dem_stor, fill_value=0)
    storage_in = rename_aggregate(_balance[_balance < 0], Group.storage_in)
    storage_out = rename_aggregate(_balance[_balance > 0], Group.storage_out)
    supply_final = supply.drop(Group.storage_out, level=DM.CARRIER)
    demand_final = demand.drop(Group.storage_in, level=DM.CARRIER)

    # ── trade saldo ────────────────────────────────────────────────────────────
    trade_saldo = (
        collect_myopic_statistics(
            nc,
            "trade_energy",
            scope=(TradeTypes.FOREIGN, TradeTypes.DOMESTIC),
            direction="saldo",
            bus_carrier=bus_carrier,
            aggregate_time=False,
            aggregate_components=None,
        )
        .pipe(filter_by, component=transmission_comps, carrier=transmission_carrier)
        .droplevel(DM.COMPONENT)
    )
    trade_saldo.attrs["unit"] = supply_final.attrs["unit"]
    trade_saldo = rename_aggregate(trade_saldo, trade_saldo.attrs["name"])

    statistics = [supply_final, demand_final, trade_saldo, storage_in, storage_out]
    names = [s.attrs.get("name", "?") for s in statistics]
    print(f"Statistics list: {names}")
    return (statistics,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ---
    ## Step 6 — `Exporter` and `Exporter.df`

    `Exporter` accepts the list of statistics and the view config.  Its `df` property
    is a **cached** call to `combine_statistics`, which:

    1. `pd.concat` — concatenates all statistics into one DataFrame.
    2. `_aggregate_locations` — rolls up NUTS sub-regions into their country codes
       (except for countries listed in `keep_regions`, e.g. AT keeps its regions).
    3. `scale` — converts values from the input unit to the configured output unit
       (e.g. `MWh_el`).
    4. `_split_trade_saldo_to_netted_import_export` — finds any row whose carrier name
       matches the trade saldo name, and splits it into separate "Net Import"
       (positive timesteps) and "Net Export" (negative timesteps) rows.

    The result has `(year, location, carrier)` as the MultiIndex and snapshot
    timestamps as columns.
    """)
    return


@app.cell
def _(config, statistics):
    from evals.fileio import Exporter

    exporter = Exporter(statistics=statistics, view_config=config["view"])
    df_combined = exporter.df

    print(f"shape         : {df_combined.shape}")
    print(f"index levels  : {df_combined.index.names}")
    print(f"snapshot cols : {df_combined.shape[1]} timestamps")
    print(f"unique carriers: {sorted(df_combined.index.unique('carrier').tolist())}")
    return (df_combined,)


@app.cell
def _(df_combined):
    df_combined.iloc[:, :3].head(16)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ---
    ## Step 7 — Apply the `categories` mapping with `rename_aggregate`

    `Exporter.export_views` passes `config["view"]["categories"]` as the `mapper` to
    `rename_aggregate(df, mapper=categories, level="carrier")`.

    This is the **dict variant** of `rename_aggregate`:
    - Keys are raw carrier strings from the network.
    - Values are display names shown in the chart legend.
    - Multiple raw carriers with the **same** display name are **summed** after renaming.
    - Any carrier not present in the dict keeps its original name.

    The side-by-side view below shows which raw carriers exist in `Exporter.df` (left)
    and what they collapse to after the mapping (right).
    """)
    return


@app.cell
def _(config, df_combined, mo, rename_aggregate):
    categories = config["view"]["categories"]
    df_named = rename_aggregate(df_combined, mapper=categories, level="carrier")

    before_carriers = sorted(df_combined.index.unique("carrier").tolist())
    after_carriers = sorted(df_named.index.unique("carrier").tolist())

    _before_md = mo.md(
        "**Before** (raw carriers)\n\n" + "\n".join(f"- `{c}`" for c in before_carriers)
    )
    _after_md = mo.md(
        "**After** (display names)\n\n" + "\n".join(f"- `{c}`" for c in after_carriers)
    )

    mo.hstack([_before_md, _after_md], gap=4)
    return (df_named,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ---
    ## Step 8 — Render the Plotly chart

    `Exporter.export_views` groups the named DataFrame by `(year, location)` and
    creates one `ESMTimeSeriesChart` per group.  Below we replicate that for one
    interactively selected group and display the figure inline.

    Select a planning year and a location to update the chart.
    """)
    return


@app.cell
def _(df_named, mo):
    year_options = sorted(df_named.index.unique("year").tolist())
    loc_options = sorted(df_named.index.unique("location").tolist())

    sel_year = mo.ui.dropdown(year_options, value=year_options[-1], label="Year")
    sel_loc = mo.ui.dropdown(loc_options, value=loc_options[0], label="Location")
    mo.hstack([sel_year, sel_loc])
    return sel_loc, sel_year


@app.cell
def _(config, df_named, pd, sel_loc, sel_year):
    from evals.constants import DataModel
    from evals.plots import ESMTimeSeriesChart
    from evals.utils import build_plot_config

    # replicate the Exporter.export() config mutations for ESMTimeSeriesChart
    _cfg = build_plot_config(config["global"])
    _cfg.chart = ESMTimeSeriesChart
    _cfg.title = config["view"]["name"] + " — {location} {year}"
    _cfg.plotby = [DataModel.YEAR, DataModel.LOCATION]
    _cfg.pivot_index = [DataModel.YEAR, DataModel.LOCATION, DataModel.CARRIER]
    _cfg.pivot_columns = []
    _cfg.cutoff = config["view"]["cutoff"]
    _cfg.cutoff_drop = config["global"]["cutoff_drop"]
    _cfg.category_orders = config["view"]["legend_order"]
    _cfg.file_name_template = config["view"]["file_name"]
    _cfg.xaxis_title = ""
    _cfg.yaxes_visible = True
    _cfg.yaxes_showgrid = True

    # select the chosen (year, location) slice
    _y, _l = sel_year.value, sel_loc.value
    _slice = df_named.xs((_y, _l), level=[DataModel.YEAR, DataModel.LOCATION])

    # restore the full (year, location, carrier, bus_carrier) MultiIndex
    _slice = pd.concat({_l: _slice}, names=[DataModel.LOCATION])
    _slice = pd.concat({_y: _slice}, names=[DataModel.YEAR])
    _slice = _slice.reorder_levels(
        [DataModel.YEAR, DataModel.LOCATION, DataModel.CARRIER, DataModel.BUS_CARRIER]
    )
    # mirror Exporter.export_views: pivot collapses bus_carrier so column labels are strings, not tuples
    _slice = _slice.pivot_table(
        index=_cfg.pivot_index, columns=_cfg.pivot_columns, aggfunc="sum"
    )
    _slice.attrs.update(df_named.attrs)

    _chart = ESMTimeSeriesChart(_slice, _cfg)
    _chart.plot()
    _chart.fig

    return


@app.cell
def _():
    return


if __name__ == "__main__":
    app.run()
