# CLAUDE.md — PyPSA-AT Project Context

PyPSA-AT is a sector-coupled open-source energy system optimization model for Austria, developed at AGGM (Austrian Gas
Grid Management AG).

**Upstream lineage:** PyPSA-Eur → PyPSA-DE → **PyPSA-AT** (this repo)
**Workflow engine:** Snakemake | **Package manager:** Pixi | **Python ≥ 3.12**

## Where to Work

**AT-owned files — edit freely:**

| Path                                      | Purpose                             |
|-------------------------------------------|-------------------------------------|
| `config/config.at.yaml`                   | Main AT configuration               |
| `rules/pypsa-at/`                         | AT-specific Snakemake rules         |
| `mods/`                                   | Model modification logic            |
| `evals/`                                  | Postprocessing solved networks      |
| `scripts/pypsa-at/`                       | AT-specific scripts                 |
| `test/`                                   | Tests (see *Writing Tests*)         |
| `docs-at/`, `mkdocs.yml`                  | AT documentation                    |
| `data/versions.csv`                       | Dataset version registry            |
| `Snakefile`                               | Root entry point (ok to edit)       |
| `.readthedocs.yml` and other infra files  | ok to edit                          |

**Upstream files — do NOT touch (except critical hotfixes):**

- `scripts/*.py` (except `scripts/pypsa-at/`)
- `rules/` (except `rules/pypsa-at/`)
- `config/config.default.yaml`, `config/config.de.yaml`

---

## Configuration Stack (last wins)

Loaded as `configfile:` directives at the top of `Snakefile`, in this order:

```
config.default.yaml    (PyPSA-Eur defaults)
↓
plotting.default.yaml  (PyPSA-Eur plotting defaults)
↓
config.de.yaml         (PyPSA-DE overrides)
↓
config.at.yaml ← work here  (AT10 default configuration)
↓
plotting.at.yaml       (AT tech_colors overlay — last word on plotting)
↓
scenarios.manual.yaml  (stakeholder overrides, via run.scenarios.manual_file)
```

`config/config.sysgf.yaml` (+ `config/scenarios.sysgf.yaml`) is a standalone
variant passed via `--configfile`; it is not part of the default stack.

### Feature toggles

Every new feature section in `config/config.at.yaml` (e.g. a block under `mods:`) carries
a boolean `enable` key as its first entry. The Python orchestrator in `mods/` guards on it
and returns early when `false` — the Snakemake DAG must not depend on it. New features
default to `enable: true`. Declare the key as `enable: bool` in the matching
`scripts/lib/validation/config/*.py` model and run `pixi run generate-config`.

## Workflow & DAG Phases

retrieve
↓
build_electricity
↓
build_sector
↓
modify ← most Austria-specific model changes happen here
↓
solve
↓
postprocess
↓
evals

### Key filenames not obvious from context

- `rules/pypsa-at/` — AT rules, one file per DAG phase: `retrieve.smk`, `build.smk`,
  `build_electricity.smk`, `build_sector.smk`, `modify.smk`, `solve.smk`, `collect.smk`
- `rules/pypsa-at/collect.smk` — defines `rule all_at`, the `default_target` of the workflow
- `mods/` is a package tree, not flat modules: `mods/__init__.py` (re-exports every
  orchestrator), `mods/clustering/`, `mods/constraints/`, `mods/demand/`, `mods/network/`,
  plus `mods/constants.py` and `mods/utils.py`
- `evals/cli.py` — entry point behind `pixi run evals`
- `data/versions.csv` — dataset version registry (see *Data Versions*)

### Wildcard Constraints

Global wildcard constraints are defined at the top of `Snakefile` (not in config):

```python
wildcard_constraints:
    clusters=r"[0-9]+(m|c)?|all|adm",    # e.g. 50, 10m, 5c, all, adm
    opts=r"[-+a-zA-Z0-9\.]*",            # electricity network options
    sector_opts=r"[-+a-zA-Z0-9\.\s]*",   # sector-coupling options
    planning_horizons=r"[0-9]{4}",       # e.g. 2030, 2040, 2050
```

`config/config.default.yaml` carries the PyPSA-Eur defaults (`clusters: [50]`,
`sector_opts: [""]`, `planning_horizons: [2050]`). The values that actually apply
come from `config/config.at.yaml` under `scenario:`:

