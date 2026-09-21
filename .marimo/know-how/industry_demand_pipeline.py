import marimo

__generated_with = "0.24.0"
app = marimo.App(width="medium", auto_download=["html"])


@app.cell(hide_code=True)
def _():
    import importlib
    import json
    import sys
    from pathlib import Path

    import marimo as mo
    import numpy as np
    import pandas as pd
    import plotly.graph_objects as go
    import tomllib
    import yaml

    def _find_project_root() -> Path:
        candidates = [Path.cwd()]
        try:
            candidates.append(Path(__file__).resolve().parent)
        except NameError:
            pass
        for start in candidates:
            for p in [start, *start.parents]:
                if (p / "Snakefile").exists() and (p / "mods").is_dir():
                    return p
        raise FileNotFoundError("PyPSA-AT project root (Snakefile + mods/) not found")

    PROJECT_ROOT = _find_project_root()
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    return PROJECT_ROOT, Path, go, importlib, json, mo, np, pd, tomllib, yaml


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    # Know-how: the industry demand pipeline in PyPSA-AT

    This notebook explains, step by step, how the **exogenous industry energy demand** of
    PyPSA-AT comes into being: which data sources are used, how they are transformed,
    scaled and regionalised, how they end up as *Loads* per energy carrier in the model,
    and which of those Loads carry a sub-annual time profile.

    It is written for energy-system experts who do not program. Every code cell is
    preceded by a plain-language explanation; the code is shown for **provenance**
    (so you can see exactly where a number comes from), not for you to write.
    All numbers in the text are computed from the loaded data, so the text stays true
    if you point the notebook at another run (see the parameter cell below).

    The notebook follows the documentation page
    [Explanations → Data Flows → Industrial Demand](https://pypsa-at.readthedocs.io/en/latest/explanations/data-flows/industrial-demand/)
    (`docs-at/explanations/data-flows/industrial-demand.md`) and uses the diagram
    convention of [Data Flow Diagrams](https://pypsa-at.readthedocs.io/en/latest/explanations/data-flows/)
    (`docs-at/explanations/data-flows/index.md`).
    Everything described here was verified against the code at the time of writing
    (2026-09-17); each step ends with a *"Where in the code"* pointer.
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Glossary

    | Term | Meaning in this notebook |
    |------|--------------------------|
    | **Final energy** | Energy delivered to the consumer's door: electricity, gas, oil products, biomass, district heat. This is what statistics (Eurostat, NEA) count. |
    | **Useful energy** | The energy service after the last conversion at the consumer: process heat, motion, light. In PyPSA-AT the Load *low-temperature heat for industry* is a useful-energy demand that heat technologies (boilers, heat pumps, district heat) have to supply. All other industry Loads are final-energy demands. |
    | **Load** | A PyPSA component that withdraws power from a bus in every snapshot. It has a name (e.g. `AT312 industry electricity`), a bus, a carrier and a power set-point `p_set` in MW. |
    | **Carrier** | The label of an energy form or technology. Loads, buses and links carry one. Industry Loads use carriers such as `industry electricity` or `gas for industry`. |
    | **Bus** | A node in the network where supply and demand of one carrier are balanced. A model region has many buses: an electricity bus, a gas bus, an `H2 for industry` bus, ... |
    | **Model region / node** | The spatial unit of the model. Austria is resolved into NUTS3 regions (`AT111`, ..., `AT341`); other countries are one node each. |
    | **Snapshot** | One time step of the optimisation. The main run uses a 3-hourly resolution of the weather year 2013, i.e. 2920 snapshots. |
    | **Snapshot weighting** | The number of hours one snapshot represents (3 for a 3-hourly run). Annual energy = Σ `p_set` × weighting. |
    | **Flat (static) load** | A Load whose `p_set` is one number: the same MW in every snapshot. Stored in `n.loads.p_set`. |
    | **Profiled (dynamic) load** | A Load with a time series `p_set` that differs per snapshot. Stored in `n.loads_t.p_set`. |
    | **Exogenous demand** | Demand fixed *before* the optimisation from statistics and scenario assumptions (all industry Loads in this notebook). |
    | **Endogenous demand** | Demand the optimiser decides itself, e.g. electricity for electrolysers or heat pumps. Not covered here. |
    | **Distribution key** | A share per model region (summing to 1 per country) used to split a national quantity across regions. |
    | **JRC-IDEES** | The EU Joint Research Centre's *Integrated Database of the European Energy System*: physical production and energy use per industrial subsector and country. |
    | **NEA** | *Nutzenergieanalyse* of Statistik Austria: final energy per Bundesland, economic sector, energy carrier and useful-energy category. |
    | **FfE** | *Forschungsstelle für Energiewirtschaft* (Munich): publishes normalised hourly industrial electricity load profiles for Germany. |
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## The data flow at a glance

    The diagram below reproduces the structure of the documentation page (the docs use
    richer HTML labels; the node names, colours and arrows are the same). Grey pills are
    raw sources, blue boxes plain transformations, amber boxes steps with scenario
    parameters, violet nodes are Austria-specific, and the green pill is the final result
    used by the optimiser.
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.mermaid(r"""
    flowchart TD
        classDef source fill:#f8fafc,stroke:#cbd5e1,stroke-width:1px,color:#1e293b,rx:10,ry:10
        classDef step fill:#f0f9ff,stroke:#7dd3fc,stroke-width:1px,color:#0c4a6e,rx:10,ry:10
        classDef aggstep fill:#fffbeb,stroke:#fcd34d,stroke-width:1px,color:#78350f,rx:10,ry:10
        classDef final fill:#ecfdf5,stroke:#6ee7b7,stroke-width:1.5px,color:#064e3b,rx:10,ry:10
        classDef at fill:#fdf2f8,stroke:#f9a8d4,stroke-width:1.5px,color:#831843,rx:10,ry:10

        subgraph retrieve["Retrieve"]
            INDUSTRYDATA(["<b>JRC-IDEES / Eurostat / ammonia</b><br/>production and energy-balance inputs<br/><i>country · annual · reference year</i><br/>retrieve_jrc_idees"]):::source
            SITES(["<b>Industrial sites and population</b><br/>Hotmaps, GEM, refineries, ammonia plants<br/><i>site/node · static</i><br/>retrieve_hotmaps_industrial_sites"]):::source
            NEA(["<b>Statistik Austria NEA</b><br/>one ODS workbook per Bundesland<br/><i>Bundesland · annual · TJ</i><br/>retrieve_nea_at"]):::at
            FFE(["<b>FfE industry profiles</b><br/>normalized electricity load shapes<br/><i>sector · hourly · reference year 2017</i><br/>retrieve_ffe_industry_load_profiles"]):::at
        end

        subgraph build["Build Sector"]
            PROD["<b>Production per country and target year</b><br/>= historical production + scenario projections<br/><i>country · annual · kt/a</i><br/>build_industrial_production_per_country(_tomorrow).py"]:::aggstep
            KEY["<b>Industrial distribution keys</b><br/>= site/plant activity, population fallback<br/><i>node · static shares</i><br/>build_industrial_distribution_key.py"]:::aggstep
            NODEPROD["<b>Production per model region</b><br/>= country production × sector key<br/><i>node · annual · kt/a</i><br/>build_industrial_production_per_node.py"]:::step
            RATIOS["<b>Sector/carrier ratios</b><br/>= energy use per unit of production<br/><i>country · static ratios · MWh/t</i><br/>build_industry_sector_ratios(_intermediate).py"]:::aggstep
            NODEDEM["<b>Energy demand per model region</b><br/>= production × sector/carrier ratios<br/><i>node · annual · TWh/a by carrier</i><br/>build_industrial_energy_demand_per_node.py"]:::step
            NEATABLE["<b>Prepared NEA data</b><br/>= clean ODS, reshape, convert TJ → TWh<br/><i>NUTS2 · annual · sector/carrier</i><br/>build_nea_at.py"]:::at
            NEAREG["<b>Regional NEA demand overrides</b><br/>= Bundesland totals × regional keys<br/><i>AT model region · annual · TWh/a</i><br/>build_nea_industry_demand.py"]:::at
            FFEBUILD["<b>Nodal FfE electricity profiles</b><br/>= subsector mix × normalized FfE shapes<br/><i>AT node · hourly · normalized</i><br/>build_industrial_demand_profiles.py"]:::at
            LOADS["<b>Initial industry Loads</b><br/>= annual demand divided into flat power<br/><i>node/carrier · static · MW</i><br/>prepare_sector_network.py (add_industry)"]:::step
        end

        subgraph prepare["Prepare Sector Network (AT)"]
            OVERRIDE["<b>Apply annual regional overrides</b><br/>= map carriers and replace target-year totals<br/><i>AT region/carrier · annual · TWh/a</i><br/>mods/demand/annual.py"]:::at
            PROFILE["<b>Apply FfE electricity profiles</b><br/>= scale Loads while preserving annual energy<br/><i>AT node · hourly · industry electricity</i><br/>mods/demand/industrial_demand.py"]:::at
        end

        subgraph solve["Solve"]
            FINAL(["<b>Final industrial demand</b><br/>solved sector-coupled network<br/><i>node/carrier · hourly or flat · MW</i>"]):::final
        end

        INDUSTRYDATA --> PROD
        INDUSTRYDATA --> RATIOS
        SITES --> KEY
        PROD --> NODEPROD
        KEY --> NODEPROD
        RATIOS --> NODEDEM
        NODEPROD --> NODEDEM
        NEA --> NEATABLE
        NEATABLE --> NEAREG
        KEY --> NEAREG
        NODEDEM --> LOADS
        LOADS --> OVERRIDE
        NEAREG --> OVERRIDE
        NODEPROD --> FFEBUILD
        RATIOS --> FFEBUILD
        FFE --> FFEBUILD
        FFEBUILD --> PROFILE
        OVERRIDE --> PROFILE
        PROFILE --> FINAL
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Step overview

    | Section | What happens | Diagram node(s) | Resolution of the result |
    |---|---|---|---|
    | 1 | Load the solved networks and the intermediate files, state their provenance | FINAL | — |
    | 2 | Data sources: provider, content, version, retrieve rule | INDUSTRYDATA, SITES, NEA, FFE | source-specific |
    | 3 | Upstream PyPSA-Eur chain: production today → tomorrow → sector ratios → distribution keys → production per region → energy demand per region | PROD, RATIOS, KEY, NODEPROD, NODEDEM | node · annual · TWh/a |
    | 4 | PyPSA-DE layer: which steps touch Austria, why `-modified` files exist | PROD | country · annual |
    | 5 | Load creation in `add_industry`: carriers, buses, links, base-load interaction | LOADS | node/carrier · flat MW |
    | 6 | Austrian NEA annual overrides for 2025 | NEATABLE, NEAREG, OVERRIDE | AT region · annual |
    | 7 | Temporal profiles: which Loads are flat, which are profiled, and the FfE pipeline | FFEBUILD, PROFILE | AT node · 3-hourly |
    | 8 | Upstream PR PyPSA/pypsa-eur#1875 and how PyPSA-AT differs | FFEBUILD | — |
    | 9 | Final energy demand by carrier in the solved networks and in `evals` | FINAL | AT / region · annual |
    | 10 | Configuration keys, switches and rebuild commands | — | — |
    | 11 | Limitations, open questions, discrepancies found | — | — |
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ---
    ## 1 · Parameters and data loading

    **All paths live in this one cell.** Point `NETWORK_DIR` at another results folder
    to re-run the notebook on other networks. `RUN_RESOURCES` is the scenario-aware
    `resources/{prefix}/{run}` folder of the *current* configuration (the intermediate
    CSVs were rebuilt there with Snakemake, see section 10); `FALLBACK_RESOURCES` is an
    older copy from a 365-hourly run of the hydro branch that is used only if a file is
    missing in `RUN_RESOURCES`. Every table built from a fallback file is labelled with
    its provenance.
    """)
    return


@app.cell(hide_code=True)
def _(PROJECT_ROOT):
    # ---- solved networks (primary source for every result-based section) ----
    NETWORK_DIR = "/mnt/storage/networks/3h-main"
    NETWORK_PATTERN = "base_s_adm__none_{year}.nc"
    YEARS = [2025, 2030, 2040, 2050]

    # ---- intermediate resources -------------------------------------------------
    SHARED_RESOURCES = PROJECT_ROOT / "resources"  # shared between runs
    RUN_RESOURCES = (
        PROJECT_ROOT / "resources/test-wind-at35/AT_KN2040"
    )  # current config
    FALLBACK_RESOURCES = PROJECT_ROOT / "resources/hydro-capacities-update/AT_KN2040"

    # ---- raw inputs -------------------------------------------------------------
    DATA_DIR = PROJECT_ROOT / "data"
    NEA_RAW_DIR = DATA_DIR / "nea-at/primary/latest"
    FFE_JSON = (
        DATA_DIR
        / "ffe_industry_load_profiles/primary/unknown/ffe_industry_load_profiles.json"
    )
    VERSIONS_CSV = DATA_DIR / "versions.csv"

    # ---- configuration stack (last wins) ----------------------------------------
    CONFIG_FILES = {
        "config.default.yaml": PROJECT_ROOT / "config/config.default.yaml",
        "config.de.yaml": PROJECT_ROOT / "config/config.de.yaml",
        "config.at.yaml": PROJECT_ROOT / "config/config.at.yaml",
    }
    PLOTTING_FILES = [
        PROJECT_ROOT / "config/plotting.default.yaml",
        PROJECT_ROOT / "config/plotting.at.yaml",
    ]
    EVALS_CONFIG = PROJECT_ROOT / "evals/config.default.toml"

    # ---- presentation -----------------------------------------------------------
    WEEK_START = "2013-03-04"  # a Monday of the weather year, used for weekly plots
    return (
        CONFIG_FILES,
        DATA_DIR,
        EVALS_CONFIG,
        FALLBACK_RESOURCES,
        FFE_JSON,
        NEA_RAW_DIR,
        NETWORK_DIR,
        NETWORK_PATTERN,
        PLOTTING_FILES,
        RUN_RESOURCES,
        SHARED_RESOURCES,
        VERSIONS_CSV,
        WEEK_START,
        YEARS,
    )


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### 1.4 Colours and interactive selectors

    Carrier colours are taken from `config/plotting.default.yaml` and overlaid with
    `config/plotting.at.yaml` (`plotting.tech_colors`), so charts use the same colours as
    the evaluation plots. The dropdowns select the planning horizon and the Austrian
    model region used in the region-specific charts further down. The default region is
    the one with the largest industry electricity demand in the first year.
    """)
    return


@app.cell(hide_code=True)
def _(PLOTTING_FILES, YEARS, mo, slices, yaml):
    tech_colors = {}
    for _p in PLOTTING_FILES:
        with open(_p) as _f:
            tech_colors.update(
                yaml.safe_load(_f).get("plotting", {}).get("tech_colors", {})
            )

    def color(carrier: str) -> str:
        return tech_colors.get(carrier, "#999999")

    _ind = slices[YEARS[0]]["industry"]
    AT_REGIONS = sorted(_ind.region[_ind.region.str.startswith("AT")].unique())
    _elec = _ind[_ind.carrier.eq("industry electricity") & _ind.region.isin(AT_REGIONS)]
    _default_region = _elec.groupby("region").annual_MWh.sum().idxmax()

    sel_year = mo.ui.dropdown(
        options=[str(y) for y in YEARS], value=str(YEARS[0]), label="Planning horizon"
    )
    sel_region = mo.ui.dropdown(
        options=AT_REGIONS, value=_default_region, label="Austrian model region"
    )
    mo.hstack([sel_year, sel_region], justify="start", gap=2)
    return AT_REGIONS, color, sel_region, sel_year


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ---
    ## 2 · Data sources

    Every external dataset is pinned in `data/versions.csv` (columns `dataset, version,
    source, tags, added, note, url`) and resolved by the retrieve rules through
    `dataset_version()` from `rules/common.smk`. The table lists the rows relevant to
    industry demand and whether the raw files are present in `data/` on this machine.
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### 2.1 Source by source

    | Source | Provider · content | Resolution | Retrieve rule | Used in |
    |---|---|---|---|---|
    | **JRC-IDEES** | EU Joint Research Centre. Physical production (kt/a) and energy use per industrial subsector, country and year 2000–2023 (version `2023-v1`). | country · annual | `retrieve_jrc_idees` (`rules/retrieve.smk`) | production today, energy demand today, sector ratios |
    | **Eurostat energy balances** | Eurostat `nrg_bal_c`. Final energy consumption of industry per country; also the coke-oven transformation output that is added to today's demand. Used to scale non-EU27 countries (Balkans, Norway, ...) relative to the EU27 average. | country · annual · TJ | `retrieve_eurostat_balances` | production today (non-EU27), coke ovens |
    | **Ammonia production** | USGS nitrogen statistics (`nitrogen_statistics`, `build_ammonia_production.py`) — ammonia production per country in kt/a, 2018–2022. | country · annual · kt/a | `retrieve_nitrogen_statistics` | production today (splits basic chemicals into ammonia / HVC / chlorine / methanol) |
    | **Industrial sites** | Hotmaps industrial database (site coordinates, subsector, emissions), Global Energy Monitor steel plant tracker (`gem_gspt`) and cement tracker (`gem_gcct`), `data/ammonia_plants.csv`, `data/refineries-noneu.csv`. | site · static | `retrieve_hotmaps_industrial_sites`, `retrieve_gem_steel_plant_tracker`, `retrieve_gem_cement_concrete_tracker` | distribution keys |
    | **Population** | Eurostat NUTS3 population (`nuts3_population`) via the clustered population layout. | node · static | `retrieve_nuts3_population` | population fallback key, base-load split |
    | **Statistik Austria NEA** | *Nutzenergieanalyse*: one ODS workbook per Bundesland, one sheet per year (2005–2024); energy carrier × useful-energy category per economic sector, in TJ. | Bundesland · annual · TJ | `retrieve_nea_at` (`rules/pypsa-at/retrieve.smk`) | AT annual overrides (section 6) |
    | **FfE load profiles** | FfE Open Data API dataset `id_opendata=59` "Normed Industrial Electrical Load Profile (Germany)": normalised hourly electricity profiles per industry branch for 2017, no space heating. | branch · hourly · 2017 | `retrieve_ffe_industry_load_profiles` (`rules/pypsa-at/retrieve.smk`) | temporal profiles (section 7) |
    | **Ariadne / FORECAST + UBA** | Ariadne scenario database (`ariadne_database`, model `FORECAST v1.0`, scenario `KN2045_Mix`) with German production projections, and the UBA *Projektionsbericht 2025* MWMS scenario (`data/pypsa-de/UBA_Projektionsbericht2025_Abbildung31_MWMS.csv`). | Germany · annual | `retrieve_ariadne_database` (`rules/pypsa-de/retrieve.smk`) | PyPSA-DE layer (section 4), Germany only |

    **Key takeaway:** the Austrian numbers come from two independent statistical worlds —
    JRC-IDEES (EU-wide, subsector production × specific energy use) for every horizon, and
    NEA (Austrian final-energy statistics) that overrides the 2025 totals. The FfE profiles
    are German measurements that only shape the *time pattern*, not the annual amount.
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ---
    ## 3 · The upstream PyPSA-Eur chain

    ### 3.1 Production today per country

    `build_industrial_production_per_country.py` reads the physical output of every
    JRC-IDEES subsector (kt/a; for some subsectors an index or "kt ethylene equivalent")
    for the configured reference year (`industry.reference_year`). Basic chemicals are
    then split into ammonia (from the USGS statistics), HVC, chlorine and methanol using
    the EU-wide `HVC_production_today`, `chlorine_production_today` and
    `methanol_production_today` totals distributed proportionally to non-ammonia basic
    chemicals. Non-EU27 countries are scaled from the EU27 aggregate with their Eurostat
    energy consumption ratio. The chart shows the Austrian row.

    *Where in the code:* `scripts/build_industrial_production_per_country.py`
    (`industry_production_per_country`, `separate_basic_chemicals`), rule
    `build_industrial_production_per_country` in `rules/build_sector.smk`. Docs node
    *Production per country and target year*.
    """)
    return


@app.cell(hide_code=True)
def _(cfg, go, mo, pd, resource_path):
    _path, _label = resource_path("industrial_production_per_country.csv")
    production_today = pd.read_csv(_path, index_col=0)
    production_today_at = production_today.loc["AT"].sort_values(ascending=False)
    _fig = go.Figure(
        go.Bar(
            x=production_today_at.index,
            y=production_today_at.values,
            marker_color="#5b9bd5",
        )
    )
    _fig.update_layout(
        title=f"Austria: industrial production today (JRC-IDEES reference year {cfg['industry']['reference_year']}) — {_label}",
        yaxis_title="production [kt/a or kt-equivalent/a]",
        xaxis_title="JRC-IDEES subsector",
        height=450,
        margin=dict(b=160),
    )
    mo.vstack(
        [
            mo.md(
                f"**Key takeaway:** Austria's largest JRC subsectors by physical output are "
                f"*{production_today_at.index[0]}* ({production_today_at.iloc[0]:,.0f} kt/a) and "
                f"*{production_today_at.index[1]}* ({production_today_at.iloc[1]:,.0f} kt/a); "
                f"'Other industrial sectors' is an index, not tonnes."
            ),
            _fig,
        ]
    )
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### 3.2 Production tomorrow: exogenous route fractions

    `build_industrial_production_per_country_tomorrow.py` keeps the total tonnage of each
    material constant but shifts it between production routes according to
    year-dependent fractions from the `industry:` config section:

    - **Steel:** `St_primary_fraction` = share of steel from primary (ore-based) routes;
      `DRI_fraction` = share of that primary steel produced via direct reduction with
      hydrogen (DRI + electric arc) instead of blast furnaces (integrated steelworks).
      The rest is secondary steel in electric arc furnaces.
    - **Aluminium:** `Al_primary_fraction` = share of primary smelting.
    - **HVC (plastics feedstock):** `HVC_primary_fraction`, `HVC_mechanical_recycling_fraction`,
      `HVC_chemical_recycling_fraction`.

    PyPSA-AT overrides the steel fractions with the PyPSA-DE *KN2045_Mix* values in
    `config/config.at.yaml`; the aluminium and HVC fractions come from
    `config/config.default.yaml` (and `config.de.yaml` for HVC). The table shows the values
    the run used and, for comparison, the PyPSA-Eur defaults.

    *Where in the code:* `scripts/build_industrial_production_per_country_tomorrow.py`,
    config keys `industry.St_primary_fraction`, `industry.DRI_fraction`,
    `industry.Al_primary_fraction`, `industry.HVC_*_fraction`.
    """)
    return


@app.cell(hide_code=True)
def _(YEARS, cfg, cfg_year, config_files, pd):
    _keys = [
        "St_primary_fraction",
        "DRI_fraction",
        "Al_primary_fraction",
        "HVC_primary_fraction",
        "HVC_mechanical_recycling_fraction",
        "HVC_chemical_recycling_fraction",
        "sector_ratios_fraction_future",
    ]
    _rows = []
    for _k in _keys:
        _run = cfg["industry"][_k]
        _default = config_files["config.default.yaml"]["industry"][_k]
        _defined_in = [
            name for name, c in config_files.items() if _k in c.get("industry", {})
        ][-1]
        for _y in YEARS:
            _rows.append(
                {
                    "parameter": _k,
                    "year": _y,
                    "run value": cfg_year(_run, _y),
                    "PyPSA-Eur default": cfg_year(_default, _y),
                    "last defined in": _defined_in,
                }
            )
    route_fractions = pd.DataFrame(_rows).pivot(
        index="parameter", columns="year", values="run value"
    )
    route_fractions["last defined in"] = (
        pd.DataFrame(_rows).groupby("parameter")["last defined in"].first()
    )
    route_fractions_default = pd.DataFrame(_rows).pivot(
        index="parameter", columns="year", values="PyPSA-Eur default"
    )
    route_fractions.rename(columns=str)
    return (route_fractions_default,)


@app.cell(hide_code=True)
def _(mo, route_fractions_default):
    mo.vstack(
        [
            mo.md("For comparison, the PyPSA-Eur defaults (`config.default.yaml`):"),
            route_fractions_default.rename(columns=str),
        ]
    )
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    The chart applies these fractions to Austria's steel: it shows the three routes per
    horizon from the `industrial_production_per_country_tomorrow_{year}-modified.csv`
    files (the `-modified` suffix is explained in section 4; for Austria the file is
    identical to the unmodified one).

    **Watch the electric-arc bar.** The script computes the persistent primary share with
    *EU-wide* sums (`st_primary_fraction * total_steel.sum() / int_steel` where both sums
    run over all countries) and applies that ratio to each country's integrated-steelworks
    tonnage. A country whose primary share is far above the EU average — Austria's
    integrated steelworks make up most of its steel — can end up with more primary steel
    than total steel, and the electric-arc remainder becomes **negative**. The numbers
    below are computed from the file, see section 11 for the consequences.
    """)
    return


