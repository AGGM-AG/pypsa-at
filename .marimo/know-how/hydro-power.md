# Hydro Power in PyPSA-AT

Austria's high share of hydroelectric generation makes hydro a structurally important component of the model.
PyPSA-AT represents three distinct hydro technologies, all sourced from powerplantmatching data and fixed in
capacity throughout the myopic planning horizon. Currently, no investment pathway or decommissioning schedule applies to
any hydro technology.

## Component Types

### Run-of-River (`ror`)

**PyPSA component:** `Generator`  
**Code:** `scripts/add_electricity.py`, function `attach_hydro`, lines 832–848

Run-of-river plants have no reservoir. Water must be used as it arrives, so the technology is modelled as a
Generator with a time-varying upper bound rather than a StorageUnit.

| Attribute | Value |
|---|---|
| `p_nom` | From powerplantmatching (existing capacity) |
| `p_max_pu` | Time-varying: inflow (MW) ÷ `p_nom`, clipped to ≤ 1.0 |
| `efficiency` | From cost data (`costs.at["ror", "efficiency"]`) |
| `p_nom_extendable` | `False` — no investment possible |

The optimizer can curtail dispatch below the inflow bound but cannot store surplus.

### Pumped Hydro Storage (`PHS`)

**PyPSA component:** `StorageUnit`  
**Code:** `scripts/add_electricity.py`, function `attach_hydro`, lines 850–867

PHS is modelled as a closed-loop storage unit. No natural inflow is assumed.

| Attribute | Value |
|---|---|
| `p_nom` | From powerplantmatching |
| `max_hours` | From `renewable.hydro.PHS_max_hours` config (default **6 h**); overrides zeros and NaN values from data |
| `efficiency_store` | `sqrt(PHS_efficiency)` |
| `efficiency_dispatch` | `sqrt(PHS_efficiency)` |
| `cyclic_state_of_charge` | `True` |
| `inflow` | None |

Round-trip efficiency is split symmetrically so both pump and turbine directions are penalised equally.
For example, an efficiency of 0.8 yields `sqrt(0.8) ≈ 0.894` in each direction.

### Hydro Reservoir (`hydro`)

**PyPSA component:** `StorageUnit`  
**Code:** `scripts/add_electricity.py`, function `attach_hydro`, lines 869–938

Reservoir plants fill passively from river inflow. There is no pumping capability: `efficiency_store=0`.
Dispatch is bounded by installed capacity and by the accumulated water volume in the reservoir.

