# Code Review Instructions

Review the PR against its target branch. Prioritize functional correctness and report only actionable issues introduced or exposed by the change.

## 1. Verify correctness

Check behavior, tests, edge cases, error handling, units, sign conventions, index alignment, component/carrier selection, and snapshot or investment-period weightings. Results must be deterministic and independent of local state or undeclared inputs.

Require focused tests for changed behavior and regression tests for bug fixes. Check compatibility when configuration keys, APIs, or output schemas change.

For Snakemake changes, verify inputs, outputs, parameters, wildcards, resources, and dependencies. Configuration options must have appropriate defaults, validation, and documentation.

## 2. Prefer reuse and established interfaces

Do not duplicate logic available within the PR, `mods/`, `scripts/_helpers.py`, `evals/`, `scripts/pypsa-at`, `rules/pypsa-at`, upstream PyPSA-Eur, or dependencies.

Prefer shared helpers, clear pandas vectorization, and `pypsa.statistics` where they provide the required behavior. Do not sacrifice correctness or readability solely for reuse or vectorization.

## 3. Keep code maintainable

Code must be concise and easy to follow. If a function has multiple responsibilities, propose a split and name the responsibilities.

Functions must have typed parameters and return values. Public or non-obvious functions need short NumPy-style docstrings with parameter descriptions and no duplicated type information.

## 4. Keep project documentation current

Documentation must be written for its audience: energy-system experts who are not programmers. Flag docs that assume programming knowledge, lean on code-level detail instead of explaining concepts, or use unexplained implementation jargon.

Update `docs-at/` and `mkdocs.yml` for substantial or user-visible changes. Update Mermaid diagrams, data-flow documentation, and DAG assets when workflows, architecture, or data flows change.

## 5. Report precise findings

For each finding, state:
- severity,
- exact file and line, or the missing artifact,
- what is wrong and when it occurs,
- the consequence,
- a concise fix suggestion.

Include a minimal example when the trigger is not obvious. Separate correctness issues from optional improvements, and do not report speculative issues or unrelated pre-existing problems.