@app.cell(hide_code=True)
def _(YEARS, go, mo, pd, resource_path):
    _routes = ["Integrated steelworks", "DRI + Electric arc", "Electric arc"]
    _rows = {}
    _labels = set()
    for _y in YEARS:
        _p, _l = resource_path(
            f"industrial_production_per_country_tomorrow_{_y}-modified.csv"
        )
        _labels.add(_l)
        _rows[_y] = pd.read_csv(_p, index_col=0).loc["AT", _routes]
    steel_routes_at = pd.DataFrame(_rows).T
    steel_routes_at.index.name = "year"
    _fig = go.Figure()
    _colors = {
        "Integrated steelworks": "#545454",
        "DRI + Electric arc": "#bf13a0",
        "Electric arc": "#2d2a66",
    }
    for _r in _routes:
        _fig.add_bar(
            name=_r,
            x=[str(y) for y in YEARS],
            y=steel_routes_at[_r],
            marker_color=_colors[_r],
        )
    _fig.update_layout(
        barmode="relative",
        title=f"Austria: steel production by route — {', '.join(sorted(_labels))}",
        yaxis_title="production [kt/a]",
        xaxis_title="planning horizon",
        height=420,
    )
    _neg = steel_routes_at["Electric arc"][steel_routes_at["Electric arc"] < 0]
    mo.vstack(
        [
            mo.md(
                f"**Key takeaway:** total Austrian steel stays at {steel_routes_at.sum(axis=1).iloc[0]:,.0f} kt/a "
                f"in every horizon, but the route split follows the config fractions. "
                + (
                    f"Electric-arc production is **negative** in {', '.join(str(i) for i in _neg.index)} "
                    f"(down to {_neg.min():,.0f} kt/a), which reduces the computed electricity demand — "
                    f"a data artefact of the EU-wide scaling, not a scenario statement."
                    if not _neg.empty
                    else "No negative route values occur."
                )
            ),
            steel_routes_at.round(1),
            _fig,
        ]
    )
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### 3.3 Sector ratios: energy per tonne, today and tomorrow

    Two files describe how much energy each subsector needs per tonne of product
    (MWh/t, per carrier):

    - `industry_sector_ratios.csv` — the **future best-in-class** technology (e.g. hydrogen
      DRI at 1.7 MWh H₂/t, electrified steam), built once from JRC-IDEES and the
      `industry:` assumptions in `build_industry_sector_ratios.py`. It has no country index.
    - `industry_sector_ratios_{year}.csv` — the **per-country interpolation** between today's
      average ratio (today's JRC energy demand ÷ today's production, per country) and the
      best-in-class ratio, weighted with `sector_ratios_fraction_future[year]`
      (5 % in 2025, 20 % in 2030, 70 % in 2040, 100 % in 2050 in this run):
      `ratio_year = today × (1 − f) + future × f`.

    Pick a subsector to see the Austrian ratios per carrier and horizon. The unit for
    "process emission" rows is tCO₂/t.

    *Where in the code:* `scripts/build_industry_sector_ratios.py`,
    `scripts/build_industry_sector_ratios_intermediate.py`, key
    `industry.sector_ratios_fraction_future`. Docs node *Sector/carrier ratios*.
    """)
    return


@app.cell(hide_code=True)
def _(YEARS, mo, pd, resource_path):
    _p, _l = resource_path("industry_sector_ratios.csv")
    sector_ratios_future = pd.read_csv(_p, index_col=0)
    sector_ratios_by_year = {}
    _labels = {_l}
    for _y in YEARS:
        _p, _l = resource_path(f"industry_sector_ratios_{_y}.csv")
        _labels.add(_l)
        sector_ratios_by_year[_y] = pd.read_csv(_p, header=[0, 1], index_col=0)
    sector_ratio_provenance = ", ".join(sorted(_labels))
    sel_subsector = mo.ui.dropdown(
        options=list(sector_ratios_future.columns),
        value="Integrated steelworks",
        label="JRC subsector",
    )
    sel_subsector
    return (
        sector_ratio_provenance,
        sector_ratios_by_year,
        sector_ratios_future,
        sel_subsector,
    )


@app.cell(hide_code=True)
def _(
    YEARS,
    cfg,
    cfg_year,
    go,
    mo,
    pd,
    sector_ratio_provenance,
    sector_ratios_by_year,
    sector_ratios_future,
    sel_subsector,
):
    _sub = sel_subsector.value
    _cols = {
        f"{y} (f={cfg_year(cfg['industry']['sector_ratios_fraction_future'], y):.2f})": sector_ratios_by_year[
            y
        ]["AT"][_sub]
        for y in YEARS
    }
    _cols["future best-in-class"] = sector_ratios_future[_sub]
    ratios_at = pd.DataFrame(_cols)
    ratios_at.index.name = "carrier [MWh/t, process emission: tCO2/t]"
    _fig = go.Figure()
    for _c in ratios_at.columns:
        _fig.add_bar(name=_c, x=ratios_at.index, y=ratios_at[_c])
    _fig.update_layout(
        barmode="group",
        title=f"Austria: specific energy use of '{_sub}' — {sector_ratio_provenance}",
        yaxis_title="MWh per tonne (tCO2/t for process emissions)",
        height=420,
    )
    mo.vstack(
        [
            mo.md(
                "**Key takeaway:** the ratios move from the Austrian average of today towards the "
                "EU best-in-class technology as `sector_ratios_fraction_future` grows; a carrier "
                "that is zero in the best-in-class column (e.g. coke for DRI steel) is phased out."
            ),
            ratios_at.round(3),
            _fig,
        ]
    )
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### 3.4 Distribution keys: from country to model region

    `build_industrial_distribution_key.py` builds, per country, one share column per
    industrial sector so that the column sums to 1 over the country's model regions:

    - **Hotmaps sites** give the keys for *Iron and steel, Cement, Refineries, Paper and
      printing, Chemical industry, Glass, Non-ferrous metals, Non-metallic mineral
      products, Other non-classified* (weighted by reported emissions, or by count).
    - **GEM trackers** refine steel into *EAF, DRI + EAF, Integrated steelworks* and cement.
    - **Ammonia plants** from `data/ammonia_plants.csv`.
    - **Population** is the fallback whenever a country has no site for a sector.

    `build_industrial_production_per_node.py` then maps every JRC subsector to one of
    these key columns (`sector_mapping`; subsectors not listed use *population*). The
    heat map shows the Austrian keys; the table summarises how many Austrian regions
    carry a site-based share and which sectors silently fell back to population.

    *Where in the code:* `scripts/build_industrial_distribution_key.py`
    (`build_nodal_distribution_key`), `scripts/build_industrial_production_per_node.py`
    (`sector_mapping`), rule `build_industrial_distribution_key`. Docs node
    *Industrial distribution keys*.
    """)
    return


