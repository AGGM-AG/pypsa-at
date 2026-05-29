# KLIEN Renewable Energy Potentials in PyPSA-AT

PyPSA-AT limits the optimised expansion of Austrian renewable generators using empirically derived capacity
potentials from the study *Erneuerbare Energiepotenziale in Österreich 2030 & 2040* (Renewable Energy Potentials
in Austria 2030 & 2040). This page describes the study, its scenario structure, the data processing pipeline,
and how the resulting regional capacity limits are applied to the model.

For technology-specific details, see:

- [Photovoltaic Potentials](pv-potentials.md)
- [Wind Power Potentials](wind-potentials.md)

## Data Source

The input data originates from the [KLIEN study](https://www.klimafonds.gv.at/publikation/erneuerbare-energiepotenziale-in-oesterreich-fuer-2030-und-2040/), 
commissioned by the Austrian Climate and Energy Fund (KLIEN) and financed by the former Federal Ministry for Climate
Action, Environment, Energy, Mobility, Innovation and Technology (BMK). The study was conducted under the leadership of 
AIT Austrian Institute of Technology GmbH together with the Environment Agency Austria (UBA), Vienna University of
Technology (TU Wien), AEE – Institute for Sustainable Technologies (AEE INTEC), and Energiewerkstatt.

The study quantifies realisable renewable energy potentials for Austria differentiated by area category, time horizon,
ambition level, and climate scenario. The raw data is published as GeoJSON files at municipality level via the
[GTIF Austria platform](https://gtif-austria.info).

## Scenario Dimensions

Each potential dataset contains columns following this naming scheme:

```
C_{year}_{ambition}_{climate_scenario}
```

Example: `C_2040_medium_mocc`

**Time horizon** (`year`)

| Value  | Meaning                              |
|--------|--------------------------------------|
| `2030` | Realisable potential up to 2030      |
| `2040` | Realisable potential up to 2040      |

**Ambition level** (`ambition`)

| Value    | Meaning                                              |
|----------|------------------------------------------------------|
| `low`    | Conservative political and societal conditions       |
| `medium` | Moderate mobilisation assumptions                    |
| `high`   | Optimistic mobilisation assumptions                  |

**Climate scenario** (`climate_scenario`)

| Code   | Meaning                                     |
|--------|---------------------------------------------|
| `wocc` | Without climate change                      |
| `mocc` | Moderate climate change (RCP 4.5)           |
| `stcc` | Strong climate change (RCP 8.5)             |

Each file also includes the column `C_technical_potential`, which represents the maximum technical potential
without political or economic constraints. This column is used when `use_technical_potentials: true` is set in
the configuration.

## Technology Coverage and Carrier Mapping

The KLIEN datasets cover photovoltaic and wind technologies. The table below maps each KLIEN dataset type to the
corresponding PyPSA carriers:

| KLIEN dataset type | PyPSA carriers               | Notes                                         |
|--------------------|------------------------------|-----------------------------------------------|
| `buildings`        | `solar rooftop`              | Rooftop and façade PV on buildings            |
| `ground`           | `solar`, `solar-hsat`        | Ground-mounted PV; both carriers share budget |
| `wind`             | `onwind`                     | Onshore wind                                  |

`solar` and `solar-hsat` share the same ground-mounted potential because both technologies compete for the same
land area. A dedicated solver constraint (`solar_potential` in `scripts/solve_network.py`) enforces this shared
budget at solve time. See [Photovoltaic Potentials](pv-potentials.md) for details.

## Data Acquisition

The KLIEN potentials are accessed in one of two modes, controlled by `data.klien_potentials.source` in
`config/config.at.yaml`:

| Mode      | Rule                      | Behaviour                                                         |
|-----------|---------------------------|-------------------------------------------------------------------|
| `build`   | `build_klien_potentials`  | Downloads raw GeoJSON files and runs area-weighted aggregation    |
| `archive` | `retrieve_klien_potentials` | Downloads pre-aggregated CSVs directly                          |

Both modes produce identical output files in `data/klien_potentials/{source}/{version}/`.

## Data Processing: Spatial Aggregation

When `source: build`, the rule `build_klien_potentials`
(`scripts/pypsa-at/build_klien_potentials.py`) aggregates municipality-level GeoJSONs to NUTS3 and AT10 regions
using an area-weighted overlay approach:

1. **Reprojection**: Both the municipality GeoDataFrame and the NUTS3 shapes are reprojected to EPSG:3035
   (ETRS89-LAEA, equal-area) to ensure accurate fractional area computation.

2. **Polygon overlay**: `geopandas.overlay` computes pairwise intersections between municipality polygons and
   NUTS3 shapes. Each intersection fragment is weighted by `fragment_area / municipality_area`.

3. **Border correction**: Intersection fragments that land outside Austria (non-`AT` NUTS3 codes) — arising
   from minor boundary misalignments at international borders — are reassigned to the nearest Austrian NUTS3
   region via centroid-based nearest-neighbour lookup.

4. **Validation**: The sum of area weights per municipality must reach at least 0.99. If any municipality falls
   below this threshold, a `ValueError` is raised immediately. There is no fallback or silent omission.

5. **Aggregation**: Weighted potential values are summed by `nuts3` (NUTS3 code) and by `at10` (NUTS2 code,
   corresponding to the AT10 regions used at `clustering.administrative.AT = 2`).

**Output files** (per dataset type):

| File                       | Description                                    |
|----------------------------|------------------------------------------------|
| `nuts3_pv_buildings.csv`   | PV buildings potential at NUTS3 resolution     |
| `nuts3_pv_ground.csv`      | Combined ground-mounted PV potential at NUTS3  |
| `at10_pv_buildings.csv`    | PV buildings potential at AT10 resolution      |
| `at10_pv_ground.csv`       | Combined ground-mounted PV potential at AT10   |
| `nuts3_wind.csv`           | Wind potential at NUTS3 resolution             |
| `at10_wind.csv`            | Wind potential at AT10 resolution              |

The ground-mounted PV outputs (`pv_ground`) are the element-wise sum of the sealed and unsealed potentials.

## Application in the Model

The function `apply_klien_potential_limits()` in `mods/klien_potentials.py` is called during the modify step
(`modify_prenetwork()` in `mods/network_updates.py`) and sets the aggregated potentials as `p_nom_max` bounds for
extendable Austrian generators:

1. The function selects the CSV resolution matching the clustering level: `at10` for
   `clustering.administrative.AT = 2`, `nuts3` for `AT = 3`. An unsupported level emits a warning and skips.

2. The scenario column is resolved from the configuration using the pattern `C_{year}_{ambition}_{climate_scenario}`,
   or `C_technical_potential` when `use_technical_potentials: true`.

3. Brownfield capacity from previous myopic periods (retrieved via `n.statistics.installed_capacity()`) is
   subtracted from the potential value for planning horizons after 2025.

4. The remaining headroom is set as `p_nom_max` for each matching extendable generator. If the remaining
   potential falls below `p_nom_min`, `p_nom_max` is clamped to `p_nom_min` to prevent solver infeasibility.

Only generators at buses with an `AT` index prefix are modified. Generators from other countries are
left unchanged.

## Configuration

KLIEN potential limits are controlled via `mods.klien_potential_limits` in `config/config.at.yaml`:

```yaml
mods:
  klien_potential_limits:
    technologies:              # carriers to cap; empty list disables all limits
      - solar rooftop
      - solar
      - solar-hsat
      - onwind
    use_technical_potentials: false  # if true, uses C_technical_potential column;
                                     # year, ambition, and climate_scenario are then ignored
    climate_scenario: mocc     # wocc | mocc | stcc
    year: 2040                 # 2030 | 2040
    ambition: medium           # low | medium | high
```

The data version and acquisition mode are configured separately:

```yaml
data:
  klien_potentials:
    source: archive  # build | archive
    version: 2026-v2
```

**Default setting**: All four carriers are limited. The default scenario column is `C_2040_medium_mocc` —
moderate climate change, medium ambition, 2040 time horizon. Individual technologies can be removed from
`technologies` to disable limits for specific carriers without affecting others.
