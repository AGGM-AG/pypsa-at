# Model Input Maps

The `plot_model_map_at` rule draws four print-quality maps (PNG, 300 dpi,
16.5 cm wide) of the model input topology for Austria and its neighbours
(lon 5–21° E, lat 44–52° N):

| File | Content |
|---|---|
| `model_map_powerplants_raw.png` | Power plants coloured by fuel type, circle area proportional to capacity |
| `model_map_industry_raw.png` | Hotmaps industrial sites coloured and shaped by subsector, marker area proportional to 2014 ETS emissions |
| `model_map_powerplants_clustered.png` | The same power plants as one pie per model region, slices by fuel type |
| `model_map_industry_clustered.png` | The same industrial sites as one pie per model region, slices by subsector |

All maps share a base layer: the model regions (dashed boundaries, Austria
filled in a distinct colour), the electricity grid and the gas grid. The raw
maps ("raw data") draw exact line geometries; the clustered maps ("PyPSA-AT
representation") draw straight corridors between the model's cluster buses.

## Build the maps

The rule is not part of `all_at`. Request its outputs explicitly, with the
`run.prefix` and `run.name` of your configuration:

```bash
pixi run snakemake -call results/{prefix}/{run}/maps/model_map_powerplants_raw.png
```

For example, with `prefix: industry-energy-map` and `name: AT_KN2040`:

```bash
pixi run snakemake -call results/industry-energy-map/AT_KN2040/maps/model_map_powerplants_raw.png
```

One call writes all four maps. On the first run, cartopy downloads the Natural Earth borders and coastlines.

## What the maps show

**Electricity grid.** Exact OSM line geometries from `resources/networks/base.nc`
(AC lines and HVDC links).

**Gas grid.** SciGRID_gas / INET pipeline geometries and capacities from
`resources/gas_network.csv`, for all countries including Austria. Missing
capacities are filled with the diameter-based estimate `p_nom_diameter`; the
log `results/{prefix}/{run}/logs/plot_model_map_at.log` states how many. Line
widths grow linearly up to 10 GW and stay constant above, so that large
transit pipelines do not cover the map.

!!! note
    The model itself replaces the Austrian gas corridors with AGGM data
    (`modify_brownfield_gas_network_AT`). The map shows the upstream pipelines
    only.

**Power plants.** `powerplants_s_adm-overwrite.csv`, the powerplantmatching list
with the Anlagenregister overrides for Austria. Only plants with at least 10 MW
are drawn; the footer states their share of the capacity in the map extent.
Units of the same fuel type at the same location (e.g. the reactors of one
nuclear site) are merged into one circle. Colours follow `tech_colors`, except
Nuclear: the map uses a dark violet, because the configured orange is hard to
tell apart from Natural Gas.

**Industrial sites.** Hotmaps industrial database. Sites are sized by their
2014 ETS emissions, or by their E-PRTR emissions where the ETS value is
missing. Sites without any reported emissions are omitted; the log lists how
many per subsector.

## Clustered maps

The clustered maps aggregate the model input to the model's spatial
resolution: 35 Austrian NUTS3 regions, five German regions (DE1–DE5) and one
region per other country (`regions_onshore_base_s_adm.geojson`).

**Pies.** Each site of the raw map is assigned to the model region that
contains it. One pie per region sits at the region's bus
(`networks/base_s_adm.nc`): slices by fuel type (capacity) or subsector
(emissions), pie area on the same scale as the raw-map markers. Pies of
regions whose bus lies outside the map (e.g. FR, NL, DE5) are skipped; the log
lists them.

**Electricity.** AC lines and HVDC links of `networks/base_s_adm.nc`, summed
per region pair. Widths follow the raw-map scale but are capped at 8,000 MVA,
because summed corridors would otherwise cover the map.

**Gas.** The model's final clustered gas network
`gas_network_base_s_adm.csv`, with the AGGM capacities for Austria, summed per
region pair and capped at 10 GW like the raw map.

## Adjust the maps

The map extent and the power plant threshold are `params` of the rule in
`rules/pypsa-at/collect.smk`. Line widths and marker sizes are set in the
`scales` dictionary of `scripts/pypsa-at/plot_model_map_at.py`.
