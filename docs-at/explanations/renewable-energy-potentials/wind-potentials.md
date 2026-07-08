# Wind Power Potentials in Austria

Austria's onshore wind resource is unevenly distributed. Viable sites are concentrated in the eastern lowlands,
the Alpine foothills, and selected ridgeline locations, while the high-alpine interior is largely unsuitable.
Capturing this geographic constraint accurately is essential for realistic energy modelling.

The study *Erneuerbare Energiepotenziale in Österreich 2030 & 2040*, conducted on behalf of the Austrian Climate
and Energy Fund (KLIEN), quantifies realisable onshore wind potentials at district level through a four-step
methodology combining GIS-based site identification, turbine placement, economic assessment, and state-level
expansion modelling. PyPSA-AT applies these potentials to constrain the optimised expansion of onshore wind
generators in Austrian regions.

For the shared data pipeline, scenario dimensions, and configuration reference, see
[KLIEN Renewable Energy Potentials](klien-potentials.md).

## Wind Power in the KLIEN Study

In 2024, Austria operated 1,413 wind power plants (WPPs) with a combined annual feed-in of 9,288 GWh. The
installed fleet spans rated capacities from 500 kW to 6,200 kW, reflecting successive turbine generations. The
KLIEN study uses installed capacity as its primary indicator rather than plant count, because capacity is a more
meaningful measure of resource utilisation across a heterogeneous fleet.

### Methodology

The study derives wind power potentials in four steps:

1. **Identification of potential areas**: A GIS-based analysis identifies areas suitable for wind power
   development by applying exclusion criteria — terrain slope, minimum distances to settlements, minimum
   distances to transport and energy infrastructure, and protected natural areas.

2. **Turbine placement and yield calculation**: Hypothetical WPPs are placed within the identified areas.
   Using local wind data from the Austrian wind atlas, the annual energy yield at each turbine location is
   calculated from an assumed turbine power curve.

3. **Economic assessment**: Each modelled turbine location is evaluated for economic feasibility, incorporating
   remuneration under the Austrian Renewable Energy Expansion Act (EAG) alongside current investment and
   operating costs.

4. **Allocation of expansion rates**: Nationwide wind power expansion rates — modelled as annual numbers of
   newly installed WPPs — are allocated to individual federal states. Results are reported for the target years
   2030 and 2040.

### Spatial Distribution and Fragmentation

Potential areas for wind power are distributed very unevenly relative to the total area of each federal state.
The spatial structure of potential areas — whether large contiguous zones or fragmented small patches —
significantly influences how many turbines can be placed, because minimum inter-turbine spacing requirements
interact with patch geometry. In highly fragmented areas, each WPP effectively occupies only its foundation
footprint. In large contiguous zones, each WPP requires a circular exclusion area with a radius of two rotor
diameters (half of the assumed 4D minimum inter-turbine spacing). Reported potential areas are therefore not
directly proportional to installed capacity or energy production.

### Repowering

Repowering sites — locations where existing turbines reach the end of their assumed 20-year operational lifetime
and become available for renewed use — are included in the technical potential. This means slightly different
technical potentials arise for 2030 and 2040, as the two target years capture different shares of the existing
fleet reaching end-of-life. At the upper end of the High storyline, approximately one third of Austria's
technical wind power potential would be realised nationwide by 2040.

## Input Data

The study provides a single GeoJSON file at municipality level for wind:

| GeoJSON file              | Technology           |
|---------------------------|----------------------|
| `wind_EEPOT_W23.geojson`  | Onshore wind power   |

This file is fetched and processed by the `build_klien_potentials` rule
(`scripts/pypsa-at/build_klien_potentials.py`). The output CSVs (`nuts3_wind.csv`, `at10_wind.csv`) contain
one row per region and one column per scenario combination.

## Carrier Mapping

Wind power maps to a single PyPSA carrier:

| KLIEN dataset | PyPSA carrier |
|---------------|---------------|
| `wind`        | `onwind`      |

There is no shared land-use constraint for wind: the `p_nom_max` value set by `apply_klien_potential_limits()`
is the sole capacity ceiling for `onwind` generators in each Austrian region. No additional solver constraint
analogous to the solar land-use constraint is required.
