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
    4. **Sectoral split** (PyPSA-AT) — the remaining base load is distributed
       *without remainder* into sectoral Loads using weights normalised over
       the JRC-IDEES sectoral energies
       (`mods.demand.electricity.base_load_load_splitting`).

    The distribution-grid-losses scaling that runs between steps 3 and 4 in the
    real workflow is config-dependent and skipped here.
    """)
    return


@app.cell
def _():
    RESOURCES = "resources/base-load-updates/AT_KN2040/"
    STAGE_COLORS = {
        "raw": "#0072B2",
        "after heat": "#E69F00",
        "after industry": "#009E73",
    }
    SECTOR_COLORS = {
        "electricity for residential": "#0072B2",
        "electricity for services": "#E69F00",
        "electricity for road": "#009E73",
        "electricity for rail": "#CC79A7",
        "agriculture electricity": "#D55E00",
    }
    return RESOURCES, SECTOR_COLORS, STAGE_COLORS


@app.cell
def _(RESOURCES, pypsa):
    n = pypsa.Network(RESOURCES + "networks/base_s_adm_elec.nc")
    base_raw = n.loads_t.p_set.copy()  # MW, one column per node
    return (base_raw,)


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
def _(STAGE_COLORS, base_raw, plot_system):
    plot_system(base_raw, "Raw base load", STAGE_COLORS["raw"])
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
def _(RESOURCES, base_raw, pd, xr):
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
            pwet[f"electricity {_sector} {_use}"]
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
def _(STAGE_COLORS, base_after_heat, plot_system):
    plot_system(
        base_after_heat,
        "Base load after electric heating deduction",
        STAGE_COLORS["after heat"],
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
def _(RESOURCES, base_after_heat, pd):
    industry_today = (
        pd.read_csv(
            RESOURCES + "industrial_energy_demand_base_s_adm_2025.csv", index_col=0
        )
        * 1e6
    )

    base_after_industry = base_after_heat.copy()
    _factors = {}
    for _ct in sorted({_c[:2] for _c in base_after_heat.columns}):
        _cols = [_c for _c in base_after_heat.columns if _c.startswith(_ct)]
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
def _(STAGE_COLORS, base_after_industry, plot_system):
    plot_system(
        base_after_industry,
        "Base load after industry electricity deduction",
        STAGE_COLORS["after industry"],
    )
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 4. Sectoral split (PyPSA-AT)

    Mirrors `mods.demand.electricity.base_load_load_splitting`: the remaining
    base load of every node is distributed **without remainder** into sectoral
    Loads. The weights are normalised over the JRC-IDEES sectoral energies
    (`w_i = E_i / ΣE_j`), so every part keeps the measured ENTSO-E profile and
    the parts sum exactly to the base load. Grid losses and the statistical gap
    between measured load and JRC bottom-up totals are distributed pro-rata.

    - `electricity for residential` / `electricity for services` exclude the
      space and water heating amounts (already deducted in step 2).
    - `electricity for road` uses the aggregate column (includes the PHEV
      share).
    - the `agriculture electricity` share **replaces the flat Load** added by
      `add_agriculture()` with a profiled time series, fixing the upstream
      double counting.
    - negative sectoral energies from source-data inconsistencies are clipped
      to zero (affects `NO`: services electricity < space + water heating).

    Because `pop_weighted_energy_totals` distributes country totals by
    population, all nodes of a country share identical weights — nodal
    differences come purely from the base load profiles.
    """)
    return


@app.cell
def _(mo, pd, pwet):
    sector_energies = pd.DataFrame(
        {
            "electricity for residential": (
                pwet["electricity residential"]
                - pwet["electricity residential space"]
                - pwet["electricity residential water"]
            ),
            "electricity for services": (
                pwet["electricity services"]
                - pwet["electricity services space"]
                - pwet["electricity services water"]
            ),
            "electricity for road": pwet["electricity road"],
            "electricity for rail": pwet["electricity rail"],
            "agriculture electricity": pwet["total agriculture electricity"],
        }
    )
    clipped_nodes = sector_energies.index[sector_energies.lt(0).any(axis=1)].to_list()
    weights = sector_energies.clip(lower=0)
    weights = weights.div(weights.sum(axis="columns"), axis="index")

    country_weights = weights.groupby(weights.index.str[:2]).first().round(3)
    mo.vstack(
        [
            mo.md(f"Nodes with clipped negative sectoral energies: `{clipped_nodes}`"),
            mo.md("**Per-country sectoral weights:**"),
            country_weights,
        ]
    )
    return (weights,)


