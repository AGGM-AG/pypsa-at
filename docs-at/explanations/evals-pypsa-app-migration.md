# Migration plan: `evals` → PyPSA App

!!! warning "Status: draft for discussion"
    This document is an implementation plan, not a description of shipped behaviour.
    It collects the findings of a scoping investigation (September 2026) and is meant to
    be refined before any code is written. Line references point at the commit this
    document was written against (`40f3348` in pypsa-at, `2cbefa3` in pypsa-app).

## 1. Goal and summary

**Goal.** Show the PyPSA-AT evaluation charts (today produced by `evals/` as static
Plotly HTML/JSON files) inside [PyPSA App](https://github.com/PyPSA/pypsa-app), with the
same content and look, while

- building on `pypsa.statistics` for aggregation and on `pypsa.plot.statistics`
  (the `n.statistics.<metric>.iplot` machinery) for chart components,
- keeping the PyPSA App fork small enough to sync with upstream frequently.

**Recommendation in one paragraph.** Extract the AT-specific evaluation logic into a
standalone, pip-installable package (working name `pypsa-at-views`) that has *no*
dependency on Snakemake, pixi, or PyPSA App. It provides (a) a global carrier mapping
registered as a custom PyPSA `carrier` grouper, (b) a custom `trade` grouper that replaces
the hand-written trade statistics, (c) a catalogue of *views* that turn a
`NetworkCollection` into a tidy DataFrame, and (d) chart renderers that delegate to
`pypsa.plot.statistics.charts.ChartGenerator.iplot` wherever possible. PyPSA App is then
extended with one generic, upstreamable *extension hook* (roughly 300 lines) that loads
such view packages via a Python entry point and exposes them under `/api/v1/views`.
The Snakemake rule keeps working through a CLI in the same package, so the static HTML
export survives until the app is the primary consumer.

**Three findings that shape the plan** (details in §5 and §6):

1. The custom-`carrier`-grouper approach from
   [pypsa-at-planning#80](https://github.com/AGGM-AG/pypsa-at-planning/issues/80) works
   on PyPSA 1.3 without patching PyPSA. Verified in a scratch experiment.
2. The trade statistics *are* reproducible with standard `supply` / `withdrawal` /
   `energy_balance` plus a custom `trade` grouper. Verified numerically against raw
   `p0`/`p1` flows.
3. PyPSA App currently has **no frontend**. The Svelte UI was removed in June 2026
   (PyPSA/pypsa-app#103) and a React replacement is announced but not started. "Show
   plots in the app" therefore has an external dependency that we do not control (§7.1).

## 2. Current state: `evals` in pypsa-at

| Item | Value |
|---|---|
| Code size | 9 086 lines Python (`evals/`), 1 683 lines TOML config |
| Registered views | 22 (`evals/views/__init__.py`), 7 view families |
| Chart classes | `ESMBarChart`, `ESMGroupedBarChart`, `ESMTimeSeriesChart`, `SankeyChart` (1 567 lines) |
| Custom statistics | `ESMStatistics(StatisticsAccessor)` in `evals/stats.py`: `trade_energy`, `trade_capacity`, `loss`, `remaining_capacity`, `technical_potential`, plus deprecated `phs_*`, `grid_*` |
| Entry points | `pixi run evals` → `evals/cli.py`; Snakemake rule `export_evaluation_pypsa_at` in `rules/pypsa-at/collect.smk:10` |
| Output | `results/<run>/evaluation/{HTML,JSON,CSV}/`, one figure per `(location[, year])` |
| Tests | `test/test_evals/test_stats.py`, `test_utils.py` (1 299 lines); no tests for views or plots |
| Pinned env | Python 3.12, pandas 2.3.3, PyPSA 1.2.4, Plotly 6.9 (`pixi.lock`) |
| Dead code | `views/curtailment.py` and `views/gridmap.py` are empty; `views/price.py` cannot run; orphaned `[view_grid_capacity]` config section |

### 2.1 How a view works today

```
NetworkCollection (one network per planning year, statistics accessor patched)
   │
   ├─ collect_myopic_statistics(nc, "supply", bus_carrier=…)      # evals/stats.py:53
   │     loops years, groupby=[location, carrier, bus_carrier, unit], drops zeros
   ├─ filter_by / rename_aggregate / .mul(-1) / concat            # evals/views/common.py
   └─ Exporter(statistics, view_config).export()                  # evals/fileio.py:227
         ├─ combine_statistics(): concat, country aggregation, EU row,
         │     unit scaling, saldo → Net Import/Export              # evals/utils.py:878
         ├─ rename_aggregate(categories from TOML)                  # evals/fileio.py:352
         ├─ pivot, groupby(plotby) → one chart per location
         └─ ESM*Chart(df, cfg).plot() → HTML + JSON
```

### 2.2 Inventory of non-standard operations

The full per-view inventory was compiled during the investigation. Condensed, every
operation that is *not* a plain `pypsa.statistics` aggregation falls into one of five
classes:

| Class | Examples | Where |
|---|---|---|
| **A. Label mapping** | 26 per-view `[view_x.categories]` tables; `Storage In` / `Storage Out` from component type; `Import Foreign` etc. from trade scope | `config.default.toml`, `common.py:78-118`, `common.py:152-156` |
| **B. Location aggregation** | cluster → country, `keep_regions`, `EU` total, country nice names; domestic trade → `Transmission Losses` after aggregation | `utils.py:758-844` |
| **C. Netting / sign** | withdrawal `.mul(-1)`; storage `supply.add(demand)` split by sign; saldo → `Net Import` / `Net Export`; heat-pump capacity sign hotfix; `MWh`→`MW` unit string patch | `common.py:107,286-300,396-414`, `utils.py:847-875` |
| **D. Derived physics** | `calculate_input_share` (virtual `ambient heat` / `latent heat`); urban heat losses split; aviation CO₂ share from `n.meta["resources"]["energy_totals"]`; sectoral FED with heat-mix expansion; Sankey link imbalances | `utils.py:395-544`, `balances.py:49-65`, `demand.py:297-451`, `sankey.py:45-118,239-278` |
| **E. Custom statistics** | `trade_energy`, `loss` | `stats.py` |

Class A and most of E can be absorbed by groupers (§5). Class B is a thin pandas layer.
Class C needs a small, explicit *transforms* layer. Class D stays custom code but only
touches four views (`balance_heat`, `balance_carbon`, `demand_*`, `sankey`).

## 3. Current state: PyPSA App

Checked out at `2cbefa3` (2026-07-01), 129 commits, essentially one core developer
(lkstrp) plus Open Energy Transition contributors. README: "early development, expect
frequent breaking changes".

| Item | Value |
|---|---|
| Stack | FastAPI + SQLAlchemy/Alembic (SQLite or Postgres) + Celery/Redis task queue; Docker compose; Python ≥ 3.13, **pandas ≥ 3.0**, PyPSA ≥ 1.2.3 |
| License | AGPL-3.0 (`LICENSE`; `pyproject.toml` still says MIT, inconsistent) |
| Frontend | **none** since PyPSA/pypsa-app#103 (June 2026). Issue #105 "Add new frontend setup (React Vite)" closed as *not planned*. Branch `pypsa-app-legacy` keeps the old Svelte UI. |
| Plot pipeline | `POST /api/v1/plots/generate {network_ids, statistic, plot_type, parameters}` → Celery task → `getattr(n.statistics, statistic).iplot.<plot_type>(**parameters)` → Plotly JSON (`services/statistics.py:36-64`). Allow-listed statistics and chart types in `utils/allowlists.py`. |
| Multi-network | `NetworkCollectionService` builds a `pypsa.NetworkCollection` from several `.nc` files, index = file stems (`services/network.py:268-300`). Files are stored as `<uuid>.nc`, so the collection index carries **no year information**. |
| Caching | In-process LRU `NetworkCache` (10 networks, TTL) + Redis result cache keyed by a hash of the task kwargs (`cache.py`) |
| Reports | `networks.reports` JSON column with a card grid (`schemas/network.py:87-105`). The removed frontend defined card types `plot`, `markdown`, `explore`, `overview`, `component_table`, and shipped a default report as YAML. This is the natural place for AT views to appear. |
| Ingest | upload, from-URL, Snakedispatch run outputs (`tasks.py:186-262`), or in-place registration in `LOCAL_MODE` |
| Extension points | none. No plugin or entry-point mechanism. |
| In flight upstream | PR #116 replaces Celery with Prefect (open, moderate size, touches the task layer we would hook into) |

Note that pypsa-at already pins `snakemake-logger-plugin-snkmt` "for better pypsa-app
integration" (`pixi.toml:134`), i.e. running pypsa-at through the app's Snakedispatch
backend is the intended long-term ingest path.

## 4. Target architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│ pypsa-at-views  (new package, MIT, no snakemake/pixi/pypsa-app imports) │
│                                                                         │
│  mapping/     global carrier mapping (TOML) keyed by                    │
│               (component, carrier, bus_carrier) [+ context]             │
│  groupers.py  carrier (nice-name override), trade, region               │
│  statistics/  loss, remaining_capacity, technical_potential             │
│  transforms/  net_storage, split_saldo, aggregate_locations, scale, …   │
│  views/       view = f(nc, params) -> pd.DataFrame with attrs           │
│  charts/      bar / facet_bar / area via ChartGenerator.iplot; sankey   │
│  registry.py  name -> (view, ParamsModel, chart)                        │
│  cli.py       export HTML/JSON/CSV  (replaces evals/cli.py)             │
└──────────────┬───────────────────────────────────┬──────────────────────┘
               │ pixi pypi-dependency              │ uv dependency
   ┌───────────▼───────────┐          ┌────────────▼─────────────────────┐
   │ pypsa-at (Snakemake)  │          │ pypsa-app fork (AGGM-AG)          │
   │ rule export_evaluation│          │ + extensions hook (~300 LOC):     │
   │ → pypsa-at-views CLI  │          │   settings.extensions, entry point │
   │                       │          │   /api/v1/views  (list, generate)  │
   └───────────────────────┘          │   get_view_task + cache            │
                                      │   card type "view" in reports      │
                                      └────────────────────────────────────┘
```

### 4.1 Package `pypsa-at-views` (working name)

**Why a separate package.** pypsa-at's pixi environment is inherited from PyPSA-Eur and
pins pandas 2.3 / Python 3.12; PyPSA App requires pandas 3 / Python 3.13. The view code
must run in both, so it needs its own CI matrix and must not import anything from the
workflow. A separate package also removes the current coupling where `evals` reads
`nc[year].meta["resources"]` and `n.meta["sector"]` (it can keep reading `n.meta`, which
travels inside the `.nc` file, but must not assume a results directory).

Alternative: keep it inside pypsa-at with a `pyproject.toml`. Simpler to start, but the
CI matrix problem remains and the app fork would have to depend on the whole workflow
repository. Recommended only if a second repository is organisationally unacceptable.

**Layers, from bottom to top.**

1. **Global mapping** (`mapping/`). One TOML/YAML table, key
   `(component, carrier, bus_carrier)` with fallbacks `(carrier, bus_carrier)` and
   `(carrier)`, value `{nice_name, color, order, pattern}`. Optional `context` key for
   the few statistic-dependent labels described in issue #80 (e.g. `Waste CHP` /
   `Waste CHP CC` merged for balances, kept apart for capacities). The 26 per-view
   `categories` tables are the source material; a script can generate the first draft
   and flag conflicts.
2. **Groupers** (`groupers.py`), registered with `pypsa.statistics.groupers.add_grouper`:
    - `carrier`: overrides the built-in. With `nice_names=False` it returns raw carriers;
      with `nice_names=True` it looks up `(c, carrier, bus_carrier@port)` in the mapping.
      Must return raw carriers for `c == "Bus"` because the built-in `bus_carrier`
      grouper calls `self.carrier(n, "Bus")` internally.
    - `trade`: classifies a branch as `local` / `domestic` / `foreign` from the
      `location` of `bus0` and `bus1` (same logic as `evals.utils.get_trade_type`).
    - `region`: `location` for `keep_regions` countries, `country` otherwise
      (optional; see §6.2 for the trade-off).
3. **Custom statistics** (`statistics/`). Only what has no `pypsa.statistics` equivalent:
   `loss` (used by residual load), `remaining_capacity`, `technical_potential`.
   `trade_energy`, `trade_capacity`, `phs_*`, `grid_*` are dropped.
4. **Transforms** (`transforms/`). Pure functions `DataFrame -> DataFrame` for class B/C
   operations: `negate_withdrawal`, `net_storage`, `split_saldo`,
   `aggregate_locations(keep_regions, add_eu, nice_names)`, `domestic_to_losses`,
   `scale_unit`, `apply_cutoff`, `to_duration_curve`. Each is small and unit-testable.
5. **Views** (`views/`). Signature `view(nc: NetworkCollection, params: ViewParams) ->
   pd.DataFrame`. A view composes statistics + transforms and returns a tidy frame with
   index `(year, location, carrier, bus_carrier)` (time series: `snapshot` columns) and
   `attrs["name"]`, `attrs["unit"]`. Views do **not** render, write files, or read config
   files. `params` is a pydantic model (location, unit, cutoff, bus_carrier subset, …)
   so the app can expose it as a JSON schema.
6. **Charts** (`charts/`). `bar`, `facet_bar`, `area` are thin adapters that call
   `ChartGenerator(nc).iplot(df, kind=…, x="year", y="value", color="carrier",
   facet_col="bus_carrier", color_discrete_map=…, color_order=…)` and then apply the AT
   styling that the ESM charts add on top (totals annotations, legend rank, footnotes,
   hover template). `sankey` stays a custom `go.Sankey` renderer; it is not expressible
   with the PyPSA chart generator.
7. **Registry and CLI**. `registry.py` maps view names to `(view, ParamsModel, chart)`;
   `cli.py` reproduces today's `pixi run evals <results>` behaviour (HTML + JSON + CSV per
   location) so `rules/pypsa-at/collect.smk` only changes its shell line.

### 4.2 PyPSA App fork: the extension hook

Keep the diff against upstream to one self-contained feature, written so it can be
proposed upstream as "custom view extensions":

| Piece | Sketch |
|---|---|
| Setting | `EXTENSIONS="pypsa_at_views"` (comma-separated import names) in `settings.py` |
| Discovery | entry-point group `pypsa_app.views`; each extension exposes `get_registry() -> dict[name, ViewSpec]` |
| Schema | `ViewSpec(name, title, description, params_schema: JSON schema, chart_kinds)` |
| Routes | `GET /api/v1/views` (catalogue), `POST /api/v1/views/generate {network_ids, view, parameters}` → `TaskQueuedResponse`, same pattern as `plots.py` |
| Task | `get_view_task` next to `get_plot_task` in `tasks.py`, wrapped in `cache("view", ttl=settings.plot_cache_ttl)` |
| Service | `services/views.py`: `load_service(file_paths)`, build the `NetworkCollection` **indexed by planning year** (from `n.meta["wildcards"]["planning_horizons"]`, falling back to `investment_periods`), call the view, render, return `fig.to_json()` |
| Reports | new card type `view` in `ReportSchema` (backend only validates `extra="allow"`, so this is a frontend concern) |

Everything else (auth, networks, runs, cache, Snakedispatch) is untouched. Upstream churn
in the task layer (Prefect PR #116) would then affect at most `tasks.py` and
`services/views.py`.

### 4.3 What must change in pypsa-at

- `rules/pypsa-at/collect.smk`: shell line calls the new CLI.
- `pixi.toml`: add `pypsa-at-views` as a pypi dependency (pinned tag); later remove
  `frozendict`, `gitpython` if nothing else needs them.
- `evals/` is deleted once the CLI reproduces the current output (§8, phase 6).
- `docs-at/how-to-guides/evals.md` and the auto-generated reference pages move to the
  package's own docs or are rewritten as "how to add a view".
- `test/test_evals/` moves into the package.

## 5. Evidence: what was verified in a scratch environment

All three experiments ran against PyPSA 1.3.0 / pandas 3 / Python 3.13 (the app's
environment), on a toy two-region, two-year network solved with HiGHS.

### 5.1 Custom `carrier` grouper with (component, carrier, bus_carrier) context

```python
from pypsa.statistics import groupers
MAPPING = {("Link", "gas pipeline", "gas"): "Gas Transport",
           ("Link", "gas pipeline", "AC"):  "Compression Energy",
           ("Link", "CCGT", "AC"):          "Thermal Powerplant",
           ("Link", "CCGT", "gas"):         "Gas for Power"}
_builtin = groupers.carrier

def carrier(n, c, port="", nice_names=True):
    raw = _builtin(n, c, nice_names=False)
    if not nice_names or c == "Bus":
        return raw
    bc = groupers.bus_carrier(n, c, port=port, nice_names=False)
    return pd.Series([MAPPING.get((c, k, b), k) for k, b in zip(raw, bc)],
                     index=raw.index, name="carrier")

groupers.add_grouper("carrier", carrier)
nc.statistics.energy_balance(groupby=["location", "carrier", "bus_carrier"],
                             bus_carrier=["AC", "gas"])
```

Result: the same `CCGT` link is labelled `Thermal Powerplant` under `bus_carrier=AC` and
`Gas for Power` under `bus_carrier=gas`; the multi-port `gas pipeline` splits into
`Gas Transport` / `Compression Energy`. The `year` level from the `NetworkCollection`
index is preserved. This resolves both ambiguities described in issue #80 without
touching PyPSA. Caveats:

- `port` and `nice_names` are only forwarded if they appear in the grouper signature
  (`pypsa/statistics/grouping.py:198-205`), so both must be declared.
- `n.statistics.<metric>.iplot` derives colours from `n.carriers.color` keyed by
  *nice names*. Mapped labels are unknown there, so charts must pass
  `color_discrete_map` from the mapping table.
- Registration is process-global (`groupers` is a module singleton). In the app this
  happens once at extension import time; in tests it needs a fixture.

### 5.2 Rendering a post-processed statistic with the PyPSA chart generator

```python
from pypsa.plot.statistics.charts import ChartGenerator
s = nc.statistics.energy_balance(groupby=["location", "carrier", "bus_carrier"],
                                 bus_carrier=["AC", "gas"], aggregate_across_components=True)
s = s.rename(index=lambda l: l[:2], level="location").groupby(level=s.index.names).sum()
s.attrs.update(name="Energy Balance", unit="MWh")
fig = ChartGenerator(nc).iplot(s, kind="bar", x="year", y="value", color="carrier",
                               facet_col="bus_carrier", stacked=True,
                               query="location == 'AT'", title="Electricity balance AT")
```

Result: a faceted stacked bar chart (`bus_carrier=AC`, `bus_carrier=gas`) with one trace
per mapped carrier, 9 kB of Plotly JSON. The same call with `kind="area"`,
`x="snapshot"`, `facet_col="year"` on a `groupby_time=False` result produced the stacked
time-series chart. This is the "plot components" reuse the goal asks for: the chart
generator accepts *any* long-format frame, so views can do arbitrary pandas work first.

What the accessor path (`nc.statistics.energy_balance.iplot.bar(...)`) cannot do:
`groupby` is derived from `x` / `color` / `facet_*` and may not be passed
(`pypsa/plot/statistics/plotter.py:79-86`), so a location filter forces a location facet.
Hence the plan renders through `ChartGenerator` directly and uses the accessor only for
ad-hoc exploration.

### 5.3 Trade statistics without `trade_energy`

```python
def trade(n, c, port=""):
    static = n.c[c].static
    if c not in n.branch_components:
        return pd.Series("", index=static.index, name="trade")
    loc0, loc1 = (static[b].map(n.buses.location) for b in ("bus0", "bus1"))
    scope = pd.Series("local", index=static.index, name="trade")
    scope[(loc0 != loc1) & (loc0.str[:2] == loc1.str[:2])] = "domestic"
    scope[loc0.str[:2] != loc1.str[:2]] = "foreign"
    return scope
groupers.add_grouper("trade", trade)

n.statistics.supply(components=["Line", "Link"], bus_carrier="AC",
                    groupby=["location", "carrier", "bus_carrier", "trade"])   # imports
n.statistics.withdrawal(components=["Line", "Link"], bus_carrier="AC",
                        groupby=["location", "carrier", "bus_carrier", "trade"])  # exports
```

Result on the toy network (line AT1→AT2 carrying 240 MWh, DC link AT2→DE at 90 %
efficiency carrying 160 MWh):

| statistic | location | trade | value |
|---|---|---|---|
| supply (import) | AT2 0 | domestic | 240 |
| supply (import) | DE0 0 | foreign | 144 |
| withdrawal (export) | AT1 0 | domestic | 240 |
| withdrawal (export) | AT2 0 | foreign | 160 |

These equal the per-port `p0`/`p1` sums that `ESMStatistics.trade_energy` computes by
hand (`evals/stats.py`, `trade_energy`), including the link loss (160 vs 144). The saldo
variant is `energy_balance` with the same `groupby`, and `trade_capacity` becomes
`optimal_capacity(groupby=[..., "trade"])`. Because `supply`/`withdrawal` are evaluated
per port, imports land in the receiving location automatically, which is what the
current code emulates with its `bus0`/`bus1` merge loop.

## 6. Obstacles and proposed solutions

### 6.1 "Some views subtract or rename series"

Split by class (see §2.2):

| Class | Proposed home | Rationale |
|---|---|---|
| A. label mapping | grouper + mapping table | one source of truth; free `nice_names=True` everywhere; `Storage In/Out` become mapping entries keyed on `component in (Store, StorageUnit)` and statistic (supply → Out, withdrawal → In) |
| B. location aggregation | `transforms.aggregate_locations` (pandas) | cheap on aggregated frames; keeps `keep_regions` and the `EU` row exactly as today. Alternative `region` grouper evaluated in §6.2 |
| C. netting / sign | `transforms/` | explicit, tested functions replacing scattered `.mul(-1)` and `.add()` calls; the heat-pump sign hotfix and `MWh→MW` patch must first be re-checked against PyPSA 1.3 (both may be obsolete) |
| D. derived physics | stays inside the four affected views | no PyPSA equivalent; document each as a "derived quantity" with a formula; port existing code with tests |

This does not eliminate custom pandas code, but it confines it to two folders with pure
functions. The views themselves become short compositions (target ≤ 40 lines each).

### 6.2 Location aggregation: transform vs grouper

A `region` grouper (`location` for AT, `country` elsewhere) would let PyPSA do the
aggregation in one pass and would work with the accessor `iplot` path. Two costs:

- `keep_regions` today yields *both* the country row and the region rows for AT; a
  grouper yields one or the other. The `EU` total row also needs a second pass.
- `domestic` trade relative to a coarser grouper silently becomes `local` and drops out,
  so the "domestic → Transmission Losses" rename would have to move into the grouper.

Recommendation: start with the transform (exact parity, simplest), keep the grouper as a
later optimisation for the app where the user picks the aggregation level interactively.

### 6.3 Trade

Solved by §5.3. Remaining work: (i) map `(trade, statistic)` → `Import Foreign` /
`Export Domestic` / … labels in the mapping layer, (ii) `split_saldo` transform for the
time-series views, (iii) `regionalize_statistics` (global import/export of EU-only fuels)
stays a transform because it is a supply-minus-demand residual, not a branch flow.

### 6.4 Year index in the app

The app names collection members after file stems (`<uuid>.nc`). The view service must
re-index the collection by planning year read from `n.meta["wildcards"]
["planning_horizons"]` (pypsa-at writes this) and sort ascending. Networks without this
metadata should get a clear error, not a silent mis-ordering.

### 6.5 Sankey

`SankeyChart` (1 567 lines) encodes the AT energy-flow topology; there is no PyPSA
counterpart. Port as-is into `charts/sankey.py`, refactor only the data preparation
(§2.2 class D) into the view. Lowest priority for the app.

## 7. Risks and dependencies

### 7.1 No frontend in PyPSA App (blocking for the stated goal)

Four ways forward, not mutually exclusive:

| Option | Effort | Notes |
|---|---|---|
| **a. Wait for the upstream React UI** | none now, unknown timeline | announced in PR #103, no issue tracks it; core dev bandwidth unclear |
| **b. Minimal server-rendered page in the fork** | ~2-3 days | `/views/{network_set}/{view}` returns a Jinja page embedding Plotly JSON; enough for stakeholders; throwaway once (a) lands |
| **c. Build a React UI in the fork** | weeks | duplicates upstream work; only if AGGM wants to own the UI |
| **d. Revive the removed Svelte UI in the fork** | ~1 week for the AT card, then ongoing upkeep | full app experience today (login, network list, report grid, plot cards); unmaintained upstream; see below |

**Option d in detail.** The Svelte frontend still exists in git history. The most
complete state is commit `252a6bf` (2026-06-22), the parent of the removal commit; it
carries the newest backend and the full UI. Branch `pypsa-app-legacy` (2026-06-12) is
ten days older and differs from main in 14 backend files, mostly `cli.py` and `uv.lock`.
Restoring `frontend/` from `252a6bf` onto a fork of main is the cleanest route, because
the backend API the UI talks to has not changed since.

| Item | Value |
|---|---|
| Stack | SvelteKit 2, Svelte 5, Tailwind 4, bits-ui, plotly.js-dist 3.6, Node 22 |
| Size | 277 source files; report components ≈ 2 700 lines (`ReportGrid` 628, `PlotCard` 354, `PlotEditorDialog` 373) |
| Build | `adapter-static` writes into `src/pypsa_app/backend/static/app`; FastAPI serves it as an SPA; Docker target `full` builds it |
| Plot contract | `plots.generate(networkIds, statistic, plotType, parameters)` → poll `/tasks/status/{id}` → `Plotly.newPlot(json)` |
| Reports | card types `plot`, `markdown`, `explore`, `overview`, `component_table` in `reportStore.svelte.ts`; default report from a YAML file |

What AGGM would add for AT views:

- `ViewCard.svelte`, a copy of `PlotCard` that calls `/views/generate` (≈ 350 lines).
- `ViewEditorDialog.svelte`, a parameter form rendered from the JSON schema the backend
  publishes per view (≈ 350 lines).
- a `view` card type in the report store and an AT default report YAML.

Roughly 700-900 lines of UI code. Three rules keep a later port to React cheap:

1. **No evaluation logic in JavaScript.** Labels, colours, ordering, units, aggregation
   all come from the Python package as Plotly JSON. `PlotCard` already sanitises
   `bus_carrier` and `query` against `network.facets` client-side; do not extend that
   pattern to views.
2. **Keep the stored card definition minimal**, e.g.
   `{type: "view", view: "balance_electricity", parameters: {...}}`. Reports live as JSON
   on the network record, so a React UI can read the same records unchanged.
3. **Add new files, do not edit upstream components.** The Svelte tree then becomes
   disposable the day the React UI lands, and the AT contribution there is one card type.

Costs: AGGM carries an unmaintained UI (no upstream security bumps for the ≈ 60 npm
dependencies), a Node toolchain in the Docker build, and any backend API change upstream
makes must be mirrored by hand in `lib/api/client.ts`.

Recommendation: (d) if stakeholders need the full app experience before the React UI
exists, otherwise (b). In both cases align with lkstrp on (a) early; the `view` card type
is the piece worth contributing upstream. If (d) is chosen, the interim page in (b) is
unnecessary.

### 7.2 Environment split

| | pypsa-at | PyPSA App |
|---|---|---|
| Python | 3.12 | ≥ 3.13 (Docker image 3.14) |
| pandas | 2.3.3 | ≥ 3.0 (copy-on-write, string dtype, `stack()` changes) |
| PyPSA | 1.2.4 | ≥ 1.2.3 (1.3.0 resolves today) |

The package needs a CI matrix over both. Expect pandas-3 fallout in
`evals/utils.py` (`insert_index_level`, `rename_aggregate`, `.stack()` in
`phs_split`) and in `plots/components.py`.

### 7.3 Upstream churn in PyPSA App

Early-stage project, single maintainer, task layer about to change (Prefect). Mitigation:
keep the fork diff to the extension hook, open the upstream PR early, and rebase the fork
on every upstream release rather than on every commit.

### 7.4 Memory and latency

`NetworkCache` holds 10 networks per worker; a myopic AT run has 4-6 planning years and
stakeholders will compare scenarios. Measure `.nc` sizes of a real run (not available in
this scoping session) and decide whether the view service should also cache the
`NetworkCollection` or the tidy view frames. Statistics on the full collection are
computed per request; Redis caches the final JSON only.

### 7.5 Licensing

PyPSA App is AGPL-3.0; the fork inherits it. The view package can stay MIT (pypsa-at's
license) only if it does not import from `pypsa_app`, which the architecture above
guarantees. Confirm with whoever owns licensing at AGGM before publishing the package.

### 7.6 PyPSA API stability

`pypsa.plot.statistics.charts.ChartGenerator` is public but undocumented as an extension
point; `groupers.add_grouper` is documented. Pin PyPSA with an upper bound in the package
and add a smoke test that runs every view against a small solved fixture network.

## 8. Phased implementation plan

Each phase ends with a reviewable PR and leaves `pixi run evals` working.

| Phase | Scope | Repo | Exit criterion |
|---|---|---|---|
| **0. Decisions** | resolve §9; measure real `.nc` sizes; agree package name and repo | planning | this document approved |
| **1. Global mapping + grouper** (issue #80) | generate mapping from the 26 `categories` tables; register custom `carrier` grouper in `evals/fileio.read_networks`; migrate `view_capacity_electricity_production` to `nice_names=True`; regression test on a solved run | pypsa-at | identical HTML/JSON for that view |
| **2. Trade grouper + transforms** | replace `trade_energy` by `trade` grouper; move class B/C code into `transforms/`; delete deprecated statistics and dead views | pypsa-at | all 22 views regression-equal (JSON diff tolerance on floats) |
| **3. Extract package** | move `evals/` → `pypsa-at-views` with `pyproject.toml`, CI matrix (py3.12/pandas2, py3.13/pandas3), CLI, tests; pypsa-at consumes it via pixi | new repo + pypsa-at | `pixi run evals` unchanged for users |
| **4. Charts on `ChartGenerator`** | re-implement `bar`, `facet_bar`, `area` on `ChartGenerator.iplot`; keep visual parity checklist (totals, legend order, patterns, footnotes); Sankey ported unchanged | package | side-by-side review of every view |
| **5. App extension hook** | fork `AGGM-AG/pypsa-app`; add settings, entry point, routes, task, service; Docker image with the package installed; UI per the §7.1 decision (server-rendered page or revived Svelte UI with a `view` card); open upstream PR | fork | AT views render from uploaded pypsa-at networks |
| **6. Decommission** | remove `evals/`, update `collect.smk`, docs, changelog | pypsa-at | no references to `evals` left |
| **7. UI** | contribute `view` card to the React UI or maintain the demo page | fork / upstream | stakeholders use the app |

Phases 1-2 are pure refactors inside pypsa-at and deliver value on their own (single
source of truth for labels, less code). Phase 5 can start in parallel with 3-4 using the
`plots` endpoint as a template.

## 9. Open questions to settle before implementation

1. **Repository layout**: separate `pypsa-at-views` repository (recommended) or a
   `pyproject.toml` inside pypsa-at?
2. **Frontend**: interim server-rendered page (7.1 b), revived Svelte UI (7.1 d), or wait for upstream React (7.1 a)?
   Has anyone talked to lkstrp about the timeline and about accepting an extension hook?
3. **Context-dependent labels** (issue #80 §3): is keying the mapping on the statistic
   name (`optimal_capacity` vs `energy_balance`) sufficient, or do we need per-view
   overrides? The inventory suggests the statistic name covers all current cases.
4. **Location aggregation in the app**: fixed to today's behaviour (country + AT regions
   + EU) or user-selectable level (needs the `region` grouper, §6.2)?
5. **Parity tolerance**: which views must be pixel-identical (stakeholder-facing) and
   which may change look when moving to `ChartGenerator`? Totals annotations and legend
   ranking are the main visual differences.
6. **Sign hotfixes**: re-verify the heat-pump `×-1` and `MWh→MW` patches against PyPSA
   1.3 before porting; if they are obsolete, drop them in phase 2.
7. **Scope of the first app release**: the 7 capacity views + 6 balance views (closest
   to plain statistics) or everything including Sankey?
8. **Ownership**: who maintains the fork sync and the upstream PR conversation?

## Appendix A: files to look at

| Purpose | Path |
|---|---|
| Custom statistics accessor | `evals/stats.py` |
| Shared view helpers (bulk of class C logic) | `evals/views/common.py` |
| Location aggregation, saldo split, unit scaling | `evals/utils.py:758-930` |
| Exporter (pivot, per-location loop, category rename) | `evals/fileio.py:227-460` |
| Chart classes | `evals/plots/{barchart,facetbars,timeseries,sankey}.py` |
| View config and per-view categories | `evals/config.default.toml` |
| App plot pipeline | `src/pypsa_app/backend/{api/routes/plots.py,services/statistics.py,tasks.py}` |
| App network loading and collection | `src/pypsa_app/backend/services/network.py` |
| App report card schema | `src/pypsa_app/backend/schemas/network.py` |
| PyPSA grouper registration | `pypsa/statistics/grouping.py` (`Groupers.add_grouper`) |
| PyPSA chart generator | `pypsa/plot/statistics/charts.py` (`ChartGenerator.iplot`) |
