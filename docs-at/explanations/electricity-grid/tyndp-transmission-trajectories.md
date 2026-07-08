# TYNDP Transmission Capacity Trajectories

PyPSA-AT derives per-corridor NTC (Net Transfer Capacity) values from ENTSO-E's Ten-Year Network Development Plan (TYNDP) reference grid and investment dataset. These values are applied in two complementary ways: as **per-snapshot flow-limit constraints** that cap net power flows on every modelled interconnector during optimisation, and as **minimum expansion lower bounds** that prevent the solver from building less transmission than TYNDP-mandated targets.

This page covers transmission capacity trajectories only. For generator capacity trajectories (onshore wind, solar PV, batteries, hydrogen electrolysis), see [Open-TYNDP Capacity Trajectories](../brownfield/open-tyndp.md).

---

## Raw Data

Both input files are part of the Open-TYNDP dataset, downloaded by the `retrieve_open_tyndp` rule (`rules/open-tyndp/retrieve.smk`):

| File | Contents | TYNDP term |
|------|----------|------------|
| `Investment Datasets/GRID.xlsx`, sheet `Electricity` | Per-border capacity increases for investment projects, with a `BORDER` column tagging each row as `"Real"` or `"Concept"` | Investment Dataset |
| `Line data/ReferenceGrid_Electricity.xlsx`, sheet `2030` | Installed NTC per border in the 2030 reference grid, columns `Summary Direction 1` / `Summary Direction 2` | Reference Grid |

The dataset is retrieved from the Open-TYNDP Google Cloud Storage archive maintained by Open Energy Transition. The version entry `tyndp,2024,archive` in `data/versions.csv` points to `https://storage.googleapis.com/open-tyndp-data-store/2024`.

---

## Building the Trajectory Table

**Rule:** `build_tyndp_transmission_trajectories` in `rules/open-tyndp/build.smk` (line 222)  
**Script:** `scripts/pypsa-at/build_tyndp_transmission_trajectories.py`  
**Output:** `resources/tyndp_transmission_trajectories.csv`

The script constructs four annual snapshots that represent the NTC capacity on each border at each planning horizon:

| Year | Derivation |
|------|------------|
| 2025 | Equal to the 2030 reference grid — projects assumed already built by 2025 |
| 2030 | Summed NTC from `ReferenceGrid_Electricity.xlsx` per border |
| 2040 | 2030 base plus all `"Real"` capacity increases from `GRID.xlsx` |
| 2050 | 2040 values plus all `"Concept"` capacity increases from `GRID.xlsx` |

The distinction between `"Real"` and `"Concept"` projects reflects TYNDP maturity levels: Real projects have a firmer status (permitting or under construction), Concept projects are longer-horizon proposals. Stacking them cumulatively gives a plausible NTC trajectory through 2050.

`direct_capacity` and `indirect_capacity` carry the NTC in each direction of a border (e.g. FR→DE and DE→FR independently). Both columns are always present in the output CSV.

### Node mapping

TYNDP uses its own node codes (`AT00`, `DE00`, `ITA0`, `ITSI`, etc.). These are mapped to PyPSA-AT location strings via `TYNDP_TO_PYPSA_LOCATION_TRANSMISSION` in `mods/constants.py`. Key rules:

- Most countries have a single node: `AT00 → AT`, `DE00 → DE`, `FR00 → FR`.
- Countries with sub-national TYNDP nodes are collapsed to their PyPSA-AT cluster code: `ITSI → IT1` (Sicily), `GBNI → GB1` (Northern Ireland), `DKE1 → DK1` (East Denmark).
- Countries not modelled in PyPSA-AT (Turkey `TR00`, Ukraine `UA00`/`UA01`, Egypt `EG00`, etc.) map to `None` and their border rows are dropped before writing the CSV.
- The function `map_tyndp_nodes` (`scripts/pypsa-at/build_tyndp_transmission_trajectories.py`, line 113) raises a `ValueError` if any unknown node code appears — this guards against silent data drift in new TYNDP releases.

Border direction is **canonicalised** so that `from_node < to_node` lexicographically. Where the raw data has the opposite ordering, `direct_capacity` and `indirect_capacity` are swapped. This ensures the CSV has a unique, predictable row per corridor.

---

## Application 1: Per-Snapshot NTC Flow Constraints

**Function:** `add_cross_border_flow_limits` in `mods/constraints.py` (line 156)  
**Called from:** `scripts/pypsa-de/additional_functionality.py`  
**Enabled by:** `mods.tyndp_cross_border_flow_limits.enable: true` in `config/config.at.yaml`

During solve, two per-snapshot linopy constraints are added for every corridor in the trajectory CSV:

