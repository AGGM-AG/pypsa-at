# Blocking Russian Gas Imports

## Background

PyPSA-Eur's default methane network includes large pipeline import capacities for countries that
historically received Russian gas — both via the Eastern European land corridor and
via TurkStream (Bulgaria). Since 2022 these flows have been curtailed or fully stopped.
PyPSA-AT reflects this geopolitical reality by zeroing out the affected pipeline import
generators for the relevant planning horizons.

The two distinct corridors are treated separately because they have different
start dates and different residual capacities:

- **Eastern border corridor** — countries receiving Russian gas via Ukraine:
  Finland (FI), Estonia (EE), Latvia (LV), Lithuania (LT), Poland (PL), Slovakia (SK),
  Romania (RO). # Pipeline import capacity is set to zero from `start_year` onward.
- **TurkStream corridor** — Bulgaria (BG) receives Russian gas via the Black Sea pipeline.
  Pipeline import capacity is reduced to the TANAP residual (~ 700 GWh/d), preserving
  Azerbaijani gas imports via the Trans-Anatolia Gas Pipeline (TANAP) that are independent
  of the Russian route. Source: [ENTSO-G](https://view.officeapps.live.com/op/view.aspx?src=https%3A%2F%2Fwww.entsog.eu%2Fsites%2Fdefault%2Ffiles%2F2026-03%2FSystem%2520Capacity%2520Map%25202026%2520-%2520Capacities.xlsx&wdOrigin=BROWSELINK)

`end_year`s can be set for each corridor indivudally - reallowing the import of Russian pipeline gas from that year on. 


## Implementation

`block_russian_gas_imports` in `mods/network/gas.py` is called during the `modify_prenetwork`
step. For each configured block:

1. Check whether the current `planning_horizons` wildcard falls within `[start_year, end_year]`.
   Horizons outside this window are skipped.
2. Filter the block's country list to countries present in `config["countries"]`.
3. Locate the generator named `{cc} gas pipeline import` for each active country.
4. Set `p_nom` to the residual capacity (zero, or `_TANAP_PIPELINE_CAPACITY` for BG) and
   `p_nom_extendable = False` to prevent the optimizer from re-opening the route.

## Defaults

| Block | Countries | `start_year` | `end_year` | Residual capacity |
|---|---|---|---|---|
| `eastern_border_block` | FI, EE, LV, LT, PL, SK, RO | 2025 | ∞ | 0 MW |
| `turkstream_block` | BG | 2030 | ∞ | 29 258 MW (TANAP) |

## Configuration

In `config/config.at.yaml` under `mods`:

```yaml
mods:
  block_russian_gas_imports:
    enable: true
    eastern_border_block:
      start_year: 2025
      countries: [FI, EE, LV, LT, PL, SK, RO]
    turkstream_block:
      start_year: 2030
      countries: [BG]
```

`end_year` is optional for both blocks and defaults to infinity (block never lifted).
Set it to a specific year to model a scenario where imports resume:

```yaml
    eastern_border_block:
      start_year: 2025
      end_year: 2040
      countries: [FI, EE, LV, LT, PL, SK, RO]
```

To disable the feature entirely, set `enable: false`.