| Attribute | Value |
|---|---|
| `p_nom` | From powerplantmatching |
| `max_hours` | Derived per country from EIA reservoir storage statistics (see [Storage Sizing](#storage-sizing)); fallback 6 h |
| `efficiency_store` | **0.0** — passive filling only, no pumping |
| `efficiency_dispatch` | From cost data |
| `inflow` | Time-varying (MW) from `resources/profile_hydro.nc` |
| `cyclic_state_of_charge` | `True` — net generation over the optimization period equals net inflow |
| `marginal_cost` | Near-zero value from `data/custom_costs.csv` (anti-degeneracy, prevents indifference on dispatch timing) |

## Inflow Time Series

**Code:** `scripts/build_hydro_profile.py`  
**Output:** `resources/profile_hydro.nc`

The inflow profile is shared by both `ror` and `hydro` reservoir plants. It is computed in three steps:

1. **Runoff from atlite** — the ERA5 cutout produces hourly runoff aggregated over each country's
   land area using country shapes from `snakemake.input.country_shapes`.
2. **Normalization to EIA statistics** — the runoff series is scaled so that the annual total matches EIA
   historical hydro generation figures for each country. This ties the modelled inflow to observed
   national production rather than raw meteorological runoff.
3. **Plant-level distribution** — within each country, the national inflow is split across individual
   plants proportional to their `p_nom` (`add_electricity.py:811`).

For years where EIA data is unavailable, the country's **median** annual generation across all available
years is used as the normalization target (`build_hydro_profile.py:200–202`).

Note: Inflow is not updated across planning horizons. `add_brownfield.py:240` explicitly skips `hydro` when updating 
renewable profiles between myopic steps. The same weather-year inflow series (derived from the 2013 cutout by default)
is used in all planning horizons: 2025, 2030, 2040, and 2050.

## Storage Sizing

**Code:** `scripts/add_electricity.py:888–913`

Reservoir `max_hours` is computed per country from EIA capacity statistics using the method set in
`renewable.hydro.hydro_max_hours` (default: `energy_capacity_totals_by_country`):

```
max_hours = (EIA E_store[TWh] − already_installed_storage) / remaining_p_nom
```

Countries with missing EIA data are assigned the **6 h fallback** and a warning is logged:
`"Assuming max_hours=6 for hydro reservoirs in the countries: …"`.

This produces significantly different reservoir depths across Europe — Alpine and Nordic countries
(AT, CH, NO) typically receive hundreds of hours, while countries with a single poorly-documented
plant receive 6 h.

## Survival into the Sector Network

`scripts/prepare_sector_network.py:740–764` (`remove_elec_base_techs`) removes electricity-only
components such as OCGT and batteries before sector coupling, but **explicitly retains** all three
hydro types via the `pypsa_eur` config section:

```yaml
# config/config.default.yaml
pypsa_eur:
  Generator:
    - ror          # retained
  StorageUnit:
    - PHS          # retained
    - hydro        # retained
```

All three technologies pass unchanged into the full sector-coupled network and are never re-added
by sector-coupling logic.

## No Investment or Decommissioning

Hydro is absent from `electricity.extendable_carriers` in `config/config.default.yaml`. No technology
in this group can be invested in or retired by the optimizer. Across all myopic planning horizons:

- Capacity is identical in every year (frozen at powerplantmatching values).
- No PEMMDB trajectory bands are applied — `mods/network/potentials.py:297–303` does not include any
  hydro carrier in its technology list.
- No KLIEN potential limits apply — `mods/network/potentials.py:325–330` covers only solar and wind.
- No `solving.constraints.limits_capacity_min` or `limits_capacity_max` entries target any hydro carrier
  in `config/config.at.yaml`.

The `add_brownfield.py` brownfield loop (`line 69`) iterates over `["Link", "Generator", "Store"]`.
`StorageUnit` is absent, so PHS and reservoir hydro are never subject to capacity locking or
decommissioning logic. They are rebuilt fresh into every planning-horizon network from the
powerplantmatching source.

## Country-Level Differences

The code applies identical logic to all countries. Variation between countries arises entirely from
the underlying data:

| Source of variation | Mechanism |
|---|---|
| Technology types present | Which carrier labels appear in powerplantmatching for a given country |
| Reservoir `max_hours` | Country-level EIA storage statistics; 6 h fallback if data is missing |
| Inflow magnitude and seasonality | Country-specific EIA annual generation used as normalization target |
| Inflow missing-year fallback | Country median used if EIA data is absent for the weather year |

Countries with no hydro plants of a given type in powerplantmatching simply receive no component of
that type. Flat-terrain countries (NL, DK, LU, Baltic states) typically have no hydro at all.
Alpine and Nordic countries (AT, CH, NO, SE) have all three types with deep seasonal reservoirs.
Germany's hydro fleet consists mainly of PHS with few reservoirs.

## Configuration Reference

All hydro settings live under `renewable.hydro` in `config/config.default.yaml`. No AT-specific
overrides exist in `config/config.at.yaml`.

```yaml
renewable:
  hydro:
    cutout: default
    carriers:
      - ror
      - PHS
      - hydro
    PHS_max_hours: 6                               # fallback storage duration for PHS
    hydro_max_hours: energy_capacity_totals_by_country  # method for reservoir sizing
    flatten_dispatch: false                        # if true, caps dispatch at mean CF + buffer
    flatten_dispatch_buffer: 0.2
    clip_min_inflow: 1.0                           # inflow values below 1 MW are zeroed
    eia_norm_year: false                           # if set, pins all countries to one year's stats
    eia_correct_by_capacity: false                 # capacity-change correction (disabled)
    eia_approximate_missing: false                 # ERA5-runoff extrapolation (disabled)
```