```
# direct direction
sum(Line-s fwd) − sum(Line-s rev) + sum(Link-p fwd) − sum(Link-p rev) ≤ direct_capacity

# indirect direction
sum(Line-s rev) − sum(Line-s fwd) + sum(Link-p rev) − sum(Link-p fwd) ≤ indirect_capacity
```

Constraint names follow the pattern `tyndp_ntc_flow_dir-{A}-{B}-{year}` (direct) and `tyndp_ntc_flow_indir-{B}-{A}-{year}` (indirect). Corridors where no matching active AC Lines or DC Links exist in the model are silently skipped with a warning.

The shared helper `compare_tyndp_and_model_borders` (`mods/utils.py`) validates that every model cross-border corridor is covered by the trajectory CSV — missing coverage raises a `ValueError`. Corridors defined in TYNDP but absent from the model are accepted (a warning is logged).

!!! info "Time-varying, not a GlobalConstraint"
    Each constraint generates one inequality per snapshot. The constraints are **not** registered as `GlobalConstraint` network objects — they operate at the snapshot level, not as annual aggregates.

---

## Application 2: Minimum Expansion Lower Bounds

**Function:** `apply_tyndp_transmission_lower_bounds` in `mods/transmission_lower_bounds.py` (line 157)  
**Called from:** `mods/network_updates.py:modify_prenetwork` (line 461)  
**Active for years listed in:** `mods.tyndp_lower_bounds.years` in `config/config.at.yaml`

This function ensures the optimizer cannot build less cross-border transmission than the TYNDP NTC target for that planning horizon. It operates on the pre-solve network (`modify_prenetwork` step), before linopy constraints are constructed.

For each corridor the function:

1. Reads the target: `NTC_target = max(direct_capacity, indirect_capacity)` — the dominant transfer direction is used as the single floor value.
2. Computes `installed_cap`: the sum of all Line and Link capacities on the corridor, weighted by `s_max_pu` / `p_max_pu` to convert rated capacity to active transfer capacity. Both extendable components (contributing their current `s_nom_min` / `p_nom_min`) and non-extendable components (contributing their fixed `s_nom` / `p_nom`) are included.
3. Derives `shortfall = NTC_target − installed_cap`. When `shortfall ≤ 0`, the target is already met and the corridor is skipped.
4. When `shortfall > 0` and extendable capacity exists, all extendable lower bounds are scaled proportionally by `cap_factor = (total_ext_cap + shortfall) / total_ext_cap`, preserving the relative distribution across parallel components.
5. When no extendable capacity is currently present (`s_nom_min = p_nom_min = 0`), the shortfall is distributed as a raw lower bound per component such that their effective capacity sum equals the shortfall.

The function validates that cross-border DC Links are modelled as bidirectional pairs with symmetric lower bounds, and raises a `ValueError` if either condition is violated.

### Why apply lower bounds separately from flow constraints?

Per-snapshot flow constraints (Application 1) cap power flows during dispatch but do not force the model to install capacity. Lower bounds on `s_nom_min` / `p_nom_min` complement them by ensuring that the installed grid itself meets TYNDP targets, regardless of whether the dispatch constraint is binding.

---

## Configuration

```yaml
mods:
  tyndp_cross_border_flow_limits:
    enable: true          # adds per-snapshot NTC constraints during solve

  tyndp_lower_bounds:
    years:                # apply s_nom_min / p_nom_min lower bounds for these horizons
      - 2030
      - 2040
```

Setting `tyndp_cross_border_flow_limits.enable: false` removes the per-snapshot constraints entirely. Setting `tyndp_lower_bounds.years` to an empty list disables all lower-bound enforcement.

---

## Interaction with Other Transmission Constraints

PyPSA-AT applies multiple transmission constraints in sequence. Their interaction is:

| Constraint | Mechanism | Scope |
|------------|-----------|-------|
| Global volume cap (`v1.25`) | `electricity.transmission_limit` → `prepare_network.py` | Total installed grid volume ≤ 125% of reference |
| TYNDP flow limits | `add_cross_border_flow_limits` (during solve) | Per-snapshot net flow per corridor |
| TYNDP lower bounds | `apply_tyndp_transmission_lower_bounds` (pre-solve) | Per-corridor minimum installed capacity |

All three can be active simultaneously. The volume cap constrains the global ceiling; the TYNDP lower bounds set per-corridor floors; the flow constraints cap dispatch-time flows independent of installed capacity.

See [Transmission Limits](electricity-transmission.md) for details on the global volume cap.  
See [Open-TYNDP Capacity Trajectories](../brownfield/open-tyndp.md) for generator capacity bounds from the same dataset.