@app.cell(hide_code=True)
def _(AT_REGIONS, go, importlib, mo, np, pd, resource_path):
    bipn = importlib.import_module("scripts.build_industrial_production_per_node")
    _p, keys_provenance = resource_path("industrial_distribution_key_base_s_adm.csv")
    distribution_keys = pd.read_csv(_p, index_col=0)
    keys_at = distribution_keys.loc[AT_REGIONS]

    _rows = []
    for _col in keys_at.columns:
        _same_as_pop = np.allclose(keys_at[_col], keys_at["population"])
        _rows.append(
            {
                "key column": _col,
                "AT regions with share > 0": int((keys_at[_col] > 0).sum()),
                "largest region": keys_at[_col].idxmax()
                if keys_at[_col].sum() > 0
                else "",
                "largest share": round(keys_at[_col].max(), 3),
                "identical to population (fallback)": _same_as_pop,
                "JRC subsectors mapped to it": ", ".join(
                    k for k, v in bipn.sector_mapping.items() if v == _col
                ),
            }
        )
    key_coverage = pd.DataFrame(_rows).set_index("key column")
    _fig = go.Figure(
        go.Heatmap(
            z=keys_at.T.values,
            x=keys_at.index,
            y=keys_at.columns,
            colorscale="Blues",
            zmin=0,
            zmax=max(0.3, float(keys_at.drop(columns="population").max().max())),
            colorbar_title="share of AT total",
        )
    )
    _fig.update_layout(
        title=f"Austrian distribution keys per sector — {keys_provenance}",
        height=520,
        xaxis_title="model region",
        yaxis_title="key column",
    )
    _fallback = [
        c
        for c in key_coverage.index[key_coverage["identical to population (fallback)"]]
        if c != "population"
    ]
    mo.vstack(
        [
            mo.md(
                f"**Key takeaway:** {len(key_coverage) - len(_fallback) - 1} of {len(key_coverage) - 1} industrial key columns are "
                f"site-based for Austria; the columns {', '.join(f'*{c}*' for c in _fallback)} equal the "
                f"population key, so the JRC subsectors mapped to them (and all subsectors without a "
                f"mapping, e.g. food, machinery, textiles, wood) are spread by population."
            ),
            key_coverage,
            _fig,
        ]
    )
    return distribution_keys, key_coverage, keys_provenance


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### 3.5 Production per model region

    Country production of the selected horizon × distribution key = production per model
    region, still in kt/a per JRC subsector. The stacked bar shows the Austrian regions
    for the selected planning horizon (only subsectors with a non-zero Austrian total).

    *Where in the code:* `scripts/build_industrial_production_per_node.py`
    (`build_nodal_industrial_production`), rule `build_industrial_production_per_node`.
    Docs node *Production per model region*.
    """)
    return


@app.cell(hide_code=True)
def _(AT_REGIONS, go, mo, pd, resource_path, year):
    _p, _l = resource_path(f"industrial_production_base_s_adm_{year}.csv")
    production_node = pd.read_csv(_p, index_col=0)
    production_node_at = production_node.loc[AT_REGIONS]
    production_node_at = production_node_at.loc[:, production_node_at.abs().sum() > 0]
    _fig = go.Figure()
    for _c in production_node_at.columns:
        _fig.add_bar(name=_c, x=production_node_at.index, y=production_node_at[_c])
    _fig.update_layout(
        barmode="relative",
        title=f"Austria {year}: industrial production per model region and subsector — {_l}",
        yaxis_title="production [kt/a]",
        xaxis_title="model region",
        height=520,
        legend=dict(font=dict(size=10)),
    )
    _top = production_node_at.sum(axis=1).sort_values(ascending=False)
    mo.vstack(
        [
            mo.md(
                f"**Key takeaway:** in {year} the regions with the largest tonnage are "
                f"{', '.join(f'{r} ({v:,.0f} kt/a)' for r, v in _top.head(3).items())}. Tonnage is not energy: "
                f"the next step weights it with the sector ratios."
            ),
            _fig,
        ]
    )
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### 3.6 Energy demand per model region and carrier

    `build_industrial_energy_demand_per_node.py` multiplies the regional production
    (kt/a → Mt/a) with the country's sector ratios (MWh/t) and sums over subsectors:
    the result is **TWh/a per region and carrier**. Three columns are *not* energy:

    - `process emission` — MtCO₂/a released by the process itself (cement calcination,
      ammonia, ...), independent of the fuel.
    - `process emission from feedstock` — MtCO₂/a from the carbon in the naphtha
      feedstock that is emitted in the steam cracker.
    - `current electricity` — today's industrial electricity demand of the region
      (from `industrial_energy_demand_today_base_s_adm.csv`), used in section 5 to
      remove industry from the measured electricity base load. It is the same in
      every horizon.

    The table shows the Austrian totals per carrier and horizon; the chart the energy
    carriers only.

    *Where in the code:* `scripts/build_industrial_energy_demand_per_node.py`,
    `scripts/build_industrial_energy_demand_per_node_today.py`,
    `scripts/build_industrial_energy_demand_per_country_today.py`
    (`add_coke_ovens`, `separate_basic_chemicals`). Docs node *Energy demand per model region*.
    """)
    return


@app.cell(hide_code=True)
def _(AT_REGIONS, YEARS, color, go, mo, pd, resource_path):
    jrc_demand_node = {}
    _labels = set()
    for _y in YEARS:
        _p, _l = resource_path(f"industrial_energy_demand_base_s_adm_{_y}.csv")
        _labels.add(_l)
        jrc_demand_node[_y] = pd.read_csv(_p, index_col=0)
    jrc_demand_provenance = ", ".join(sorted(_labels))
    jrc_demand_at = pd.DataFrame(
        {y: d.loc[AT_REGIONS].sum() for y, d in jrc_demand_node.items()}
    )
    jrc_demand_at.index.name = "carrier (TWh/a; process emission columns: MtCO2/a)"
    _energy = jrc_demand_at.drop(
        index=[
            "process emission",
            "process emission from feedstock",
            "current electricity",
        ]
    )
    _fig = go.Figure()
    for _c in _energy.index:
        _fig.add_bar(
            name=_c,
            x=[str(y) for y in YEARS],
            y=_energy.loc[_c],
            marker_color=color(_c),
        )
    _fig.update_layout(
        barmode="relative",
        title=f"Austria: JRC-based industrial energy demand per carrier — {jrc_demand_provenance}",
        yaxis_title="TWh/a",
        xaxis_title="planning horizon",
        height=450,
    )
    mo.vstack(
        [
            mo.md(
                f"**Key takeaway:** the JRC-based Austrian industry demand totals "
                f"{_energy[YEARS[0]].sum():.1f} TWh/a in {YEARS[0]} and {_energy[YEARS[-1]].sum():.1f} TWh/a in {YEARS[-1]}; "
                f"electricity grows from {jrc_demand_at.loc['electricity', YEARS[0]]:.1f} to "
                f"{jrc_demand_at.loc['electricity', YEARS[-1]]:.1f} TWh/a and hydrogen from "
                f"{jrc_demand_at.loc['hydrogen', YEARS[0]]:.2f} to {jrc_demand_at.loc['hydrogen', YEARS[-1]]:.1f} TWh/a "
                f"as the sector ratios move to best-in-class technology."
            ),
            jrc_demand_at.round(2).rename(columns=str),
            _fig,
        ]
    )
    return (jrc_demand_node,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ---
    ## 4 · The PyPSA-DE layer: what changes for Austria?

    PyPSA-AT inherits PyPSA-DE, which inserts two Germany-specific modifications into
    the chain. Both were checked in the code for their country filters:

    1. **`modify_industry_production`** (`rules/pypsa-de/modifications.smk`,
       `scripts/pypsa-de/modify_industry_production.py`): reads
       `industrial_production_per_country_tomorrow_{year}.csv`, overwrites **only the
       `DE` row** (`existing_industry.loc["DE", ...]`) with FORECAST projections from the
       Ariadne database (cement, ammonia, methanol, pulp & paper, non-metallic minerals,
       steel total) and writes `..._{year}-modified.csv`. The rule order
       `modify_industry_production > build_industrial_production_per_country_tomorrow`
       makes every downstream rule read the `-modified` file — that is why the file exists
       in an AT run although Austria's row is untouched. Config: `pypsa-de.leitmodelle.industry`
       (`FORECAST v1.0`) and `pypsa-de.reference_scenario` (`KN2045_Mix`).
    2. **`modify_prenetwork` → `modify_industry_demand`** (`scripts/pypsa-de/modify_prenetwork.py`):
       for the years in `pypsa-de.uba_for_industry.enable` it rescales the Loads
       `industry electricity`, `solid biomass for industry` and `low-temperature heat for
       industry` **whose bus starts with `DE`** to the UBA Projektionsbericht 2025 totals.
       Austrian Loads are not touched.

    The cell below proves point 1 numerically: it compares the unmodified and modified
    production files and lists the countries with any difference.
    """)
    return


@app.cell(hide_code=True)
def _(YEARS, cfg, mo, pd, resource_path):
    _rows = []
    de_changes = None
    for _y in YEARS:
        _p0, _l0 = resource_path(f"industrial_production_per_country_tomorrow_{_y}.csv")
        _p1, _l1 = resource_path(
            f"industrial_production_per_country_tomorrow_{_y}-modified.csv"
        )
        _a = pd.read_csv(_p0, index_col=0)
        _b = pd.read_csv(_p1, index_col=0)
        _diff = (_b - _a).abs()
        _changed = _diff.index[_diff.sum(axis=1) > 1e-6].tolist()
        _rows.append(
            {
                "year": _y,
                "countries changed by modify_industry_production": ", ".join(_changed)
                or "none",
                "AT max abs change [kt/a]": round(float(_diff.loc["AT"].max()), 6),
                "provenance": f"{_l0} / {_l1}",
            }
        )
        if _y == YEARS[0]:
            de_changes = pd.DataFrame(
                {"unmodified (JRC)": _a.loc["DE"], "modified (FORECAST)": _b.loc["DE"]}
            )
            de_changes = de_changes[
                (
                    de_changes["unmodified (JRC)"] - de_changes["modified (FORECAST)"]
                ).abs()
                > 1e-6
            ]
    modified_check = pd.DataFrame(_rows).set_index("year")
    mo.vstack(
        [
            mo.md(
                f"**Key takeaway:** the `-modified` files differ from the unmodified ones only for "
                f"**{', '.join(sorted({c for cell in modified_check.iloc[:, 0] for c in cell.split(', ')}))}**; the Austrian row is identical. "
                f"UBA rescaling of German Loads is active for the years "
                f"{cfg['pypsa-de']['uba_for_industry']['enable']} (`pypsa-de.uba_for_industry.enable`)."
            ),
            modified_check,
            mo.md(f"German subsectors rewritten by FORECAST in {YEARS[0]} (kt/a):"),
            de_changes.round(1),
        ]
    )
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    Point 2 can be seen in the solved networks themselves: for each horizon the table
    compares the annual energy of the three affected Load carriers in the networks with
    the JRC-based file, for Austria and Germany. For Germany the ratio deviates from 1
    for the rescaled carriers in the UBA years; for Austria in 2030+ it is exactly 1 (in
    2025 the NEA override of section 6 applies instead).
    """)
    return


@app.cell(hide_code=True)
def _(CARRIER_TO_LOAD, YEARS, jrc_demand_node, mo, pd, slices):
    _carriers = [
        "industry electricity",
        "solid biomass for industry",
        "low-temperature heat for industry",
    ]
    _inv = {v: k for k, v in CARRIER_TO_LOAD.items()}
    _rows = []
    for _y in YEARS:
        _ind = slices[_y]["industry"]
        for _ct in ("AT", "DE"):
            for _c in _carriers:
                _net = (
                    _ind[
                        _ind.carrier.eq(_c) & _ind.region.str.startswith(_ct)
                    ].annual_MWh.sum()
                    / 1e6
                )
                _jrc_df = jrc_demand_node[_y]
                _jrc = _jrc_df.loc[_jrc_df.index.str.startswith(_ct), _inv[_c]].sum()
                _rows.append(
                    {
                        "year": _y,
                        "country": _ct,
                        "load carrier": _c,
                        "network [TWh/a]": _net,
                        "JRC file [TWh/a]": _jrc,
                        "ratio network / JRC": _net / _jrc if _jrc else float("nan"),
                    }
                )
    de_vs_at = pd.DataFrame(_rows).set_index(["year", "country", "load carrier"])
    mo.vstack([de_vs_at.round(3)])
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ---
    ## 5 · How the Loads are created: `add_industry`

    `add_industry()` in `scripts/prepare_sector_network.py` reads
    `industrial_energy_demand_base_s_adm_{year}.csv`, converts TWh/a → MWh
    (× 10⁶, × `nyears`) and creates one Load per carrier and node with
    **`p_set = annual energy / nhours`** where `nhours` is the sum of the snapshot
    weightings (8760 for a full year). That is why every industry Load starts **flat**:
    the same MW in every snapshot. Profiles, if any, are added later by PyPSA-AT
    (section 7).

    The AT configuration keeps all industry demand regional:
    `sector.ammonia: regional`, `sector.methanol.regional_methanol_demand: true`,
    `sector.regional_oil_demand: true`, `sector.regional_coal_demand: true`,
    `sector.regional_gas_demand`/`gas_network: true`, `sector.biomass_spatial: true`,
    `sector.co2_spatial: true`. With the PyPSA-Eur defaults several of these would
    collapse into one EU-wide Load. The table lists every industry Load carrier found in
    the selected network, the bus carrier it sits on, how many Loads exist and whether
    any of them is EU-wide.

    *Where in the code:* `scripts/prepare_sector_network.py::add_industry`;
    spatial options in `config/config.at.yaml` under `sector:`. Docs node
    *Initial industry Loads*.
    """)
    return


@app.cell(hide_code=True)
def _(INDUSTRY_LOAD_CARRIERS, cfg, mo, pd, slices, year):
    _ind = slices[year]["industry"]
    _rows = []
    for _c in INDUSTRY_LOAD_CARRIERS:
        _g = _ind[_ind.carrier.eq(_c)]
        _at = _g[_g.region.str.startswith("AT")]
        _rows.append(
            {
                "load carrier": _c,
                "bus carrier(s)": ", ".join(sorted(_g.bus_carrier.unique())),
                "loads total": len(_g),
                "loads in AT": len(_at),
                "EU-wide loads": int(_g.index.str.startswith("EU").sum()),
                "AT loads with time series": int(_at.dynamic.sum()),
                "AT annual [TWh/a] (process emissions: MtCO2/a)": _at.annual_MWh.sum()
                / 1e6,
                "unit of p_set": "tCO2/h (negative = source)"
                if _c == "process emissions"
                else "MW",
            }
        )
    load_carrier_table = pd.DataFrame(_rows).set_index("load carrier")
    _spatial = cfg["sector"]
    mo.vstack(
        [
            mo.md(
                f"**Key takeaway ({year}):** {len(load_carrier_table)} industry Load carriers, all regional "
                f"({int(load_carrier_table['EU-wide loads'].sum())} EU-wide Loads). Run settings: "
                f"`sector.ammonia={_spatial['ammonia']!r}`, "
                f"`regional_methanol_demand={_spatial['methanol']['regional_methanol_demand']}`, "
                f"`regional_oil_demand={_spatial['regional_oil_demand']}`, "
                f"`regional_coal_demand={_spatial['regional_coal_demand']}`, "
                f"`gas_network={_spatial['gas_network']}`, `regional_gas_demand={_spatial.get('regional_gas_demand')}`, "
                f"`biomass_spatial={_spatial['biomass_spatial']}`, `co2_spatial={_spatial['co2_spatial']}`."
            ),
            load_carrier_table.round(3),
        ]
    )
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### 5.1 Bus and link topology behind each Load

    Most industry Loads do not sit directly on the region's main carrier bus. Instead
    `add_industry` creates a **dedicated demand bus** (e.g. `AT312 gas for industry`) and
    an extendable **Link** from the main bus into it. The link carries the CO₂ accounting:
    its `bus2` is `co2 atmosphere`, and a parallel `... CC` link with carbon capture sends
    part of the CO₂ to the `co2 stored` bus instead. Exceptions:

    - `industry electricity` is attached to the region's low-voltage electricity bus.
    - `low-temperature heat for industry` is attached to the `urban central heat` bus if
      the region has district heating, otherwise to `services urban decentral heat`.
    - `H2 for industry` is attached upstream to the plain `H2` bus; **PyPSA-AT** then adds
      a dedicated `H2 for industry` bus + link per node (`mods/network/h2.py::add_h2_for_industry_bus`)
      so that methane pyrolysis can deliver hydrogen directly to industry.
    - `process emissions` is a *negative* Load on the `process emissions` bus (it injects
      CO₂), with links to `co2 atmosphere` and a CC variant.

    The table shows every Load of the selected region together with the links that feed
    its bus (`bus0 → bus1`, plus the CO₂ side buses).
    """)
    return


