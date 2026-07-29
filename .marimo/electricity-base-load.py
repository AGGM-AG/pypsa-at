import marimo

__generated_with = "0.23.13"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo
    import matplotlib.pyplot as plt
    import pandas as pd
    import pypsa
    import xarray as xr

    return mo, pd, plt, pypsa, xr


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    # Electricity base load deduction chain

    Walks the `electricity` base load through the deductions applied in
    `prepare_sector_network` and shows the remaining time series with
    descriptive statistics after every step:

    1. **Raw base load** — measured ENTSO-E/OPSD country load, distributed to
       nodes and attached by `add_electricity.attach_load`.
    2. **− electric heating** — shaped profile subtraction
       (`build_heat_demand`, energy_totals `electricity residential/services
       water/space` × hourly heat demand shape).
    3. **− today's industry electricity** — multiplicative scaling per country
       (`add_industry`, `current electricity` from JRC-IDEES).
    4. **− rail electricity** (PyPSA-AT) — proportional per-node scaling
       (`mods.demand.electricity.base_load_load_splitting`).

    The distribution-grid-losses scaling that runs between steps 3 and 4 in the
    real workflow is config-dependent and skipped here.
    """)
    return


@app.cell
def _():
    RESOURCES = "resources/base-load-updates/AT_KN2040/"
    NYEARS = 1.0  # elec network has 8760 hourly snapshots -> full calendar year
    COLORS = {
        "raw": "#0072B2",
        "after heat": "#E69F00",
        "after industry": "#009E73",
        "after rail": "#CC79A7",
    }
    return COLORS, NYEARS, RESOURCES


@app.cell
def _(RESOURCES, pypsa):
    n = pypsa.Network(RESOURCES + "networks/base_s_adm_elec.nc")
    base_raw = n.loads_t.p_set.copy()  # MW, one column per node
    nodes = base_raw.columns
    return base_raw, nodes


@app.cell
def _(pd, plt):
    def describe_load(df):
        """Descriptive statistics of a nodal load time series in MW."""
        _system = df.sum(axis=1) / 1e3  # GW
        _nodal_energy = df.sum() / 1e6  # TWh/a per node (hourly snapshots)
        _stats = {
            "total energy [TWh/a]": df.sum().sum() / 1e6,
            "system mean [GW]": _system.mean(),
            "system min [GW]": _system.min(),
            "system max (peak) [GW]": _system.max(),
            "system std [GW]": _system.std(),
            "system 5% quantile [GW]": _system.quantile(0.05),
            "system 95% quantile [GW]": _system.quantile(0.95),
            "largest node [TWh/a]": _nodal_energy.max(),
            "smallest node [TWh/a]": _nodal_energy.min(),
            "negative node-hours": float(df.lt(0).sum().sum()),
            "nodes with negative hours": float(df.lt(0).any().sum()),
        }
        return pd.Series(_stats, name="value").round(3).to_frame()

    def plot_system(df, title, color):
        """Plot the system-wide (sum over nodes) load profile in GW."""
        _system = df.sum(axis=1) / 1e3
        _fig, _ax = plt.subplots(figsize=(10, 3.5))
        _ax.plot(
            _system.index, _system, color=color, lw=0.3, alpha=0.35, label="hourly"
        )
        _ax.plot(
            _system.rolling(168, center=True).mean(),
            color=color,
            lw=1.8,
            label="7-day mean",
        )
        _ax.set_ylabel("system load [GW]")
        _ax.set_title(title, loc="left")
        _ax.grid(axis="y", color="0.9", lw=0.6)
        _ax.spines[["top", "right"]].set_visible(False)
        _ax.legend(frameon=False, loc="upper right")
        _fig.tight_layout()
        return _fig

    return describe_load, plot_system


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 1. Raw base load (ENTSO-E/OPSD, nodal)
    """)
    return


@app.cell
def _(base_raw, describe_load):
    stats_raw = describe_load(base_raw)
    stats_raw
    return


@app.cell
def _(COLORS, base_raw, plot_system):
    plot_system(base_raw, "Raw base load", COLORS["raw"])
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 2. Deduct electric heating

    Mirrors `build_heat_demand`: the annual electric heating energy per node
    (`electricity {residential,services} {water,space}`, TWh/a) is shaped with
    the hourly heat demand profile (normalised to 1) and subtracted hour by
    hour. This is a *shaped profile* subtraction — winter-peaked — and the
    source of the known negative-load edge cases.
    """)
    return


@app.cell
def _(NYEARS, RESOURCES, base_raw, pd, xr):
    pwet = pd.read_csv(RESOURCES + "pop_weighted_energy_totals_s_adm.csv", index_col=0)

    _shape = (
        xr.open_dataset(RESOURCES + "hourly_heat_demand_total_base_s_adm.nc")
        .to_dataframe()
        .unstack(level=1)
    )
    _supply = {}
    for _name in [
        "residential water",
        "residential space",
        "services water",
        "services space",
    ]:
        _sector, _use = _name.rsplit(" ", 1)
        _supply[_name] = (_shape[_name] / _shape[_name].sum()).multiply(
            pwet[f"electricity {_sector} {_use}"] * NYEARS
        ) * 1e6

    electric_heat = pd.concat(_supply, axis=1).T.groupby(level=1).sum().T
    electric_heat.index = base_raw.index

    base_after_heat = base_raw - electric_heat[base_raw.columns]
    return base_after_heat, pwet


@app.cell
def _(base_after_heat, describe_load):
    stats_heat = describe_load(base_after_heat)
    stats_heat
    return


@app.cell
def _(COLORS, base_after_heat, plot_system):
    plot_system(
        base_after_heat,
        "Base load after electric heating deduction",
        COLORS["after heat"],
    )
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 3. Deduct today's industry electricity

    Mirrors `add_industry`: per country, the base load is scaled by
    `1 − current_industry_el / total_base_load` — a multiplicative scaling that
    preserves the profile shape. Uses the 2025 planning-horizon file, whose
    `current electricity` column carries today's industrial demand.
    """)
    return


