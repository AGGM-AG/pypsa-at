# Sourcery review rules for PyPSA-AT

Sourcery's AI reviewer does **not** read `CLAUDE.md`, `REVIEW.md` or any other
instruction file in the repository, and `.sourcery.yaml` rejects free-text
instructions. The only way to make Sourcery follow those documents is to enter
them as **Review rules** in the Sourcery dashboard:

> app.sourcery.ai → *Repo settings* → `AGGM-AG/pypsa-at` → *Review rules*

Each review rule is one short imperative sentence plus a comma-separated list of
path globs it applies to. Sourcery checks every rule against the diff of the
matching files and only comments when a rule is violated. Keep the sentences
explicit and actionable; Sourcery ignores vague "ensure that" phrasing.

This file is the source of truth for what is configured in the dashboard.
When `REVIEW.md` or `CLAUDE.md` changes, update the rules here **and** in the
dashboard in the same PR.

## Recommended dashboard settings

| Setting                     | Value                                   | Why                                                                                |
|-----------------------------|-----------------------------------------|------------------------------------------------------------------------------------|
| Review profile              | *Balanced*                              | *Verbose* floods PRs with nits; *Quiet* hides the maintainability findings we want. |
| PR summary                  | on                                      | Fills the "Changes proposed" section of the PR template.                           |
| Reviewer's guide            | on                                      | File-by-file map, useful for the human reviewer.                                   |
| Mermaid diagrams            | off                                     | Rarely helpful for pandas / PyPSA code, adds noise.                                |
| Tips and commands           | off                                     | Boilerplate footer on every review.                                                |
| Approvals                   | off                                     | Human review is mandatory (see CLAUDE.md "Git & PR Process").                      |
| Review draft pull requests  | off                                     | Review once the author asks for it.                                                |
| Base branches               | `main`                                  | Feature branches stacked on other branches are reviewed on merge to `main`.        |
| Keywords to ignore          | `[skip sourcery]`, `WIP`                | Opt-out in the PR title.                                                           |
| Path filters (exclude)      | see below                               | Mirrors the `ignore` list of `.sourcery.yaml` for the AI reviewer.                 |

Path filters to exclude (one per line in the dashboard):

```
data/**
resources/**
results/**
benchmarks/**
logs/**
cutouts/**
envs/**
docs-at/reference/**
test/test_data/**
pixi.lock
**/*.ipynb
**/*.nc
**/*.csv
```

## Review rules

Paste each row as one rule. Glob patterns are comma-separated in the dashboard.

### 0. How to report (REVIEW.md §5)

| Rule                                                                                                                                                                                                                | Paths |
|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|-------|
| For every finding state the severity, the exact file and line (or the missing artifact), what is wrong and when it occurs, the consequence, and a concise fix; add a minimal example when the trigger is not obvious. | `**`  |
| Separate correctness issues from optional improvements, and do not report speculative issues or pre-existing problems that the diff does not introduce or expose.                                                    | `**`  |

### 1. Correctness (REVIEW.md §1)

| Rule                                                                                                                                                                                                                       | Paths                                                                            |
|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------|
| Flag changes to numeric behaviour where units, sign conventions, index alignment, component or carrier selection, or snapshot and investment-period weightings could be wrong, and state the concrete failing case.        | `mods/**,evals/**,scripts/pypsa-at/**`                                           |
| Flag results that depend on local state or undeclared inputs, such as files not declared as Snakemake inputs, environment variables, the current date, or non-deterministic ordering.                                      | `mods/**,evals/**,scripts/pypsa-at/**,rules/**,Snakefile`                        |
| Do not catch exceptions only to log a warning and continue; missing or invalid input must make the workflow fail.                                                                                                          | `mods/**,evals/**,scripts/pypsa-at/**`                                           |
| Require a focused test under `test/` for every changed behaviour in `mods/`, `evals/*.py` or `scripts/pypsa-at/`, and a regression test for every bug fix.                                                                 | `mods/**,evals/*.py,scripts/pypsa-at/**`                                         |
| When a configuration key, function signature or output schema changes, check backward compatibility and that every caller, config file and scenario file is updated.                                                       | `mods/**,evals/**,scripts/pypsa-at/**,scripts/lib/validation/**,config/**`       |
| For Snakemake rule changes verify that inputs, outputs, params, wildcards, resources and dependencies are consistent; guard logic belongs in the Python script, and the DAG must not depend on config values.               | `rules/**,Snakefile`                                                             |
| A new config key under `config/config.at.yaml` needs a default, a pydantic model in `scripts/lib/validation/config/`, and regenerated defaults and schema via `pixi run generate-config`; a new feature section starts with `enable: bool`. | `config/config.at.yaml,scripts/lib/validation/**`                    |
| Do not introduce new Snakemake wildcards; use config options or existing wildcards instead.                                                                                                                                | `rules/**,Snakefile`                                                             |
| A new or bumped external dataset needs a row in `data/versions.csv` (primary and archive source) and must be resolved via `dataset_version()`; do not hard-code download URLs in rules.                                    | `rules/**,Snakefile,data/versions.csv`                                           |

