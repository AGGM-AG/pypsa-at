# Open-TYNDP Capacity Trajectories

## Motivation

PyPSA-Eur allows the optimizer to freely expand any extendable technology up to whatever capacity minimizes
total system cost. For variable renewable energy sources (wind, solar) and storage this freedom is often
over-optimistic: the model can install far more capacity than real-world supply chains, political constraints,
or regulatory processes would ever permit within a given time period.

The [Open-TYNDP](https://github.com/open-energy-transition/open-tyndp) project uses the capacity
trajectories from ENTSO-E's Ten-Year Network Development Plan (TYNDP). These trajectories encode the
minimum and maximum buildout that European Transmission System Operators (TSOs) report per
technology, country, and year. PyPSA-AT ingests these trajectories and enforces them as
`p_nom_min` / `p_nom_max` bounds for EU country regions.

!!! note "Austria and Germany are excluded"
    Austria (`AT`) and Germany (`DE`) receive their dedicated calibration functions in PyPSA-AT
    and -DE, respectively. instead of Open-TYNDP. They are excluded via the `skip_countries`
    configuration key.

## Covered Technologies

The following PyPSA carriers are constrained by TYNDP trajectories:

| PyPSA-Eur carrier         | Component     | Constraint mechanism                   |
|---------------------------|---------------|----------------------------------------|
| `onwind`                  | Generator     | `p_nom_min` / `p_nom_max` set directly |
| `solar rooftop`           | Generator     | `p_nom_min` / `p_nom_max` set directly |
| `solar` + `solar-hsat`    | Generator     | Combined linopy constraint (see below) |
| `battery discharger`      | Link (port 1) | `p_nom_min` / `p_nom_max` set directly |
| `home battery discharger` | Link (port 1) | `p_nom_min` / `p_nom_max` set directly |
| `H2 Electrolysis`         | Link (port 0) | `p_nom_min` / `p_nom_max` set directly |

!!! info "Utility scale Solar PV: flat-panel and single-axis tracking (hsat)"
    The TYNDP `solar-pv-utility` trajectory covers the **combined** deployment of `solar` (flat-panel)
    and `solar-hsat` (single-axis horizontal tracking). Rather than forcing a fixed split, PyPSA-AT adds
    a linopy constraint that enforces the joint floor and ceiling over both technologies, leaving the
    optimal technology mix to the solver:

    ```
    p_nom_opt[solar @ loc] + p_nom_opt[solar-hsat @ loc] >= floor
    p_nom_opt[solar @ loc] + p_nom_opt[solar-hsat @ loc] <= ceiling
    ```

## Implementation Assumptions

### Brownfield deduction

For planning horizons beyond 2025, existing brownfield capacity is subtracted from the trajectory bounds
so that the bounds represent the *additional* capacity still available to build:

```
effective_p_nom_min = max(0, traj_p_nom_min - existing_brownfield)
effective_p_nom_max = max(0, traj_p_nom_max - existing_brownfield)
```

End-of-life assets are removed by the upstream `add_brownfield` step before the trajectories are applied,
so `existing_brownfield` reflects only assets that remain economically active.

For the 2025 base year `p_nom_min` is set to zero for all non-nuclear carriers. The 2025 investment
optimum should not be pre-determined by a floor constraint.

### Geographic aggregation

TYNDP uses its own bus codes (e.g. `ITA0`, `ITN1`, `SE01`). PyPSA-AT maps these to PyPSA-AT location
codes via an explicit dictionary in `mods/pemmdb_overwrites.py`. Key rules:

- Sub-national TYNDP zones are resolved to the corresponding PyPSA-AT cluster code (e.g. `ITSI` → `IT1`
  for Sicily, `GBNI` → `GB1` for Northern Ireland).
- Multiple TYNDP buses that collapse to the same location have their `p_nom_min` and `p_nom_max` summed.
- Kosovo (`XK`) has no TYNDP entry; it inherits Serbia's (`RS`) trajectory as a proxy.
- Cyprus (`CY`) is not modeled in PyPSA-AT and is excluded from the aggregated trajectories.
- Northern Ireland (`GB1`) has no H2 Electrolysis trajectory; its bounds are set to zero.

### Backward extrapolation for 2025

The TYNDP source data starts at 2030. A synthetic 2025 row is created with zero values and then
extrapolated backward using the slope between the two earliest non-zero data points per group. The
extrapolated `p_nom_min` is clipped to zero and can never exceed `p_nom_max`.

### TYNDP scenario

The default scenario is `All`, which is the only scenario in the current dataset that covers every
technology. Selecting `DE`, `GA`, or `NT` will cause a runtime error due to missing technology entries.

## Example Data

The table below shows raw TYNDP trajectory data for France (`FR00`). Nuclear appears only under the
`DE`, `GA`, and `NT` scenarios — it has no `All` entry — which is why selecting those scenarios causes a
runtime error (see [TYNDP scenario](#tyndp-scenario) above).

| Technology           | Scenario | Year | p_nom_min (MW) | p_nom_max (MW)  |
|----------------------|----------|------|---------------:|----------------:|
| H2 Electrolysis      | All      | 2025 |            0.0 |             0.0 |
| H2 Electrolysis      | All      | 2030 |            0.0 |         9 999.0 |
| H2 Electrolysis      | All      | 2035 |            0.0 |        19 999.0 |
| H2 Electrolysis      | All      | 2040 |            0.0 |        29 999.0 |
| H2 Electrolysis      | All      | 2045 |            0.0 |        39 999.0 |
| H2 Electrolysis      | All      | 2050 |            0.0 |        49 999.0 |
| battery discharger   | All      | 2025 |            0.0 |             0.0 |
| battery discharger   | All      | 2030 |        2 203.7 |         4 298.0 |
| battery discharger   | All      | 2035 |        6 358.4 |        13 423.8 |
| battery discharger   | All      | 2040 |       10 513.1 |        22 549.6 |
| battery discharger   | All      | 2045 |       17 037.9 |        39 687.2 |
| battery discharger   | All      | 2050 |       24 460.8 |        59 107.0 |
| home battery discharger | All   | 2025 |            0.0 |             0.0 |
| home battery discharger | All   | 2030 |            0.0 |             0.0 |
| home battery discharger | All   | 2035 |        4 418.6 |         9 328.4 |
| home battery discharger | All   | 2040 |       10 100.9 |        21 665.3 |
| home battery discharger | All   | 2045 |       15 109.1 |        35 194.4 |
| home battery discharger | All   | 2050 |       19 219.2 |        46 441.2 |
| onwind               | All      | 2025 |            0.0 |        28 000.0 |
| onwind               | All      | 2030 |       28 000.0 |        39 000.0 |
| onwind               | All      | 2035 |       29 250.0 |        50 000.0 |
| onwind               | All      | 2040 |       30 500.0 |        61 000.0 |
| onwind               | All      | 2045 |       35 250.0 |        70 500.0 |
| onwind               | All      | 2050 |       40 000.0 |        80 000.0 |
| solar rooftop        | All      | 2025 |            0.0 |             0.0 |
| solar rooftop        | All      | 2030 |        5 670.0 |        12 340.0 |
| solar rooftop        | All      | 2035 |       14 350.0 |        41 205.0 |
| solar rooftop        | All      | 2040 |       23 030.0 |        70 070.0 |
| solar rooftop        | All      | 2045 |       29 845.0 |        92 355.0 |
| solar rooftop        | All      | 2050 |       35 200.0 |       110 000.0 |
| solar(-hsat)         | All      | 2025 |            0.0 |        32 025.0 |
| solar(-hsat)         | All      | 2030 |       17 330.0 |        45 660.0 |
| solar(-hsat)         | All      | 2035 |       20 650.0 |        59 295.0 |
| solar(-hsat)         | All      | 2040 |       23 970.0 |        72 930.0 |
| solar(-hsat)         | All      | 2045 |       33 655.0 |       104 145.0 |
| solar(-hsat)         | All      | 2050 |       44 800.0 |       140 000.0 |

## Configuration

The feature is controlled under `mods.PEMMDB_trajectories` in `config/config.at.yaml`:

```yaml
mods:
  PEMMDB_trajectories:
    enable: true
    tyndp_scenario: All  # All is the only complete scenario
    skip_countries: [ "AT", "DE" ]  # use PyPSA-DE/AT calibrations instead
```

Set `enable: false` to revert to unconstrained PyPSA-Eur behavior for all covered carriers.
