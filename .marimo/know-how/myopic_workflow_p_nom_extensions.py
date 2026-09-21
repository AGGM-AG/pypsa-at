import marimo

__generated_with = "0.20.4"
app = marimo.App(width="medium")


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    # Myopic Workflow & p_nom Extensions

    This tutorial explains how the **myopic foresight workflow** accumulates optimised capacities
    across planning horizons (2025 → 2030 → 2040 → 2050) and why solved result networks stay lean
    despite carrying assets from multiple build years.

    Topics covered:

    1. Workflow structure: the network files produced in `resources/` and `results/`
    2. Rule names, their Python entry points, and the `.nc` files they produce
    3. How brownfield capacity is injected into each successive horizon
    4. Inspecting a 2050 result network — multiple assets per carrier per node
    5. File sizes and why they stay flat (zlib compression inside NetCDF4)
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ---

    ## 1. Workflow Structure

    The DAG for each planning horizon follows this linear chain of network files:

    ```
    ── ... simplify, cluster, add_sectors
    ── resources/base_*{year}.nc
    ── resources/*{year}_brownfield.nc ← first: add_existing_baseyear(...)
                                       ← later: add_brownfield(...)
    ── resources/*{year}_final.nc      ← modify_prenetwork (DE/AT mods)
    ── results/*{year}.nc              ← solve_sector_network_myopic
    ```

    The `_brownfield.nc` is the output of the brownfield rules and the **input** to `modify_prenetwork`.
    The `_final.nc` is what actually enters the solver. The solved result in `results/` then feeds
    the **next** horizon's `add_brownfield` rule.
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ---

    ## 2. Rules, Functions, and Output Files

    | Snakemake rule | Python entry point | Key output `.nc` |
    |---|---|---|
    | `base_network` | `scripts/base_network.py` | `resources/networks/base.nc` |
    | `add_transmission_projects_and_dlr` | `scripts/add_transmission_projects_and_dlr.py` | `resources/networks/base_extended.nc` |
    | `simplify_network` | `scripts/simplify_network.py` | `resources/networks/base_s.nc` |
    | `cluster_network` | `scripts/cluster_network.py` | `resources/networks/base_s_{clusters}.nc` |
    | `add_electricity` | `scripts/add_electricity.py` | `resources/networks/base_s_{clusters}_elec.nc` |
    | `prepare_network` | `scripts/prepare_network.py` | `resources/networks/base_s_{clusters}_elec_{opts}.nc` |
    | `prepare_sector_network` | `scripts/prepare_sector_network.py` | `resources/networks/…_{year}.nc` |
    | `add_existing_baseyear` *(first horizon only)* | `scripts/add_existing_baseyear.py` | `resources/networks/…_{year}_brownfield.nc` |
    | `add_brownfield` *(subsequent horizons)* | `scripts/add_brownfield.py` | `resources/networks/…_{year}_brownfield.nc` |
    | `modify_prenetwork` | `scripts/pypsa-de/modify_prenetwork.py` | `resources/networks/…_{year}_final.nc` |
    | `solve_sector_network_myopic` | `scripts/solve_network.py` | `results/{run}/networks/…_{year}.nc` |

    ### Rule order guard

    Both `add_existing_baseyear` and `add_brownfield` produce the same output filename `resources/networks/…_{year}_brownfield.nc`.
    Snakemake picks the correct rule via:

    ```python
    # rules/solve_myopic.smk
    ruleorder: add_existing_baseyear > add_brownfield
    ```

    A `wildcard_constraints` on `add_existing_baseyear` limits it to
    `config['scenario']['planning_horizons'][0]`, so `add_brownfield` handles all later years automatically.

    ```python
    rule add_existing_baseyear:
        ...
        wildcard_constraints:
            # TODO: The first planning_horizon needs to be aligned across scenarios
            # snakemake does not support passing functions to wildcard_constraints
            # reference: https://github.com/snakemake/snakemake/issues/2703
            planning_horizons=config["scenario"]["planning_horizons"][0],  #only applies to baseyear

    ```

    This means, that the `rule add_existing_baseyear` is only added to the DAG if the current `wildcards.planning_horizons` value matches the first value in the configs `wildcard.planning_horizons` list. Once both rules exist, the `add_existing_baseyear` takes precidence over `add_brownfield`.
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ---

    ## 3. How Brownfield Capacity is Added

    ### First horizon — `add_existing_baseyear`

    Reads today's installed capacities from:

    - **Powerplant matching** (`powerplantmatching`) for conventional thermal plants
    - **IRENA STAT** for existing renewables (onwind, solar, offwind)
    - **Custom powerplants CSV** for German CHPs

    Each existing plant becomes a non-extendable component with:

    - `build_year` = historical installation year
    - `lifetime` = technology-specific value from the costs CSV
    - `p_nom_extendable = False` → capacity is fixed, not re-optimised
    - `p_nom` = installed capacity in MW

    New greenfield assets from the optimiser get `build_year = baseyear` appended to their name,
    e.g. `FR 0 onwind-2025`.

    ### Subsequent horizons — `add_brownfield`

    Source: `scripts/add_brownfield.py` → function `add_brownfield(n, n_p, year, ...)`

    Key logic (simplified):

    ```python
    # Fix transmission at the previously optimised level
    n.lines.s_nom_min = n_p.lines.s_nom_opt

    for c in n_p.components[["Link", "Generator", "Store"]]:

        # Drop trackers (CO2, global EU) — already rebuilt from scratch in n
        n_p.remove(c.name, c.static.index[c.static.lifetime == np.inf])

        # Retire assets past end-of-life: build_year + lifetime <= current year
        n_p.remove(c.name, c.static.index[
            c.static.build_year + c.static.lifetime <= year
        ])

        # Drop negligible-capacity assets (below threshold)
        n_p.remove(c.name, c.static.index[
            c.static[f"{attr}_nom_extendable"]
            & (c.static[f"{attr}_nom_opt"] < capacity_threshold)
        ])

        # Fix remaining assets at their optimised capacity
        c.static[f"{attr}_nom"] = c.static[f"{attr}_nom_opt"]
        c.static[f"{attr}_nom_extendable"] = False

        # Inject into the new greenfield network
        n.add(c.name, c.static.index, **c.static)
    ```

    ### Attributes that drive brownfield logic

    | Attribute | Role |
    |---|---|
    | `build_year` | Identifies which planning horizon built this asset |
    | `lifetime` | `build_year + lifetime <= year` → asset is retired |
    | `p_nom_opt` / `e_nom_opt` | Copied to `p_nom` / `e_nom` → locked capacity in next horizon |
    | `p_nom_extendable` | Set to `False` for all carried-over assets |
    | `p_nom` | Now equals `p_nom_opt` from the previous solve — the hard lower bound |

    The result: the 2050 network contains **multiple rows per carrier per node**, one for each
    build year that is still within its operational lifetime.
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ---

    ## 4. Inspecting the `Network` objects

    Change the planning_horizon year from 2025 (base year) to a subsequent myopic year to view brownfields `p_nom > 0` for the base year and brownfield `p_nom = 0` for myopic years.
    """)
    return


@app.cell
def _(mo):
    import pandas as pd
    import pypsa

    year_select = mo.ui.dropdown(
        [2025, 2030, 2040, 2050], 2025, label="planning_horizon"
    )
    year_select
    return pd, pypsa, year_select


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### Multiple vintages — `carrier="onwind"`, location `FR`

    In the 2050 network each node carries **one row per surviving build year**.
    Here we filter for onwind generators whose bus starts with `FR`:
    """)
    return


