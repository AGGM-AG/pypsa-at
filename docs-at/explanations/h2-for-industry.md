# H2 for Industry Bus

## Background

In the upstream PyPSA-EUR / PyPSA-DE model, hydrogen demand from the industrial
sector is represented as a `Load` component placed directly on the general `H2`
bus. This means that from the optimiser's perspective, industry H2 demand competes
with all other H2 consumers — fuel cells, power-to-X processes, pipeline exports —
on exactly the same bus, drawing hydrogen exclusively from the central H2
infrastructure.

This representation is sufficient for high-level European studies, where the
question is how much green hydrogen to produce system-wide. For Austrian industry
decarbonisation research, however, it misses a structurally important distinction:
industrial hydrogen demand can be — and in practice often is — satisfied by
**on-site production** rather than delivery via the public hydrogen grid.

## On-site H2 Production Routes

Several commercially relevant technologies produce hydrogen at or adjacent to an
industrial site without requiring connection to a shared H2 transmission network:

| Technology | Carrier in | Carrier out | Note |
|---|---|---|---|
| Methane pyrolysis (plasma) | Gas (CH₄) | H₂ | Turquoise H₂; solid carbon by-product |
| On-site electrolysis | Electricity | H₂ | Green H₂; sized to local demand |
| SMR / SMR CC | Gas (CH₄) | H₂ | Grey / blue H₂ with optional capture |
| Biomass-to-H₂ | Solid biomass | H₂ | Bio H₂ route |

All of these technologies can, in principle, be located inside a factory boundary.
The H₂ they produce does not enter the public transmission grid at all — it goes
directly into the industrial process.

When industry H2 demand sits on the general `H2` bus, the optimiser treats
on-site production and grid supply as perfect substitutes. This is correct for
the energy balance, but it erases the structural difference between:

- **Grid-connected supply** — hydrogen produced elsewhere and transported via
  pipeline (requires H₂ infrastructure investment, creates long-range flow)
- **On-site supply** — hydrogen produced and consumed at the same industrial node
  (no transmission infrastructure required, potentially lower losses)

## The "H2 for Industry" Bus Topology

PyPSA-AT introduces a dedicated `H2 for industry` bus per clustered node, mirroring
the existing `gas for industry` pattern already present in the upstream model:

```
H2 bus ──[H2 for industry Link]──▶ H2 for industry Bus ──[Load]
                                           ▲
                              on-site H2 producers
                              (pyrolysis, electrolysis, …)
```

The key properties of this topology are:

**Unidirectional supply link.** The `H2 for industry` Link runs from the general
`H2` bus to the industry bus only (PyPSA Links have `p_min_pu = 0` by default).
The industrial H2 bus cannot feed hydrogen back into the public network. This
correctly represents the physical reality that on-site production plant is not
grid-connected.

**On-site technologies attach directly to the industry bus.** Any technology that
produces hydrogen for captive industrial use — currently methane pyrolysis plasma,
and structurally any future on-site electrolysis or bio-H₂ route — sets
`bus1 = "{node} H2 for industry"`. Their output never enters the public H₂ bus.

**Grid supply remains available.** The optimiser can still decide to supply
industry from the public H₂ grid by routing through the `H2 for industry` Link.
The topology does not force on-site production; it enables the model to make
the trade-off endogenously.

## No-Regret Nature of the Addition

Introducing the `H2 for industry` bus is a **no-regret** structural improvement for
all PyPSA-AT research questions that touch industry decarbonisation:

**It does not restrict the solution space.** When no on-site H₂ production is
built, the `H2 for industry` Link simply passes through the full industrial hydrogen
demand from the public grid — functionally identical to the upstream topology.
Results for scenarios without on-site production are numerically unchanged.

**It enables previously impossible questions.** Without the separate bus, there is
no way to distinguish how much industry H₂ comes from the grid versus on-site
sources, because all flows pass through the same node. With it, the energy balance
of the `H2 for industry` bus directly answers: how much on-site production vs.
grid supply does the optimal system choose for each Austrian region?

**It is consistent with the existing model philosophy.** The upstream model already
applies this pattern to gas (`gas for industry`), solid biomass, coal, methanol, and
naphtha — all industrial fuel buses are separated from the primary carrier bus by a
dedicated link. Hydrogen was the only major industrial energy carrier missing this
treatment.

**It is robust to technology availability.** The bus is created unconditionally at
network build time (in `prepare_sector_network`), independently of which on-site
technologies are enabled in the configuration. This means the topology is stable
across scenario variants, and evaluation code can rely on the bus existing in every
PyPSA-AT network.

## Implementation Notes

- `setup_h2_industry_bus` in `mods/network_updates.py` creates the buses, rewires
  the existing `H2 for industry` Loads, and adds the supply Links. It is called
  unconditionally from `scripts/prepare_sector_network.py` just before the
  AT-specific technology additions.
- All three hydrogen evaluation views (`view_capacity_hydrogen_production`,
  `view_balance_hydrogen`, `view_timeseries_hydrogen`) aggregate over
  `bus_carrier = ["H2", "H2 for industry"]` so that on-site production and
  grid-supplied demand are both captured without double-counting.