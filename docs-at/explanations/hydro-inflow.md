# Hydroelectric Inflow Calculation and Application

## Overview

Hydroelectric inflow time-series represent the natural water availability for hydro power generation. They are derived from climate data, normalized to observed generation statistics, and calculated per model region.

## Data Sources and Processing

### ERA5 Runoff Data

Hourly runoff data from the ERA5 climate reanalysis dataset is extracted from atlite cutouts at model-region level using country boundary shapes. The default reference year is **2013**.
The profiles per region are created in **`scripts/pypsa-at/build_inflow_profile.py`**

### PEMMDB Normalization

Raw ERA5 runoff is normalized using hydroelectric inflow statistics from PEMMDB, also using **2013** as the reference year. This ensures that the inflow patterns reflect actual observed generation behavior in each country.
The PEMMDB total per region are extracted in  **`scripts/pypsa-at/build_inflow_totals_per_region.py`** and then combined
with the profiles in  **`scripts/pypsa-at/build_inflows_per_region.py`**

## Network Patch

The **network patch** applies calculated inflow time-series to three types of hydroelectric components in the PyPSA network. The function `patch_inflows()` in `mods/network/hydro.py` reads the aggregated inflow DataArray and distributes it appropriately:

### Hydro Storage Units

**Reservoir and pumped-storage inflow** — The inflow time-series is attached directly to storage units with carrier `hydro`. This represents natural water inflow that fills the reservoir over time, available for dispatch in subsequent snapshots.

### Run-of-River (ROR) Generators

**ROR dispatch constraint** — Inflow is normalized to the installed capacity (`p_nom`) of ROR generators, creating a `p_max_pu` time-series that limits hourly generation to available water. A **peak redistribution algorithm** (`_redistribute_peaks()`) ensures that inflow peaks are not artificially truncated; any excess inflow is redistributed proportionally across all hours, preventing infeasibility when inflow briefly exceeds capacity.

### Pumped Hydro Storage (PHS) Inflow

**PHS generation potential** — Inflow is converted to a `p_max_pu` profile for dedicated PHS inflow generators (carrier `PHS inflow`). The nominal power is set to the maximum inflow value observed, allowing the optimizer to dispatch PHS generation up to the available water supply each hour.

### Implementation Detail

The function filters inflows by hydro type (hydro, ror, PHS) and matches them to network components by location name. Missing components generate warnings but do not halt execution, allowing flexibility in model configurations with selective hydro types.
