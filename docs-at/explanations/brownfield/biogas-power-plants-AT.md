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
   (`scripts/pypsa-at/overwrite_powerplants.py`): each Anlagenregister plant is mapped from PLZ to NUTS3 and added to the powerplants table with the build year 2010. This year is an assumption based on the historic peak of Austrian governmental grants for
    biogas-to-power plants.
    The result is written to `powerplants_s_{clusters}-overwrite.csv`.
2. **`add_existing_baseyear`** (upstream) turns these `powerplantmatching` .csv into network components:
   - Plants **< 2 MW** are tagged `biogas`; larger plants remain `solid biomass`.
     - This filter does not apply to the added plants from the Anlagenregister. 
   - Plants are **aggregated per NUTS3 region**; a region receives a non-extendable
     `biogas` Link only if its **summed** capacity exceeds `threshold_capacity` (PyPSA-Eur default = 10 MW)
     - This filter does apply to the added plants from the Anlagenregister. 
     - To preserve the small powerplants, the threshold needs to be lowered for PyPSA-AT. The expected threshold is <= 5 MW.  


## Configuration

Enabled via `mods.existing_capacities.add_biogas_to_power_plants_AT` in `config.at.yaml`.
When disabled, only `powerplantmatching` plants are used.