@app.cell(hide_code=True)
def _(mo, pd, region, slices, year):
    _ind = slices[year]["industry"]
    _links = slices[year]["links"]
    _loads = _ind[_ind.region.eq(region)]
    _rows = []
    for _name, _l in _loads.iterrows():
        _feed = _links[_links.bus1.eq(_l.bus)]
        if _feed.empty:
            _feed = _links[_links.bus0.eq(_l.bus)]
        _rows.append(
            {
                "load": _name,
                "load carrier": _l.carrier,
                "bus": _l.bus,
                "bus carrier": _l.bus_carrier,
                "p_set static [MW]": round(float(_l.p_set), 2),
                "time series": bool(_l.dynamic),
                "annual [TWh/a]": round(float(_l.annual_MWh) / 1e6, 3),
                "feeding links (carrier: bus0 → bus1 | bus2 | bus3)": "; ".join(
                    f"{r.carrier}: {r.bus0} → {r.bus1}"
                    + (f" | {r.bus2}" if isinstance(r.bus2, str) and r.bus2 else "")
                    + (f" | {r.bus3}" if isinstance(r.bus3, str) and r.bus3 else "")
                    for r in _feed.itertuples()
                )
                or "(direct supply on this bus, e.g. electricity or heat bus)",
            }
        )
    topology_table = pd.DataFrame(_rows).set_index("load")
    mo.vstack(
        [
            mo.md(f"Industry Loads and feeding links in **{region}**, {year}:"),
            topology_table,
        ]
    )
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### 5.2 No double counting with the electricity base load

    The measured electricity demand time series (ENTSO-E based "base load", carrier
    `electricity`) already contains today's industrial electricity. `add_industry`
    therefore scales the base load of every country down by the factor
    `1 − current electricity / base-load energy` before adding the `industry electricity`
    Loads (column `current electricity` of section 3.6; the country loop is in
    `add_industry`). What remains of the base load is households, services, rail and
    agriculture.

    PyPSA-AT goes one step further: `mods/demand/electricity.py::base_load_load_splitting`
    splits the remaining base load of every node **without remainder** into the sectoral
    Loads `electricity for residential`, `electricity for services`, `electricity for road`,
    `electricity for rail` and `agriculture electricity`, weighted with the JRC-based energy
    totals, and removes the original `electricity` Load. Industry is not one of these
    parts — its electricity is exclusively the `industry electricity` Load. The check
    below counts the Loads in the selected network.

    *Where in the code:* `scripts/prepare_sector_network.py::add_industry` ("remove today's
    industrial electricity demand"), `mods/demand/electricity.py::base_load_load_splitting`,
    called from `mods/network/common.py::prepare_sector_network`.
    """)
    return


@app.cell(hide_code=True)
def _(AT_REGIONS, jrc_demand_node, mo, pd, slices, year):
    from mods.demand.electricity import BASE_LOAD_CARRIERS

    _loads = slices[year]["loads"]
    _at = _loads[_loads.region.isin(AT_REGIONS)]
    _counts = _at.carrier.value_counts()
    base_load_check = pd.DataFrame(
        {
            "AT Loads": [int(_counts.get("electricity", 0))]
            + [int(_counts.get(c, 0)) for c in BASE_LOAD_CARRIERS]
            + [int(_counts.get("industry electricity", 0))],
        },
        index=["electricity (original base load)"]
        + list(BASE_LOAD_CARRIERS)
        + ["industry electricity"],
    )
    _jrc = jrc_demand_node[year].loc[AT_REGIONS]
    mo.vstack(
        [
            mo.md(
                f"**Key takeaway ({year}):** the original `electricity` base-load Loads are gone for all "
                f"{len(AT_REGIONS)} Austrian regions; they were replaced by the {len(BASE_LOAD_CARRIERS)} sectoral "
                f"Loads. Today's industrial electricity removed from the base load before the split: "
                f"{_jrc['current electricity'].sum():.1f} TWh/a (`current electricity`), versus the "
                f"{_jrc['electricity'].sum():.1f} TWh/a JRC-based industry electricity of {year}."
            ),
            base_load_check,
        ]
    )
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ---
    ## 6 · Austrian annual overrides from the NEA (2025 only)

    The JRC-based numbers are EU statistics disaggregated with keys. For the base year
    PyPSA-AT replaces the Austrian totals with Statistik Austria's *Nutzenergieanalyse*.
    **This applies to the years in `industry.annual_demand_overrides.target_years`
    only** — in this run that is 2025, fed from NEA year 2024
    (`source_years: {2025: 2024}`). Every later horizon comes from the JRC projection of
    section 3.6. Section 6.6 quantifies the jump this causes between 2025 and 2030.

    ### 6.1 The raw workbook

    One ODS workbook per Bundesland, one sheet per year (`NEA_2005` … `NEA_2024`). Each
    sheet stacks one table per economic sector (*Bereich*): rows are energy carriers
    (*Energieträger*), columns are useful-energy categories (*Nutzenergiekategorie*:
    space heat & hot water, process heat < 200 °C, > 200 °C, stationary motors, transport,
    lighting & IT, electrochemistry), values in **TJ of final energy** allocated to the
    useful-energy category (the "energiebilanzkonform" final-energy view). The cell below
    shows the head of the *Produzierender Bereich insgesamt* block of one workbook.

    *Where in the code:* rule `retrieve_nea_at` in `rules/pypsa-at/retrieve.smk`
    (`data/versions.csv` row `nea-at`). Docs node *Statistik Austria NEA*.
    """)
    return


@app.cell(hide_code=True)
def _(NEA_RAW_DIR, cfg, cfg_year, mo, pd):
    _files = sorted(NEA_RAW_DIR.glob("NEA*Daten.ods")) if NEA_RAW_DIR.exists() else []
    _ov_cfg = cfg["industry"]["annual_demand_overrides"]
    nea_source_year = int(cfg_year(_ov_cfg["source_years"], _ov_cfg["target_years"][0]))
    if _files:
        _wb = (
            [f for f in _files if "Wien" in f.name][0]
            if any("Wien" in f.name for f in _files)
            else _files[0]
        )
        _raw = pd.read_excel(
            _wb,
            engine="odf",
            sheet_name=f"NEA_{nea_source_year}",
            header=None,
            usecols="A:I",
        )
        _hdr = _raw.index[
            _raw.apply(lambda r: r.eq("Energieträger").any(), axis=1)
        ].tolist()
        _start = next(
            (
                h
                for h in _hdr
                if str(_raw.iloc[h - 1, 0]).startswith("Produzierender Bereich")
            ),
            _hdr[0],
        )
        _block = _raw.iloc[_start - 1 : _start + 12].fillna("")
        _block.columns = [f"col {i}" for i in range(_block.shape[1])]
        nea_raw_preview = mo.vstack(
            [
                mo.md(
                    f"Raw files present: {', '.join(f.name for f in _files)}. Preview of `{_wb.name}`, "
                    f"sheet `NEA_{nea_source_year}`, block *{_raw.iloc[_start - 1, 0]}* (values in TJ):"
                ),
                _block,
            ]
        )
    else:
        nea_raw_preview = mo.md(
            f"**Raw NEA workbooks are missing** under `{NEA_RAW_DIR}`; continuing from the prepared `resources/nea_at.csv`."
        )
    nea_raw_preview
    return (nea_source_year,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### 6.2 The cleaned long table `resources/nea_at.csv`

    `scripts/pypsa-at/build_nea_at.py` repairs `#DIV/0!` cells, finds every
    *Energieträger* header row, skips the aggregate blocks (*insgesamt*), melts each block
    into a long table, tags it with the Bundesland's NUTS2 code (`mods/constants.py::NUTS2_CODES`),
    assigns the sector category (`SECTOR_TO_CATEGORY`) and converts **TJ → TWh (÷ 3600)**.
    The override uses only category **`Produzierender Bereich`** (manufacturing, mining and
    construction) and sums over *all* useful-energy categories — i.e. it takes the full
    final energy of the sector, including the space-heating part.

    *Where in the code:* `scripts/pypsa-at/build_nea_at.py::read_workbook`, rule
    `build_nea_at`. Docs node *Prepared NEA data*.
    """)
    return


@app.cell(hide_code=True)
def _(cfg, go, mo, nea_source_year, pd, resource_path):
    _p, _l = resource_path("nea_at.csv")
    nea = pd.read_csv(_p)
    _cat = cfg["industry"]["annual_demand_overrides"]["source_category"]
    nea_pb = nea[nea.Kategorie.eq(_cat) & nea.year.eq(nea_source_year)].copy()
    nea_by_land_carrier = nea_pb.pivot_table(
        index="Bundesland", columns="Energieträger", values="value_TWh", aggfunc="sum"
    )
    nea_by_land_carrier = nea_by_land_carrier.loc[:, nea_by_land_carrier.sum() > 0]
    nea_by_use = (
        nea_pb.groupby("Nutzenergiekategorie")
        .value_TWh.sum()
        .sort_values(ascending=False)
    )
    _fig = go.Figure()
    for _c in nea_by_land_carrier.columns:
        _fig.add_bar(name=_c, x=nea_by_land_carrier.index, y=nea_by_land_carrier[_c])
    _fig.update_layout(
        barmode="relative",
        title=f"NEA {nea_source_year}, '{_cat}': final energy per Bundesland and Energieträger — {_l}",
        yaxis_title="TWh/a",
        height=450,
    )
    mo.vstack(
        [
            mo.md(
                f"**Key takeaway:** the NEA {nea_source_year} final energy of the producing sector is "
                f"**{nea_pb.value_TWh.sum():.1f} TWh/a** over {nea_pb.Bundesland.nunique()} Bundesländer, "
                f"{nea_pb.Bereich.nunique()} sub-sectors and {nea_pb['Energieträger'].nunique()} carriers; "
                f"the largest carriers are {', '.join(f'{c} ({v:.1f} TWh)' for c, v in nea_by_land_carrier.sum().sort_values(ascending=False).head(3).items())}. "
                f"Of this, {nea_by_use.get('Raumklima und Warmwasser', 0):.1f} TWh is space heat and hot water."
            ),
            _fig,
            mo.md(
                "Final energy by useful-energy category (all categories are summed by the override):"
            ),
            nea_by_use.round(2).to_frame("TWh/a"),
        ]
    )
    return nea, nea_pb


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### 6.3 Mapping NEA labels to model carriers and distribution keys

    `scripts/pypsa-at/build_nea_industry_demand.py` carries two dictionaries:

    - **`CARRIER_MAPPING`** — NEA *Energieträger* → model carrier name. Several NEA
      carriers merge into one (blast-furnace gas and coke-oven gas → methane; waste and
      wood → solid biomass; all oil products → naphtha; petroleum coke → coal).
    - **`SECTOR_DISTRIBUTION_KEYS`** — NEA *Bereich* → distribution-key column of
      section 3.4. Only steel, chemicals, non-ferrous metals and paper have a dedicated
      key; all other sub-sectors use *Other non-classified*, which for Austria equals the
      population key. Sub-sectors missing from the dictionary would fall back to
      *population* explicitly.

    The tables show both mappings with the NEA energy attached, and the final Load
    carrier each model carrier ends up in via `demand.carrier_to_load_mapping`.
    """)
    return


@app.cell(hide_code=True)
def _(CARRIER_TO_LOAD, importlib, key_coverage, mo, nea_pb, pd):
    bni = importlib.import_module("scripts.pypsa-at.build_nea_industry_demand")
    _by_carrier = nea_pb.groupby("Energieträger").value_TWh.sum()
    carrier_mapping_table = pd.DataFrame(
        {
            "model carrier": pd.Series(bni.CARRIER_MAPPING),
        }
    )
    carrier_mapping_table["load carrier"] = carrier_mapping_table["model carrier"].map(
        CARRIER_TO_LOAD
    )
    carrier_mapping_table["NEA TWh/a"] = carrier_mapping_table.index.map(
        lambda c: _by_carrier.get(c, float("nan"))
    )
    carrier_mapping_table.index.name = "NEA Energieträger"
    _unmapped = sorted(set(nea_pb["Energieträger"]) - set(bni.CARRIER_MAPPING))
    _by_sector = nea_pb.groupby("Bereich").value_TWh.sum()
    sector_key_table = pd.DataFrame(
        {"distribution key": pd.Series(bni.SECTOR_DISTRIBUTION_KEYS)}
    )
    sector_key_table["NEA TWh/a"] = sector_key_table.index.map(
        lambda s: _by_sector.get(s, float("nan"))
    )
    sector_key_table["key is population-like"] = sector_key_table[
        "distribution key"
    ].map(
        lambda k: (
            bool(key_coverage.loc[k, "identical to population (fallback)"])
            if k in key_coverage.index
            else True
        )
    )
    sector_key_table.index.name = "NEA Bereich"
    _pop_share = (
        sector_key_table.loc[
            sector_key_table["key is population-like"], "NEA TWh/a"
        ].sum()
        / sector_key_table["NEA TWh/a"].sum()
    )
    mo.vstack(
        [
            mo.md(
                f"**Key takeaway:** all {len(bni.CARRIER_MAPPING)} NEA carriers are mapped"
                + (
                    f"; NEA carriers without mapping: {_unmapped}"
                    if _unmapped
                    else " (no NEA carrier is dropped)"
                )
                + f". Carriers in the mapping but absent from the NEA data (e.g. *Wasserstoff*, *Methanol*, *Ammoniak*) "
                f"produce no override, so those Loads keep their JRC values. "
                f"**{_pop_share:.0%} of the NEA energy is regionalised by population** rather than by industrial sites."
            ),
            mo.hstack(
                [carrier_mapping_table.round(3), sector_key_table.round(3)],
                gap=2,
                widths="equal",
            ),
        ]
    )
    return (bni,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### 6.4 From Bundesland totals to model regions

    `build_demand()` groups the NEA rows by Bundesland (NUTS2), *Bereich*, carrier and
    distribution key, then `allocate_to_regions()` splits each Bundesland total across
    its NUTS3 model regions: the national key column is **re-normalised within each
    Bundesland** (so the Bundesland total is conserved), NaN keys (0/0 for a Bundesland
    without any site) fall back to population. Model region **`AT333`** (Osttirol) is
    assigned to parent `AT33` by `nuts2_parent()`, as NUTS3 code prefixes alone would
    not place it correctly. The result is `industrial_demand_overrides_base_s_adm.csv`
    with columns `year, region, sector, carrier, value_TWh`.

    The cell recomputes the table with the module's own functions from `nea_at.csv` and
    the current distribution keys and compares it with the table stored in the solved
    network (`n.meta["resources"]["industrial_demand_overrides"]`).

    *Where in the code:* `scripts/pypsa-at/build_nea_industry_demand.py`
    (`build_demand`, `allocate_to_regions`, `nuts2_parent`), rule
    `build_industrial_demand_overrides_at` in `rules/pypsa-at/build_sector.smk`. Docs node
    *Regional NEA demand overrides*.
    """)
    return


@app.cell(hide_code=True)
def _(
    YEARS,
    bni,
    cfg,
    distribution_keys,
    go,
    keys_provenance,
    mo,
    nea,
    np,
    pd,
    slices,
):
    _ov_cfg = cfg["industry"]["annual_demand_overrides"]
    _source_years = {int(k): int(v) for k, v in _ov_cfg["source_years"].items()}
    overrides_recomputed = bni.build_demand(
        nea,
        distribution_keys,
        [int(y) for y in _ov_cfg["target_years"]],
        _source_years,
        _ov_cfg["source_category"],
    )
    overrides_run = pd.DataFrame.from_dict(
        slices[YEARS[0]]["meta"]["resources"]["industrial_demand_overrides"]
    )
    _m = overrides_recomputed.merge(
        overrides_run,
        on=["year", "region", "sector", "carrier"],
        how="outer",
        suffixes=("_recomputed", "_run"),
    )
    _max_diff = float((_m.value_TWh_recomputed - _m.value_TWh_run).abs().max())
    overrides_pivot = overrides_run.pivot_table(
        index="region", columns="carrier", values="value_TWh", aggfunc="sum"
    )
    _fig = go.Figure()
    for _c in overrides_pivot.columns:
        _fig.add_bar(name=_c, x=overrides_pivot.index, y=overrides_pivot[_c])
    _fig.update_layout(
        barmode="relative",
        title=f"NEA override totals per model region and carrier (from n.meta of the {YEARS[0]} network)",
        yaxis_title="TWh/a",
        height=450,
    )
    mo.vstack(
        [
            mo.md(
                f"**Key takeaway:** the override table in the run covers year(s) {sorted(overrides_run.year.unique().tolist())}, "
                f"{overrides_run.region.nunique()} regions and carriers {sorted(overrides_run.carrier.unique().tolist())}; "
                f"its total is {overrides_run.value_TWh.sum():.1f} TWh/a. Recomputing it from `nea_at.csv` with the "
                f"distribution keys ({keys_provenance}) gives a maximum difference of {_max_diff:.2e} TWh per row"
                + (
                    " — identical."
                    if np.isclose(_max_diff, 0, atol=1e-9)
                    else " — **check the key file provenance**."
                )
                + f" `nuts2_parent('AT333')` → `{bni.nuts2_parent('AT333')}`."
            ),
            _fig,
        ]
    )
    return (overrides_run,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### 6.5 Replacing the Load totals: `apply_annual_demand_overrides`

    During `prepare_sector_network` (after the upstream `add_industry`), PyPSA-AT calls
    `mods/demand/annual.py::apply_annual_demand_overrides`. It returns immediately unless
    `enable` is true **and** the planning horizon is in `target_years`. Otherwise it maps
    each `(sector, carrier)` to a Load carrier with `demand.carrier_to_load_mapping`,
    sums to `(region, load carrier)` targets and, for every matching Load:

    - **static Load** (no time series): `p_set = target energy / Σ weightings` — a new flat value;
    - **dynamic Load** (time series present): the series is multiplied by
      `target / current annual energy`, so its shape is kept and only the annual total is
      replaced; the static `p_set` is set to 0.

    Note that both `coal` and `coke` map to `coal for industry` and are simply added,
    whereas `add_industry` converts coke to coal-equivalent with the factor 1.366 (see
    section 11). The order in `mods/network/common.py::prepare_sector_network` is:
    `add_h2_for_industry_bus` → methane pyrolysis → hydro → `base_load_load_splitting` →
    **`apply_annual_demand_overrides`** → `apply_industrial_demand_profiles`. So at
    override time the `industry electricity` Loads are still flat and take the *static*
    rule; the profile is imposed afterwards.

    The check below compares, for the override year, the annual energy of every
    Austrian industry Load carrier in the solved network against (a) the NEA override
    targets and (b) the JRC-based file. Carriers with an NEA target must equal (a);
    carriers without one (hydrogen, methanol, ammonia) must still equal (b).
    """)
    return


