# Production Targets

Annual production targets can be set in `solving.constraints` using TWh/a:

```yaml
solving:
  constraints:
    limits_volume_min:
      solar:
        AT:
          2030: 22
    limits_volume_max:
      wind:
        AT:
          2040: 20
```

`limits_volume_min` sets a minimum and `limits_volume_max` sets a maximum. A
constraint is applied only in the configured planning year and region. The
available source names and covered model carriers are:

| Source | Covered carriers |
|---|---|
| `solar` | `solar`, `solar-hsat`, `solar rooftop` |
| `wind` | `onwind`, `offwind-ac`, `offwind-dc`, `offwind-float` |
| `hydro` | `hydro inflow`, `ror`, `PHS inflow` |
| `biomass` | Links from `solid biomass`, `biogas`, `gas`, or `renewable gas` to `AC` or `low voltage` |

The biomass target also covers gas-fired electricity. The 2030 EAG constraint
requires Austrian electricity produced from gas to be covered by domestically
produced biogas or renewable gas.

The `hydro` source counts natural inflow only: the run-of-river generators and the
inflow generators that fill the reservoir and pumped-storage stores. The turbine output
of pumped storage is deliberately not part of it, because a floor on turbine output would
reward pumping and turbining water for no other reason than meeting the floor.
E-Control's hydro statistic, against which the EAG progress is measured, does include
generation from pumped water (3–4 TWh/a). The configured Austrian floor for 2030 is
therefore the EAG target minus a fixed 4 TWh credit for that share (47 − 4 = 43 TWh).
Which weather years can meet it is discussed in
[Hydropower Capacities and Inflows](../explanations/hydro-capacity-trajectories.md#the-eag-hydro-target).

## Adding Sources

To add a generator-based source, add its model carriers to
`GENERATOR_CARRIERS` in `mods/constraints/production.py`. For a link-based
source, add its input and output bus carriers to `LINK_CARRIERS`:

```python
GENERATOR_CARRIERS["geothermal"] = ["geothermal"]
LINK_CARRIERS["renewable_heat"] = (["renewable gas"], ["low temperature heat"])
```

The new key can then be used in `limits_volume_min` or `limits_volume_max`.
