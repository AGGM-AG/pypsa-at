# Hydro Capacity Trajectories

This page explains where the **hydropower capacity limits** in PyPSA-AT come from: how much
run-of-river, reservoir, and pumped-storage capacity the optimizer is allowed to build in each
country and planning horizon, and why Austria is treated differently from the rest of Europe.

How these limits are technically enforced during the solve — the `trajectories.csv` schema and
the constraint mechanism — is described in
[Generic Capacity Trajectories](capacity-trajectories.md). This page covers the hydro *content*
of that file.

## Why hydro needs capacity corridors

Hydropower capacities in PyPSA-AT are extendable: the optimizer decides how much capacity to
build, the same way it decides on wind or solar. Unlike wind and solar, however, hydro buildout
is tightly limited in reality — usable river stretches and reservoir sites are finite, and most
of Europe's hydro potential is already developed. Without an upper bound, the optimizer would
happily build implausible amounts of hydropower, because in the model every added run-of-river
turbine receives a proportional share of river inflow ("free water").

The capacity trajectories therefore define, per country, technology, and planning horizon, an
**upper corridor**: existing plants are always allowed (the brownfield fleet is never forced
below its installed capacity), and new capacity may be added up to the trajectory value. Whether
the corridor is used remains an optimization result.

## Data sources

### All countries: TYNDP / PEMMDB

For every modelled country, the corridors come from the **PEMMDB market node data** published
with the TYNDP scenarios (Open-TYNDP "Hydro Inflows" dataset). PEMMDB reports installed
capacity and storage volume per market node, year, and hydro category. These categories map to
the model's hydro technologies as follows:

| PEMMDB category                  | Model technology              | Bounded quantity        |
|----------------------------------|-------------------------------|-------------------------|
| Run of River, Pondage            | Run-of-river (`ror`)          | Turbine capacity (MW)   |
| Reservoir                        | Reservoir (`hydro`)           | Turbine capacity (MW) and storage volume (MWh) |
| Pumped storage, open and closed loop (`PS`) | Pumped storage (`PHS`) | Pump and turbine capacity (MW) and storage volume (MWh) |

Planning horizons or countries missing from PEMMDB receive a zero corridor, which in practice
means "no buildout beyond the existing fleet" (installed capacity always remains allowed).

### Austria: KLIEN realisable potential for run-of-river

The PEMMDB values are not calibrated for Austria. The Austrian **run-of-river** corridor is
therefore replaced with the *realisable* hydropower pathway from the KLIEN study
[*Erneuerbare Energiepotenziale in Österreich für 2030 und 2040*](https://gtif-austria.info/narratives/tf2-hydropower)
(Resch et al. 2026, AIT / Umweltbundesamt, CC BY 4.0) — the same study that already provides
the Austrian PV and wind potential limits. The study assesses every Austrian river catchment
and quantifies how much additional river hydropower is realistically developable under three
ambition pathways (low / medium / high) and two climate scenarios (RCP 4.5 / RCP 8.5), with
values for today, 2040, and 2070.

The Austrian corridor is built as a **growth factor, not an absolute value**: the study's
Austria-wide realisable capacity for a pathway year is divided by the study's current capacity,
and this factor is applied to the model's calibrated Austrian run-of-river fleet (which is
itself validated against the Anlagenregister and the E-Control Bestandsstatistik, see
[issue #312](https://github.com/AGGM-AG/pypsa-at-planning/issues/312)). This avoids mixing two
different definitions of "today's fleet": the study's baseline and the model's brownfield data
do not delineate river hydropower identically, but the *relative* growth they imply is
transferable. Factors are anchored at the first planning horizon (factor 1.0), 2040, and 2070,
and interpolated linearly for horizons in between.

With the default settings (medium ambition, RCP 4.5), the Austrian run-of-river corridor is:

| Horizon | Growth factor | Upper limit |
|---------|---------------|-------------|
| 2025    | 1.000         | ≈ 6.3 GW    |
| 2030    | 1.066         | ≈ 6.7 GW    |
| 2040    | 1.198         | ≈ 7.5 GW    |
| 2050    | 1.227         | ≈ 7.7 GW    |

for a calibrated 2025 fleet of ≈ 6.3 GW.

### Why only run-of-river is overridden for Austria

- **Reservoir plants**: Austria's storage sites are essentially built out; the KLIEN realisable
  pathway contains no meaningful new reservoir capacity. The PEMMDB corridor for reservoirs
  already sits below the calibrated existing fleet, which the constraint treats as "no
  buildout" — the desired behaviour.
- **Pumped storage**: buildout is real (Limberg III, Reißeck II+, Tauernmoos) and is *not*
  covered by the KLIEN river-catchment assessment. PHS keeps its PEMMDB corridor, which allows
  roughly +1.3 GW by 2040.
- The study's realisable potential is dominated by revitalisation and efficiency gains on
  existing plants plus small-hydro additions — effects that appear in the model as new
  run-of-river capacity.

## Configuration

| Setting | Meaning |
|---------|---------|
| `mods.update_hydro_capacities_AT.enable` | Master switch for the Austrian hydro data calibration, including the KLIEN run-of-river corridor. When off, the Austrian rows keep their PEMMDB values. |
| `mods.klien_potential_limits.ambition` | Pathway ambition (`low` / `medium` / `high`), shared with the KLIEN PV and wind limits. |
| `mods.klien_potential_limits.climate_scenario` | Climate scenario (`wocc` / `mocc` / `stcc`), shared with the KLIEN PV and wind limits. The hydro study publishes pathways only for `mocc` (RCP 4.5) and `stcc` (RCP 8.5); `wocc` falls back to `mocc`, which is logged. |
| `mods.trajectories.apply_trajectories` | Enables/disables enforcement of all capacity trajectories during the solve (see [Generic Capacity Trajectories](capacity-trajectories.md)). |
