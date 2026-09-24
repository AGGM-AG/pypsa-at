# Modified brownfield of the Austrian gas grid
## PyPSA-Eur default
The default dataset used in PyPSA-Eur is the [SciGRID_gas](https://zenodo.org/records/4767098) dataset. While this is a reasonably accurate dataset for the low spatial resolution of PyPSA-Eur, a more refined resolution on a sub-national level is not given. 
The values for capacities given for transport corridors between Austrian regions when using a NUTS3 clustering especially are not realistic and need to be improved for a truly sector-coupled consideration of the Austrian energy system. 



![Map of PyPSA-Eur default gas pipelines in Austria in 2025 with NUTS3 clustering](../../assets/with-label_pypsa-eur-pipeline-through-tyrol.png){ height="500" }

![Map of PyPSA-AT gas pipelines in Austria in 2025 with NUTS3 clustering after all proposed changes were applied](../../assets/with-label_pypsa-at-turned-off-building-gas-pipelines.png){ height="500" }



## In PyPSA-AT 
PyPSA-AT is hosted and maintained by the [Austrian Gas Grid Management GmbH](https://www.aggm.at/en/). This means that PyPSA-AT can be supplied directly with expert knowledge of the complete Austrian brownfield gas grid. 
In collaboration with those experts, a dataset for Austria was generated and added to PyPSA-AT in the `/data/pypsa-at/` folder. 

The dataset is maintained at NUTS3 resolution (35 Austrian regions, file `AGGM_gas_network_base_AT35.csv`). It holds the capacities of the links between regions ("transport corridors"), the reverse capacity of asymmetric corridors, and the year each corridor was commissioned. Data on pipeline diameter is not added and will not be added due to reasons of confidentiality. Corridor lengths are not supplied either; they are computed from the straight-line distance between the region centroids, multiplied by the length factor for links set in the config (`links: length_factor`) to account for the detours of real pipeline routes. This is the same method `cluster_gas_network` uses for the rest of Europe. Every corridor in the file needs a transport capacity: if a row has a capacity of zero, the workflow stops with an error that names the row, so the file can be corrected. 

For a NUTS2 run (ten Austrian regions), `aggregate_gas_pipeline_corridors_to_nuts2` derives the coarser network from the same file: each corridor's buses are remapped to their NUTS2 parent region, corridors that then start and end in the same region are dropped, and all corridors between the same pair of regions are merged into one by summing each flow direction on its own. It does not matter which region a NUTS3 row names first: the merged corridor always points along its stronger flow direction. 

Only those two AT clusterings are supported; any other raises an error in the rule. 

## Rule `modify_brownfield_gas_network_AT` 
To overwrite the original dataset for Austrian regions, a new rule was introduced. It is built between the existing rules `cluster_gas_network` and `prepare_sector_network`. The new rule takes the output of the clustering rule, modifies it, and returns its output to `prepare_sector_network`. If the config setting for modification of the Austrian brownfield is disabled, the rule is still called, but only passes the input through, preserving the original workflow. 

## In `config.at.yaml` 
The changes added by this improved dataset can be turned on via the config setting 
`modify_brownfield_gas_network_AT`:  
```yaml 
mods: 
    modify_brownfield_gas_network_AT: true
```

---
# Asymmetric and monodirectional gas pipelines

Real pipelines are directional, because compressor stations are built and sized for one direction.
AGGM models the TAG (Trans-Austria-Gas pipeline) as three parallel corridors between AT211 and
IT0, each rated 16 672 MW north-south against 6 015 MW south-north, so 50 GW against 18 GW in
total.

PyPSA-Eur labels a corridor either bidirectional or monodirectional and nothing in between, then
proceeds to treat all corridors the same: `lossy_bidirectional_links` in `scripts/prepare_sector_network.py` splits every
carrier listed under `sector.transmission_efficiency.enable` into a forward and a reverse Link,
zeroes `p_min_pu`, and copies `p_nom` onto the reverse leg. The split is wanted and necessary, because the
reverse leg is free (`capital_cost = 0`, `length = 0`) and the corridor is billed only once. The copied
capacity is not implemented correctly however: a compressor-limited corridor comes out symmetric, and a monodirectional one
gains a reverse direction it does not have, doubling both costs and capacity in the corridor.

The AGGM dataset adds a `p_nom_reverse` column, set only on bidirectional corridors, with the forward leg always the bigger capacity one (`p_nom`  > `p_nom_reverse`).  
`apply_reverse_flow_limits` converts it into the PyPSA bound and drops the column:

| `p_min_pu` | Corridor | Reverse capacity |
|------------|---|---|
| `-1`       | symmetric, bidirectional | equal to `p_nom` |
| `[-1,0]`   | asymmetric | `-p_min_pu x p_nom` |
| `0`        | monodirectional | none |

`restore_asymmetric_pipeline_capacities` in `mods/network/gas.py` then runs during
`modify_prenetwork`, for Austrian corridors only:

1. Select the corridors whose `p_min_pu` lies in `(-1, 0]`. Symmetric ones sit at `-1` and are
   skipped.
2. Resize the reverse leg to `-p_min_pu x p_nom`, which is zero for a monodirectional corridor.
3. Fix those legs with `p_nom_extendable = False`, so
   `add_lossy_bidirectional_link_constraints` does not tie them back to the forward leg.

This holds before the retrofit start year (see below), i.e. in the calibration and base years.
From the retrofit start year on the directional limits no longer apply: the reverse leg follows
the forward leg, so every corridor can carry gas in both directions up to its full capacity, and
reversing a pipeline does not carry a cost in the model. Pipes are symmetric by construction and
only the compressor stations are directional; adapting them costs far less than a retrofit and
happens alongside it, so it is treated as free once retrofitting is allowed.

---
# Gas grid capacity, new pipelines and H2 retrofitting

Two more changes keep the methane grid consistent with the AGGM planning premise: the grid stays
at its target capacity up to a threshold year, and endogenous H2 retrofitting is coupled to that
fixed grid instead of duplicating it.

## Horizon classes

`mods.threshold_year_for_gas_grid_expansion` (2040 in `config/config.at.yaml`) is the last horizon
of the fixed grid. The retrofit start year is read from the upstream key
`first_technology_occurrence.Link."H2 pipeline retrofitted"` (2030 in `config/config.at.yaml`):
PyPSA-DE drops the retrofit candidates before that year, and PyPSA-AT reads the same key, so no
second switch exists. With `sector.H2_retrofit: false` retrofitting never starts, which keeps the
legacy behaviour of a fully fixed grid up to the threshold year.

```yaml
first_technology_occurrence:
  Link:
    H2 pipeline retrofitted: 2030

mods:
  threshold_year_for_gas_grid_expansion: 2040
```

| Horizon | `gas pipeline` (both legs) | `gas pipeline new` | `H2 pipeline retrofitted` | Asymmetric corridors |
|---|---|---|---|---|
| before the retrofit start (2025) | fixed at the AGGM target | fixed | absent, dropped upstream | reverse legs resized and fixed |
| retrofit start up to the threshold (2030, 2040) | extendable, `p_nom_min = 0`, `p_nom_max = target` | fixed | extendable, `p_nom_max = 0.6 x target - carried-over` | symmetric, reverse legs synced to the forward legs |
| after the threshold (2050) | upstream behaviour | extendable | upstream behaviour | symmetric |

`make_gas_pipelines_unextendable` in `mods/network/gas.py` implements the gas pipeline columns
during `modify_prenetwork`; `restore_asymmetric_pipeline_capacities` the last column.

## The coupling equality

`add_pipe_retrofit_constraint` in `scripts/solve_network.py` adds, for every extendable forward
`gas pipeline` leg with a retrofit candidate:

```
gas + H2 retrofitted / H2_retrofit_capacity_per_CH4 = p_nom of the gas pipeline
```

The constraint exists only for extendable gas pipelines. Fixing them, as PyPSA-AT did before,
silently skipped the constraint for the whole network, and the optimiser could use the same
physical pipeline as full CH4 capacity and as retrofitted H2 capacity at the same time. Keeping the
pipelines extendable within `[0, target]` makes the equality bind: retrofitted H2 capacity gives
way to gas capacity on the same corridor and the sum stays at the AGGM target. The reverse legs of
both carriers are tied to their forward legs by `Link-bidirectional_sync`.

The upstream constraint pairs the extendable forward gas pipelines with the extendable forward
retrofit candidates **by position**, not by name. With unequal counts linopy silently drops the H2
term, fixes the gas pipelines at `p_nom` and leaves the retrofits unconstrained; in a different
order it couples the wrong corridors. PyPSA-DE's Kernnetz logic fixes the German-internal
candidates up to 2030, which is exactly such a case. `make_gas_pipelines_unextendable` therefore
fixes every gas pipeline without an extendable candidate (it could not be retrofitted anyway) and
`check_retrofit_pairing` raises during `modify_prenetwork` if the two sets still differ in length,
membership or order.

## Carried-over retrofits

In a myopic run the retrofits of an earlier horizon are carried over as fixed
`H2 pipeline retrofitted` links with a build-year suffix (`... AT225 <-> AT213-2030`,
`... AT225 <-> AT213-reversed-2030`). Upstream `add_brownfield` lowers the candidates' `p_nom_max`
by this carry-over and means to lower the gas pipeline capacity as well, but its name mapping keeps
the build-year suffix while gas pipelines (lifetime `inf`) never carry one. The gas grid is
therefore left at the full target: a silent no-op.

`deduct_retrofitted_gas_capacity` in `mods/network/gas.py` closes the gap in every horizon with
carried-over retrofits, gated on `sector.H2_retrofit`:

1. Map each carried-over link (build year before the horizon, both legs) to its gas pipeline leg
   by stripping the year and swapping the carrier prefix, then sum per leg and divide by
   `H2_retrofit_capacity_per_CH4`.
2. Take the target capacity from the clustered gas network; both legs of a corridor get the
   forward value, in line with the symmetric reverse legs from the retrofit start year on.
3. Set `p_nom` and `p_nom_max` to `min(current, target - carried-over / ratio)`, clipped at zero.

The `min` is the double-deduction guard: should upstream fix its mapping, the current capacity
already equals the deducted one and nothing changes. The function is idempotent. A carried-over
retrofit without a gas pipeline leg, or a gas pipeline without a target capacity, raises.

## Known limitations

- **Compressor physics.** From the retrofit start year on compressor adaptation is free and the
  reverse leg follows the forward leg, so asymmetric and one-way corridors regain their full
  reverse capacity. The directional limits hold only in the base years.
- **Wasserstoff-Kernnetz overlap.** On German corridors upstream lowers the gas capacity for the
  exogenous Kernnetz retrofits too. The `min` keeps only the larger of the two reductions, so
  those corridors may end up less reduced than the sum of both. All Austrian corridors are exact.
- **Upstream `add_brownfield` no-op.** Not filed upstream; the AT deduction covers it and guards
  against a later upstream fix.
- **AGGM build years.** The commissioning years in the AGGM dataset are not applied yet, so the
  target capacity is horizon-independent and corridors with a future build year are present in
  every horizon, including the base year.