@app.cell
def _():
    carriers = ["solar", "solar rooftop"]
    cc = "FR"

    show_cols = ["p_nom", "p_nom_opt", "build_year", "lifetime", "p_nom_extendable"]
    query = "carrier in @carriers and bus.str.startswith(@cc)"
    return carriers, cc, query, show_cols


@app.cell
def _(brownfield, query, show_cols):
    brownfield.generators.query(query).filter(show_cols).sort_index()
    return


@app.cell
def _(final, query, show_cols):
    final.generators.query(query).filter(show_cols).sort_index()
    return


@app.cell
def _(query, show_cols, solved):
    solved.generators.query(query).filter(show_cols).sort_index()
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    | Column | Meaning |
    |---|---|
    | `build_year` | Planning horizon in which this capacity was optimised |
    | `p_nom` | Fixed installed capacity [MW] (= `p_nom_opt` from that earlier solve) |
    | `p_nom_opt` | Capacity found in the **2050** solve |
    | `p_nom_extendable` | `False` for brownfield vintages; `True` for the new 2050 greenfield asset |

    Three rows, three build years — the 2025 and 2040 vintages are locked, only the 2050 row is free to expand.
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    The 2030 vintage has `2030 + 30 = 2060 > 2050`, so it should still be alive.
    It was simply not built in the 2030 solve — the optimiser chose not to invest there.
    Only build years with `p_nom_opt > threshold` survive into the next horizon.
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ---

    ## 5. File Sizes and Why They Don't Bloat

    TL;DR - network file sizes do not grow because
    1. assets drop out during `add_brownfield()`
    2. time series are highly correlated and compress well
    """)
    return


@app.cell
def _(pd):
    import os

    import pypsa as _pypsa

    base = "results/v2025.04/AT_KN2040/networks"
    years = [2025, 2030, 2040, 2050]

    rows = {}
    for yr in years:
        path = f"{base}/base_s_adm__none_{yr}.nc"
        n = _pypsa.Network(path)

        disk_mb = os.path.getsize(path) / 1e6
        static_mb = (
            sum(
                getattr(n, n.components[c]["list_name"]).memory_usage(deep=True).sum()
                for c in n.all_components
            )
            / 1e6
        )
        dynamic_mb = (
            sum(
                df.memory_usage(deep=True).sum()
                for c in n.all_components
                for df in getattr(n, n.components[c]["list_name"] + "_t").values()
            )
            / 1e6
        )

        rows[yr] = {
            "disk_MB": round(disk_mb, 1),
            "memory_MB": round(static_mb + dynamic_mb, 1),
        }

    df_sizes = pd.DataFrame.from_dict(rows, orient="index").rename_axis("year")
    df_sizes["ratio"] = (df_sizes["memory_MB"] / df_sizes["disk_MB"]).round(1)
    df_sizes
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### Why the files stay flat

    PyPSA exports networks with **zlib compression (level 4) + byte shuffling** for every
    time-series variable (dispatch, capacity factors, state-of-charge …). Scalar attributes
    (`p_nom`, `build_year`, …) take negligible space.

    The time-series arrays dominate file size — and they don't grow between horizons:

    - Each solved network covers the **same time resolution** (e.g. 3-hourly, one representative year).
    - Brownfield vintages add new rows to component tables (a few KB each), but their
      **dispatch time-series has the same fixed length** as any other asset.
    - Old assets retire, new ones enter — the total count of active components stays roughly constant.

    ```
    Dominant driver:  time-series length × number of active components
      time-series length  = constant (same snapshots every horizon)
      brownfield metadata = tiny compared to compressed time-series payload
      zlib + shuffle      = ~3–6× compression ratio on floating-point series
    ```

    The flat ~28–31 MB across all four horizons is therefore expected and intentional.
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### How statistics handle duplicated assets
    """)
    return


