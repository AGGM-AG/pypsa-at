# Code Review Instructions

## 1. No duplicated logic

Make sure the PR does not introduce logic that already exists in the repo (`mods/`, `scripts/_helpers.py`, `evals/`, `scripts/pypsa-at`, `rules/pypsa-at`, upstream PyPSA-Eur) or is repeated within the PR itself.

## 2. Docs and diagrams are up to date

Make sure `docs-at/` and `mkdocs.yml` reflect the change, including mermaid and other diagrams (e.g. `docs-at/explanations/data-flows/`, DAG images in `docs-at/assets/`).