@app.cell(hide_code=True)
def _(
    AT_REGIONS,
    CARRIER_TO_LOAD,
    INDUSTRY_LOAD_CARRIERS,
    cfg,
    jrc_demand_node,
    mo,
    np,
    overrides_run,
    pd,
    slices,
):
    _target_year = int(cfg["industry"]["annual_demand_overrides"]["target_years"][0])
    _ind = slices[_target_year]["industry"]
    _ind = _ind[_ind.region.isin(AT_REGIONS)]
    _net = _ind.groupby("carrier").annual_MWh.sum() / 1e6
    _ov = overrides_run[overrides_run.year.eq(_target_year)].copy()
    _ov["load carrier"] = _ov.carrier.map(CARRIER_TO_LOAD)
    _ov_by_load = _ov.groupby("load carrier").value_TWh.sum()
    _jrc_regional = jrc_demand_node[_target_year].loc[AT_REGIONS]
    _jrc = _jrc_regional.sum()
    _jrc_clipped = _jrc_regional.clip(
        lower=0
    ).sum()  # clip_negative_loads_for_edge_cases sets negative Loads to 0
    _jrc_by_load = pd.Series(dtype=float)
    _jrc_clipped_by_load = pd.Series(dtype=float)
    for _model_c, _load_c in CARRIER_TO_LOAD.items():
        _factor = (
            1.366 if _model_c == "coke" else 1.0
        )  # mwh_coal_per_mwh_coke in add_industry
        _jrc_by_load[_load_c] = (
            _jrc_by_load.get(_load_c, 0.0) + _jrc.get(_model_c, 0.0) * _factor
        )
        _jrc_clipped_by_load[_load_c] = (
            _jrc_clipped_by_load.get(_load_c, 0.0)
            + _jrc_clipped.get(_model_c, 0.0) * _factor
        )
    _rows = []
    for _c in INDUSTRY_LOAD_CARRIERS:
        if _c == "process emissions":
            continue
        _value = _net.get(_c, 0.0)
        if _c in _ov_by_load and np.isclose(_value, _ov_by_load[_c], rtol=1e-4):
            _source = "NEA override"
        elif np.isclose(_value, _jrc_by_load.get(_c, 0), rtol=1e-3):
            _source = "JRC (no NEA target)"
        elif np.isclose(_value, _jrc_clipped_by_load.get(_c, 0), rtol=1e-3):
            _source = "JRC, negative regional Loads clipped to 0"
        else:
            _source = "UNEXPLAINED"
        _rows.append(
            {
                "load carrier": _c,
                "network [TWh/a]": _value,
                "NEA override target [TWh/a]": _ov_by_load.get(_c, float("nan")),
                "JRC file [TWh/a]": _jrc_by_load.get(_c, float("nan")),
                "JRC file, negatives clipped [TWh/a]": _jrc_clipped_by_load.get(
                    _c, float("nan")
                ),
                "source in network": _source,
            }
        )
    override_check = pd.DataFrame(_rows).set_index("load carrier")
    _n_ok = (override_check["source in network"] != "UNEXPLAINED").sum()
    _n_clipped = (
        override_check["source in network"].str.startswith("JRC, negative")
    ).sum()
    mo.vstack(
        [
            mo.md(
                f"**Key takeaway ({_target_year}):** {_n_ok} of {len(override_check)} Austrian Load carriers are fully explained: "
                f"{(override_check['source in network'] == 'NEA override').sum()} carry the NEA totals, "
                f"{(override_check['source in network'] == 'JRC (no NEA target)').sum() + _n_clipped} still carry the JRC values"
                + (
                    f" ({_n_clipped} of them after `mods/network/common.py::clip_negative_loads_for_edge_cases` set negative "
                    f"regional Loads to zero, which raises the Austrian sum above the net JRC value)."
                    if _n_clipped
                    else "."
                )
                + f" Austrian industry final energy in the network: {_net.drop('process emissions', errors='ignore').sum():.1f} TWh/a."
            ),
            override_check.round(3),
        ]
    )
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### 6.6 NEA versus JRC for 2025, and the jump to 2030

    Because only 2025 is overridden, the 2025 → 2030 change per carrier mixes two things:
    the genuine JRC projection (route shift, efficiency) and the **switch of statistical
    source**. The tables separate them: the first compares NEA and JRC for 2025 per
    carrier; the second shows the network values 2025 → 2030 next to the JRC-only
    2025 → 2030 change. Select a carrier to see the regional NEA-vs-JRC comparison.
    """)
    return


@app.cell(hide_code=True)
def _(
    AT_REGIONS,
    CARRIER_TO_LOAD,
    YEARS,
    cfg,
    go,
    jrc_demand_node,
    mo,
    overrides_run,
    pd,
    slices,
):
    _y0 = int(cfg["industry"]["annual_demand_overrides"]["target_years"][0])
    _y1 = min(y for y in YEARS if y > _y0)
    _ov = overrides_run[overrides_run.year.eq(_y0)].copy()
    _ov["load carrier"] = _ov.carrier.map(CARRIER_TO_LOAD)

    def _jrc_by_load(year):
        _j = jrc_demand_node[year].loc[AT_REGIONS].copy()
        _j["coke"] = _j["coke"] * 1.366
        _out = pd.DataFrame(index=_j.index)
        for _model_c, _load_c in CARRIER_TO_LOAD.items():
            _out[_load_c] = _out.get(_load_c, 0.0) + _j.get(_model_c, 0.0)
        return _out

    jrc_by_load_region = {y: _jrc_by_load(y) for y in YEARS}
    _nea_c = _ov.groupby("load carrier").value_TWh.sum()
    nea_vs_jrc = pd.DataFrame(
        {f"NEA {_y0} (override)": _nea_c, f"JRC {_y0}": jrc_by_load_region[_y0].sum()}
    )
    nea_vs_jrc["NEA / JRC"] = nea_vs_jrc.iloc[:, 0] / nea_vs_jrc.iloc[:, 1]
    nea_vs_jrc.index.name = "load carrier [TWh/a]"

    def _net_by_carrier(year):
        _i = slices[year]["industry"]
        _i = _i[_i.region.isin(AT_REGIONS) & _i.carrier.ne("process emissions")]
        return _i.groupby("carrier").annual_MWh.sum() / 1e6

    jump = pd.DataFrame(
        {
            f"network {_y0}": _net_by_carrier(_y0),
            f"network {_y1}": _net_by_carrier(_y1),
            f"JRC {_y0}": jrc_by_load_region[_y0].sum(),
            f"JRC {_y1}": jrc_by_load_region[_y1].sum(),
        }
    )
    jump[f"network change {_y0}→{_y1} [%]"] = (
        jump.iloc[:, 1] / jump.iloc[:, 0] - 1
    ) * 100
    jump[f"JRC-only change {_y0}→{_y1} [%]"] = (
        jump.iloc[:, 3] / jump.iloc[:, 2] - 1
    ) * 100
    jump.index.name = "load carrier [TWh/a]"
    _fig = go.Figure()
    for _col in [f"network {_y0}", f"network {_y1}", f"JRC {_y0}", f"JRC {_y1}"]:
        _fig.add_bar(name=_col, x=jump.index, y=jump[_col])
    _fig.update_layout(
        barmode="group",
        title=f"Austria: industry demand per carrier — network ({_y0} NEA, {_y1} JRC) vs JRC-only",
        yaxis_title="TWh/a",
        height=450,
    )
    _tot_net = jump.iloc[:, :2].sum()
    _tot_jrc = jump.iloc[:, 2:4].sum()
    _biggest = (
        jump[f"network change {_y0}→{_y1} [%]"]
        .abs()
        .sort_values(ascending=False)
        .head(3)
    )
    mo.vstack(
        [
            mo.md(
                f"**Key takeaway:** total Austrian industry demand is {nea_vs_jrc.iloc[:, 0].sum():.1f} TWh/a in the NEA "
                f"override versus {nea_vs_jrc.iloc[:, 1].sum():.1f} TWh/a in the JRC file for {_y0}. In the networks the total "
                f"moves from {_tot_net.iloc[0]:.1f} ({_y0}) to {_tot_net.iloc[1]:.1f} TWh/a ({_y1}), "
                f"a change of {(_tot_net.iloc[1] / _tot_net.iloc[0] - 1) * 100:+.1f} %, whereas the JRC projection alone moves "
                f"{(_tot_jrc.iloc[1] / _tot_jrc.iloc[0] - 1) * 100:+.1f} %. The largest carrier jumps are "
                f"{', '.join(f'{c} ({v:+.0f} %)' for c, v in _biggest.items())}. **Modelling caveat:** part of the "
                f"{_y0}→{_y1} development is a change of data source, not a projected development."
            ),
            mo.hstack([nea_vs_jrc.round(2), jump.round(2)], gap=2, widths="equal"),
            _fig,
        ]
    )
    return jrc_by_load_region, nea_vs_jrc


@app.cell(hide_code=True)
def _(CARRIER_TO_LOAD, mo, nea_vs_jrc):
    sel_carrier = mo.ui.dropdown(
        options=[c for c in nea_vs_jrc.index if c in CARRIER_TO_LOAD.values()],
        value="industry electricity",
        label="Load carrier for the regional comparison",
    )
    sel_carrier
    return (sel_carrier,)


@app.cell(hide_code=True)
def _(
    CARRIER_TO_LOAD,
    cfg,
    color,
    go,
    jrc_by_load_region,
    overrides_run,
    sel_carrier,
):
    _y0 = int(cfg["industry"]["annual_demand_overrides"]["target_years"][0])
    _c = sel_carrier.value
    _ov = overrides_run[overrides_run.year.eq(_y0)].copy()
    _ov["load carrier"] = _ov.carrier.map(CARRIER_TO_LOAD)
    _nea_r = _ov[_ov["load carrier"].eq(_c)].groupby("region").value_TWh.sum()
    _jrc_r = jrc_by_load_region[_y0][_c]
    _fig = go.Figure()
    _fig.add_bar(
        name=f"NEA {_y0}",
        x=_jrc_r.index,
        y=_nea_r.reindex(_jrc_r.index).fillna(0),
        marker_color=color(_c),
    )
    _fig.add_bar(name=f"JRC {_y0}", x=_jrc_r.index, y=_jrc_r, marker_color="#bbbbbb")
    _fig.update_layout(
        barmode="group",
        title=f"{_c}: NEA override vs JRC-based demand per Austrian region, {_y0}",
        yaxis_title="TWh/a",
        xaxis_title="model region",
        height=420,
    )
    _fig
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ---
    ## 7 · Temporal profiles: which industry Loads vary over the year?

    ### 7.1 Static versus dynamic Loads in the solved networks

    The answer comes straight from the networks: a Load is *profiled* if its name is a
    column of `n.loads_t.p_set`, otherwise it is flat. The table counts the Austrian
    Loads per carrier and horizon.
    """)
    return


