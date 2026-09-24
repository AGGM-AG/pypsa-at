# Austrian Gas-Fired Power Plant Brownfield

The Austrian gas-fired fleet that `powerplantmatching` 0.8.1 hands to
`add_existing_baseyear` is 15 plants and 4 596 MW. Against the E-Control
Bestandsstatistik that is 218 MW short, but the agreement is coincidental: the
fleet carries a plant that was demolished in all but name, misses four units
outright, dates a combined-cycle plant to 1970, and labels the most productive
gas plant in the country a steam turbine — which removed it from the brownfield
entirely.

This page explains how PyPSA-AT corrects that fleet, and what it does **not**
fix.

## The two problems

### Duplicate registrations in the Anlagenregister

The Anlagenregister cannot be summed over natural gas: its raw gas techcodes
total 7 180 MW, half again the 4 814 MW of the Bestandsstatistik. Three
mechanisms inflate it, and `scripts/pypsa-at/build_anlagenregister_at.py`
removes each one separately.

**Two taxonomies.** The register mixes a legacy German vocabulary (`Erdgas`,
45 rows, 5 551 MW) with the newer EECS English one (`Fossil - Natural gas` and
four `Thermal - ...` variants, 70 rows, 1 629 MW). One plant can appear under
both. `drop_duplicate_gas_registrations` collapses registrations that share a
postal code and a capacity, keeping the one with the higher realised feed-in.

