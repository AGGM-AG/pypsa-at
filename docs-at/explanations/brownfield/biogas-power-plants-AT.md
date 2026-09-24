# Austrian Biogas-to-Power Brownfield Capacities

Austria's existing biogas-to-power capacities are historically small and spatially distributed.
They are not included from `powerplantmatching`.
Additionally, due to their size, most
plants would fall below the capacity threshold of `powerplantmatching` and would be dropped.
PyPSA-AT adds all known biogas-to-power plants explicitly from the Austrian
[Anlagenregister](https://anlagenregister.at/).

## Modelling approach

The plants from the Anlagenregister become non-extendable `biogas CHP` capacity in the base year
and are carried forward until they retire. The design choices behind this:

- **Register plants up to 5 MW count.** The register lists plants that generate electricity
  from biogas, sewage gas or landfill gas, so the fuel is known per plant. Above 5 MW, 
  `Anlagenregister` entries are dropped: a handful of large sites are already present in
  `powerplantmatching` under their true fuel type, and adding them again from the register
  would double-count that capacity (as `gas CHP` and `biogas CHP`).
- **Biogas is the fuel.** The plants draw from the regional biogas supply and feed the regional
  electricity grid. They therefore compete with biogas upgrading for the same biogas potential,
  and their output falls when the potential is exhausted.
- **Aggregated per region.** Plants are summed per model region and vintage. A region only
  receives capacity if the sum exceeds the general threshold for existing capacities, which
  PyPSA-AT lowers to 2 MW so that the many small plants are kept. The threshold must stay
  at or below 5 MW for this to work.
- **Technology assumptions borrowed from solid biomass CHP.** Efficiency, costs and lifetime
  come from the central solid biomass CHP technology data, in the absence of Austrian
  plant-level data.
- **Kept separate from the general power plant table.** If the plants entered the general
  table, PyPSA-Eur would model them as solid biomass CHPs. They are therefore added by a
  dedicated PyPSA-AT modification step instead.

## Build years
To best represent the reality of the Austrian biogas-to-power brownfield, the `build_year` of plants is assumed to be 2003. There is no available data on the actual build times of individual plants. The year 2003 is assumed for two reasons:
First, the Austrian government allowed large grants for the building of biogas-to-power plants in the years between 2005 and 2010. Second, with a lifetime of 25 years, plants installed after 2005 would still be viable in the myopic investment period 2030-2040.

To force the assets to be decommissioned before 2030, we assume 2003 + 25 years = 2028 + 1 buffer year = 2029.
In the network this shows as vintage 2005 (the next grouping year) with a remaining lifetime of 24 years.

## Configuration

Enabled via `mods.existing_capacities.add_biogas_to_power_plants_AT` in `config.at.yaml`.
When disabled, `biogas_plants_at_{clusters}.csv` is empty and no Links are added.
