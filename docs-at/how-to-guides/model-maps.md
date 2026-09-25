# Model Input Maps

The `plot_model_map_at` rule draws two print-quality maps (PNG, 300 dpi,
16.5 cm wide) of the model input topology for Austria and its neighbours:

- `model_map_powerplants.png`: power plants coloured by fuel type, circle area
  proportional to capacity,
- `model_map_industry.png`: Hotmaps industrial sites coloured and shaped by
  subsector, marker area proportional to 2014 ETS emissions.

Both maps share a base layer: the AT35DE5 model regions, the electricity grid
(line width proportional to `s_nom`) and the gas grid (line width proportional
to `p_nom`).

## Build the maps

The rule is not part of `all_at`. Request its outputs explicitly, with the
`run.prefix` and `run.name` of your configuration:

```bash
pixi run snakemake -call \
  results/{prefix}/{run}/maps/model_map_powerplants.png \
  results/{prefix}/{run}/maps/model_map_industry.png
```

For example, with `prefix: industry-energy-map` and `name: AT_KN2040`:

```bash
pixi run snakemake -call results/industry-energy-map/AT_KN2040/maps/model_map_powerplants.png
```

One call writes both maps. The rule needs `mods.modify_nuts3_shapes` to be
an `AT35*` clustering, because the AGGM corridors are defined on AT35 regions.
On the first run, cartopy downloads the Natural Earth borders and coastlines.

## What the maps show

**Electricity grid.** Exact OSM line geometries from `resources/networks/base.nc`
(AC lines and HVDC links).

**Gas grid.** SciGRID_gas / INET pipeline geometries from
`resources/gas_network.csv`. Missing upstream capacities are filled with the
diameter-based estimate `p_nom_diameter`. In Austria, the map shows the AGGM
capacities the model uses:

1. Each pipeline is assigned to a region pair (corridor) by locating its end
   points in the model regions, like `cluster_gas_network`.
2. For corridors in `data/pypsa-at/AGGM_gas_network_base_AT35.csv`, the AGGM
   capacity replaces the upstream one. The AGGM strands of a corridor are summed
   per flow direction and the stronger direction is used. That capacity is split
   across the corridor's pipelines in proportion to their upstream capacity.
3. AGGM corridors without an upstream pipeline are drawn as dashed straight
   lines between the regions.
4. Upstream pipelines in Austrian corridors without AGGM data are drawn grey
   and dotted: the model drops them (see `modify_brownfield_gas_network_AT`).

The log `results/{prefix}/{run}/logs/plot_model_map_at.log` lists the corridors
of steps 3 and 4.

**Power plants.** `powerplants_s_adm-overwrite.csv`, the powerplantmatching list
with the Anlagenregister overrides for Austria. Only plants with at least 10 MW
are drawn; the footer states their share of the capacity in the map extent.

**Industrial sites.** Hotmaps industrial database. The emissions are filled as
in `build_industrial_distribution_key`: ETS 2014, else E-PRTR 2014, else the
20 % quantile of the sites in the same country and subsector. Sites with a
filled value are drawn hollow.

## Adjust the maps

The map extent and the power plant threshold are `params` of the rule in
`rules/pypsa-at/collect.smk`. Line widths and marker sizes are set in the
`scales` dictionary of `scripts/pypsa-at/plot_model_map_at.py`.