@app.cell(hide_code=True)
def _(AT_REGIONS, INDUSTRY_LOAD_CARRIERS, YEARS, mo, pd, slices):
    _rows = {}
    for _y in YEARS:
        _ind = slices[_y]["industry"]
        _ind = _ind[_ind.region.isin(AT_REGIONS)]
        _rows[_y] = {
            c: f"{int(_ind[_ind.carrier.eq(c)].dynamic.sum())} of {int(_ind.carrier.eq(c).sum())} profiled"
            for c in INDUSTRY_LOAD_CARRIERS
        }
    static_dynamic = pd.DataFrame(_rows)
    static_dynamic.index.name = "load carrier (Austrian Loads)"
    _profiled = [
        c
        for c in INDUSTRY_LOAD_CARRIERS
        if any(not v.startswith("0 of") for v in static_dynamic.loc[c])
    ]
    _flat_static = []
    for _y in YEARS:
        _ind = slices[_y]["industry"]
        _e = _ind[
            _ind.region.isin(AT_REGIONS) & _ind.carrier.isin(_profiled) & ~_ind.dynamic
        ]
        _flat_static += [f"{n} ({_y})" for n in _e.index]
    mo.vstack(
        [
            mo.md(
                f"**Key takeaway:** only **{', '.join(f'`{c}`' for c in _profiled)}** carries a time series; every other industry "
                f"Load is flat in all horizons. "
                + (
                    f"Profiled carrier Loads that are nevertheless static: {', '.join(_flat_static)} (their region has no profile in the resource)."
                    if _flat_static
                    else ""
                )
            ),
            static_dynamic.rename(columns=str),
        ]
    )
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### 7.2 What the profile looks like

    Left: one week (starting `WEEK_START`) of `industry electricity` for the selected
    region and horizon against the flat `gas for industry` Load of the same region, in
    MW per 3-hour snapshot. Right: the full-year duration curve of both, normalised to
    their annual mean, so that a flat Load is a horizontal line at 1.
    """)
    return


@app.cell(hide_code=True)
def _(WEEK_START, color, mo, pd, region, slices, year):
    from plotly.subplots import make_subplots

    _s = slices[year]
    _ind = _s["industry"]
    _w = _s["weights"]
    _elec_name = f"{region} industry electricity"
    _gas = _ind[_ind.region.eq(region) & _ind.carrier.eq("gas for industry")]
    _gas_series = pd.Series(
        float(_gas.p_set.iloc[0]) if not _gas.empty else 0.0, index=_w.index
    )
    if _elec_name in _s["p_set_t"].columns:
        _elec_series = _s["p_set_t"][_elec_name]
    else:
        _elec_series = pd.Series(float(_ind.loc[_elec_name, "p_set"]), index=_w.index)
    _start = pd.Timestamp(WEEK_START)
    _week = slice(_start, _start + pd.Timedelta(days=7))
    _fig = make_subplots(
        rows=1,
        cols=2,
        subplot_titles=(
            f"One week from {WEEK_START} [MW]",
            "Duration curve (normalised to annual mean)",
        ),
    )
    _fig.add_scatter(
        x=_elec_series[_week].index,
        y=_elec_series[_week],
        name="industry electricity",
        line=dict(color=color("industry electricity")),
        row=1,
        col=1,
    )
    _fig.add_scatter(
        x=_gas_series[_week].index,
        y=_gas_series[_week],
        name="gas for industry (flat)",
        line=dict(color=color("gas for industry")),
        row=1,
        col=1,
    )
    _fig.add_scatter(
        y=(_elec_series / _elec_series.mean()).sort_values(ascending=False).values,
        name="industry electricity",
        line=dict(color=color("industry electricity")),
        showlegend=False,
        row=1,
        col=2,
    )
    _fig.add_scatter(
        y=(_gas_series / _gas_series.mean()).sort_values(ascending=False).values,
        name="gas for industry (flat)",
        line=dict(color=color("gas for industry")),
        showlegend=False,
        row=1,
        col=2,
    )
    _fig.update_yaxes(title_text="MW", row=1, col=1)
    _fig.update_yaxes(title_text="p / mean(p)", row=1, col=2)
    _fig.update_xaxes(title_text="snapshot (3-hourly)", row=1, col=2)
    _fig.update_layout(
        title=f"{region}, {year}: profiled vs flat industry Load", height=420
    )
    mo.vstack(
        [
            mo.md(
                f"**Key takeaway:** in {region} ({year}) industry electricity swings between "
                f"{_elec_series.min() / _elec_series.mean():.2f} and {_elec_series.max() / _elec_series.mean():.2f} times its "
                f"mean of {_elec_series.mean():,.0f} MW; the gas Load is constant at {_gas_series.mean():,.0f} MW."
            ),
            _fig,
        ]
    )
    return (make_subplots,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### 7.3 The raw FfE shapes

    The FfE dataset contains one normalised hourly profile (8760 values summing to 1)
    per industry branch for the reference year **2017**. The API response holds 11 of the
    14 documented branches; *Industry total (0)*, *Chemical Industry (2)* and
    *Non-ferrous Metals (3)* are missing. The chart shows one week of each profile,
    scaled to its annual mean, so 1.0 means "average hour".

    *Where in the code:* `scripts/pypsa-at/build_industrial_demand_profiles.py`
    (`FFE_ID_TO_PROFILE`, `FFE_REFERENCE_YEAR`, `load_ffe_load_profiles`). Docs node
    *FfE industry profiles*.
    """)
    return


@app.cell(hide_code=True)
def _(FFE_JSON, go, importlib, json, mo, np, pd):
    bidp = importlib.import_module("scripts.pypsa-at.build_industrial_demand_profiles")
    if FFE_JSON.exists():
        with open(FFE_JSON) as _f:
            _ffe = json.load(_f)
        _ts = pd.date_range(
            f"{bidp.FFE_REFERENCE_YEAR}-01-01",
            f"{bidp.FFE_REFERENCE_YEAR}-12-31 23:00",
            freq="h",
        )
        _df = pd.json_normalize(_ffe["data"])
        _df = _df.set_index(_df["internal_id"].map(lambda x: x[0]))["values"]
        ffe_profiles = (
            pd.DataFrame(np.vstack(_df), index=_df.index, columns=_ts)
            .rename(index=bidp.FFE_ID_TO_PROFILE)
            .T
        )
        ffe_meta_table = pd.DataFrame(
            {
                "FfE id": list(range(14)),
                "profile": [
                    {
                        0: "Industry total",
                        2: "Chemical Industry",
                        3: "Non-ferrous Metals",
                    }.get(i, bidp.FFE_ID_TO_PROFILE.get(i, ""))
                    for i in range(14)
                ],
            }
        ).set_index("FfE id")
        ffe_meta_table["in API response"] = ffe_meta_table.index.isin(_df.index)
        _week = ffe_profiles.loc[
            f"{bidp.FFE_REFERENCE_YEAR}-03-06" : f"{bidp.FFE_REFERENCE_YEAR}-03-12 23:00"
        ]
        _fig = go.Figure()
        for _c in ffe_profiles.columns:
            _fig.add_scatter(
                x=_week.index, y=_week[_c] * len(ffe_profiles), name=_c, mode="lines"
            )
        _fig.update_layout(
            title=f"FfE '{_ffe['title']}' — one week (Mon 6 – Sun 12 March {bidp.FFE_REFERENCE_YEAR}), hourly",
            yaxis_title="load / annual mean",
            height=450,
        )
        ffe_view = mo.vstack(
            [
                mo.md(
                    f"**Key takeaway:** all {len(ffe_profiles.columns)} profiles sum to "
                    f"{ffe_profiles.sum().mean():.3f} over {len(ffe_profiles)} hours (normalised); the shapes differ mainly in the "
                    f"weekend dip — e.g. *Iron & steel industry* stays at "
                    f"{(ffe_profiles['Iron & steel industry'][ffe_profiles.index.dayofweek >= 5].mean() / ffe_profiles['Iron & steel industry'].mean()):.2f} "
                    f"of its mean on weekends, *Machinery* at "
                    f"{(ffe_profiles['Machinery'][ffe_profiles.index.dayofweek >= 5].mean() / ffe_profiles['Machinery'].mean()):.2f}. "
                    f"Dataset description: *{_ffe['oep_metadata']['description'][:220]}...*"
                ),
                ffe_meta_table,
                _fig,
            ]
        )
    else:
        ffe_profiles = None
        ffe_meta_table = None
        ffe_view = mo.md(
            f"**The raw FfE JSON is missing** (`{FFE_JSON}`); the nodal profiles of 7.6 are taken from the network metadata instead."
        )
    ffe_view
    return (bidp,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### 7.4 Mapping JRC subsectors to FfE branches

    Each of the 27 JRC subsectors is assigned one FfE branch in
    `INDUSTRY_CATEGORY_TO_PROFILE`. Because three FfE branches are missing, the mapping
    contains documented approximations (rationale from the upstream PR, citing Ganz et al.
    2021): chemical products → *Paper, Pulp and Print* (both run continuously all week),
    non-ferrous metals → *Iron & steel industry* (continuous metal production),
    pharmaceuticals → *Food and Tobacco* (batch production, reduced weekends). Two
    further choices are not explained upstream and are listed as open questions in
    section 11: HVC → *Non-metallic Minerals* and *Other non-ferrous metals* →
    *Non-metallic Minerals* (while aluminium goes to iron & steel).
    """)
    return


@app.cell(hide_code=True)
def _(bidp, pd):
    _direct = {
        "Electric arc",
        "DRI + Electric arc",
        "Integrated steelworks",
        "Cement",
        "Ceramics & other NMM",
        "Glass production",
        "Pulp production",
        "Paper production",
        "Printing and media reproduction",
        "Food, beverages and tobacco",
        "Transport equipment",
        "Machinery equipment",
        "Textiles and leather",
        "Wood and wood products",
        "Other industrial sectors",
    }
    _rationale = {
        "Paper, Pulp and Print": "chemicals approximated by paper: continuous full-load operation (Ganz et al. 2021)",
        "Iron & steel industry": "non-ferrous metals approximated by steel: continuous metal production",
        "Food and Tobacco": "pharmaceuticals approximated by food: batch production, reduced weekends",
        "Non-metallic Minerals": "no rationale stated upstream",
    }
    subsector_profile_map = pd.DataFrame(
        {"FfE profile": pd.Series(bidp.INDUSTRY_CATEGORY_TO_PROFILE)}
    )
    subsector_profile_map["approximation"] = [
        "direct match"
        if s in _direct
        else _rationale.get(p, "yes, no rationale stated")
        for s, p in bidp.INDUSTRY_CATEGORY_TO_PROFILE.items()
    ]
    subsector_profile_map.index.name = "JRC subsector"
    subsector_profile_map
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### 7.5 Nodal weighting by subsector electricity demand

    For every planning horizon and node, `nodal_sector_electricity_demand()` recomputes
    the subsector electricity demand (regional production × the country's sector ratios,
    exactly as section 3.6 but *before* summing over subsectors) and normalises it. The
    FfE branch profiles are then summed with these weights (`build_nodal_profiles`), so a
    region dominated by steel gets a flat, continuous profile, a region of machinery and
    food plants a profile with strong weekend dips. The chart shows the resulting weights
    per FfE branch for the Austrian regions of the selected horizon.

    Note that the weights are the *JRC* subsector mix even in 2025 — the NEA override
    changes the annual amount but not the mix.
    """)
    return


@app.cell(hide_code=True)
def _(AT_REGIONS, bidp, go, mo, resource_path, year):
    _rp, _rl = resource_path(f"industry_sector_ratios_{year}.csv")
    _pp, _pl = resource_path(f"industrial_production_base_s_adm_{year}.csv")
    _shares = bidp.nodal_sector_electricity_demand(str(_rp), str(_pp))
    _elec = _shares["elec"].unstack(level=1).loc[AT_REGIONS].fillna(0)
    _elec = _elec.T.groupby(bidp.INDUSTRY_CATEGORY_TO_PROFILE).sum().T
    profile_weights = _elec.div(_elec.sum(axis=1), axis=0).fillna(0)
    _fig = go.Figure()
    for _c in profile_weights.columns:
        _fig.add_bar(name=_c, x=profile_weights.index, y=profile_weights[_c])
    _fig.update_layout(
        barmode="relative",
        title=f"Austria {year}: weight of each FfE branch in the nodal industry electricity profile — {_rl}, {_pl}",
        yaxis_title="share of nodal industry electricity",
        height=450,
    )
    _dominant = profile_weights.idxmax(axis=1).value_counts()
    mo.vstack(
        [
            mo.md(
                f"**Key takeaway ({year}):** the dominant FfE branch is *{_dominant.index[0]}* in {_dominant.iloc[0]} of "
                f"{len(profile_weights)} Austrian regions; regions with a zero row (no electricity demand at all) get no profile "
                f"and stay flat."
            ),
            _fig,
        ]
    )
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### 7.6 From FfE hours to model snapshots, and the calendar shift

    `load_ffe_load_profiles()` relabels the 2017 timestamps to the model's weather year
    by **replacing only the year** (`date.replace(year=2013)`), keeps those that exist
    in the hourly snapshot index, and `build_nodal_profiles()` sums the hourly values
    onto the model's 3-hourly snapshots with a backward `merge_asof`. The result is
    normalised to 1 per (year, region, carrier) and stored as one resource file for all
    horizons: `industrial_demand_profiles_base_s_adm__none.csv`
    (columns `year, region, carrier, snapshot, value`).

    Replacing only the year means the **weekday pattern is not aligned**: the FfE year
    starts on a Sunday, the weather year on a Tuesday (computed below), so FfE Saturdays
    land on model Mondays. Holidays are not treated either. The upstream PR (section 8)
    rotates the profile by weekday and replaces holidays; PyPSA-AT does not.

    The first chart shows one week of the nodal shapes stored in the network metadata for
    a few regions (selected region plus the largest ones); the second shows the average
    Austrian industry electricity Load per weekday of the *model* calendar, taken from
    the solved network — the weekend dip appears on Monday and Tuesday.
    """)
    return


@app.cell(hide_code=True)
def _(
    AT_REGIONS,
    WEEK_START,
    bidp,
    cfg,
    make_subplots,
    mo,
    pd,
    region,
    slices,
    year,
):
    _prof = pd.DataFrame.from_dict(
        slices[year]["meta"]["resources"]["industrial_demand_profiles"]
    )
    _prof = _prof[_prof.year.astype(str).eq(str(year))]
    _prof["snapshot"] = pd.to_datetime(_prof["snapshot"])
    nodal_profiles = _prof.pivot(index="snapshot", columns="region", values="value")
    _ind = slices[year]["industry"]
    _elec = (
        _ind[_ind.carrier.eq("industry electricity") & _ind.region.isin(AT_REGIONS)]
        .groupby("region")
        .annual_MWh.sum()
        .sort_values(ascending=False)
    )
    _show = [region] + [r for r in _elec.index[:3] if r != region]
    _show = [r for r in _show if r in nodal_profiles.columns]
    _start = pd.Timestamp(WEEK_START)
    _week = nodal_profiles.loc[_start : _start + pd.Timedelta(days=7), _show] * len(
        nodal_profiles
    )
    _weather_year = int(cfg["snapshots"]["start"][:4])
    _ffe_dow = pd.Timestamp(bidp.FFE_REFERENCE_YEAR, 1, 1).day_name()
    _model_dow = pd.Timestamp(_weather_year, 1, 1).day_name()
    _pt = slices[year]["p_set_t"]
    _cols = [
        c
        for c in _pt.columns
        if c.endswith(" industry electricity") and c.split(" ")[0] in AT_REGIONS
    ]
    _at_sum = _pt[_cols].sum(axis=1)
    _by_dow = (
        _at_sum.groupby(_at_sum.index.day_name())
        .mean()
        .reindex(
            [
                "Monday",
                "Tuesday",
                "Wednesday",
                "Thursday",
                "Friday",
                "Saturday",
                "Sunday",
            ]
        )
    )
    _fig = make_subplots(
        rows=1,
        cols=2,
        subplot_titles=(
            f"Nodal profile shapes, week from {WEEK_START} (3-hourly, ×N so mean = 1)",
            f"AT industry electricity by model weekday, {year} [MW]",
        ),
    )
    for _r in _show:
        _fig.add_scatter(
            x=_week.index, y=_week[_r], name=_r, mode="lines", row=1, col=1
        )
    _fig.add_bar(
        x=_by_dow.index,
        y=_by_dow.values,
        name="mean load",
        marker_color="#2d2a66",
        showlegend=False,
        row=1,
        col=2,
    )
    _fig.update_layout(
        height=420,
        title=f"Nodal FfE profiles from n.meta (year {year}) and the calendar shift",
    )
    _lowest = _by_dow.idxmin()
    mo.vstack(
        [
            mo.md(
                f"**Key takeaway:** the profile resource in the run covers {nodal_profiles.shape[1]} regions × "
                f"{nodal_profiles.shape[0]} snapshots for {year} and sums to {nodal_profiles.sum().mean():.3f} per region. "
                f"1 January {bidp.FFE_REFERENCE_YEAR} was a **{_ffe_dow}**, 1 January {_weather_year} a **{_model_dow}**; in the "
                f"model calendar the lowest average industry electricity falls on **{_lowest}** "
                f"({_by_dow.min() / _by_dow.mean():.2f} × the weekly mean), not on the weekend."
            ),
            _fig,
        ]
    )
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### 7.7 Applying the profile while preserving annual energy

    `mods/demand/industrial_demand.py::apply_industrial_demand_profiles` runs last in
    `prepare_sector_network`. It returns unless `industry.demand_profiles.enable` is
    true, filters the resource to the planning horizon, joins profile rows to Loads on
    `(region, carrier)` — the carrier having been renamed from the FfE label `elec` to the
    Load carrier through `industry.demand_profiles.carrier_mapping` when the resource
    was built — and sets

    `p_set_t[snapshot] = value[snapshot] × p_set_flat × (Σ weightings / weighting[snapshot])`.

    Because Σ value = 1, the annual energy Σ p_set_t × weighting equals
    `p_set_flat × Σ weightings`, i.e. exactly the flat Load's energy (the NEA total in
    2025, the JRC total afterwards). The static `p_set` is set to 0. The check below
    verifies this for every horizon.

    *Where in the code:* `mods/demand/industrial_demand.py`,
    `scripts/pypsa-at/build_industrial_demand_profiles.py`, rule
    `build_industrial_demand_profiles_at` in `rules/pypsa-at/build_sector.smk`, tests
    `test/test_build_industrial_demand_profiles.py`, `test/test_mods/demand/test_industrial_demand.py`.
    Docs nodes *Nodal FfE electricity profiles*, *Apply FfE electricity profiles*.
    """)
    return


