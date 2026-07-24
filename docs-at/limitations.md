# Limitations

PyPSA-AT is a techno-economic optimisation model designed for strategic scenario
analysis of the Austrian energy system. Like every model, it is a simplified
representation of reality. This page explains in detail what that means for the
interpretation of model results: first, why results are **indicative** rather
than technical planning statements, and second, which **limitations PyPSA-AT
inherits** from its upstream model [PyPSA-Eur](https://github.com/pypsa/pypsa-eur).

!!! warning "Read before drawing conclusions"
    Model results are indicative and **do not replace the detailed hydraulic
    assessments or power-flow/load-flow calculations** that may be required for
    technical evaluation, validation, or planning purposes.

## Indicative Results

PyPSA-AT answers questions about the cost-optimal long-term development of a
sector-coupled energy system: which technologies are built where and when, how
energy carriers flow between regions, and how policy constraints shape the
system. It does **not** answer questions about the technical feasibility of
operating a specific piece of infrastructure. The main reasons are:

### Linearised electricity network representation

The electricity grid is modelled with a *linearised* optimal power flow
(DC approximation). This captures active power transfers and congestion between
regions, but it ignores:

- **reactive power, voltage levels, and voltage stability**,
- **dynamic phenomena** such as frequency response, transient stability, and
  fault behaviour,
- **detailed contingency analysis**: security margins are approximated by a
  uniform reduction of usable line capacity rather than an explicit N-1
  (or N-k) calculation.

A grid expansion that appears cost-optimal in PyPSA-AT therefore still requires
a dedicated **load-flow/power-flow study** before any technical conclusion can
be drawn.

### Capacity-based gas and hydrogen networks

Gas and hydrogen pipelines are modelled as transport capacities between
regions: energy can flow up to a technical pipe capacity. The model does
**not** simulate pressures, flow velocities, compressor behaviour, linepack, or
gas quality. Statements about whether a pipeline or storage facility can
physically deliver a given profile require a dedicated **hydraulic
assessment**, which is outside the scope of this model.

### Spatial and temporal aggregation

Each model region (for Austria: NUTS3 zones) is represented by a single node.
All demand and generation within a region is aggregated, and grids below the
transmission level are only represented by simplified cost and loss
assumptions. Time is resolved in steps of one to three hours for a limited set
of representative weather years, so extreme events outside those years and
sub-hourly dynamics (balancing, ramping within the hour) are not captured.

### Idealised optimisation assumptions

The optimisation assumes global perfect foresight (within every planning year
in the myopic workflow), perfect competition, and rational cost-minimising behaviour. 
Real-world market frictions, actor behaviour, financing constraints, permitting timelines, and
supply-chain bottlenecks are not modelled. Results also depend strongly on
uncertain input assumptions such as technology cost projections, fuel prices,
and demand trajectories - they should always be read as *scenario outcomes*,
not forecasts.

## Inherited Limitations

PyPSA-AT builds on [PyPSA-Eur](https://github.com/pypsa/pypsa-eur) (via
[PyPSA-DE](https://github.com/pypsa/pypsa-de)) and inherits its
[documented limitations](https://pypsa-eur.readthedocs.io/en/latest/limitations/).
Some of them have since been addressed or mitigated in PyPSA-AT for the
Austrian model scope — these are marked below — but many still apply, in
particular for regions outside Austria.