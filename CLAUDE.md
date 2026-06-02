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
| `test/test_mods/`, `test/test_evals/`     | Tests for `mods/` and `evals/` code |
| `Snakefile`                               | Root entry point (ok to edit)       |
| `.readthedocs.yaml` and other infra files | ok to edit                          |

**Upstream files — do NOT touch (except critical hotfixes):**

- `scripts/*.py` (except `scripts/pypsa-at/`)
- `rules/` (except `rules/pypsa-at/`)
- `config/config.default.yaml`, `config/config.de.yaml`

---

## Configuration Stack (last wins)

config.default.yaml   (PyPSA-Eur defaults)
↓
config.de.yaml        (PyPSA-DE overrides)
↓
config.at.yaml ← work here
↓
scenarios.manual.yaml  (stakeholder overrides)

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

- `rules/pypsa-at/modify.smk`  the single AT Snakemake rule file
- `mods/__init__.py`, `mods/clustering.py`, `mods/constraints.py`, `mods/network_updates.py`

### Wildcard Constraints

Global wildcard constraints are defined at the top of `Snakefile` (not in config):

```python
wildcard_constraints:
    clusters=r"[0-9]+(m|c)?|all|adm",    # e.g. 50, 10m, 5c, all, adm
    opts=r"[-+a-zA-Z0-9\.]*",            # electricity network options
    sector_opts=r"[-+a-zA-Z0-9\.\s]*",   # sector-coupling options
    planning_horizons=r"[0-9]{4}",       # e.g. 2030, 2040, 2050
```

Default values come from `config/config.default.yaml` under `scenario:`:
```yaml
scenario:
  clusters: "adm"
  opts: ""
  sector_opts: "none"
  planning_horizons: 
  - 2050
```

**Adding new wildcards is strongly discouraged — it is rarely needed.** If you think you need one, you probably don't. Exhaust all alternatives first and discuss with the team before introducing any new wildcard.

### Snakemake

Use helper functions from `scripts/_helpers.py`:

- `resources()` - Path to resources/ directory (scenario-aware)
- `logs()` - resolves Path to logs/
- `benchmarks()` - resolves Path to benchmarks/
- `scripts()` - resolves Path to scripts/
- `config_provider()` - fetch items from the config 

Rule functions from `rules/common.smk`:

- `config_provider()` - to access configuration in Snakemake rules

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
4. Add tests to `test/test_mods.py`

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

Tests live in `test/test_mods/` and `test/test_evals/`. Shared fixtures are in `test/conftest.py`.

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

- Branch naming: feat/, fix/, chore/, docs/
- All changes to main via Pull Request + human review — no direct pushes
- gh pr view <nr> --comments # check review comments

## Conventions & Key Patterns

- Each `scripts/**/*.py` maps 1:1 to a rule name in `rules/**/*.smk`
- `inputs`/`outputs`/`params` come via the `snakemake` object
- Import one orchestrator function from `mods/` per Python script in `scripts/`
- Let the Snakemake workflow fail early on missing input (do not catch exceptions to raise warnings, just fail)
- Prefer f-strings over %s whenever possible, especially during logging
- Keep Snakemake simple: implement guard logic in Python scripts (The DAG should not depend on the config). 

## Common Gotchas

- Tests marked with `AT` require the ``--result-path`` argument to load solved networks

## Agent Routing

Adopt the appropriate role based on task type:

- **Product Owner** (`.claude/agents/product-owner.md`): GitHub issue management, backlog prioritisation, feature planning, stakeholder questions, upstream research
- **Developer** (`.claude/agents/developer.md`): Code implementation, bugfixes, tests, Snakemake rules, refactoring  