@app.cell
def _(brownfield, carriers, cc, filter_by):
    groups = ["name", "location", "carrier"]
    groups.remove("name")

    brownfield.statistics.optimal_capacity(
        groupby=groups,
        carrier=carriers,
        aggregate_across_components=True,
    ).pipe(filter_by, location=cc)
    return (groups,)


@app.cell
def _(carriers, cc, filter_by, groups, solved):
    solved.statistics.optimal_capacity(
        groupby=groups,
        carrier=carriers,
        aggregate_across_components=True,
    ).pipe(filter_by, location=cc)
    return


@app.cell
def _():
    import sys

    import marimo as mo

    sys.path.insert(0, ".")

    from evals.utils import filter_by

    return filter_by, mo


@app.cell
def _():
    return


@app.cell
def _(pypsa, year_select):
    year = year_select.value
    brownfield = pypsa.Network(
        f"resources/v2025.04/AT_KN2040/networks/base_s_adm__none_{year}_brownfield.nc"
    )
    final = pypsa.Network(
        f"resources/v2025.04/AT_KN2040/networks/base_s_adm__none_{year}_final.nc"
    )
    solved = pypsa.Network(
        f"results/v2025.04/AT_KN2040/networks/base_s_adm__none_{year}.nc"
    )
    return brownfield, final, solved


if __name__ == "__main__":
    app.run()