### 2. Reuse (REVIEW.md §2)

| Rule                                                                                                                                                                                                  | Paths                                            |
|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|--------------------------------------------------|
| Flag logic that duplicates helpers already available in `mods/utils.py`, `scripts/_helpers.py`, `evals/`, `scripts/pypsa-at/`, upstream PyPSA-Eur or `pypsa.statistics`, and name the existing helper. | `mods/**,evals/**,scripts/pypsa-at/**`           |
| Prefer clear pandas vectorisation and `pypsa.statistics` over row-wise loops, but do not trade correctness or readability for reuse or vectorisation.                                                  | `mods/**,evals/**,scripts/pypsa-at/**`           |

### 3. Maintainability (REVIEW.md §3, CLAUDE.md conventions)

| Rule                                                                                                                                                                                     | Paths                                                                                  |
|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------|
| Every new or changed function must annotate all parameters and the return value.                                                                                                        | `mods/**,evals/**,scripts/pypsa-at/**,scripts/lib/**`                                  |
| Public or non-obvious functions need a short NumPy-style docstring with parameter descriptions; do not repeat type information in the docstring.                                         | `mods/**,evals/**,scripts/pypsa-at/**,scripts/lib/**`                                  |
| If a function has more than one responsibility, propose a split and name each responsibility.                                                                                            | `mods/**,evals/**,scripts/pypsa-at/**`                                                 |
| Use f-strings, including in logging calls, instead of `%`-formatting or `str.format`.                                                                                                    | `mods/**,evals/**,scripts/pypsa-at/**,scripts/lib/**,test/**`                          |
| A new orchestrator in `mods/` must be exported from `mods/__init__.py`, and each script in `scripts/pypsa-at/` imports exactly one orchestrator from `mods`.                               | `mods/**,scripts/pypsa-at/**`                                                          |
| New evaluation views go into `evals/views/` and must be registered in `evals/views/__init__.py`; plotting helpers go into `evals/plots/`.                                                | `evals/**`                                                                             |
| Tests must mirror the `mods/` package layout under `test/test_mods/`, use `tmp_path` for files, compare DataFrames with `.compare()`, and stay small; group large tests in a class.        | `test/**`                                                                              |
| Do not modify upstream PyPSA-Eur or PyPSA-DE files unless the PR description states a critical hotfix; Austria-specific changes belong in `mods/`, `scripts/pypsa-at/` or `rules/pypsa-at/`. | `scripts/*.py,scripts/open-tyndp/**,rules/*.smk,config/config.default.yaml,config/config.de.yaml` |
| Keep Snakemake rules simple: guard logic and config-dependent branching go into the Python script, not into the rule.                                                                     | `rules/**,Snakefile`                                                                   |

### 4. Documentation (REVIEW.md §4, CLAUDE.md "Writing Documentation")

| Rule                                                                                                                                                                                                  | Paths                                                                     |
|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------|
| Documentation must be written for energy-system experts who are not programmers; flag text that assumes programming knowledge, leans on code-level detail instead of concepts, or uses unexplained jargon. | `docs-at/**/*.md,README.md`                                          |
| Substantial or user-visible changes need an update in `docs-at/`, an `mkdocs.yml` nav entry for new pages, and updated Mermaid diagrams, data-flow docs and DAG assets when workflows or data flows change. | `mods/**,rules/**,scripts/pypsa-at/**,evals/**,docs-at/**,mkdocs.yml` |
| User-visible behaviour changes need a short entry in `CHANGELOG.AT.md` (Keep a Changelog format); refactors, relocations, tooling and docs-only changes do not.                                        | `mods/**,rules/pypsa-at/**,scripts/pypsa-at/**,evals/**,config/config.at.yaml` |
| New rules under `rules/pypsa-at/` must be documented in the appropriate `docs-at/` page.                                                                                                              | `rules/pypsa-at/**`                                                       |

## Keeping this in sync

- `REVIEW.md` is the human-readable contract; this file is its Sourcery encoding.
- `.sourcery.yaml` carries the pattern-based part (type annotations, function
  length, print statements, f-strings, `sys.path` in tests) so those findings
  come from deterministic rules rather than from the language model.
- Org-level defaults in the dashboard apply to every AGGM repository. Set the
  rules above as **repository** rules for `pypsa-at` so they do not leak into
  other projects.