**Multi-fuel sites.** A plant that can burn several fuels is registered once per
fuel, each time at the *plant* capacity. Dürnrohr appears five times at
398.4 MW — as waste, natural gas, liquid biomass, hard coal and solid biomass.
`drop_shared_capacity_gas_registrations` reads the realised 2021–2026 feed-in as
the evidence for which fuel is the primary one, and drops the gas row when
another combustion fuel outproduced it. It never removes a non-gas row, so the
register totals of every other fuel are untouched; extending the same treatment
to them is [#323](https://github.com/AGGM-AG/pypsa-at-planning/issues/323).

**Sites split across postal codes.** GDK Mellach and the Fernheizkraftwerk
Mellach sit on one site that the river Mur splits between PLZ 8410 (Wildon,
AT225) and PLZ 8402 (Werndorf, AT221) — Verbund's environmental statement calls
it *"ein Doppelstandort, welcher räumlich lediglich durch den Fluss Mur getrennt
ist"*. Both plants are registered on both banks. No rule on postal code and
capacity can see this, so the two superfluous rows are named explicitly in
`GAS_DEDUP_DROP`.

Together these remove 895 MW and bring the register to 6 285 MW.

!!! note "Why deduplication alone does not reach the statistic"
    The deduplicated register is still 1 471 MW above the Bestandsstatistik.
    The remainder is dormant registrations — plants that report zero feed-in in
    all six published years but were never deregistered, such as the 405 MW at
    Zwentendorf or the 175 MW second Mellach entry. A rule that dropped every
    non-reporting plant would also retire roughly 1.3 GW of plants that are
    running, because the legacy taxonomy rows stopped reporting in 2026 and
    `feedin_kwh_2026` is only partially populated (26.3 TWh against 61.3 TWh
    Austria-wide). The register is therefore used as evidence per plant, never
    as a capacity total.

### An unreliable brownfield fleet

`data/pypsa-at/gas_powerplant_overrides_AT.csv` carries one row per correction,
each with the source URL, the evidence quoted from it, and the figures from
competing sources that were rejected. Precedence is operator publication
> E-Control > Global Energy Monitor / Wikipedia.

| Correction | Effect | Why |
| --- | --- | --- |
| **Theiß** split into four units | 485 → 865 MW | `powerplantmatching` carries only the 485 MW combined-cycle block B. Gas turbines C and D (70 MW each) and the 240 MW turbine added in 2020 are missing. |
| **Mellach** split into two units | 1 084 → 997 MW | GDK Mellach is 832 MW. The Fernheizkraftwerk is carried at its 246 MW coal-era rating, but it stopped burning coal on 31 March 2020 and delivers 165 MW net on gas. |
| **Donaustadt** relabelled `CCGT` | 0 → 395 MW in the brownfield | `powerplantmatching` labels it `Steam Turbine`. `add_existing_baseyear` selects on `Technology in (OCGT, CCGT)`, so Austria's most productive gas plant (7 349 GWh over 2021–2026) never entered the fleet. |
| **Linz Mitte** split into two units | 217 MW, unchanged | Units 1a (103 MW) and 1b (114 MW) were commissioned in 2004 and 2010. `powerplantmatching` dates the whole site to 1970, the year the site opened, putting a modern combined-cycle plant in a 1970 vintage bin. |
| **Leopoldau** given `DateOut = 2012` | −140 MW from 2025 | The plant delivered 140 MW until about 2012; today only hot water boilers remain. The register reports zero feed-in in all six published years. |
| **Steyrermühl** dropped | −40 MW | The register holds exactly one plant of this size in the Laakirchen/Steyrermühl area, which is already the Laakirchen row. The duplicate carries no `DateIn`, so `add_existing_baseyear` would have invented a vintage for it. |
| **voestalpine Werk Linz** dropped | −153 MW | The works power plant burns blast furnace and coke oven gas. E-Control accounts it under *Derivate* (409 MW, a separate line from *Erdgas*), so it must not be calibrated against the Erdgas statistic. |
| **Kirchdorf an der Krems** added | +13.2 MW | Energie AG's gas engine CHP, fully operational January 2013, 156 GWh over 2021–2026. Absent from `powerplantmatching`. |

`Set = "CHP"` is preserved throughout: 14 of the 15 original rows are CHP
plants, and `add_existing_baseyear` only acts on `Set` inside a
Germany-specific guard.

## Which plants belong in the fleet

The criterion is **regular commercial supply to the public grid at 110 kV or
above**. Demand-side response — APG contracting industrial sites to stabilise
the grid — is out of scope for PyPSA-AT, so a plant that only ever exports under
such a contract does not qualify.

Sappi Gratkorn and the Laakirchen paper mill stay in the fleet and are tagged
`autoproducer`, because their primary purpose is on-site process energy even
though they do supply the grid. voestalpine Werk Linz leaves the *natural gas*
fleet on fuel grounds, not on this criterion.

Two plants remain undecided and are carried unchanged from
`powerplantmatching`: Lenzing Energy (70 MW) and Krems Industriepark (41 MW).
Both look like Global Energy Monitor encoding errors — Krems' technology field
reads *"ICCC (Integrated Coal Combined Cycle)"* for what is a ~4 MW process-gas
CHP — but neither has been confirmed. Jenbach (INNIO, 45 + 18 MW) sells
19.5 GWh a year commercially, matching INNIO's own ESG report to 0.4 %, but its
grid voltage level is unproven, so it is not added.

## Calibration

`check_gas_calibration_at` runs at build time against
`data/pypsa-at/gas_calibration_targets_AT.csv`, the E-Control series for
2010–2025.

**Capacity, one-sided.** The modelled fleet must not *exceed* the
Bestandsstatistik Brutto-Engpassleistung by more than 2 %. A shortfall only
appears in the log: plants that never supply the public grid are out of scope by
design, so the fleet is expected to sit below the statistic.

**Full load hours, two-sided and fatal.** E-Control's 2025 gross generation
divided by the modelled fleet must fall inside 1 500–2 500 h. The band brackets
every year from 2015 to 2025 (1 541 h in 2015, 2 483 h in 2019, mean 1 994 h).
2013 and 2014 sit below it at 1 249 h and 1 057 h, when gas was pushed out of
the merit order; excluding them is deliberate. This is the check a capacity
error in *either* direction shows up in.

The corrected fleet is **4 569 MW** operating in 2025, 244 MW (5.1 %) below the
statistic, implying **2 088 full load hours** against E-Control's own 1 982 h.

A second check runs after solving, as the `AT`-marked
`test_at_gas_full_load_hours_are_plausible`, against the dispatch of the solved
networks. It is fatal for the base year and informational for later horizons: a
decarbonising fleet is expected to drift out of a band measured on today's
system.

!!! warning "The residual 244 MW is not explained plant by plant"
    It is consistent with the autoproducer and small-plant capacity the fleet
    deliberately omits, and with the two undecided plants above, but no
    reconciliation is claimed. `resources/gas_brownfield_deviations_{clusters}.csv`
    carries the three-way comparison — `powerplantmatching`, model, deduplicated
    register — per NUTS3 region so the gap can be inspected.

## Known limitations

- **Gross and net are conflated.** The Bestandsstatistik publishes
  Brutto-Engpassleistung. Where a source gives only one capacity, the override
  file records it as both `capacity_mw_net` and `capacity_mw_gross`, which
  understates the modelled gross total by roughly the plants' own consumption
  and makes the one-sided test marginally easier to pass. Only the
  Fernheizkraftwerk Mellach has genuinely distinct figures.
- **Simmering is not split.** `powerplantmatching` gives 1 180 MW for the site;
  the unit capacities reported for blocks 1, 2 and 3 do not reconcile with each
  other or with the register's rows, so the site is left aggregated rather than
  split on figures that disagree.
- **The register is not reconciled per region.** Nine NUTS3 regions deviate from
  the deduplicated register by more than 10 % and 50 MW. These are logged as
  warnings, not errors, because the register's dormant registrations cannot be
  separated mechanically from operating plants.
- **`add_electricity` ignores `DateIn` and `DateOut`.** It computes `lifetime`
  and `build_year` from them, then PyPSA's default aggregation strategies
  overwrite both with `0` and `inf` when generators are grouped per bus and
  carrier. Leopoldau's `DateOut = 2012` therefore does not remove it there. It
  has no effect on PyPSA-AT's results: `prepare_sector_network` deletes every
  `OCGT` and `CCGT` generator from the electricity-only network, because gas is
  modelled as links from the gas bus in the sector-coupled network.

## Configuration

```yaml
mods:
  update_gas_capacities_AT:
    enable: true
```

With `enable: false` the powerplants table passes through unchanged and the
deviations file is written empty, so the Snakemake DAG does not depend on the
setting.