@app.cell(hide_code=True)
def _(
    AT_REGIONS,
    CARRIER_TO_LOAD,
    YEARS,
    cfg,
    jrc_by_load_region,
    mo,
    np,
    overrides_run,
    pd,
    slices,
):
    _target_years = [
        int(y) for y in cfg["industry"]["annual_demand_overrides"]["target_years"]
    ]
    _rows = []
    for _y in YEARS:
        _ind = slices[_y]["industry"]
        _e = _ind[
            _ind.carrier.eq("industry electricity") & _ind.region.isin(AT_REGIONS)
        ]
        _dyn_energy = _e[_e.dynamic].annual_MWh.sum() / 1e6
        _static_energy = _e[~_e.dynamic].annual_MWh.sum() / 1e6
        if _y in _target_years:
            _ov = overrides_run[overrides_run.year.eq(_y)].copy()
            _ov["load carrier"] = _ov.carrier.map(CARRIER_TO_LOAD)
            _expected = _ov[
                _ov["load carrier"].eq("industry electricity")
            ].value_TWh.sum()
            _src = "NEA override"
        else:
            _expected = jrc_by_load_region[_y]["industry electricity"].sum()
            _src = "JRC file"
        _rows.append(
            {
                "year": _y,
                "profiled Loads [TWh/a]": _dyn_energy,
                "flat Loads [TWh/a]": _static_energy,
                "expected annual total [TWh/a]": _expected,
                "expected from": _src,
                "relative difference": (_dyn_energy + _static_energy) / _expected - 1,
            }
        )
    energy_preservation = pd.DataFrame(_rows).set_index("year")
    _ok = np.allclose(energy_preservation["relative difference"], 0, atol=1e-3)
    mo.vstack(
        [
            mo.md(
                "**Key takeaway:** the profiled Austrian industry electricity Loads reproduce the annual totals "
                + (
                    "exactly (differences below 0.1 %)."
                    if _ok
                    else "**only approximately — investigate.**"
                )
            ),
            energy_preservation.round(4),
        ]
    )
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ---
    ## 8 · The upstream pull request PyPSA/pypsa-eur#1875 "Temporal industry load"

    State checked on 2026-09-17 via the GitHub API: **open, not merged** (author
    JulianGeis, opened 2025-11-03, last updated 2026-02-04, 17 commits, 9 files changed:
    `config/config.default.yaml`, `doc/configtables/industry.csv`, `doc/data-retrieval.rst`,
    `doc/release_notes.rst`, `pixi.toml`, `rules/build_sector.smk`, `rules/retrieve.smk`,
    `scripts/build_industrial_energy_demand_per_node.py`, `scripts/prepare_sector_network.py`).

    **What the PR offers**

    - One boolean switch `industry.temporal_electricity_industry_load` (default `true` in
      the PR); when on, `add_industry` reads an hourly `industrial_electricity_demand_temporal`
      file (MW) instead of creating flat Loads; when off, the flat Loads are created as today.
    - Data: FfE Open Data API dataset `id_opendata=59`, reference year 2017, retrieved in a
      new retrieve rule; the profile build lives inside
      `build_industrial_energy_demand_per_node.py` (one output per horizon).
    - FfE categories available: Iron & steel industry (1), Non-metallic Minerals (4),
      Transport Equipment (5), Machinery (6), Mining and Quarrying (7), Food and Tobacco (8),
      Paper, Pulp and Print (9), Wood and Wood Products (10), Construction (11), Textile and
      Leather (12), Non-specified (Industry) (13); missing in the API response: Industry
      total (0), Chemical Industry (2), Non-ferrous Metals (3).
    - The same `INDUSTRY_CATEGORY_TO_PROFILE` mapping as in PyPSA-AT (PyPSA-AT copied it).
    - Profiles apply to **electricity only**.
    - `map_profile_to_snapshots()`: average day profiles per (weekday, hour), German 2017
      holidays replaced by weekday averages, the profile rotated so that weekdays align
      with the target year, target-country holidays replaced by the Sunday profile, and a
      **3 % tolerance** check of the annual energy after the rotation (leap years).
    - Validated by the author on 3H and 365H runs (system cost differences below 0.3 %).

    **How PyPSA-AT differs**

    | Aspect | PR #1875 | PyPSA-AT |
    |---|---|---|
    | Where the profile is built | inside `build_industrial_energy_demand_per_node.py`, per horizon | separate rule `build_industrial_demand_profiles_at`, one resource file for all horizons |
    | Where it is applied | `add_industry` creates the Loads with the hourly series | `add_industry` creates flat Loads; `apply_industrial_demand_profiles` reshapes them afterwards (after the NEA override) |
    | Switch | `industry.temporal_electricity_industry_load` | `industry.demand_profiles.enable` |
    | Carriers | electricity only, hard-wired | `industry.demand_profiles.carrier_mapping` (`elec → industry electricity`), designed to accept further profile carriers |
    | Temporal aggregation | hourly, aligned to snapshots by the PR's own logic | summed onto the model's (3-hourly) snapshots with `merge_asof` |
    | Calendar | weekday rotation + holiday replacement + 3 % check | year relabelled only, no weekday alignment, no holidays |
    | Annual energy | tolerance check | exact by construction (normalised profile × flat power × weighting correction) |

    *Where in the code:* comment block above `rule build_industrial_demand_profiles_at`
    in `rules/pypsa-at/build_sector.smk`; PR page https://github.com/PyPSA/pypsa-eur/pull/1875.
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ---
    ## 9 · Final energy demand of industry in the model

    The table and chart are computed from the solved networks: annual energy of every
    industry Load carrier (Σ `p_set` × weighting) for Austria or one region. Process
    emissions are excluded here (they are CO₂, not energy).

    **Final versus useful energy.** All these Loads are *final* energy — electricity,
    gas, hydrogen, biomass, naphtha, coal, methanol and ammonia delivered to industry —
    except `low-temperature heat for industry`, which is **useful energy**: it sits on a
    heat bus and must be supplied by heat technologies (gas or biomass boilers, heat
    pumps, district heat, CHP), whose fuel input is the corresponding final energy. The
    evaluation view `view_demand_fed_sectoral` (`evals/views/demand.py`, helper
    `_get_sectoral_fed`) therefore takes all Loads matching `industry|NH3`, replaces the
    decentral heat Loads by the *fuel mix* that produced the heat
    (`apply_heat_mix_to_decentral_heat_buses`), removes distribution losses from central
    heat, adds the energy lost in the `... for industry CC` capture links as "CC losses"
    and reports everything under the sector *Industry* in TWh, grouped by the categories
    of the view config (`[view_demand_fed_sectoral]` in `evals/config.default.toml`).
    """)
    return


@app.cell(hide_code=True)
def _(AT_REGIONS, mo):
    sel_fed_region = mo.ui.dropdown(
        options=["AT (all regions)"] + AT_REGIONS,
        value="AT (all regions)",
        label="Region for the final-energy chart",
    )
    sel_fed_region
    return (sel_fed_region,)


@app.cell(hide_code=True)
def _(
    AT_REGIONS,
    EVALS_CONFIG,
    INDUSTRY_LOAD_CARRIERS,
    YEARS,
    color,
    go,
    mo,
    pd,
    sel_fed_region,
    slices,
    tomllib,
):
    _regions = (
        AT_REGIONS
        if sel_fed_region.value.startswith("AT (")
        else [sel_fed_region.value]
    )
    _cols = {}
    for _y in YEARS:
        _ind = slices[_y]["industry"]
        _ind = _ind[_ind.region.isin(_regions) & _ind.carrier.ne("process emissions")]
        _cols[_y] = _ind.groupby("carrier").annual_MWh.sum() / 1e6
    fed_table = (
        pd.DataFrame(_cols)
        .reindex([c for c in INDUSTRY_LOAD_CARRIERS if c != "process emissions"])
        .fillna(0)
    )
    fed_table.loc["total"] = fed_table.sum()
    fed_table.index.name = f"{sel_fed_region.value}: industry demand [TWh/a]"
    _fig = go.Figure()
    for _c in fed_table.index.drop("total"):
        _fig.add_bar(
            name=_c,
            x=[str(y) for y in YEARS],
            y=fed_table.loc[_c],
            marker_color=color(_c),
        )
    _fig.update_layout(
        barmode="relative",
        title=f"{sel_fed_region.value}: annual industry demand per Load carrier (solved networks)",
        yaxis_title="TWh/a",
        xaxis_title="planning horizon",
        height=450,
    )
    with open(EVALS_CONFIG, "rb") as _f:
        _evals_cfg = tomllib.load(_f)["view_demand_fed_sectoral"]
    _process = {
        y: slices[y]["industry"][
            slices[y]["industry"].carrier.eq("process emissions")
            & slices[y]["industry"].region.isin(_regions)
        ].annual_MWh.sum()
        / 1e6
        for y in YEARS
    }
    mo.vstack(
        [
            mo.md(
                f"**Key takeaway:** industry demand in {sel_fed_region.value} goes from {fed_table.loc['total', YEARS[0]]:.1f} TWh/a "
                f"({YEARS[0]}) to {fed_table.loc['total', YEARS[-1]]:.1f} TWh/a ({YEARS[-1]}); the electricity share rises from "
                f"{fed_table.loc['industry electricity', YEARS[0]] / fed_table.loc['total', YEARS[0]]:.0%} to "
                f"{fed_table.loc['industry electricity', YEARS[-1]] / fed_table.loc['total', YEARS[-1]]:.0%}. Process-emission "
                f"Loads (negative = CO₂ source): {', '.join(f'{y}: {v:.2f} MtCO₂/a' for y, v in _process.items())}. "
                f"`evals` reports this in the view *{_evals_cfg['name']}* ({_evals_cfg['unit']}, chart `{_evals_cfg['chart']}`, "
                f"file `{_evals_cfg['file_name']}`)."
            ),
            fed_table.round(2).rename(columns=str),
            _fig,
        ]
    )
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ---
    ## 10 · Configuration, switches and rebuild commands

    The table lists every key a stakeholder can change, with the value used in the run
    (from `n.meta`) and the last file of the configuration stack that defines it
    (`config.default.yaml` → `config.de.yaml` → `config.at.yaml`; scenario overrides in
    `config/scenarios.manual.yaml` come last and are merged under the scenario name,
    `AT_KN2040` here). Feature blocks carry an `enable` key as their first entry, and the
    Python code guards on it — the Snakemake DAG does not (with one exception noted in
    section 11).
    """)
    return


@app.cell(hide_code=True)
def _(cfg, config_files, pd):
    def _get(d, path):
        for k in path.split("."):
            if isinstance(d, dict) and k in d:
                d = d[k]
            else:
                return None
        return d

    _keys = [
        ("industry.annual_demand_overrides.enable", "switch the NEA override on/off"),
        (
            "industry.annual_demand_overrides.target_years",
            "planning horizons whose totals are replaced",
        ),
        (
            "industry.annual_demand_overrides.source_years",
            "NEA year used per target year",
        ),
        ("industry.annual_demand_overrides.source_category", "NEA Kategorie included"),
        (
            "industry.demand_profiles.enable",
            "switch the FfE electricity profiles on/off (also gates the build rule)",
        ),
        ("industry.demand_profiles.carrier_mapping", "profile carrier → Load carrier"),
        ("demand.carrier_to_load_mapping.industry", "NEA/model carrier → Load carrier"),
        ("industry.St_primary_fraction", "share of primary steel"),
        ("industry.DRI_fraction", "share of primary steel via H2 direct reduction"),
        ("industry.Al_primary_fraction", "share of primary aluminium"),
        ("industry.HVC_primary_fraction", "share of primary plastics feedstock"),
        ("industry.HVC_mechanical_recycling_fraction", "mechanical recycling share"),
        ("industry.HVC_chemical_recycling_fraction", "chemical recycling share"),
        (
            "industry.HVC_environment_sequestration_fraction",
            "plastics not returned as waste/CO2",
        ),
        (
            "industry.sector_ratios_fraction_future",
            "progress towards best-in-class energy intensity",
        ),
        ("industry.steam_biomass_fraction", "best-in-class steam from biomass"),
        ("industry.steam_hydrogen_fraction", "best-in-class steam from hydrogen"),
        ("industry.steam_electricity_fraction", "best-in-class steam from electricity"),
        ("industry.reference_year", "JRC-IDEES reference year for 'today'"),
        (
            "industry.hotmaps_locate_missing",
            "geocode Hotmaps sites without coordinates",
        ),
        ("industry.HVC_production_today", "EU HVC production today [Mt/a]"),
        ("sector.HVC_demand_factor", "scales the naphtha Load"),
        ("sector.ammonia", "ammonia demand as NH3 Load (regional/true/false)"),
        ("sector.methanol.regional_methanol_demand", "regional vs EU methanol Load"),
        ("sector.regional_oil_demand", "regional vs EU naphtha Load"),
        ("sector.regional_coal_demand", "regional vs EU coal Load"),
        (
            "sector.gas_network",
            "gas network; with regional_gas_demand keeps gas Loads regional",
        ),
        ("sector.biomass_spatial", "regional vs EU biomass Load"),
        ("sector.co2_spatial", "regional process-emission Loads"),
        ("pypsa-de.leitmodelle.industry", "Ariadne model for German production"),
        ("pypsa-de.reference_scenario", "Ariadne scenario for German production"),
        (
            "pypsa-de.uba_for_industry.enable",
            "years with UBA rescaling of German industry Loads",
        ),
        (
            "mods.methane_pyrolysis.plasma",
            "pyrolysis supply to the H2 for industry bus",
        ),
    ]
    _rows = []
    for _k, _desc in _keys:
        _defined = [name for name, c in config_files.items() if _get(c, _k) is not None]
        _rows.append(
            {
                "key": _k,
                "run value": str(_get(cfg, _k)),
                "last defined in": _defined[-1]
                if _defined
                else "(not in the three files)",
                "meaning": _desc,
            }
        )
    switches = pd.DataFrame(_rows).set_index("key")
    switches
    return


