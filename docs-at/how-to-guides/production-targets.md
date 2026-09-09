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
reward pumping and turbining water for no other reason than meeting the floor. To state
the floor in delivered electricity, every generator on a store bus is weighted by the
efficiency of the turbine link of that store (0.90 for reservoirs, 0.87 for pumped
storage with the default cost data); generators on an electricity bus count fully. This
matches the accounting behind the Austrian target: the EAG (§ 4 (4)) requires hydropower
generation to rise by 5 TWh/a from the 2020 production, which is about 42 TWh on the
Statistik Austria basis that counts the natural inflow of pumped-storage plants but not
generation from pumped water; the configured Austrian floor for 2030 is therefore 47 TWh.
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