```yaml
scenario:
  ll:
  - v1.25
  clusters:
  - adm
  opts:
  - ''
  sector_opts:
  - none
  planning_horizons:
  - 2025
  - 2030
  - 2040
  ...
```

**Adding new wildcards is strongly discouraged — it is rarely needed.** If you think you need one, you probably don't. Exhaust all alternatives first and discuss with the team before introducing any new wildcard.

### Snakemake

Path providers — module-level globals bound in `Snakefile` from `path_provider()` /
`script_path_provider()` in `scripts/_helpers.py`. Call them in rules, do not import them:

- `resources(...)` - path under `resources/` (scenario-aware)
- `logs(...)` - path under `logs/`
- `benchmarks(...)` - path under `benchmarks/`
- `scripts(...)` - path under `scripts/`

Rule functions from `rules/common.smk`:

- `config_provider(*keys, default=None)` - access configuration in Snakemake rules
- `dataset_version(name, ...)` - resolve a dataset URL/version from `data/versions.csv`
- `solver_threads(w)`, `memory(w)` - resource callables for `solve` rules
- `input_cutout(wildcards, cutout_names="default")` - resolve cutout inputs

Additional relevant Snakemake rule functions:

- `branch(condition, then, otherwise)` - choose different input files based on a given conditional

## Common Commands

```bash
# Pull latest before anything
git fetch --all && git pull

# Dry-run (show plan, no execution)
pixi run snakemake -n -c1 -p

# Full run
pixi run workflow

# Run specific rules (possible for rules without wildcards)
pixi run snakemake <rule> -call

# Force rebuild of specific output (filename includes wildcards)
pixi run snakemake -f <output_file> -call

# Restart after failure
pixi run snakemake -call --rerun-incomplete

# Clean up stale locks after kill
rm -rf .snakemake/locks/

# Run evaluations
pixi run evals "results/{prefix}/{scenario}"

# Linting
pixi run ruff check .
pixi run ruff format .

# Testing
pixi run pytest --result-path="results/{prefix}/{scenario}"  # all tests
pixi run pytest -m "AT" --result-path="results/{prefix}/{scenario}"  # PyPSA-AT modifications

# Generate workflow DAGs (Rules and Files)
pixi run snakemake rulegraph --cores 1
pixi run snakemake filegraph --cores 1
pixi run update-dags                   # regenerate all_at-{rule,file}graph.png

# Regenerate config defaults + JSON schema after touching scripts/lib/validation
pixi run generate-config

# Wipe logs/, resources/, benchmarks/, results/, .snakemake/ (interactive confirm)
pixi run reset

# Docs
pixi run -e doc mkdocs build --strict
```

## Working Principles

Before writing any code:

1. Analyse — read relevant files, understand existing patterns
2. Propose architecture — explain the approach, wait for feedback
3. Break into small tasks — incremental, no big-bang changes
4. Touch only what's needed — minimal, surgical edits

### Modifying Networks

When adding Austrian-specific network modifications:

1. Add business logic to `mods/`. Separate complex logic in functions and collect them in one orchestrator.
2. Register orchestrator in `mods/__init__.py`
3. Call from relevant Snakemake script
4. Add tests under `test/test_mods/` — mirror the `mods/` package layout
   (`test/test_mods/network/`, `.../constraints/`, `.../demand/`, `.../clustering/`)

### Adding Evaluation Views

To add new analysis/visualization:

1. Create view function in `evals/views/`. A view aggregates `pypsa.statistics`
2. Register views in `evals/views/__init__.py`
3. Add plotting utilities to `evals/plots/` if needed
4. Add tests for `evals/*.py` modules (not views or plots)

### Writing Documentation

Docs live in `docs-at/`, built with MkDocs. Structure follows:

| Directory                | Purpose                                       |
|--------------------------|-----------------------------------------------|
| `docs-at/explanations/`  | Conceptual background (why things work)       |
| `docs-at/how-to-guides/` | Task-oriented recipes (how to do X)           |
| `docs-at/tutorials/`     | Learning-oriented walkthroughs                |
| `docs-at/reference/`     | Auto-generated API docs — do not edit by hand |

