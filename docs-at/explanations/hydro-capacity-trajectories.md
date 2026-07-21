# Hydro Capacity Trajectories

See [Generic Capacity Trajectories](capacity-trajectories.md) for the general `trajectories.csv`
schema and how the constraints derived from it are applied and configured. This page covers the
hydro-specific application that currently populates `trajectories.csv`.

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