@app.cell
def _(base_after_industry, pd, weights):
    sector_loads = {
        _carrier: base_after_industry.mul(weights[_carrier], axis="columns")
        for _carrier in weights.columns
    }

    sector_stats = pd.DataFrame(
        {
            "total energy [TWh/a]": {
                _c: _df.sum().sum() / 1e6 for _c, _df in sector_loads.items()
            },
            "system peak [GW]": {
                _c: _df.sum(axis=1).max() / 1e3 for _c, _df in sector_loads.items()
            },
            "negative node-hours": {
                _c: float(_df.lt(0).sum().sum()) for _c, _df in sector_loads.items()
            },
        }
    )
    sector_stats["share [%]"] = (
        100
        * sector_stats["total energy [TWh/a]"]
        / sector_stats["total energy [TWh/a]"].sum()
    )
    sector_stats.round(2)
    return (sector_loads,)


@app.cell
def _(SECTOR_COLORS, plt, sector_loads):
    _fig, _ax = plt.subplots(figsize=(10, 3.5))
    for _carrier, _df in sector_loads.items():
        _system = _df.sum(axis=1) / 1e3
        _ax.plot(
            _system.rolling(168, center=True).mean(),
            color=SECTOR_COLORS[_carrier],
            lw=1.8,
            label=_carrier,
        )
    _ax.set_ylabel("system load [GW]")
    _ax.set_title("Sectoral Loads, 7-day rolling mean", loc="left")
    _ax.grid(axis="y", color="0.9", lw=0.6)
    _ax.spines[["top", "right"]].set_visible(False)
    _ax.legend(frameon=False, loc="upper right", fontsize=8)
    _fig.tight_layout()
    _fig
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    !!! note "Conservation and negatives"

        The sectoral parts sum exactly to the post-industry base load at every
        node and hour — the split neither adds nor removes energy (the
        agriculture share is not dropped; it replaces the flat upstream Load).
        The negative node-hours introduced by the heat deduction in step 2
        propagate proportionally into **all** sectoral Loads; they are handled
        later by `clip_negative_loads_for_edge_cases` in `modify_prenetwork`.
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Summary — energy per stage and duration curves
    """)
    return


@app.cell
def _(base_after_heat, base_after_industry, base_raw, pd, sector_loads):
    _totals = {
        "raw": base_raw.sum().sum() / 1e6,
        "after heat": base_after_heat.sum().sum() / 1e6,
        "after industry": base_after_industry.sum().sum() / 1e6,
    }
    summary_table = pd.DataFrame({"total energy [TWh/a]": pd.Series(_totals)})
    summary_table["removed [TWh/a]"] = -summary_table["total energy [TWh/a]"].diff()

    _split = pd.Series(
        {_c: _df.sum().sum() / 1e6 for _c, _df in sector_loads.items()},
        name="total energy [TWh/a]",
    )
    _split.loc["sum of sectoral Loads"] = _split.sum()
    pd.concat([summary_table.round(2), _split.round(2).to_frame()], axis=0).fillna("")
    return


@app.cell
def _(STAGE_COLORS, base_after_heat, base_after_industry, base_raw, plt):
    _stages = {
        "raw": base_raw,
        "after heat": base_after_heat,
        "after industry": base_after_industry,
    }
    _fig, _ax = plt.subplots(figsize=(10, 3.5))
    for _label, _df in _stages.items():
        _system = (
            _df.sum(axis=1).sort_values(ascending=False).reset_index(drop=True) / 1e3
        )
        _ax.plot(_system, color=STAGE_COLORS[_label], lw=1.8, label=_label)
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
