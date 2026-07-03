# Generic Capacity Trajectories

## The `trajectories.csv` Schema

| Column     | Meaning                                                                 |
|------------|--------------------------------------------------------------------------|
| `year`     | Planning horizon the row applies to                                     |
| `region`   | Country/region code (e.g. `AT`, `DE`, `IT0`) — expanded to model buses  |
| `carrier`  | PyPSA carrier name of the components to be aggregated and constrained    |
| `variable` | `"{Component}-{property}"`, e.g. `Generator-p_nom`, `Link-p_nom`, `Store-e_nom` |
| `sense`    | `max` (upper bound) or `min` (lower bound)                              |
| `value`    | Target capacity level (MW or MWh, matching the property's unit)         |

The `variable` column is the key design choice that makes the mechanism generic: it names the
PyPSA component class (`n.components[component].df`) and the attribute (`property`) to bound,
so the same code path can express "cap all `Generator`s with carrier `ror` at `p_nom` ≤ X" or
"cap all `Store`s with carrier `PHS store` at `e_nom` ≤ Y" without any per-technology branching.
Adding a new use case (e.g. a solar capacity cap, an industrial demand-side limit) only requires
adding rows to the CSV — no changes to `mods/constraints/trajectories.py` are needed, as long as
the target component exposes a `carrier` column and the standard `{property}`/`{property}_min`/
`{property}_max`/`{property}_extendable` attributes.

---

## Building the Trajectories (Hydro Application)

**Script:** `scripts/pypsa-at/build_capacity_trajectories.py`
**Rule:** `build_capacity_trajectories` (`rules/pypsa-at/build.smk`)
**Output:** `resources/trajectories.csv`

For the current hydro use case, the script:

1. Reads PEMMDB `MarketNodeInfo` sheets from every `PEMMDB_<country>_Hydro_Inflows_<year>.xlsx`
   file in the Open-TYNDP "Hydro Inflows" folder (`extract_hydro_capacities_tyndp`). Each sheet
   reports installed capacity (MW) and energy volume (GWh) for run-of-river, reservoir, and both
   open- and closed-loop pumped-storage (PS) technologies, per TYNDP node and year.
2. Maps TYNDP node codes to PyPSA-AT country codes via `TYNDP_TO_PYPSA_LOCATION`
   (`mods/constants.py`), and the PEMMDB technology labels to `(carrier, variable, sense)`
   tuples via `HYDRO_CARRIER_MAPPING` — also in `mods/constants.py`. Both mappings are applied
   generically through the reusable helper `_map_index`, which expands a single index level into
   one or more new levels based on the mapping's (possibly tuple-valued) targets.
3. Drops rows whose mapping resolves to `None` (e.g. `"... - GWh"` energy volumes, which are
   informational only and are not turned into capacity constraints).
4. Fills in any planning horizon or region missing from the raw PEMMDB data with `value = 0`
   (`add_missing_years`, `add_missing_regions`), so that every configured planning horizon and
   every modelled country has a defined (possibly zero) row for the constraint step to consume.

### Hydro Technology Mapping

```python
HYDRO_CARRIER_MAPPING = {
    "Run of River - MW":        ("ror", "Generator-p_nom", "max"),
    "Pondage - MW":              ("ror", "Generator-p_nom", "max"),
    "Pondage - GWh":              ("ror", None, None),
    "Reservoir - MW":            ("hydro discharger", "Link-p_nom", "max"),
    "Reservoir - GWh":            ("hydro store", "Store-e_nom", "max"),
    "PS Open (turbine) - MW":    ("PHS discharger", "Link-p_nom", "max"),
    "PS Open (pump) - MW":       ("PHS charger", "Link-p_nom", "max"),
    "PS Open - GWh":              ("PHS store", "Store-e_nom", "max"),
    "PS Closed (turbine) - MW":  ("PHS discharger", "Link-p_nom", "max"),
    "PS Closed (pump) - MW":     ("PHS charger", "Link-p_nom", "max"),
    "PS Closed - GWh":             ("PHS store", "Store-e_nom", "max"),
}
```

This mapping is the only hydro-specific artifact in the whole feature — everything downstream
of it (constraint construction, region aggregation, brownfield deduction) is carrier-agnostic.
---

## Applying the Constraints

**Module:** `mods/constraints/trajectories.py`
**Entry point:** `constraint_generic_trajectories(n, snakemake, investment_year)`
**Called from:** `scripts/pypsa-at/additional_functionality.py`, once per planning horizon during solve

```python
constraint_generic_trajectories(n, snakemake, investment_year)
```

If `scenario.trajectories.apply_trajectories` is `false`, the function returns immediately.
Otherwise, for the given `investment_year` it:

1. **Filters** `trajectories.csv` to the current year and expands each `region` into the
   matching model bus locations (`add_regions_to_trajectories` → `_get_region_mapping`).
   Region codes are matched by prefix (e.g. `AT` matches `AT111`, `AT112`, …), and `EU` maps to
   every model region. Kosovo (`XK`) is appended to Serbia's (`RS`) region group as a proxy,
   since PEMMDB has no dedicated Kosovo entry.
2. **Groups rows by `(variable, sense)`** — i.e. by which PyPSA component/attribute/bound
   direction is being constrained — and processes each group independently via
   `calculate_limit`.
3. **Calculates effective limits** (`calculate_limit`): for each trajectory row, existing
   non-extendable capacity is subtracted from the target value (mirroring the brownfield
   deduction used for Open-TYNDP trajectories), and the result is clamped so it never falls
   below the capacity already mandated by extendable components' own `p_nom_min`/`p_nom_max`
   bounds. Limits are clipped to be non-negative.
4. **Builds the linopy expression** (`build_model_expression`): selects the relevant network
   decision variable (e.g. `n.model.variables["Link-p_nom"]`) for exactly the components that
   matched a trajectory row, and sums them per trajectory row (one aggregate expression per
   `region`/`carrier` combination — potentially spanning many clustered buses).
5. **Adds the constraint** (`apply_constraint`): `sum(components) <= limit` for `sense="max"`,
   `sum(components) >= limit` for `sense="min"`, with a small epsilon
   (`scenario.trajectories.eps`) applied to avoid infeasibilities from floating-point ties at
   the boundary. A bookkeeping `GlobalConstraint` entry is registered (named
   `Trajectories {variable} {limit_name} for carriers {carriers}`) so repeated solves don't
   accumulate duplicate constraints.

Because every step operates purely in terms of `component`/`property`/`carrier` strings read
from the CSV, this pipeline works unchanged for any future non-hydro trajectory: it never
imports carrier lists or component names from hydro-specific code.

---

## Configuration

```yaml
scenario:
  trajectories:
    apply_trajectories: true  # master switch for the generic trajectory constraints
    eps: 0.1                  # slack applied to upper/lower bounds (MW / MWh)
```

Set `apply_trajectories: false` to disable all generic trajectory constraints without removing
`trajectories.csv` from the workflow.

!!! note "Only fully wired for myopic foresight"
    `rules/pypsa-at/solve.smk` passes `trajectories_eps` and the nested
    `scenario.trajectories.apply_trajectories` key only to the myopic solve rule (the foresight
    mode PyPSA-AT currently runs, inherited from `config.de.yaml`). The overnight and
    perfect-foresight variants still read a flat `scenario.apply_trajectories` key that is not
    set anywhere in `config/config.at.yaml`; these foresight modes would need their `params` and
    the config key aligned before generic trajectories can be used with them.

---

## Adding a New Trajectory Constraint

To constrain a new component/carrier via this framework, no changes to
`mods/constraints/trajectories.py` are required:

1. Produce (or extend) a CSV with `year, region, carrier, variable, sense, value` rows for the
   desired component/property (e.g. `Generator-p_nom`/`max` for a solar capacity cap).
2. Ensure the target network component has a `carrier` column and the standard extendable
   attribute set (`{property}`, `{property}_min`, `{property}_max`, `{property}_extendable`).
3. Feed the CSV into `resources/trajectories.csv` (either by extending
   `build_capacity_trajectories.py` or adding a separate build rule that writes to the same
   output schema).

`constraint_generic_trajectories` will pick up the new rows automatically on the next solve.