**Adding narrative docs:**

1. Create a `.md` file in the appropriate `docs-at/` subdirectory.
2. Add an entry to the `nav:` section of `mkdocs.yml`.
3. Build locally to verify: `pixi run -e doc mkdocs build --strict`

**Available Markdown extensions:** admonitions (`!!! note`), tabbed content (`=== "Tab"`), code blocks with copy
buttons, Plotly charts, Marimo notebooks, footnotes, cross-references via `[text][module.Symbol]`.

### Writing Tests

Tests live in `test/`. Shared fixtures and `--result-path` are defined in `test/conftest.py`.

| Location            | Covers                                                          |
|---------------------|-----------------------------------------------------------------|
| `test/test_mods/`   | `mods/` — mirrors the package layout, plus its own `conftest.py` |
| `test/test_evals/`  | `evals/*.py` modules (not views or plots)                        |
| `test/test_*.py`    | `scripts/pypsa-at/` scripts, config schema, data versions layer  |
| `test/test_data/`   | Test fixtures data                                               |

A few top-level files (`test_base_network.py`, `test_build_shapes.py`,
`test_build_powerplants.py`) come from upstream — treat them like other upstream code.

`pytest.ini` puts `.`, `scripts`, `scripts/pypsa-at` and `scripts/open-tyndp` on
`pythonpath`, so import script modules directly — no `sys.path` juggling in test files.

**Unit tests** — test small isolated logic
**Integration tests** — validate business logic (`mods/`) or end-to-end results

The `nc` fixture is loaded from a solved run. Pass `--result-path` to point pytest at results:

```bash
pixi run pytest test/test_mods/ --result-path=results/{prefix}/{scenario}
```

- Use `tmp_path` (pytest built-in) for temporary files; no manual cleanup needed
- Compare DataFrames with `.compare()`: `assert df_out.compare(df_expected).empty`
- Session-scoped fixtures for expensive setup (config loading, large data); function-scoped otherwise
- prefer many small isolated and simple tests
- Group complicated large tests in a class

## Git & PR Process

- Code reviews follow the criteria in REVIEW.md
- Branch naming: feat/, fix/, chore/, docs/
- All changes to main via Pull Request + human review — no direct pushes
- `gh pr view <nr> --comments` — check review comments
- Add a short entry to `CHANGELOG.AT.md` (Keep a Changelog format) for user-visible changes
- Fill in `.github/pull_request_template.md`; its checklist is the source of truth:
  tests pass, docs updated, changelog entry, Sourcery Bot suggestions addressed,
  config changes reflected in `scripts/lib/validation`, new rules documented in `docs-at/`
- `pre-commit` runs ruff, ruff-format, codespell, snakefmt, yaml formatting, and no commits to main branch

## Conventions & Key Patterns

- Each `scripts/**/*.py` maps 1:1 to a rule name in `rules/**/*.smk`
- `inputs`/`outputs`/`params` come via the `snakemake` object
- Import one orchestrator function from `mods/` per Python script in `scripts/`
- Let the Snakemake workflow fail early on missing input (do not catch exceptions to raise warnings, just fail)
- Prefer f-strings over %s whenever possible, especially during logging
- Keep Snakemake simple: implement guard logic in Python scripts (The DAG should not depend on the config).

## Data Versions

External datasets are pinned in `data/versions.csv` (columns: `dataset`, `version`,
`source`, `tags`, `added`, `note`, `url`). Rules resolve them via `dataset_version()`
from `rules/common.smk`; `Snakefile` binds the common ones as constants
(`OSM_DATASET`, `KLIEN_POTENTIALS`, ...).

To add or bump a dataset: add a row to `data/versions.csv` (both `primary` and
`archive` sources where available), then reference it via `dataset_version()`.
`test/test_data_versions_layer.py` guards the layer.

## Common Gotchas

- Tests marked with `AT` require the ``--result-path`` argument to load solved networks
- `mods` subpackages are imported through `mods/__init__.py` re-exports — a new
  orchestrator is invisible to `scripts/` until it is added to `__all__` there
- Scripts under `scripts/pypsa-at/` live in a hyphenated directory (not a valid Python
  package name); `pytest.ini`'s `pythonpath` is what makes them importable in tests