@app.cell(hide_code=True)
def _(RUN_RESOURCES, mo):
    mo.md(f"""
    **Rebuilding the industry resources.** Resources are scenario-aware: with
    `run.prefix` and `run.name` of `config.at.yaml` they live in
    `{RUN_RESOURCES.relative_to(RUN_RESOURCES.parents[2])}`. The commands used to rebuild the intermediates for this
    notebook (they ran in about a minute; all retrieve inputs were already present):

    ```bash
    R=resources/test-wind-at35/AT_KN2040
    pixi run snakemake $R/industrial_energy_demand_base_s_adm_2025.csv \\
                       $R/industrial_energy_demand_base_s_adm_2030.csv \\
                       $R/industrial_energy_demand_base_s_adm_2040.csv \\
                       $R/industrial_energy_demand_base_s_adm_2050.csv \\
                       $R/industrial_demand_overrides_base_s_adm.csv --cores 4
    ```

    The FfE profile resource needs the electricity pre-network (snapshot weightings), so
    its rebuild pulls in `add_electricity`, `prepare_network` and `time_aggregation`
    (28 jobs in a dry run); it was therefore taken from `n.meta` instead:

    ```bash
    pixi run snakemake resources/test-wind-at35/AT_KN2040/industrial_demand_profiles_base_s_adm__none.csv -n
    ```

    Related rules: `build_nea_at` (NEA workbooks → `resources/nea_at.csv`),
    `build_industrial_demand_overrides_at`, `build_industrial_demand_profiles_at`,
    `prepare_sector_network_at` (all in `rules/pypsa-at/build_sector.smk`), and
    `pixi run generate-config` after changing a key in `scripts/lib/validation/config/`.
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ---
    ## 11 · Limitations and open questions

    Found while building this notebook (numbers refer to the loaded run; see the
    respective sections):

    **Method and data**

    1. **Negative electric-arc steel for Austria (3.2).** The primary-steel scaling in
       `build_industrial_production_per_country_tomorrow.py` uses EU-wide sums, so Austria's
       EAF production is negative in 2025–2040. The negative tonnage is multiplied with the EAF
       ratios and *reduces* the computed electricity demand. In 2025 the NEA override hides it,
       from 2030 on it is in the Loads.
    2. **NEA only for 2025 (6.6).** The 2025 → 2030 change per carrier mixes a source switch
       with the projection. Any 2030 result that is compared with 2025 should be read with the
       JRC-only change next to it.
    3. **Naphtha semantics (6.3).** In the JRC chain `naphtha` is feedstock for HVC (non-energy
       use) and drives the process emissions from feedstock; the NEA override replaces it with
       *energetic* oil use (Diesel, Heizöl, Flüssiggas, ...) of the producing sector, because the
       NEA has no non-energy use. The `process emission from feedstock` ratio in `add_industry`
       is still computed from the JRC naphtha values.
    4. **Coke accounting (6.5).** `add_industry` converts coke to coal-equivalent with 1.366
       MWh coal/MWh coke; the override maps `coal` and `coke` to `coal for industry` and adds
       them 1:1.
    5. **Carriers without NEA data (6.3).** Hydrogen, methanol and ammonia keep their JRC values
       in 2025; NEA *Wasserstoff*, *Methanol*, *Ammoniak* are mapped but absent from the data.
       The `coke` category includes *Koks* but blast-furnace and coke-oven gas go to methane.
    6. **Population-based regionalisation (3.4, 6.3).** Only steel, chemicals, non-ferrous
       metals and paper have site-based keys; food, machinery, construction, mining, wood,
       textiles, vehicles and "other" are spread by population — for Austria this is the larger
       part of the NEA energy (share computed in 6.3). *Refineries*, *Cement* and *Glass* keys
       are site-based but only used by the JRC chain (cement, glass) or not at all (refineries).
    7. **NEA scope.** `Produzierender Bereich` includes *Bau* and *Bergbau* (construction, mining)
       and the space-heating share of industry; whether the JRC-based 2030+ values cover the
       same scope is not verified here. Agriculture is not part of the industry pipeline at all
       (its Loads come from the energy totals, `add_agriculture`).
    8. **German profiles for Austria (7.3).** The FfE shapes are German 2017 measurements;
       they are applied to all countries.
    9. **Electricity only (7.1).** Gas, hydrogen, biomass, heat, naphtha, coal, methanol and
       ammonia Loads of industry are flat for the whole year.
    10. **Calendar shift, no holidays (7.6).** The weekday dip lands on Monday/Tuesday of the
        model calendar; the upstream PR handles this, PyPSA-AT does not.
    11. **Mapping approximations (7.4).** Chemicals → paper, non-ferrous → iron & steel, pharma
        → food are documented; HVC → non-metallic minerals and *Other non-ferrous metals* →
        non-metallic minerals (while aluminium → iron & steel) are not.
    12. **Profile weights are JRC-based even in 2025 (7.5).** The NEA override changes the
        amount, not the subsector mix that shapes the profile.
    13. **Negative regional Loads are clipped (6.5).** Some regional JRC values are negative
        (e.g. hydrogen in 2025, a consequence of subtracting today's chlorine/ammonia hydrogen
        from the JRC totals); `clip_negative_loads_for_edge_cases` sets them to zero for
        horizons up to 2030, so the Austrian sum is larger than the net JRC value.

    **Code and documentation discrepancies (not edited here)**

    14. `mods/demand/industrial_demand.py` docstring refers to
        `industry.demand_profiles.definitions.*.carrier_mapping`; the actual key is
        `industry.demand_profiles.carrier_mapping`.
    15. `rule build_industrial_demand_profiles_at` is only defined when
        `industry.demand_profiles.enable` is true (`if config.get(...)` in
        `rules/pypsa-at/build_sector.smk`), and `prepare_sector_network_at` uses `branch()` on the
        same key and on `annual_demand_overrides.enable`. This makes the DAG depend on the config,
        contrary to the guideline in `CLAUDE.md` ("the Snakemake DAG must not depend on it").
    16. The docs page labels the FfE node "AT node · hourly · normalized" and the profile
        application "AT node · hourly"; the resource and the Loads are at model snapshot
        resolution (3-hourly in this run) and cover all countries' nodes, not only Austria.
    17. The docs page says the NEA override applies to "matching industry Loads"; it does not
        mention that carriers absent from the NEA (hydrogen, methanol, ammonia) keep the JRC
        values, nor the coke factor (items 4, 5, 13).
    18. `scripts/pypsa-at/build_industrial_demand_profiles.py::nodal_sector_electricity_demand`
        normalises over *all* carriers (docstring says so); only the `elec` rows are used
        afterwards, so the per-region normalisation to 1 in `build_nodal_profiles` is what makes
        the result correct — worth a comment.
    """)
    return


@app.cell(hide_code=True)
def _(NETWORK_DIR, NETWORK_PATTERN, Path, YEARS, pd):
    import datetime as _dt
    import time as _time

    import pypsa

    def _load_industry_slice(path: Path) -> dict:
        n = pypsa.Network(path)
        mapping = n.meta["demand"]["carrier_to_load_mapping"]["industry"]
        carriers = sorted(set(mapping.values()) | {"process emissions"})
        weights = n.snapshot_weightings["generators"]
        loads = n.loads[["bus", "carrier", "p_set"]].copy()
        location = loads.bus.map(n.buses.location)
        loads["region"] = location.where(location.notna() & location.ne(""), loads.bus)
        loads["bus_carrier"] = loads.bus.map(n.buses.carrier)
        loads["dynamic"] = loads.index.isin(n.loads_t.p_set.columns)
        industry = loads[loads.carrier.isin(carriers)].copy()
        dynamic_names = industry.index[industry.dynamic]
        p_set_t = n.loads_t.p_set[dynamic_names].copy()
        annual = industry.p_set * weights.sum()
        annual[dynamic_names] = p_set_t.mul(weights, axis=0).sum()
        industry["annual_MWh"] = annual
        industry_buses = industry.bus.unique()
        links = n.links[
            n.links.bus1.isin(industry_buses) | n.links.bus0.isin(industry_buses)
        ][["bus0", "bus1", "bus2", "bus3", "carrier", "p_nom_opt"]].copy()
        return {
            "name": n.name,
            "carriers": carriers,
            "weights": weights,
            "loads": loads,
            "industry": industry,
            "p_set_t": p_set_t,
            "links": links,
            "meta": n.meta,
        }

    slices = {}
    _rows = []
    for _year in YEARS:
        _path = Path(NETWORK_DIR) / NETWORK_PATTERN.format(year=_year)
        _t0 = _time.time()
        slices[_year] = _load_industry_slice(_path)
        _rows.append(
            {
                "year": _year,
                "file": _path.name,
                "last modified": _dt.datetime.fromtimestamp(
                    _path.stat().st_mtime
                ).strftime("%Y-%m-%d %H:%M"),
                "size GB": round(_path.stat().st_size / 1e9, 2),
                "network name": slices[_year]["name"],
                "snapshots": len(slices[_year]["weights"]),
                "hours per snapshot": sorted(
                    slices[_year]["weights"].unique().tolist()
                ),
                "load seconds": round(_time.time() - _t0, 1),
            }
        )
    run_info = pd.DataFrame(_rows).set_index("year")
    cfg = slices[YEARS[0]]["meta"]  # merged run configuration
    INDUSTRY_LOAD_CARRIERS = slices[YEARS[0]]["carriers"]
    CARRIER_TO_LOAD = cfg["demand"]["carrier_to_load_mapping"]["industry"]

    def cfg_year(mapping, y):
        """Year-keyed config values: n.meta (JSON) uses string keys, YAML uses ints."""
        if not isinstance(mapping, dict):
            return mapping
        return mapping.get(y, mapping.get(str(y)))

    return (
        CARRIER_TO_LOAD,
        INDUSTRY_LOAD_CARRIERS,
        cfg,
        cfg_year,
        run_info,
        slices,
    )


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### 1.1 Loading the solved networks

    Each solved network is 1.5–1.7 GB. To keep the notebook light we open each file
    once with PyPSA, extract only what this notebook needs — the Load table, the time
    series of the profiled industry Loads, the snapshot weightings, the links that feed
    the industry buses and the run configuration stored in `n.meta` — and release the
    network again. `n.meta` also contains two small resources that were used in the
    run: the NEA override table and the FfE profile resource. They are the *primary*
    source for sections 6 and 7.

    The list of industry Load carriers is taken from the run's own configuration
    (`demand.carrier_to_load_mapping.industry`) plus `process emissions`.
    """)
    return


@app.cell
def _(NETWORK_DIR, cfg, mo, run_info):
    mo.vstack(
        [
            mo.md(
                f"**Run:** `{NETWORK_DIR}` — prefix `{cfg['run']['prefix']}`, scenario "
                f"`{', '.join(cfg['run']['name'])}`, foresight `{cfg['foresight']}`, "
                f"weather year {cfg['snapshots']['start'][:4]}, sector resolution "
                f"`{cfg['clustering']['temporal']['resolution_sector']}`."
            ),
            run_info,
        ]
    )
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### 1.2 Intermediate files and their provenance

    The helper below resolves every intermediate CSV by name: first in `RUN_RESOURCES`,
    then in `FALLBACK_RESOURCES`, and for run-independent files in the shared
    `resources/` folder. The table lists which file came from where. Section 6.5 and
    section 7.8 contain the consistency checks that compare these files against the
    Loads in the solved networks, so a stale fallback file would show up as a difference.
    """)
    return


@app.cell(hide_code=True)
def _(FALLBACK_RESOURCES, RUN_RESOURCES, SHARED_RESOURCES, YEARS, pd):
    def resource_path(name: str) -> tuple:
        """Return (path, provenance label) for an intermediate resource file."""
        for folder, label in (
            (RUN_RESOURCES, "current config (rebuilt)"),
            (SHARED_RESOURCES, "shared resources"),
            (FALLBACK_RESOURCES, "FALLBACK: hydro branch 365H run"),
        ):
            if (folder / name).exists():
                return folder / name, label
        raise FileNotFoundError(f"{name} not found in any resources folder")

    _names = [
        "industrial_production_per_country.csv",
        "industrial_energy_demand_per_country_today.csv",
        "ammonia_production.csv",
        "nea_at.csv",
        "industry_sector_ratios.csv",
        "industrial_distribution_key_base_s_adm.csv",
        "industrial_energy_demand_today_base_s_adm.csv",
        "industrial_demand_overrides_base_s_adm.csv",
        "industrial_demand_profiles_base_s_adm__none.csv",
        "pop_weighted_energy_totals_s_adm.csv",
    ]
    for _y in YEARS:
        _names += [
            f"industrial_production_per_country_tomorrow_{_y}.csv",
            f"industrial_production_per_country_tomorrow_{_y}-modified.csv",
            f"industry_sector_ratios_{_y}.csv",
            f"industrial_production_base_s_adm_{_y}.csv",
            f"industrial_energy_demand_base_s_adm_{_y}.csv",
        ]
    _rows = []
    for _n in _names:
        try:
            _p, _label = resource_path(_n)
            _rows.append(
                {
                    "file": _n,
                    "provenance": _label,
                    "modified": pd.Timestamp(_p.stat().st_mtime, unit="s").strftime(
                        "%Y-%m-%d %H:%M"
                    ),
                }
            )
        except FileNotFoundError:
            _rows.append({"file": _n, "provenance": "MISSING", "modified": ""})
    provenance_table = pd.DataFrame(_rows).set_index("file")
    provenance_table
    return (resource_path,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### 1.3 Does the current configuration match the run?

    The intermediate CSVs were rebuilt with the *current* `config/config.at.yaml`, while
    the networks carry the configuration that was active when they were solved. The
    check below compares the `industry` and `demand` sections of both. Differences would
    mean that rebuilt intermediates cannot be compared one-to-one with the Loads.
    """)
    return


@app.cell(hide_code=True)
def _(CONFIG_FILES, cfg, mo, pd, yaml):
    def _load_yaml(path):
        with open(path) as f:
            return yaml.safe_load(f)

    config_files = {name: _load_yaml(path) for name, path in CONFIG_FILES.items()}

    def _flatten(d, prefix=""):
        out = {}
        for k, v in d.items():
            key = f"{prefix}{k}"
            if isinstance(v, dict):
                out.update(_flatten(v, key + "."))
            else:
                out[key] = v
        return out

    _at = config_files["config.at.yaml"]
    _diff = []
    for _section in ("industry", "demand"):
        _current = _flatten(_at.get(_section, {}), f"{_section}.")
        _run = _flatten(cfg.get(_section, {}), f"{_section}.")
        for _k, _v in _current.items():
            if str(_run.get(_k)) != str(_v):
                _diff.append(
                    {"key": _k, "config.at.yaml now": _v, "run (n.meta)": _run.get(_k)}
                )
    config_diff = pd.DataFrame(_diff)
    mo.vstack(
        [
            mo.md(
                "**Result:** the `industry` and `demand` sections of the current "
                "`config.at.yaml` are identical to the run configuration."
                if config_diff.empty
                else f"**Result:** {len(config_diff)} key(s) differ between the current config and the run:"
            ),
            config_diff,
        ]
    )
    return (config_files,)


@app.cell
def _(sel_region, sel_year):
    year = int(sel_year.value)
    region = sel_region.value
    return region, year


@app.cell
def _(DATA_DIR, VERSIONS_CSV, pd):
    _datasets = {
        "jrc_idees": "data/jrc_idees",
        "eurostat_balances": "data/eurostat_balances",
        "nitrogen_statistics": "data/nitrogen_statistics",
        "hotmaps_industrial_sites": "data/hotmaps_industrial_sites",
        "gem_gspt": "data/gem_gspt",
        "gem_gcct": "data/gem_gcct",
        "nuts3_population": "data/nuts3_population",
        "ariadne_database": "data/ariadne_database.csv",
        "nea-at": "data/nea-at",
        "ffe_industry_load_profiles": "data/ffe_industry_load_profiles",
    }
    versions = pd.read_csv(VERSIONS_CSV)
    versions = versions[versions.dataset.isin(_datasets)]
    versions = versions[versions.tags.str.contains("latest")].copy()
    versions["raw files present"] = versions.dataset.map(
        lambda d: (DATA_DIR.parent / _datasets[d]).exists()
    )
    versions_table = versions[
        ["dataset", "version", "source", "tags", "added", "raw files present", "note"]
    ].set_index("dataset")
    versions_table
    return


if __name__ == "__main__":
    app.run()
