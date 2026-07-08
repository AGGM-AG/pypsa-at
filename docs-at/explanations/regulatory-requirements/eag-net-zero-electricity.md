# EAG §4(2) — Net-Zero Electricity Balance

## Legal requirement

[EAG §4(2)](https://www.ris.bka.gv.at/GeltendeFassung.wxe?Abfrage=Bundesnormen&Gesetzesnummer=20011619)
(*Erneuerbaren-Ausbau-Gesetz*, Renewable Energy Expansion Act) requires that Austria's total
electricity consumption is covered 100% nationally on a net-balance basis ("bilanziell") from
renewable energy sources from 2030 onwards.

**"Bilanziell"** means the balance is assessed annually across the whole country, not
hour-by-hour or region-by-region. An hour of deficit can be offset by a surplus in another
hour, and electricity imported at one moment can be balanced by exports at another.

## Implementation approach

The requirement is enforced through four coupled linear constraints added to the linopy model
at the start of each `solve_network` call for planning horizons ≥ 2030.

### Why four constraints?

Gas, hydrogen, and methanol power plants can contribute to the electricity balance under the
"bilanziell" interpretation — their electricity output is renewable *if and only if* their
fuel inputs are domestically produced from renewable sources. Three companion constraints
(2–4) enforce this fuel-origin condition on each fuel chain independently and propagate
green-ness across cross-fuel chains (e.g. H2 used by Sabatier to make green gas must itself
be domestically produced green H2).

```
Constraint 1: green electricity produced  ≥  national electricity demand
Constraint 2: domestic green gas produced ≥  gas consumed by gas-fired power plants (elec. share)
Constraint 3: domestic green H2 produced  ≥  H2 consumed for power (elec. share)
                                             + H2 consumed by other green-fuel synthesis
Constraint 4: domestic green methanol     ≥  methanol consumed by methanol-fired plants (elec. share)
```

Biomass-to-power plants count as green in constraint 1 without a companion constraint because
solid biomass is treated as an inherently renewable carrier in the model.

## Mathematical formulation

**Electricity balance (Constraint 1):**

$$G_c - L_c \geq D_c$$

<div style="display: grid; grid-template-columns: 1fr 1fr; gap: 1.5rem;" markdown>
<div markdown>

**Left-hand side — net green production**

| Symbol | Description | Unit |
|---|---|---|
| $G_c$ | Annual green electricity production — renewables, storage dispatch, green fuel-to-power links | MWh/yr |
| $L_c$ | Annual electricity withdrawals — P2X, charging, auxiliary loads, grid losses | MWh/yr |

</div>
<div markdown>

**Right-hand side — exogenous demand**

| Symbol | Description | Unit |
|---|---|---|
| $D_c$ | Annual exogenous electricity demand — `Load` `p_set` on AC and low-voltage buses | MWh/yr |

</div>
</div>

**Fuel-origin constraints (Constraints 2–4), for each fuel $f \in \{\text{gas, H}_2\text{, methanol}\}$:**

$$P_c^f \geq \phi_c^f \cdot F_c^f + X_c^f$$

<div style="display: grid; grid-template-columns: 1fr 1fr; gap: 1.5rem;" markdown>
<div markdown>

**Left-hand side — green fuel production**

| Symbol | Description | Unit |
|---|---|---|
| $P_c^f$ | Domestic green production of fuel $f$ | MWh/yr |

</div>
<div markdown>

**Right-hand side — fuel consumed for electricity**

| Symbol | Description | Unit |
|---|---|---|
| $F_c^f$ | Fuel $f$ consumed by power plants | MWh/yr |
| $\phi_c^f$ | Electricity fraction (see below): share of fuel input attributed to electricity output | — |
| $X_c^f$ | Fuel $f$ consumed by green-fuel synthesis links (H2 only; see Constraint 3) | MWh/yr |

</div>
</div>

### Electricity fraction

For a link $i$ with output ports $p$ (each landing on a bus with carrier $c_{i,p}$ and efficiency
$\eta_{i,p}$), the electricity fraction is

$$
\phi_i \;=\; \frac{\displaystyle\sum_{p \in \mathcal{E}_i}\eta_{i,p}\,\mathbb{1}\!\left[c_{i,p}\in\{\text{AC},\,\text{low voltage}\}\right]}
                  {\displaystyle\sum_{p \in \mathcal{E}_i}\eta_{i,p}}
$$

where $\mathcal{E}_i$ is the set of output ports landing on **energy buses** only. Ports landing
on accounting-only carriers (`co2`, `co2 stored`, `process emissions`) are excluded from both
numerator and denominator — their `efficiency` is an emission rate (e.g. ≈ 0.198 tCO2/MWh
for fossil gas), not an energy output. Negative efficiencies (electricity-input ports such as
methanolisation `bus2 = AC`, `efficiency2 < 0`) are also excluded.

For a pure power plant (single AC output) this evaluates to 1.0. For a gas CHP with electrical
efficiency $\eta_1$ and heat efficiency $\eta_2$ it evaluates to $\eta_1 / (\eta_1 + \eta_2)$:
only the electricity-attributable share of fuel input must be green; the heat output share is
not required to be covered by green fuel.

## Constraint 1 — electricity balance

### Right-hand side scalar — exogenous demand

Sum of weighted `p_set` for all active Austrian `Load` components on AC and low-voltage buses
(base load, industry, agriculture, transport, heat-pump-coupled loads, etc.). Loads on other
buses (e.g. hydrogen, gas) are out of scope and are governed by the energy-system optimisation
as usual.

### Left-hand side positive terms — green production

- **Renewable generators** — generators where `carrier` ∈ `n.meta["renewable"]` (including
  hydro sub-carriers such as run-of-river and PHS, plus `solar rooftop`) and bus on an
  Austrian electricity bus.
- **StorageUnit dispatch** — `StorageUnit-p_dispatch` of hydro reservoir and PHS units in
  Austria.
- **Green fuel-to-power links** — `Link-p × efficiency × weightings` for any link whose
  `bus0` is in an Austrian fuel bus (carrier ∈ `mods.net_zero_electricity.fuels`) and any
  positive-efficiency output port lands on an Austrian electricity bus. Green-ness of the
  consumed fuel is enforced by Constraints 2–4.
- **Storage discharger Links** — battery, home-battery, and V2G dischargers, valued at
  `Link-p × efficiency`.

### Left-hand side withdrawal terms — subtracted from production

All terms are positive Power×time quantities; the constraint subtracts them from the green
LHS before comparing against $D_c$.

- **PHS pumping** — `StorageUnit-p_store` of PHS units (captures the round-trip loss; PHS
  dispatch on the supply side and pumping here together carry the energy cycle).
- **Power-to-X consumption** — `Link-p × weightings` for any link with `bus0` on an
  Austrian electricity bus and no output port landing on any electricity bus (battery and
  home-battery chargers, H2 electrolysis, heat pumps with `p_max_pu > 0`, …). AC-to-AC
  transmission and distribution links are excluded by the "no electricity output port"
  filter.
- **Auxiliary electricity at negative-efficiency ports** — for any port $p$ with bus on
  an electricity bus and `efficiency_p < 0` (e.g. methanolisation `bus2 = AC`,
  `efficiency2 < 0`), the consumed power `−Link-p × efficiency_p` is added back to the
  RHS.
- **Reverse-flow links (heat pumps)** — PyPSA-Eur models heat pumps with `bus0 = heat`,
  `bus1 = electricity`, `p_max_pu ≤ 0`. They draw electricity at `bus1` even though `bus0`
  is not on an electricity bus, so they are added explicitly via `−Link-p × efficiency`.
- **Electricity distribution grid losses** — the `electricity distribution grid` link has
  `bus0 = AC`, `bus1 = low voltage`, `efficiency < 1`. LV loads are already captured in $D_c$;
  only the dissipated fraction `Link-p × (1 − efficiency)` is added here.
- **Domestic AC transmission line losses** — when `transmission_losses > 0` in config, PyPSA
  creates a `Line-loss` variable and the constraint subtracts `Line-loss × weightings` summed
  over Austrian AC lines (both `bus0` and `bus1` in Austria).

Cross-border AC transmission and DC interconnectors are excluded from withdrawal: the P2X
filter requires no electricity output, and bidirectional transmission links have electricity
at both ports.

## Constraint 2 — green gas production

**Left-hand side** — domestic green gas production:

Links where `name.startswith(country)`, `bus1` ∈ Austrian gas buses, and `bus0` carrier ≠
`"gas"`. This structurally captures `biogas to gas`, `biogas to gas CC`, and `Sabatier`
while excluding EU→AT gas imports and pipeline flows (whose `bus0` also has carrier `"gas"`).

Sabatier (H2 → gas) is counted as green gas. Its green-ness is propagated to the H2 chain by
Constraint 3, which requires the H2 it consumes to come from domestic green producers.

**Right-hand side** — gas attributed to electricity production:

$$\sum_i \phi_i \cdot F_i^{\text{gas}}$$

summed over all gas-to-power links $i$ (links with `bus0` in Austrian gas buses and a
positive-efficiency electricity output port). For a pure gas turbine $\phi = 1.0$. For a gas
CHP $\phi = \eta_\text{elec} / (\eta_\text{elec} + \eta_\text{heat})$, so the heat output
share is not required to be covered by green gas.

## Constraint 3 — green H2 production

**Left-hand side** — domestic green H2 production:

Links where `name.startswith(country)`, `bus1` ∈ Austrian H2 buses, and `bus0` carrier is in
the configurable `mods.net_zero_electricity.h2_sources` allowlist. The default allowlist is
`{"AC", "low voltage", "solid biomass"}`, admitting H2 Electrolysis and biomass-to-H2 as
green producers.

Why an allowlist and not a "`bus0` ≠ H2" mirror of the gas/methanol pattern: SMR / SMR CC
(`bus0 = gas`, `bus1 = H2`) are blue/grey H2. A "`bus0` ≠ H2" filter would silently admit
fossil-gas H2 onto the green-H2 LHS. The allowlist makes the policy decision explicit.

**Right-hand side** — two-part demand:

1. **H2 consumed by H2-to-power** × `electricity_fraction` (same pattern as Constraints 2/4).
2. **Full H2 withdrawal by H2-to-other-green-fuel synthesis** — for each green fuel
   $f' \in \{\text{gas, methanol, solid biomass}\}$, every link with `bus0` ∈ Austrian H2
   buses and any output port on an Austrian $f'$ bus contributes its **entire** H2 input
   (`Link-p × weightings`, no electricity-fraction scaling). This captures Sabatier (H2 → gas)
   and methanolisation (H2 → methanol).

The second term ensures green-fuel chains are not satisfied with grey-H2-derived "green"
products: any green gas or green methanol made from H2 is itself backed by domestically
produced green H2.

## Constraint 4 — green methanol production

**Left-hand side** — domestic green methanol production:

Links where `bus1` ∈ Austrian methanol buses and `bus0` carrier ≠ `"methanol"`. Captures
`biomass-to-methanol`, `biomass-to-methanol CC`, and `methanolisation`. Excludes EU→AT
methanol imports (`bus0` carrier `"methanol"`).

**Right-hand side** — methanol consumed by methanol-to-power links (`CCGT methanol`,
`OCGT methanol`, `CCGT methanol CC`) × `electricity_fraction`. For these pure-electricity-output
plants $\phi = 1.0$.

## Configuration

```yaml
mods:
  net_zero_electricity:
    enable: true
    fuels: ["gas", "H2", "solid biomass", "methanol"]
    # Primary-green source bus_carriers admitted as green-H2 producers.
    # "gas" is intentionally omitted: SMR / SMR CC (bus0=gas → bus1=H2)
    # is blue/grey H2 and the green-gas constraint only enforces green gas
    # for gas-to-power, NOT for gas-to-H2. Admitting "gas" here would let
    # fossil gas reach the green-H2 LHS through SMR.
    h2_sources: ["AC", "low voltage", "solid biomass"]
    # Country keys map to inclusive start years. Constraints activate for
    # planning_horizons >= the listed year.
    AT: "2030"
```

| Key | Purpose |
|---|---|
| `enable` | Master toggle. If false or absent, all four constraints are skipped. |
| `fuels` | Carriers treated as green fuels for Constraint 1 LHS (green fuel-to-power links). |
| `h2_sources` | Bus carriers admitted as green-H2 producers in Constraint 3 LHS. |
| `<country>: <year>` | Inclusive start year per country prefix (e.g. `AT: "2030"`). |

## Known limitations

**Export overstatement** — if a gas, H2, or methanol plant produces electricity that is
exported (and therefore not counted toward the Austrian demand in Constraint 1's RHS),
its fuel consumption is still included in the RHS of Constraints 2–4. The required domestic
green fuel production is slightly overstated in scenarios where Austrian power plants are
net exporters. For Austria as a structural electricity importer the practical impact is
expected to be small.

**CHP heat share** — only the electricity-attributable share of fuel consumption (via
`electricity_fraction`) must come from green sources. The heat output share is not required
to be backed by green fuel. This reflects the model interpretation that the EAG target
covers electricity specifically, not total final energy.

**Annual balance only** — the constraint is assessed over the full simulation period
(weighted snapshot sum), not hour-by-hour. Hourly deficits are permissible as long as the
annual total balance is satisfied.

**Biogas-fed SMR not admitted as green H2** — extending the green-H2 LHS to admit biogas-fed
SMR would require a downstream "share of H2 that ends up as electricity" factor analogous to
$\phi$, propagated across two conversion stages (gas → H2 → power). Today `gas` is intentionally
omitted from `h2_sources` so the single-stage constraint stack stays consistent.

## Implementation reference

The four constraint functions live in [`mods/constraints/eag.py`][mods.constraints.eag]:

| Function | Constraint |
|---|---|
| `_add_net_zero_electricity_production_constraint` | Constraint 1 |
| `_add_green_gas_production_constraint` | Constraint 2 |
| `_add_hydrogen_production_constraint` | Constraint 3 |
| `_add_methanol_production_constraint` | Constraint 4 |
| `_compute_electricity_fraction` | shared helper computing $\phi_i$ |

The orchestrator `constraint_net_zero_electricity` calls all four, is exported from
`mods/__init__.py`, and is invoked from `scripts/pypsa-at/additional_functionality.py`.

## Verification

Each constraint is independently verified by a `pytest.statistics`-based test that mirrors
the constraint's LHS/RHS using `pypsa.statistics` aggregations:

| Test | Verifies |
|---|---|
| `test_net_zero_electricity_constraint_statistics` | Constraint 1 |
| `test_green_gas_constraint_statistics` | Constraint 2 |
| `test_green_h2_constraint_statistics` | Constraint 3 |
| `test_green_methanol_constraint_statistics` | Constraint 4 |

The tests live in `test/test_mods/test_mods.py` and require a solved scenario via
`--result-path`. A second per-constraint test reuses the constraint
helpers directly to provide an algebraic cross-check; both must pass before a scenario is
considered EAG-compliant.
