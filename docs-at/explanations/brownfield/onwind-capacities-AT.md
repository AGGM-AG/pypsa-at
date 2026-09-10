# Austrian Onshore-Wind Brownfield Capacities

PyPSA-AT represents existing Austrian onshore-wind capacity as fixed brownfield
vintages instead of allowing the model to rebuild the whole fleet.

## Data flow

1. `retrieve_wind_power_at` downloads annual wind generation by Austrian federal
   state for 2005–2024.
2. `build_onwind_brownfield_at` maps the generation data to the model regions and
   estimates yearly capacity additions from positive production changes.
3. The additions are grouped into five-year build-year vintages and normalised to
   the current regional capacities from the KLIEN wind-potential data.

## Applying the brownfield

During `modify_prenetwork`, `apply_onwind_brownfield` keeps only vintages whose
lifetime extends into the current planning horizon. It then:

- sets matching pre-base-year generators to their brownfield capacity;
- sets obsolete or missing pre-base-year generators to zero; and
- keeps base-year generators extendable, with the brownfield capacity as their
  minimum in the base year.

The resulting vintages are fixed generators with the existing onshore-wind
capacity-factor profiles. New capacity can still be built through the regular
extendable onshore-wind generators.
