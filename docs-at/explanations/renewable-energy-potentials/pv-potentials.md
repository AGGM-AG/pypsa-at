# PV Expansion Potentials in Austria

PyPSA-AT limits the optimised expansion of photovoltaics in Austrian regions based on empirically derived potentials
from the study "Erneuerbare Energiepotenziale in Österreich 2030 & 2040" (Renewable Energy Potentials in Austria
2030 & 2040). This page describes the data source, the available scenario categories, and the processing steps that
generate regional capacity limits for the model from the raw data.


## Data Source: KLIEN Study

The input data originates from the study
[Erneuerbare Energiepotenziale in Österreich 2030 & 2040](https://gtif-austria.info/narratives/photovoltaic)
(Renewable Energy Potentials in Austria 2030 & 2040). The study quantifies realisable PV potentials for all Austrian
municipalities, differentiated by area category, time horizon, political and economic ambition level, and climate scenario.

The raw data are provided as GeoJSON files at municipality level and are aggregated to NUTS3 and AT10 level for the
model. The data versions used are configured in `config/config.at.yaml` under `data` and recorded in
`data/versions.csv`.

## Data Categories

The study distinguishes three area categories, which are mapped to different carriers (`carrier`) in the model:

| Category | Source file | Model carrier |
|----------|-------------|---------------|
| Buildings (rooftop PV) | `pv_buildings_potential.geojson` | `solar-rooftop` |
| Ground-mounted – sealed surfaces | `pv_ground_sealed_potential.geojson` | `solar`, `solar-hsat` |
| Ground-mounted – unsealed surfaces | `pv_ground_unsealed_potential.geojson` | `solar`, `solar-hsat` |

Sealed surfaces include, for example, car parks, landfills, and industrial sites. Unsealed surfaces refer to
open-land areas suitable for agricultural or ecological use.

The potentials of the two ground-mounted categories are summed: the combined ground-mounted potential serves as a
shared upper bound for all ground-level PV carriers in a region — i.e. `solar` and `solar-hsat` share the same
budget.

## Scenario Dimensions

Each potential file contains columns following this naming scheme:

```
C_{year}_{ambition}_{climate_scenario}
```

Example: `C_2030_medium_mocc`

**Time horizon** (`year`)

| Value | Meaning |
|-------|---------|
| `2030` | Mobilisable potential up to 2030 |
| `2040` | Mobilisable potential up to 2040 |

**Ambition level** (`ambition`)

| Value | Meaning |
|-------|---------|
| `low` | Conservative political and societal framework conditions |
| `medium` | Medium mobilisation assumptions |
| `high` | Optimistic mobilisation assumptions |

**Climate scenario** (`climate_scenario`)

| Code | Meaning |
|------|---------|
| `wocc` | Without climate change |
| `mocc` | Moderate climate change (RCP 4.5) |
| `stcc` | Strong temperature climate change (RCP 8.5) |

Each file also contains the column `C_technical_potential`, which represents the maximum technical potential without
political or economic constraints.

## Data Transformation

The raw potentials are available at municipality level and are aggregated to model regions in two steps by the
Snakemake rule `aggregate_pv_potentials` (`scripts/pypsa-at/aggregate_pv_potentials.py`):

1. **Spatial assignment**: The representative point of each municipality is assigned to a NUTS3 area via a spatial
   join. Municipalities that do not fall within any polygon are assigned to the geometrically nearest NUTS3 area
   (`sjoin_nearest`).

2. **Aggregation**: The potential values (all `C_` columns) are summed by `nuts3` and `at10`. The result is written
   as CSV to `data/pv_potentials/`.

The combined ground-mounted potentials (`nuts3_pv_ground.csv`, `at10_pv_ground.csv`) are produced as the sum of the
sealed and unsealed potentials.

## Application in the Model

The function `apply_pv_potential_limits()` in `mods/pv_potentials.py` sets the aggregated potentials as `p_nom_max`
bounds for extendable Austrian solar generators:

1. The function reads the CSV at the granularity matching the clustering resolution: `at10` for
   `clustering.administrative.AT = 2`, `nuts3` for `AT = 3`.
2. The target column is constructed from the configuration using the pattern `C_{year}_{ambition}_{climate_scenario}`.
   Alternatively, the column `C_technical_potential` is used.
3. Already installed capacity from past years is subtracted from the potential value.
4. The remaining potential is set as `p_nom_max` for each extendable generator. If the potential falls below
   `p_nom_min`, `p_nom_max = p_nom_min` is set to avoid infeasibility.

Only generators at buses with the index prefix `AT` are modified. Generators from other countries (e.g. DE, CH) are
left unchanged.

For the technologies `solar` and `solar-hsat`, the same limit is applied to both. A corresponding constraint is set
in `add_solar_potential_constraints` in `solve_network.py`.

## Configuration

The PV potential limit is controlled via `mods.pv_potential_limits` in `config/config.at.yaml`:

```yaml
mods:
  pv_potential_limits:
    use_technical_potentials: false # if true, technical potentials are used.
                                    # if true, climate_scenario, year and ambition are ignored.
    enable: false           # true activates the limit
    climate_scenario: mocc  # wocc | mocc | stcc
    year: 2040              # 2030 | 2040
    ambition: medium        # low | medium | high
```

**Default setting**: The limit is enabled (`enable: true`). By default, the scenario `C_2040_medium_mocc` is used —
moderate climate change, medium ambition level, time horizon 2040.
