# Photovoltaic Potentials in Austria

Austria's photovoltaic expansion pathway is shaped by land availability, building stock, grid infrastructure, and
societal acceptance. The study *Erneuerbare Energiepotenziale in Österreich 2030 & 2040*, conducted on behalf of the
Austrian Climate and Energy Fund (KLIEN), quantifies these constraints at municipality level and derives realisable
PV potentials for three area categories, two target years, and three ambition storylines.

PyPSA-AT uses these potentials to constrain the optimised expansion of PV generators in Austrian regions. For the
shared data pipeline, scenario dimensions, and configuration reference, see
[KLIEN Renewable Energy Potentials](klien-potentials.md).

## PV in the KLIEN Study

The KLIEN study distinguishes three area categories for PV deployment, each governed by different technical,
economic, and social constraints:

**Buildings (rooftop and façade)**

The technical potential for roof and façade installations is derived from GIS datasets of the Austrian building
stock. System efficiency is assumed to improve over time — from 19.0 % in 2030 to 20.4 % in 2040 — reflecting
expected advances in module technology. The long-term 2040 potential extends to roof areas with global irradiation
of at least 550 kWh/m²·a, unlocking a larger share of the building stock compared to 2030. Realisable potentials
are derived by applying economic and social realisation factors to the technically usable area, differentiated
between pitched and flat roofs and weighted by three storylines (Low, Medium, High).

**Ground-mounted PV on sealed surfaces**

This category covers areas where land is already sealed or otherwise compromised, including car parks, landfills,
industrial sites, and linear technical infrastructure (e.g., motorway verges, railway embankments). These sites
combine PV deployment with minimal additional land-use conflict.

**Ground-mounted PV on unsealed surfaces**

Unsealed open land is assessed across 26 land-use categories. Areas unsuitable for ground-mounted PV — including
forests, protected natural areas, and settlement zones — are excluded from the analysis. Realisable potentials are
determined by applying economic and social realisation factors in a two-step procedure, with individual usability
factors assigned per land-use class.

The three storylines represent distinct assumptions about the pace of barrier removal:

- **Low**: Permitting, grid connection, and supply chain constraints persist. PV remains concentrated on buildings
  using the best-suited areas. Ground-mounted PV falls significantly short of its area potential.
- **Medium**: Gradual removal of administrative and grid-related barriers enables continued growth on buildings,
  complemented by increasing ground-mounted and agrivoltaic installations.
- **High**: Most barriers are resolved. Grid access is widely available. Storage, energy communities, and digital
  energy management enable high system flexibility, activating the full potential on buildings and open land.

New and renovated buildings are assumed to be PV-optimised in line with EU building regulations.

## Input Data

The study provides three GeoJSON files at municipality level, each containing `C_`-prefixed scenario columns:

| GeoJSON file                              | Area category                     |
|-------------------------------------------|-----------------------------------|
| `pv_buildings_EEPOT_W23.geojson`          | Buildings (rooftop and façade)    |
| `pv_ground_mounted_sealed_EEPOT_W23.geojson`   | Ground-mounted, sealed surfaces  |
| `pv_ground_mounted_unsealed_EEPOT_W23.geojson` | Ground-mounted, unsealed surfaces|

These files are fetched and processed by the `build_klien_potentials` rule
(`scripts/pypsa-at/build_klien_potentials.py`). The sealed and unsealed ground-mounted files are summed
element-wise to form the combined ground-mounted output (`nuts3_pv_ground.csv`, `at10_pv_ground.csv`).

## Carrier Mapping

The three area categories map to PyPSA carriers as follows:

| Area category                    | PyPSA carrier    |
|----------------------------------|------------------|
| Buildings                        | `solar rooftop`  |
| Ground-mounted (sealed + unsealed combined) | `solar`, `solar-hsat` |

`solar` (fixed-tilt ground-mounted) and `solar-hsat` (single-axis horizontal tracking) are treated as distinct
technologies but share the same physical land area. Both are capped against the combined ground-mounted potential.

## Shared Land-Use Constraint for `solar` and `solar-hsat`

Because `solar` and `solar-hsat` compete for the same land, setting the same `p_nom_max` on both carriers would
allow the model to install up to twice the available potential. `apply_klien_potential_limits()` therefore sets
identical `p_nom_max` values on both carriers as a first-order bound.

The precise combined limit is then enforced at solve time by the constraint `solar_potential` in
`scripts/solve_network.py` (`add_solar_potential_constraints()`):

```
solar_p_nom + solar_hsat_p_nom × 1.13 ≤ total_solar_potential
```

The factor **1.13** is the ratio of land-use intensities:

```
solar.capacity_per_sqkm / solar-hsat.capacity_per_sqkm = 5.1 / 4.43 ≈ 1.13
```

Single-axis tracking systems require wider row spacing to avoid self-shading, so a given land area yields
less installed capacity in MW for `solar-hsat` than for fixed-tilt `solar`. The constraint corrects for this
by penalising `solar-hsat` capacity relative to the shared land budget.