@app.cell
def _(NYEARS, RESOURCES, base_after_heat, nodes, pd):
    industry_today = (
        pd.read_csv(
            RESOURCES + "industrial_energy_demand_base_s_adm_2025.csv", index_col=0
        )
        * 1e6
        * NYEARS
    )

    base_after_industry = base_after_heat.copy()
    _factors = {}
    for _ct in sorted({_c[:2] for _c in nodes}):
        _cols = [_c for _c in nodes if _c.startswith(_ct)]
        _factor = (
            1
            - industry_today.loc[_cols, "current electricity"].sum()
            / base_after_heat[_cols].sum().sum()
        )
        base_after_industry[_cols] *= _factor
        _factors[_ct] = _factor

    industry_factors = pd.Series(_factors, name="scaling factor").round(4)
    industry_factors.to_frame().T
    return (base_after_industry,)


@app.cell
def _(base_after_industry, describe_load):
    stats_industry = describe_load(base_after_industry)
    stats_industry
    return


@app.cell
def _(COLORS, base_after_industry, plot_system):
    plot_system(
        base_after_industry,
        "Base load after industry electricity deduction",
        COLORS["after industry"],
    )
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 4. Deduct rail electricity (PyPSA-AT)

    Mirrors `mods.demand.electricity.base_load_load_splitting`: per node, the
    rail share `s = E_rail / E_base` scales the base load down; the removed
    part keeps the identical profile shape and becomes the
    `electricity for rail` Load in the real workflow.
    """)
    return


@app.cell
def _(NYEARS, base_after_industry, pwet):
    rail_energy = pwet["electricity rail"] * NYEARS * 1e6  # MWh/a
    rail_share = rail_energy / base_after_industry.sum()
    rail_profile = base_after_industry.mul(rail_share, axis="columns")
    base_after_rail = base_after_industry - rail_profile
    rail_share.sort_values(ascending=False).head(10).round(4).to_frame("rail share")
    return base_after_rail, rail_share


@app.cell
def _(mo, rail_share):
    _invalid = rail_share[~rail_share.between(0, 1)]
    mo.md(
        r"""
    !!! warning "Invalid rail shares"

        Nodes whose rail share falls outside `[0, 1)` — here the heat
        deduction has already consumed the node's entire base load (annual
        residual ≤ 0), so a share is meaningless. This is the known `AT126`
        edge case handled by `clip_negative_loads_for_edge_cases`; the
        production sanity check in `base_load_load_splitting` raises for
        these nodes.

    """
        + _invalid.round(3).to_frame("rail share").to_markdown()
        if not _invalid.empty
        else "All rail shares within `[0, 1)`."
    )
    return


@app.cell
def _(base_after_rail, describe_load):
    stats_rail = describe_load(base_after_rail)
    stats_rail
    return


@app.cell
def _(COLORS, base_after_rail, plot_system):
    plot_system(
        base_after_rail,
        "Remaining base load after rail deduction",
        COLORS["after rail"],
    )
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Summary — energy removed per stage and duration curves
    """)
    return


@app.cell
def _(base_after_heat, base_after_industry, base_after_rail, base_raw, pd):
    _totals = {
        "raw": base_raw.sum().sum() / 1e6,
        "after heat": base_after_heat.sum().sum() / 1e6,
        "after industry": base_after_industry.sum().sum() / 1e6,
        "after rail": base_after_rail.sum().sum() / 1e6,
    }
    summary_table = pd.DataFrame({"total energy [TWh/a]": pd.Series(_totals)})
    summary_table["removed [TWh/a]"] = -summary_table["total energy [TWh/a]"].diff()
    summary_table["removed [%]"] = (
        100
        * summary_table["removed [TWh/a]"]
        / summary_table["total energy [TWh/a]"].iloc[0]
    )
    summary_table.round(2)
    return


@app.cell
def _(
    COLORS,
    base_after_heat,
    base_after_industry,
    base_after_rail,
    base_raw,
    plt,
):
    _stages = {
        "raw": base_raw,
        "after heat": base_after_heat,
        "after industry": base_after_industry,
        "after rail": base_after_rail,
    }
    _fig, _ax = plt.subplots(figsize=(10, 3.5))
    for _label, _df in _stages.items():
        _system = (
            _df.sum(axis=1).sort_values(ascending=False).reset_index(drop=True) / 1e3
        )
        _ax.plot(_system, color=COLORS[_label], lw=1.8, label=_label)
    _ax.set_xlabel("hours (sorted)")
    _ax.set_ylabel("system load [GW]")
    _ax.set_title("Load duration curves per deduction stage", loc="left")
    _ax.grid(axis="y", color="0.9", lw=0.6)
    _ax.spines[["top", "right"]].set_visible(False)
    _ax.legend(frameon=False, loc="upper right")
    _fig.tight_layout()
    _fig
    return


if __name__ == "__main__":
    app.run()
