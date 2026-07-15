# Austrian Biogas-to-Power Brownfield Capacities

Austria's existing biogas-to-power capacities are historically small and spatially distributed. 
They are not included from `powerplantmatching`. 
Additionally, due to their size, most
plants would fall below the capacity threshold of `powerplantmatching` and would be dropped. 
PyPSA-AT adds all known biogas-to-power plants explicitly from the Austrian
[Anlagenregister](https://anlagenregister.at/).

## Data

| File | Purpose |
| ---- | ------- |
| `data/pypsa-at/Anlagenregister_electricity_from_renewable_gas_AT.csv` | Existing AT plants generating electricity from renewable gas (biogas, landfill/sewage gas) with capacity (`Engpassleistung`) and postal code. |
| `data/pypsa-at/AT-Postal-to-NUTS.csv` | Maps every Austrian postal code (PLZ) to its NUTS3 region ([European Commission](https://gisco-services.ec.europa.eu/tercet/)). |

## Data flow

1. **`overwrite_powerplants_at`** rule → `overwrite_biogas_to_power_plants_AT`
   (`scripts/pypsa-at/overwrite_powerplants.py`): each Anlagenregister plant is mapped from PLZ to NUTS3 and added to the powerplants table.
    The result is written to `powerplants_s_{clusters}-overwrite.csv`.
2. **`add_existing_baseyear`** (upstream) turns these `powerplantmatching` .csv into network components:
   - Plants **< 2 MW** are tagged `biogas`; larger plants remain `solid biomass`.
     - This filter does not apply to the added plants from the Anlagenregister, which are added after the filter gate. 
   - Plants are **aggregated per NUTS3 region**; a region receives a non-extendable
     `biogas` Link only if its **summed** capacity exceeds `threshold_capacity` (PyPSA-Eur default = 10 MW)
     - This filter does apply to the added plants from the Anlagenregister. 
     - To preserve the small powerplants, the threshold needs to be lowered for PyPSA-AT. The expected threshold is <= 5 MW.  

## Build years
To best represent the reality of the Austrian biogas-to-power brownfield, the `build_year` of plants is assumed to be 2003. There is no available data on the actual build times of individual plants. The year 2003 is assumed for two reasons: 
First, the Austrian government allowed large grants for the building of biogas-to-power plants in the years between 2005-2010. Second, with a lifetime of 25 years, plants installed after 2005 would still be viable in the myopic investment period 2030-2040. 

To force the assets to be decommissioned before 2030, we assume 2003 + 25 years = 2028 + 1 buffer year = 2029. 

## Configuration

Enabled via `mods.existing_capacities.add_biogas_to_power_plants_AT` in `config.at.yaml`.
When disabled, only `powerplantmatching` plants are used.
