# EAG §4(4) — Renewable Expansion Targets

## Legal requirement

[EAG §4(4)](https://www.ris.bka.gv.at/GeltendeFassung.wxe?Abfrage=Bundesnormen&Gesetzesnummer=20011619)
(*Erneuerbaren-Ausbau-Gesetz*) requires that renewable electricity generation in Austria
rises by 27 TWh/a from the 2020 production to 2030, and names the technologies that are to
deliver it: 11 TWh from photovoltaics, 10 TWh from wind, 5 TWh from hydropower and 1 TWh from
biomass. Unlike the net-zero balance of [§4(2)](eag-net-zero-electricity.md), which is a
constraint on the whole system, these are production levels per technology.

## Implementation approach

Each target is enforced as an annual production floor for Austria in 2030 through
`solving.constraints.limits_volume_min` (see the how-to guide
[Production Targets](../../how-to-guides/production-targets.md)). The floor sums the
snapshot-weighted output of the source's generators over the year and requires it to reach the
configured energy; the solver then decides which capacity to build to get there, within the
capacity corridors and potentials that bound every technology.

| Source | 2030 floor | Basis |
|---|---:|---|
| `solar` | 14 TWh | 2020 production plus the EAG increment, rounded to the monitoring of energie.gv.at |
| `wind` | 17 TWh | likewise |
| `hydro` | 47 TWh | 2020 production of about 42 TWh on the Statistik Austria basis plus 5 TWh (see below) |
| `biomass` | 5.6 TWh | electricity from solid biomass, biogas and renewable gas |

The floors are registered as `production_limit_lower-{source}-AT` in `n.global_constraints`
with their right-hand side, so the shadow price of each target can be read from the solved
network. In the 365H reference run of 2030 the wind floor binds at 14 €/MWh and the hydro
floor at 8 €/MWh; the solar floor is slack.

## The hydro target

The 5 TWh for hydropower rest on the Statistik Austria accounting, which counts the natural
inflow of pumped-storage plants but not generation from pumped water. On that basis the 2020
production was about 42 TWh, so the 2030 level is 47 TWh/a.

The floor counts natural inflow only: the run-of-river generators and the inflow generators of
the reservoir and pumped-storage stores, each weighted by the efficiency of the turbine of its
store (0.90 for reservoirs, 0.87 for pumped storage), which states the floor in delivered
electricity. The turbine output of pumped storage is not part of it, because a floor on turbine
output would reward pumping and turbining water for no other reason than meeting the floor.
This is the same basis as the target: generation from pumped water counts nowhere. E-Control's
statutory monitoring of the EAG goes one step further and leaves the pumped-storage plants out
entirely, natural inflow included, because its statistics cannot separate the two; on that
basis the 2020 production was 39.0 TWh and the 2030 level would be 44 TWh. The two readings
differ by the natural inflow of the pumped-storage plants, about 3 TWh/a, and the model
follows the law's figure of 47.

### Which weather years can meet it

Whether the floor can be met depends on the weather year, because the inflow targets scale
with it while the fleet does not, and the law's figure is a snapshot for 2030 rather than a
normalised value. How the inflow of the calibrated Austrian fleet is built and scaled to a
weather year is explained in
[Hydropower Capacities and Inflows](../hydro-capacity-trajectories.md#part-3-inflows). The
table shows, per weather year, the delivered natural inflow of the calibrated 2025 fleet,
counted as the floor counts it, the energy still missing to 47 TWh, and what the run-of-river
corridor of 2030 could add: 704 MW of regional headroom at the vintage yields, 2.4 TWh in 2013
hours and 1.7–2.6 TWh in the other years.

| Weather year | Delivered natural inflow, 2025 fleet | Missing to 47 TWh | 2030 corridor at vintage yield | Feasible in 2030 |
|---|---:|---:|---:|:---:|
| 2025, 2022, 2003, 2011 | 33.4–38.9 TWh | 8.1–13.6 TWh | 1.7–2.0 TWh | no |
| 2018, 2021, 2006, 2015, 2017, 2023, 2007, 2005, 2019 | 39.7–42.6 TWh | 4.4–7.3 TWh | 2.0–2.3 TWh | no |
| 2004, 2016, 2010, 2020, 2008 | 43.5–43.8 TWh | 3.2–3.5 TWh | 2.2–2.3 TWh | no |
| 2014 | 45.1 TWh | 1.9 TWh | 2.3 TWh | within the corridor |
| 2013, 2009, 2024 | 46.3–46.5 TWh | 0.5–0.7 TWh | 2.4 TWh | within the corridor |
| 2001, 2002, 2012, 2000 | 47.0–49.1 TWh | 0 | | yes |

![Delivered natural inflow of the 2025 fleet for every E-Control weather year from 2000 to 2025, split into run-of-river, reservoir and pumped storage, against the 47 TWh EAG floor; the energy of the KLIEN run-of-river corridor headroom for 2030 and 2040 is stacked on top.](../../assets/hydro/03_weather_years_vs_eag_target.png)

With the configured 2013 weather year the fleet delivers 46.3 TWh, so the floor binds: the
optimizer has to add about 0.7 TWh of run-of-river energy from the corridor, a third of what
the 2030 headroom offers. In the reference run it adds 150 MW in 2030, mostly on the Danube
and in the Mühlviertel where the remaining hours are highest, and the floor's shadow price is
7.8 €/MWh; by 2040 the run-of-river additions reach 1.3 GW without any floor, because the
study's remaining stretches are competitive at their hours. Four wet years reach the floor on
their own, four average-to-wet years reach it with buildout inside the corridor, and eighteen
of the 26 years, every dry or below-average one, cannot meet it with any buildout the corridor
permits. That is the honest picture: E-Control's monitoring reports hydropower behind its
linear path in every year but the wet 2024. A hard floor makes a dry year infeasible, which is
the intended signal rather than a defect; the pumped-storage column follows E-Control's natural
inflow of the respective year.

## Configuration

| Setting | Meaning |
|---|---|
| `solving.constraints.limits_volume_min.{solar,wind,hydro,biomass}.AT.2030` | The four production floors in TWh/a. |
| `snapshots` | The weather year, which decides the hydro inflow the floor is measured against. |
| `mods.trajectories.apply_trajectories` | Enables the capacity corridors that bound how much run-of-river the optimizer may add to reach the hydro floor. |
