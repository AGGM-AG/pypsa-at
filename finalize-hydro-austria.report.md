# Finalising the Austrian hydro work for pypsa-at-planning #312

Branch `feat/scale-austrian-hydro-capacities` @ f6e2f4c0 (review planned against 3f247206; the
line references of the review still apply). Reference run: `results/hydro-capacities-update/AT_KN2040`
(365H, weather year 2013). Review material: `chore/full-at-layer-review-2026-09`, folder `review/`.
Evidence: `/mnt/storage/2026-09-full-at-layer-review/evidence/p3/`.

Verification status of what this report relies on:

- All five evidence scripts of part 2 ran against the current run (ported unchanged to the
  scratchpad, outputs in `scratchpad/evidence/*.txt`); the review numbers reproduce exactly.
- The KLIEN per-region prototype ran on the run's resources (`scratchpad/klien_regional_proto.py`,
  table in `scratchpad/regional_corridor_table.csv`).
- The reference run was re-solved by the user on 2026-09-21 (networks 09:27–09:59) with the
  hydro floor at 47 TWh (`n.meta` of the 2030 network; GC `production_limit_lower-hydro-AT`
  constant 4.7e7, mu 1e-8). The analysis of part 2 was made on the previous solve (floor
  43.5 TWh) and re-checked on the new one: the AT130 additions, the corridor slack and the
  available energies are identical, because the floor was inert in both solves (P6-01).

---

## 1. Open todos for #312

### 1a. Issue checklist against the branch

"Done" means implemented and covered by a test or a documented number.

| Issue item | State | Where |
|---|---|---|
| **Quantify the gap** — run 2030 without the hydro floor, report AT production by `ror` / `hydro inflow` / `PHS inflow` | **partly done**. The reference run is effectively such a run (floor 43.5, mu 0, and inert per P6-01). The split exists for the 2025 fleet (48.6 TWh = ror 34.1 + reservoir 10.05 + PHS 4.45, docs table and `.marimo/review-hydro-slides.py`), but no 2030 figure is documented, and the 2030 ror value (37.05 TWh) contains 2.9 TWh of phantom AT130 additions (P3-01). | `docs-at/explanations/hydro-capacity-trajectories.md` "The EAG hydro target"; `scratchpad/evidence/p3_T1_at130_dispatch.txt` |
| Compare with E-Control / Statistik Austria / EIA; split inflow-limited vs capacity-limited (spilled inflow, hours at `p_max_pu = 1`) | **partly done**. E-Control comparison documented ("Result against E-Control": 34.1 vs 30.5 TWh ror, 4,790 vs 5,470 h). Spilled inflow and saturated hours are only in the review evidence (AT130 saturated 12 of 24 snapshots; AT reservoir curtailment 123 GWh, 98 % in AT341), not in the repo. | docs page §"Result against E-Control"; review `03-hydro-trajectories-tyndp.md` P3-14, P3-15 |
| **Inflow side** — PEMMDB inflow patch active for AT, what energy it yields | **done**. AT rows of the PEMMDB totals are replaced by the KLIEN targets (`apply_hydro_inflow_targets`), the PEMMDB PS Open value (7.6 TWh) is documented as rejected. | `scripts/pypsa-at/build_inflow_totals_per_region.py`, `test/test_build_inflow_totals_per_region.py::test_apply_hydro_inflow_targets_replaces_at_rows_only`, docs §"Pumped storage" |
| Decide and document the AT inflow normalisation (normal hydrological year for the future fleet, not one weather year) | **done, but contested**. KLIEN Regelarbeitsvermögen (1991–2020 mean) × E-Control year factor; documented with the full year table. The factor definition is under review (P3-04 generation ratio, P3-11 constant pumped-water share) and would lower the 2013 natural inflow by 2.0–2.4 TWh. | `build_hydro_inflow_targets.py::weather_year_factors`, `test/test_build_hydro_inflow_targets.py`, docs §"Weather-year scaling" |
| Added capacity adds usable inflow energy (not re-dividing the same 40 TWh) | **open** — it adds *too much*. A new MW inherits the region's `p_max_pu`, i.e. the existing fleet's hours; in AT130 that is 6,188 h against KLIEN's marginal 3,686 h. Physically justified yield is the subject of Q-P3-09. | `mods/network/hydro.py:503-509`; P3-01 |
| Cross-check `clip_min_inflow`, `flatten_dispatch`, `hydro_max_hours` for AT | **partly done**. The AT path does not use `clip_min_inflow` (atlite's global `lower_threshold_quantile` instead, P3-14); `flatten_dispatch` is off by default and untouched; `hydro_max_hours` handling is defective at bus level (P3-15: 58 of 77 AT storage plants lack a Duration, AT341 gets 116.5 instead of ≈ 850 GWh). Not documented as a cross-check. | `mods/network/hydro.py:205-244`, `scripts/pypsa-at/build_inflow_profile.py:60-65` |
| Align with #247 (catchment-based inflow distribution) incl. Restwassermenge | **done for the energy allocation, Restwasser implicit**. Catchment allocation implemented and tested; the KLIEN RAV is realised generation, so residual-flow obligations are inside the number, not modelled explicitly. Only the *profile* stays region-based (P3-14, Danube upstream profile is an open option Q-P3-05). | `build_hydro_inflow_targets.py`, `test/test_build_hydro_inflow_targets.py` (33 tests), docs §"Allocation" |
| **Capacity side** — AT hydro trajectory 2030/2040/2050 from ÖNIP/EAG/operator pipelines, separating new build / Erweiterung / Revitalisierung | **partly done, different source**. The KLIEN realisable pathway replaces the operator pipeline; it does not separate new build from revitalisation (KLIEN's C and E per catchment are the sum). Reservoir turbines keep the PEMMDB corridor (zero headroom), PHS turbines/pumps keep PEMMDB (+1.1 GW_el effective, P3-13). | `scripts/pypsa-at/build_klien_hydro_trajectory_at.py`, `test/test_build_klien_hydro_trajectory_at.py`, docs §"Austria: KLIEN study" |
| Feed it through the trajectory mechanism instead of `skip_countries` | **done, but national**. One AT row per horizon in `trajectories_{clusters}.csv`; the constraint binds in every horizon (slack −0.1 MW). The row is national, hence P3-01. | `build_capacity_trajectories.py::apply_klien_hydro_buildout_at`, `test/test_build_trajectories_capacity.py::test_build_trajectories_klien_ror_at`, `scratchpad/evidence/p3_T1_network_ror.txt` |
| Reconcile with brownfield #126 and Grenzkraftwerke #92 | **done with two open fleet findings**. Calibrated fleet with six curated lists, treaty shares, register small hydro, residual plants; 18 tests. Open: Oberaudorf-Ebbs still double (P2-07, 30 MW), register class double counts 59–90 MW (P2-08). | `scripts/pypsa-at/overwrite_powerplants.py`, `data/pypsa-at/grenzkraftwerke_AT.csv`, `test/test_overwrite_powerplants.py` |
| **Close out** — set `2030: 47`, remove the placeholder comment | **done in config, not in a solve**. `config/config.at.yaml:293-299` has 47 with a comment about dry years. The reference run predates it (43.5). | `config/config.at.yaml:285-299` |
| Re-run and confirm feasibility; document a residual gap with its cause | **open**. No solve with 47 exists; with P6-01 unfixed the floor cannot bind, so a "feasible" solve would prove nothing. | P6-01, section 03 of the plan |
| Acceptance: 2030 solves feasibly, floor non-binding or binding at a plausible shadow price | **open** (same reason). The review's re-solve with 47 and the P6-01 broadcast gives mu 1.5e-5, i.e. meaningless. | review `06-solve-constraints.md` P6-01 |
| Acceptance: calibration-year AT hydro reproduces reference statistics within a documented tolerance | **partly done**: numbers documented (ror +12 % vs E-Control 2013 generation, −12 % in hours; storage +3.0 TWh open item), no tolerance stated, and P3-24 says the storage comparison figures are wrong (E-Control's own series gives 3.58, not 4.5 TWh PHS natural inflow). | docs §"Result against E-Control" |
| Acceptance: installed AT hydro capacity per carrier and horizon traceable to a cited source | **done with one caveat**: every curated row carries a note and source; the 389 MW of KLIEN residual plants cite only the study (Q-P2-17). | `data/pypsa-at/*.csv`, `resources/.../hydro_residual_plants_adm.csv` |

### 1b. Review findings and questions: in scope for #312 vs follow-up

Classification from `finding-disposition.md` and the plan sections; all findings are "still
present" at 3f247206. Every question is blocking since 2026-09-17 (AT-team instruction); the
recommendation column is the reviewer's.

**In scope — must be resolved before #312 closes** (they decide whether the 47 TWh floor is a
modelling result):

| ID | Class / sev. | Plan § | What | Blocking question → reviewer's recommendation |
|---|---|---|---|---|
| P3-01 | BALANCE / critical | 04 + 05 | National KLIEN corridor + free placement + inherited yield: 472 / 1,415 / 1,621 MW in AT130 at 6,188 h | Q-P3-04 → regional corridor, ror share = existing ror/(ror+reservoir) per region (Q-P3-03 folded in); Q-P3-09 → (a) regional bound + KLIEN marginal hours for the new vintage |
| P3-16 | BOUND / medium | 05 | New ror vintage keeps `p_nom` = fleet: `installed_capacity` 14,257 vs 7,600 MW | — (same restructure as P3-01) |
| P3-20 | BOUND / low | 05 | `threshold_capacity: 2` deletes 1.95 MW / 9.0 GWh of existing AT ror in 2030 | Q-P3-13 → keep 2; the restructure removes the exposure |
| P3-30 | TEST / low | 05 | `test_hydro_capacity_never_decreases` measures `p_nom`, blind to P3-20 | — |
| P3-14 | TIME / medium | 06 | Global runoff quantile zeroes 3,234 h of AT130 and saturates its profile (what makes AT130 the "best" region) | Q-P3-05 → `lower_threshold_quantile=None`; Danube upstream profile later |
| P3-04 | TIME / high | 06 | Year factors are generation ratios (fleet growth; reservoir includes PHS generation): −0.4 to −0.8 TWh ror, −0.7 TWh reservoir in 2013 | Q-P3-02 → full-load-hour factors, non-PHS storage class |
| P3-11 | CALIBRATION / high | 06 | Constant 2025 pumped-water share instead of Erz col. 10: PHS natural inflow 4.45 → 3.58 TWh | Q-P3-01 → per-year series |
| P3-29 | TEST / low | 06 | Tests lock in P3-04/P3-11 | — |
| P3-24, P3-28 | DOC / low | 06 | Docs contradict E-Control (PHS share, storage figures, Danube hours); weather-year table | — (regenerate after 06) |
| P6-01 | CONSTRAINT / critical | 03 | Production floors broadcast by generator count (hydro LHS = 92 × Σp); the 47 TWh floor has never acted | Q-P6-12 (wind/solar feasibility, not hydro) → keep 17, `ambition: high` if medium infeasible |
| P6-10 | CONSTRAINT / low | 04 | Trajectory GCs carry constant 0 and no dual; the binding AT ror corridor reads "0 MW, mu 0" | Q-P6-16 → yes, report the shadow prices |
| P3-13 | UNIT / medium | 04 | PEMMDB turbine MW_el compared with discharger `p_nom` at bus0; AT PHS headroom 2,239 → 1,096 MW_el | Q-P3-17 → yes, bound the electric port |
| P3-03 | UNIT / high | 05 | Reservoir dischargers sized water-side: 2,793 instead of 3,103 MW_el, binds in 5 AT regions | Q-P3-11 → electric (store × 1/η as well) |
| P3-15 | SPATIAL / medium | 05 | No-Duration plants at partially covered buses get no storage: AT341 116.5 vs ≈ 850 GWh, 121 GWh curtailed | Q-P3-10 → none needed (national 3.2 TWh conserved) |
| P3-19 | TIME / low | 05 | `_redistribute_peaks` ignores snapshot weightings: 13.86 GWh AT ror lost at 365H | — |
| P2-07 | BALANCE / medium | 08 | Oberaudorf-Ebbs 60 MW on AT335 and DE2 in full | Q-IMPL-06 → 0.5 |
| P2-08 | BALANCE / medium | 08 | Register small-hydro class double counts 59 (up to 90) MW | Q-P2-18 → drop ppm hydro ≤ 10 MW of all technologies |
| P2-17 | DOC / low | 08 | Residual-plant figures quoted from the run commit (389 / 32 MW vs 381 / 24 at HEAD) | Q-P2-17 → keep the residual plants |

Why P3-03, P3-15, P3-19, P3-13 are in scope although they are not about the corridor: they all
change the hydro floor's left-hand side or the AT storage fleet the floor is measured on
(P3-03 and P3-15 together remove the AT341 curtailment; P3-13 changes the PHS headroom the
issue's "capacity side" promises), and the plan puts them in the same milestone M2. They are
smaller than the corridor work and could be split into their own PRs inside #312.

**Follow-up issue (not needed to close #312):**

| ID | Class / sev. | Plan § | Why out of scope for #312 |
|---|---|---|---|
| P3-10 | BOUND / high | 04 | Zero corridor for non-PEMMDB horizons (2035/2045) and non-2025 base year; the default horizons are unaffected. Q-P3-16 → interpolate. |
| P3-21 | ROBUSTNESS / low | 04 | Latent: `add_missing_regions` silences a guard; no AT effect in the run. |
| Q-IMPL-05 / P7-09 | PLAUSIBILITY / high | 04 (05) | Non-AT ror vintages per node (XK takes 52 % of the RS pool). Same mechanism as P3-01 but not Austrian; recommendation (a) node share of the PEMMDB headroom. See 2.3 for whether to take it along. |
| P7-01 | PLAUSIBILITY / critical | 07 | Superseded for AT by this branch (Q-0 = merge target); the non-AT mechanism is P3-07. |
| Q-P3-08 | question only | 06 | Kühtai stage in section 30407: a 3.6 GWh dilution; record the decision, no code. |
| Q-P2-16 | question only | 08 | ÖBB 16.7 Hz plants as 50 Hz capacity: a modelling decision (recommendation keep); no code. |
| Q-P2-18, Q-P2-17 | questions | 08 | Listed above with P2-08 / P2-17 as the decision that gates them; the code work is in scope. |

None of the 21 findings and 21 questions in the candidate list was dropped; every one appears in
one of the two tables.

### 1c. Ordered todo list

Dependency order as in the plan: 06 targets → 04 corridors → 05 network → 03 floor re-check →
docs → full re-solve. Items marked **[re-solve 2025]** change the brownfield fleet or the vintage
naming, so the milestone run must start from a fresh 2025 solve (the M0 brownfield files are
incompatible).

| # | Item | Closes | Files | Test that proves it | Expected number (plan) | Decision I need from you |
|---|---|---|---|---|---|---|
| 1 | E-Control per-year pumped-water series (Erz col. 10) replaces `PUMPED_WATER_SHARE`; drop the `Bil` read | P3-11, P3-29 (half) | `scripts/pypsa-at/build_hydro_inflow_targets.py:85-93, 116, 823-826`; `test/test_build_hydro_inflow_targets.py:355-442` | fixture with the real Erz layout; `phs_natural = psw − col10`; red on HEAD | 2013 PHS target 4.453 → 3.579 TWh; mean 3.547 → 3.146; factor 1.2555 → 1.1376 | Q-P3-01 (rec.: per-year series) |
| 2 | Year factors on full-load hours (Engpassleistung from `BeStGes-JR_KWEPL.xlsx`, new rule input); reservoir class without PHS | P3-04, P3-29 (rest) | same script (`:822, :884-886`), `rules/pypsa-at/build.smk` (input), tests | factor test on a synthetic Leistung sheet; red on HEAD | ror 34.14 → 33.34–33.75 TWh; reservoir 10.05 → 9.34 TWh; AT natural inflow 48.64 → ≈ 46.2–46.6 TWh | Q-P3-02 (rec.: FLH factors). Mid-year or year-end capacity (1.0613 vs 1.0485) |
| 3 | `lower_threshold_quantile=None` (or per region) in the profile build; new `test_build_inflow_profile.py` | P3-14 | `scripts/pypsa-at/build_inflow_profile.py:60-65` | per-region sum = 1, no zero hour for continuous runoff | AT130 zero snapshots 3 → 0, saturated 12 → fewer; energy unchanged | Q-P3-05 (rec.: None now) |
| 4 | Regional KLIEN corridor: catchment→region map exported by `build_hydro_inflow_targets_at`, one row per AT region and year, national sum logged | P3-01 (build side) | `build_klien_hydro_trajectory_at.py`, `build_hydro_inflow_targets.py` (new CSV output), `rules/pypsa-at/build.smk:226-279`, `build_capacity_trajectories.py:293-360` | regional rows sum to the national value; zero-ΔC region keeps its capacity; AT ror rows per region | 35 AT rows/year; national 7,545 / 8,376 / 8,551 MW with the fleet ror share (7,600 / 8,542 / 8,749 today; see 2.3 for the share choice) | Q-P3-04 (rec.: regional), ror share (see 2.3) |
| 5 | Corridor rows for dischargers at the electric port (divide by η); GCs with `constant` and duals | P3-13, P6-10 | `build_capacity_trajectories.py:380-382`, `mods/constants.py:142-148`, `mods/constraints/trajectories.py:265-283`, `test/test_mods/constraints/test_trajectories.py` | GC constant = limit, mu finite; PHS row = PEMMDB/0.866 | AT PHS discharger 2040 bus0 9,852 MW; AT ror rows mu < 0 where binding | Q-P3-17, Q-P6-16 (both rec.: yes) |
| 6 | **[re-solve 2025]** Restructure the ror block: `{bus} ror` fixed at `p_nom`, extendable vintage `{bus} ror-{year}` with `p_nom = 0`, `p_nom_max` = regional headroom, yield factor on `p_max_pu` | P3-01 (network side), P3-16, P3-20, P3-30 | `mods/network/hydro.py:301-307, 503-509`, `rules/pypsa-at/build_sector.smk` (regional corridor input), `test/test_mods/network/test_hydro.py:26-43` + new | vintage `p_nom == 0`, `p_nom_max == headroom`, `p_max_pu ≤` existing; every base-year ror present in each `_brownfield.nc`; `optimal_capacity` never decreases | AT130 additions 472 → ≤ 5 MW (2030); AT ror available energy −1.2 / −3.5 / −4.1 TWh; `installed_capacity(ror, AT)` 14,257 → 7,600 MW; AT111/112/113/125 1.95 MW kept | Q-P3-09 (rec.: (a) marginal hours), Q-P3-13 (rec.: keep 2) |
| 7 | **[re-solve 2025]** Reservoir dischargers at `p_nom / η`; plant-level Duration fill; weighted peak redistribution | P3-03, P3-15, P3-19 | `mods/network/hydro.py:262-275, 205-244, 341-443` | discharger `p_nom × η == ppm Capacity`; two-plant bus energy = Σ p·D; weighted frame conserves energy to 1e-9 | AT reservoir peak 2,793 → 3,103 MW_el; AT341 store 116.5 → ≈ 850 GWh, curtailment 121 → < 5 GWh; loss 13.86 → 0 GWh | Q-P3-11 (rec.: electric, store × 1/η), Q-P3-10 (rec.: none) |
| 8 | **[re-solve 2025]** Fleet: Oberaudorf-Ebbs treaty rows; register de-dup (> 10 MW entries, ppm hydro ≤ 10 MW of all technologies, `register_id` column) | P2-07, P2-08, P2-17 | `data/pypsa-at/grenzkraftwerke_AT.csv`, `data/pypsa-at/missing_hydro_plants_AT.csv`, `overwrite_powerplants.py:434-489, 586-677, 722-729`, `test/test_overwrite_powerplants.py` | AT/DE same-name pairs all in the treaty list; no register entry > 10 MW survives; clash check on register ids | AT335 −30 MW; AT hydro −59 (to −90) MW; scale factor 0.875 → ≈ 0.9; residual 80602 grows back | Q-IMPL-06 (rec.: 0.5), Q-P2-18 (rec.: drop all ≤ 10 MW), Q-P2-17 (rec.: keep residuals) |
| 9 | Fix the floor dimension (`inflow_turbine_weights` index name `name`, term-count assertion); fix `test_production_targets` | P6-01, P6-16 | `mods/utils.py:374`, `mods/constraints/production.py:31-90`, `test/test_mods/constraints/test_constraints.py:31-48` | 2 generators × 2 snapshots → 4 terms, not 8; production test counts ≥ 1 checked limit | wind floor binds (mu ≈ 15 €/MWh, AT onwind 15.57 → 17.0 TWh); hydro floor then real | Q-P6-12 (wind 17 TWh vs KLIEN 2030 caps; rec.: keep 17, `high` if needed) |
| 10 | Docs: corridor section (regional), yield of additions, P3-24 corrections, regenerate the weather-year table and residual figures from the M2 run; CHANGELOG entry | P3-24, P3-28, P2-17 | `docs-at/explanations/hydro-capacity-trajectories.md` §191-247, 346-349, 430-444, 497-512, 553-566; `CHANGELOG.AT.md` | `mkdocs build --strict` | 2013 row ≈ 46.2–46.6 TWh, "needs 0.4–0.8 TWh of additions" | — |
| 11 | Full re-solve from 2025 (fresh `run.prefix`), then `p3_T1_network_additions.py`, `p3_T2_ror_expansion.py`, `p6_T2_floors.py`, `pytest --result-path`; before that the cheap 2030 re-solve `p6_T2_solve_cf.py 2030 fix47` for the floor | closes #312 acceptance | — | AT-marked tests green; additions in several buses, AT130 ≤ 14 MW in 2040; `production_limit_lower-hydro-AT` feasible with mu > 0 or documented slack | see 1d | whether the 3H confirmation (M6) is needed before closing |

Items 1–3 and 9 need no re-solve of the brownfield chain (targets and constraints are
horizon-independent), but they only show in a solve.

### 1d. Feasibility risk of the 47 TWh floor after the corrections

Quoting the plan (section 06 §5, section 03 §5, review 06 H1): the corrected 2013 natural inflow
of the 2025 fleet is ≈ 46.2–46.6 TWh (section 06: 48.64 − 2.0 to 2.4 TWh; the P6 analytic bound
says 48.515 TWh without the AT130 phantom, minus 1.97–2.38 TWh = 46.1–46.5 TWh), i.e. below 47.
With the regional corridor the 2030 headroom of ≈ 473 MW at KLIEN's marginal hours (≈ 3,686 h)
adds at most 1.74 TWh, so the floor "binds via ror additions at marginal hours" and is feasible
in 2013 by 0.4–0.8 TWh of additions (section 06 P3-28 expectation). Two things the plan flags:
the floor was never active (P6-01), so this is the first solve in which it can bind at all, and
the alternative reading of the EAG basis (E-Control monitoring, 44 TWh) remains the documented
fallback. My prototype's regional headroom (415 MW at the fleet ror share, 1.74 TWh at
marginal hours, see 2.3) is inside the plan's bound; with the catchment-technology share it
would be 300 MW / ≈ 1.2 TWh, which still covers a 0.8 TWh gap but with less margin. The plan
asks to verify with `p6_T2_solve_cf.py 2030 fix47` before releasing M2; I recommend the same.

---

## 2. Regionalised corridor

### 2.1 Reproduction on the current run

All five scripts ran unchanged (paths already point at `hydro-capacities-update/AT_KN2040`).

- **Corridor binds in every horizon** (`p3_T1_network_ror.txt`): AT ror `p_nom_opt` 7,600.4 /
  8,542.5 / 8,748.8 MW against 7,600.3 / 8,542.4 / 8,748.7 MW, slack −0.1 MW (the tolerance).
  The GC row reads constant 0.0, mu 0.0 (P6-10).
- **Additions per bus vs KLIEN ΔC** (`p3_T1_network_additions.txt`, medium/mocc, ΔC located by
  the catchment representative point as the review did):

| bus | add 2030 | KLIEN ΔC 2030 | add 2040 | KLIEN ΔC 2040 | add 2050 | FLH 2013 | KLIEN FLH (RAV) | existing 2025 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| AT130 | 472.1 | 4.6 | 1,414.8 | 13.9 | 1,621.2 | 6,188 | 6,062 | 181.8 |
| AT126 | 0.2 | 15.4 | 0.1 | 46.2 | 0.0 | 6,341 | 5,908 | 621.2 |
| AT121 | 0.1 | 5.0 | 0.1 | 15.0 | 0.0 | 6,161 | 5,892 | 583.2 |
| AT335 | 0.0 | 165.8 | 0.0 | 497.3 | 0.0 | 4,067 | 2,641 | 241.2 |
| AT334 | 0.0 | 100.7 | 0.0 | 302.0 | 0.0 | 4,615 | 2,054 | 302.6 |
| AT322 | 0.0 | 82.0 | 0.0 | 245.9 | 0.0 | 3,439 | 3,465 | 468.6 |
| AT341 | 0.0 | 52.0 | 0.0 | 156.0 | 0.0 | 4,035 | 3,683 | 209.9 |
| AT313 | 0.0 | 39.5 | 0.0 | 118.5 | 0.0 | 6,171 | 5,793 | 688.9 |
| AT332 | 0.0 | 37.4 | 0.0 | 112.2 | 0.0 | 3,966 | 5,012 | 197.0 |
| all other AT buses | ≤ 0 | … | ≤ 0 | … | ≤ 0 | | | |
| **sum** | **471** | **704** | **1,413** | **2,113** | **1,619** | | | 7,129 |

  Buses with additions > 1 MW in 2040: 1. Capacity-weighted FLH of the additions 6,188 h against
  the AT ror mean of 4,789 h. AT111/112/113/125 show small negative additions (P3-20).
- **AT130 dispatch** (`p3_T1_at130_dispatch.txt`): 654 / 1,597 / 1,803 MW, generation 4.05 /
  9.88 / 11.16 TWh (available = generation), 6,188 h, 10.9 / 23.0 / 25.3 % of AT ror. The
  hydro floor GC in the 2030 network is 43.5 TWh with mu 1.05e-8.
- **Vintages** (`p3_T2_ror_expansion.txt`): post-2025 vintages 473.0 / 1,415.1 / 1,621.4 MW,
  all in AT130, carrying 2,926 / 8,757 / 10,033 GWh/a; AT ror available energy 37.047 /
  42.878 / 44.154 TWh. The 2030 vintage carries `p_nom` 7,129 MW next to `p_nom_opt` 473 MW
  (P3-16, confirmed in the network: build_year 2030, extendable, p_nom 7,129.3).
- **E- vs C-factor** (`p3_T1_klien_corridor.txt` and the prototype): medium/mocc 2040 C-factor
  1.1982 against E-factor 1.1647. ΔE/ΔC 2040 = 7,254.7 GWh / 2,113.0 MW = 3,433 h (RAV); with
  the 2013 ror factor 1.0738 that is 3,687 h. It is nearly identical across ambitions (3,424–3,434 h
  in 2040) and a little lower in 2070 (3,299–3,368 h). The model's headroom (factor − 1) × ror
  fleet is 471 / 1,413 / 1,619 MW against a KLIEN ΔC of 704 / 2,113 / 2,421 MW (ratio 0.669 =
  ror fleet / KLIEN C_current).
- **P3-14 for AT130** (`p3_T1_network_additions.txt`): the 2025 AT130 profile is 1.0 in 12 of 24
  snapshots and 0.0 in three (17 July, 1 and 16 October); AT126 on the same river has four
  saturated and no zero snapshot. The global quantile, applied at NUTS3, zeroes local runoff in
  Vienna for 3,234 hours; the proportional redistribution then pushes the region's energy into
  the saturated snapshots, which is what makes a Vienna MW worth 6,188 h to the optimiser.

### 2.2 Is the KLIEN study suited to provide capacity corridors per NUTS3 region?

Data: `catchments_hydro.csv` (249 rows, all with a polygon carrying `E_current`; 289 polygons in
the GeoJSON, 40 without `E_current`). Columns per catchment: `C_current`, `E_current`,
`C/E_{2040,2070}_{low,medium,high}_{mocc,stcc}`, `LCOE_*`, `MV_*`; the GeoJSON adds `ABSCHNITT`
(river stretch name) and `BUNDESLAND`. There is no readme in `data/klien_potentials/`;
`data/versions.csv` gives the units (C in MW_el, E in GWh/a) and the reference period is stated
in the docs page (1991–2020 discharge, data status November 2024). "Current" is the study's
inventory year, which the branch anchors at 2025 (`KLIEN_BASE_YEAR`). There is **no technology
attribute**: C and E are the sum of Lauf- und Speicherkraftwerke on the stretch, pumped storage
excluded except where the study counts a storage group with pumps as a Speicherkraftwerk
(`_phs_counted_sections`).

**How many catchments grow, and where the growth sits** (prototype, ΔC = study pathway minus the
study's own `C_current`, i.e. unaffected by the two catchment corrections):

| pathway | catchments with ΔC > 0 | ΔC (MW) | ΔE (GWh/a) | ΔE/ΔC (h, RAV) |
|---|---:|---:|---:|---:|
| 2040 low | 223 | 1,054 | 3,617 | 3,434 |
| 2040 medium | 227 | 2,113 | 7,255 | 3,433 |
| 2040 high | 231 | 2,892 | 9,903 | 3,424 |
| 2070 low | 230 | 2,634 | 9,043 | 3,433 |
| 2070 medium (mocc / stcc) | 231 | 3,038 / 3,270 | 10,231 / 10,786 | 3,368 / 3,299 |
| 2070 high (mocc / stcc) | 231 | 3,038 / 3,270 | 10,231 / 10,786 | 3,368 / 3,299 |

No catchment shrinks. The climate scenario changes nothing in 2040 and only the 2070 column;
"high" and "medium" coincide in 2070.

Where the 2,113 MW of medium/mocc ΔC 2040 lie (membership from the calibrated fleet as
`build_hydro_inflow_targets` builds it, overrides included):

| class | catchments | ΔC 2040 (MW) | ΔC 2070 (MW) |
|---|---:|---:|---:|
| polygon fully inside one NUTS3 region (≥ 99 % of area) | 131 | 1,207 | 1,771 |
| polygon straddles regions | 96 | 906 | 1,266 |
| all member plants in one region (fleet key) | 176 | 1,698 | 2,473 |
| member plants in several regions | 51 | 415 | 565 |
| no plant of the calibrated fleet in the catchment | **0** | 0 | 0 |

The fleet key resolves most of the straddling: of the 906 MW in straddling polygons, 507 MW sit
in catchments whose plants are all in one region. The 415 MW that remain split by plant
capacity are dominated by the Danube (60200 Danube Ybbs–Krems 60 MW: AT121 0.53 / AT313 0.47;
60100 Danube upstream 45 MW: AT313 0.53 / AT312 0.35 / AT311 0.12), the Ill (10105, 10113: AT341
≈ 0.8 / AT342 ≈ 0.2), the Drau (80700: AT211 0.75 / AT213 0.25) and the Mur (71000, 71002).
Every catchment with growth contains at least one plant of the calibrated fleet (the residual
plants guarantee this by construction), so the membership key covers 100 % of ΔC and no
representative-point fallback is needed for growth.

**Run-of-river or total hydro?** ΔC is total river hydro (ror + reservoir, PHS where counted).
Three ways to take the ror share, with the national result:

| ror share definition | national ror share of ΔC 2040 | regional headroom 2030 / 2040 / 2050 (MW) |
|---|---:|---|
| region's existing ror/(ror+reservoir) (reviewer default) | 0.697 (fleet) → 0.59 ΔC-weighted | 416 / 1,247 / 1,421 |
| technology of the existing plants in the growing catchments, ΔC-weighted | 0.512 | ≈ 300 / 900 / 1,030 (from the per-region column) |
| all ΔC as ror (share 1) | 1.0 | 704 / 2,113 / 2,421 |
| today's national corridor (factor × ror fleet) | 0.669 implicit | 471 / 1,413 / 1,619 |

The reviewer's default gives 7,545 / 8,376 / 8,551 MW nationally, i.e. 1 to 2 % below today's
7,600 / 8,542 / 8,749 MW. The gap comes from the alpine storage regions: AT335, AT334, AT322,
AT341 and AT212 hold 63 % of ΔC 2040 but only 0.21–0.44 of their fleet is ror, so a per-region
share cuts their ror headroom hard, while the national factor spread the same ΔC over the whole
ror fleet. The catchment-technology share is lower still (AT335 0.13, AT334 0.23), because the
growing alpine catchments are dominated by reservoir plants (Kaunertal, Zillertal, Kaprun). Which
share is "right" is a modelling decision: KLIEN does not say whether the alpine ΔC is a new
run-of-river stage or an extension of a storage group. There is no KLIEN attribute to settle it.

**Marginal energy per new MW vs the region's existing hours** (medium/mocc 2040, 2013 factor
applied to the marginal value):

| region | existing ror MW | ΔC 2040 | ror share | headroom 2040 | FLH existing 2013 | marginal FLH (RAV) | marginal FLH 2013 | yield factor |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| AT335 | 241 | 500 | 0.42 | 210 | 4,069 | 1,920 | 2,062 | 0.51 |
| AT334 | 303 | 303 | 0.44 | 132 | 4,616 | 1,959 | 2,104 | 0.46 |
| AT332 | 197 | 109 | 0.97 | 106 | 3,966 | 4,924 | 5,287 | 1 (capped) |
| AT322 | 469 | 246 | 0.39 | 97 | 3,440 | 3,515 | 3,775 | 1 (capped) |
| AT313 | 689 | 65 | 0.95 | 62 | 6,174 | 5,465 | 5,868 | 0.95 |
| AT121 | 583 | 57 | 1.00 | 57 | 6,163 | 5,690 | 6,110 | 0.99 |
| AT126 | 621 | 46 | 1.00 | 46 | 6,344 | 5,906 | 6,342 | 1 (capped) |
| AT130 | 182 | 14 | 0.97 | 13.5 | 6,191 | 6,062 | 6,509 | 1 (capped) |
| AT341 | 210 | 141 | 0.21 | 29 | 4,038 | 3,775 | 4,054 | 1 (capped) |
| AT212 | 170 | 88 | 0.29 | 25 | 3,567 | 3,497 | 3,755 | 1 (capped) |

Two things stand out. First, KLIEN's marginal hours are *above* the region's existing hours in
26 of 35 regions, so the plan's factor `min(1, marginal/existing)` is 1 almost everywhere; it
bites only in AT334 (0.46), AT335 (0.51), AT323 (0.83), AT225 (0.90), AT313 and AT121 (0.95,
0.99). The reason is the fleet: the existing regional hours are pulled down by small plants and
residual plants, while KLIEN's ΔE/ΔC describes the best remaining stretches. Second, on the
Danube the marginal hours (5,700–6,100 h RAV) are as high as the fleet's, so the "Vienna
problem" is not a yield problem but a *quantity* problem: KLIEN allows 13.5 MW there, not 1,400.
The regional bound alone fixes P3-01; the yield factor matters for AT334/AT335, where without it
each new MW would deliver twice KLIEN's energy. Using the marginal hours directly (not capped at
one) is not advisable: in AT332 or AT221 it would give a new MW more hours than the existing
Danube-free fleet, which KLIEN's ΔE (a catchment mean) does not justify at NUTS3 granularity.

**Year anchors.** KLIEN gives "current" (2025), 2040 and 2070. `klien_buildout_factors` puts
2030 at one third of the 2025→2040 step and 2050 at 2040 plus one third of the 2040→2070 step,
nationally. Applying the same weights per region is defensible because they are linear in ΔC:
the regional rows sum to the national row exactly for every year (checked in the prototype:
704 / 2,113 / 2,421 MW of ΔC). What the linear split hides is that KLIEN's LCOE and market-value
columns would allow a cost-ordered phasing (cheap stretches first); that is a refinement beyond
#312.

**Vienna.** KLIEN section 60400 (Danube below Vienna, `ABSCHNITT` "Staatsgrenze nach Ungarn",
the Freudenau stretch; members Freudenau 172 MW, Debant 5 MW reservoir, eight small plants) has
`C_current` 177.6 MW, `E_current` 1,077 GWh/a (6,062 h) and ΔC 2040 of 6.9 / 13.9 / 18.7 MW
(low / medium / high), ΔC 2070 18.7 MW; ΔE 2040 84 GWh/a. Section 60300 (Danube Ybbs–Wien,
"Pegel Wien-Reichsbrücke"; Altenwörth 328 MW, Greifenstein 293 MW, AT126) has 621 MW, 3,669
GWh/a and ΔC 2040 of 23 / 46 / 62 MW, ΔC 2070 62 MW (5,909 h marginal). AT127 has 5.9 MW of
small plants and ΔC 1.7 MW. So KLIEN sees the Vienna Danube as developed: 14 MW (AT130) and
46 MW (AT126) by 2040 under medium ambition, consistent with revitalisation-scale gains at
Freudenau and Greifenstein. What E-Control or Verbund say about the revitalisation potential of
the two plants is **not in the data** at hand (the fleet files only carry the nameplates; no
operator project list is registered).

**Conclusion: yes, with three caveats.** KLIEN can provide per-NUTS3 corridors: the pathway is per
catchment, every growing catchment holds fleet plants so the existing plant→catchment membership
maps 100 % of ΔC to regions, and 80 % of ΔC sits in catchments whose plants are all in one
region. The caveats: (1) ΔC is technology-blind, so the ror share per region is our assumption,
and it decides 300 vs 700 MW of national ror headroom in 2030; (2) the marginal hours are a
catchment mean, useful as a cap for AT334/AT335 but not as a bonus elsewhere; (3) the 2030/2050
points are our interpolation of a 2040/2070 study, exactly as today.

### 2.3 Design proposal (architecture; no repo code yet)

Builds on plan sections 04 and 05; deviations are marked.

**Build side.**

1. `build_hydro_inflow_targets_at` gains a second output `hydro_catchment_regions_{clusters}.csv`
   with columns `section, bus, weight` = the membership rows of the AT plants of eligible
   carriers (ror, hydro, PHS where counted), aggregated to capacity weights per section and bus
   (weights sum to one per section). It is the by-product of `assign_plants_to_sections` +
   `allocate_section_energy` that already run; no new logic, one `groupby`. Empty with header when
   the feature is disabled. Rule change in `rules/pypsa-at/build.smk:226-252` (new `output`),
   and `build_klien_hydro_trajectory_at` (`:255-279`) gets it as input.
   *Deviation from section 04:* the plan says "membership or representative point"; I would use
   the membership only and raise if a catchment with ΔC > 0 has no member (today: none). The
   representative point is the wrong key for the Danube (it lands 60200's 60 MW in AT121 alone).
2. `build_klien_hydro_trajectory_at.py`: new function `regional_ror_corridor(klien, catchment_regions,
   fleet, planning_horizons, ambition, climate_scenario, ror_share)` returning one row per
   `(year, region)` with columns `existing_ror_mw, delta_c_mw, ror_share, headroom_mw, value,
   marginal_flh` (`value = existing + headroom`; `marginal_flh` = ΔE/ΔC of the region's catchments,
   RAV, weighted by ΔC). `klien_buildout_factors` stays for the interpolation weights and the
   logged national cross-check (`Σ value` vs `brownfield × factor`, logged with the difference;
   equal only if `ror_share = 1` for every region, which is a documented non-identity, not a bug).
   Output `klien_ror_trajectory_{clusters}.csv` changes from `year`-indexed to `(year, region)`
   rows; `COLUMNS` grow accordingly.
3. `build_capacity_trajectories.apply_klien_hydro_buildout_at` writes one `(year, region, "ror",
   "Generator-p_nom", "max")` row per AT region and drops the national `AT` row (otherwise both
   would apply; harmless but confusing in the GC list). The `min > max` guard stays per row.
4. `mods/constraints/trajectories.py`: **verified, no change needed.** `_get_region_mapping` maps
   a trajectory region to every model region that starts with it, so `AT130` → `[AT130]`;
   `calculate_limit` groups by the trajectory row index, so each regional row becomes its own
   constraint with limit = value − Σ non-extendable `p_nom` (= headroom) and the model expression
   sums only that region's ror generators. The `startswith` mapping means a national `AT` row
   would still match every AT region; hence step 3 removes it. Note that with the fixed `{bus} ror`
   plus a vintage with `p_nom_max`, the trajectory row is belt-and-braces; it is still needed
   because it bounds the *cumulative* additions across vintages (2030 + 2040 ≤ headroom 2040),
   which `p_nom_max` of a single vintage cannot express.

**Network side** (`mods/network/hydro.py:301-307`, `:503-509`).

1. `{bus} ror` stays non-extendable at `p_nom` with `lifetime = inf` (upstream semantics). This
   removes P3-16 (`installed_capacity` correct), P3-20 (`add_brownfield` drops inf-lifetime assets
   from `n_p` and re-adds them at full `p_nom`, so the 2 MW threshold never sees them) and makes
   P3-30's `optimal_capacity` test meaningful.
2. In non-base years add `{bus} ror-{planning_horizon}` per AT bus with `p_nom = 0`, `p_nom_min = 0`,
   `p_nom_extendable = True`, `lifetime = 100`, `capital_cost` / `onight_cost` from the `ror` cost
   row, `p_nom_max = headroom(region, year)` from the regional corridor file (new input of
   `prepare_sector_network_at` in `rules/pypsa-at/build_sector.smk`, plus `code_files`), and
   `p_max_pu = p_max_pu_existing × yield_factor(region)` with
   `yield_factor = min(1, marginal_flh × year_factor / existing_flh)`. Because the vintage is a
   separate generator, `_patch_component_inflows` (`:503-509`) computes the existing profile with
   the existing `p_nom` as today and then copies it scaled to the vintage; no division by zero.
   In the base year no vintage is added (headroom 0). `add_brownfield` carries the vintage by
   `p_nom_opt` into the next horizon as a fixed generator; the next horizon's vintage gets the
   full headroom of its year as `p_nom_max` and the trajectory row bounds the cumulative sum.
   *Deviation from section 05:* the plan sizes `p_nom_max` at "the region's corridor headroom for
   that year"; I would make it the headroom *minus the already built vintages* at prepare time
   only if that is cheap, otherwise rely on the trajectory row (same result in the solve).
3. `threshold_capacity: 2` (Q-P3-13): keep; only new vintages below 2 MW are dropped, which is
   the intended meaning. Small regions (AT111–AT125, headroom < 2 MW) will simply never build.
4. Statistics: `installed_capacity(ror)` becomes the fixed fleet, `optimal_capacity` fleet plus
   vintages, `expanded_capacity` the vintages (P3-16 closed). `inflow_turbine_weights` is not
   affected (ror sits on an AC bus, weight 1); the EAG floor expression selects by carrier `ror`
   and bus prefix, so the vintages enter it automatically with their reduced `p_max_pu`.
5. Non-AT ror vintages (Q-IMPL-05 / P7-09): the same restructure applies to every country once
   `{bus} ror` is fixed and the vintage is separate; the only AT-specific part is the regional
   headroom. I recommend doing the restructure for all countries in this PR (one code path,
   otherwise the non-AT vintages keep P3-16/P3-20) and setting the non-AT vintage `p_nom_max` to
   the node's share of the national PEMMDB headroom by existing ror capacity (option a), which is
   five lines next to the AT branch. If you prefer to keep the PR Austrian, leave non-AT
   `p_nom_max = inf` and file the follow-up; the restructure itself still removes P3-16/P3-20
   for them.

**Config** (`config/config.at.yaml`, `mods.update_hydro_capacities_AT`): two new keys under the
existing block, both read by the Python side only (DAG unchanged, empty-with-header outputs when
disabled):

```yaml
  update_hydro_capacities_AT:
    enable: true
    fix_store_volumes: true
    klien_residual_plants: true
    ror_corridor:
      regional: true          # one corridor row per NUTS3 region (false: national factor as before)
      ror_share: fleet        # fleet | catchment | 1.0 — share of the KLIEN ΔC that may be run-of-river
      marginal_yield: true    # new vintages get min(1, KLIEN ΔE/ΔC / existing FLH) on p_max_pu
```

`mods.trajectories` is unchanged. `mods.klien_potential_limits.ambition / climate_scenario` keep
selecting the pathway. No validation model exists for the AT mods keys (project-wide decision
recorded in the memory file), so no `generate-config` run.

**Tests.**

- `test/test_build_klien_hydro_trajectory_at.py`: regional rows sum to the national ΔC per year;
  a region with zero ΔC gets `value == existing`; `ror_share` options; a catchment with ΔC and no
  membership raises; interpolation weights per region equal the national ones; wocc fallback.
- `test/test_build_hydro_inflow_targets.py`: the catchment-region map sums to one per section and
  covers every section with members.
- `test/test_build_trajectories_capacity.py`: AT ror rows are per region, national row absent,
  `min > max` guard per row.
- `test/test_mods/network/test_hydro.py`: synthetic network — the vintage has `p_nom == 0`,
  `p_nom_max == headroom`, `p_max_pu ≤` the existing profile and equal to it where the factor is
  1; the existing `ror` is non-extendable with `lifetime == inf`; `test_hydro_capacity_never_decreases`
  on `optimal_capacity`; a brownfield-stage test that every base-year ror is present in each
  `_brownfield.nc` at unchanged `p_nom` (`nc` fixture, AT-marked).
- `test/test_mods/constraints/test_trajectories.py`: two regional rows produce two constraints
  whose limits equal the regional headroom.

**Expected effect** (plan sections 04/05, my numbers where they differ): AT130 additions
472 → ≤ 5 MW in 2030 (KLIEN allows 4.5 MW); additions spread over AT335/AT334/AT332/AT322/
AT313/AT121; AT ror available energy 37.05 / 42.88 / 44.15 TWh falls by ≈ 1.2 / 3.5 / 4.1 TWh
(plan) — with the prototype's fleet-share headroom the additions carry at most 1.6–1.74 /
4.8–5.2 / 5.4–5.9 TWh (capped / uncapped marginal hours), so the fall is 1.2–1.3 / 3.5–4.0 /
4.1–4.6 TWh, bracketing the plan;
`installed_capacity(ror, AT)` 14,257 → 7,129 MW in 2030; the 47 TWh hydro floor may bind
(section 1d).

**Prototype table** (medium/mocc, fleet ror share; full 35-region table in
`scratchpad/regional_corridor_table.csv`; headroom energy = headroom × KLIEN marginal FLH ×
1.0738, uncapped. With the yield factor capped at one the sums are 1,596 / 4,789 / 5,427 GWh,
at the existing regional hours 1,866 / 5,598 / 6,369 GWh):

| region | existing ror MW | ΔC 2030 / 2040 / 2050 | ror share | headroom 2030 / 2040 / 2050 (MW) | marginal FLH (RAV) | headroom energy 2030 / 2040 / 2050 (GWh) |
|---|---:|---|---:|---|---:|---|
| AT335 | 241 | 167 / 500 / 582 | 0.42 | 70 / 210 / 244 | 1,920 | 144 / 432 / 503 |
| AT334 | 303 | 101 / 303 / 355 | 0.44 | 44 / 132 / 155 | 1,959 | 93 / 278 / 325 |
| AT332 | 197 | 36 / 109 / 124 | 0.97 | 35 / 106 / 121 | 4,924 | 187 / 560 / 638 |
| AT322 | 469 | 82 / 246 / 285 | 0.39 | 32 / 97 / 112 | 3,515 | 122 / 365 / 423 |
| AT313 | 689 | 22 / 65 / 73 | 0.95 | 21 / 62 / 70 | 5,465 | 122 / 366 / 410 |
| AT121 | 583 | 19 / 57 / 64 | 1.00 | 19 / 57 / 64 | 5,690 | 117 / 350 / 390 |
| AT126 | 621 | 15 / 46 / 52 | 1.00 | 15 / 46 / 52 | 5,906 | 98 / 293 / 327 |
| AT333 | 193 | 17 / 51 / 59 | 0.87 | 15 / 45 / 51 | 4,674 | 75 / 224 / 256 |
| AT211 | 471 | 15 / 44 / 49 | 0.95 | 14 / 42 / 47 | 4,061 | 61 / 182 / 203 |
| AT311 | 300 | 14 / 41 / 45 | 1.00 | 14 / 41 / 45 | 5,509 | 80 / 240 / 268 |
| AT226 | 206 | 15 / 45 / 51 | 0.88 | 13 / 40 / 45 | 4,410 | 63 / 190 / 213 |
| AT222 | 226 | 22 / 65 / 73 | 0.61 | 13 / 39 / 45 | 4,309 | 61 / 182 / 207 |
| AT213 | 352 | 12 / 36 / 40 | 1.00 | 12 / 36 / 40 | 4,562 | 58 / 174 / 195 |
| AT314 | 346 | 11 / 32 / 36 | 1.00 | 11 / 32 / 36 | 4,198 | 48 / 144 / 161 |
| AT312 | 368 | 10 / 31 / 35 | 1.00 | 10 / 31 / 35 | 5,136 | 58 / 173 / 193 |
| AT223 | 185 | 10 / 31 / 35 | 1.00 | 10 / 31 / 35 | 4,876 | 54 / 162 / 181 |
| AT323 | 79 | 15 / 46 / 52 | 0.65 | 10 / 30 / 34 | 4,123 | 44 / 131 / 149 |
| AT341 | 210 | 47 / 141 / 159 | 0.21 | 10 / 29 / 33 | 3,775 | 39 / 118 / 133 |
| AT212 | 170 | 29 / 88 / 100 | 0.29 | 8 / 25 / 29 | 3,497 | 32 / 96 / 108 |
| AT225 | 185 | 9 / 28 / 32 | 0.76 | 7 / 21 / 24 | 2,642 | 20 / 61 / 68 |
| AT315 | 73 | 8 / 23 / 26 | 0.86 | 7 / 20 / 22 | 4,961 | 35 / 104 / 118 |
| AT342 | 51 | 7 / 20 / 23 | 0.73 | 5 / 15 / 16 | 3,989 | 21 / 63 / 70 |
| AT221 | 252 | 5 / 14 / 16 | 1.00 | 5 / 14 / 16 | 4,748 | 25 / 74 / 82 |
| **AT130** | 182 | 4.6 / 13.9 / 15.5 | 0.97 | **4.5 / 13.5 / 15.1** | 6,062 | 29 / 88 / 98 |
| AT122 | 33 | 3 / 9 / 10 | 1.00 | 3 / 9 / 10 | 4,622 | 15 / 45 / 51 |
| AT331, AT224, AT123, AT321, AT124, AT127, AT113, AT112, AT125, AT111 | 145 | 12 / 35 / 39 | 0.58–1.00 | 10 / 30 / 33 | 3,700–4,960 | 40 / 121 / 135 |
| **sum** | **7,129** | **704 / 2,113 / 2,421** | 0.59 (ΔC-weighted) | **416 / 1,247 / 1,421** | 3,433 | **1,737 / 5,212 / 5,906** |

Sanity checks: the ΔC columns sum to KLIEN's national ΔC exactly; existing + headroom is
7,545 / 8,376 / 8,551 MW against today's 7,600 / 8,542 / 8,749 MW; the headroom energy at
KLIEN's own marginal hours would be 1,737 GWh in 2030, which is the ≤ 1.74 TWh the plan uses
for the floor risk.

---

## 3. Decisions taken 2026-09-21 (user)

| Question | Decision |
|---|---|
| Q-P3-04 / Q-P3-03 ror share of KLIEN ΔC | **share 1.0**: every KLIEN megawatt of growth becomes run-of-river headroom in its region (704 / 2,113 / 2,421 MW nationally); reservoir turbines keep the PEMMDB corridor |
| Q-P3-09 yield of a new vintage | `p_max_pu_new = p_max_pu_existing × min(1, FLH_marginal(region) × year factor / FLH_existing(region))` |
| Q-IMPL-05 non-AT ror vintages | restructure for all countries; non-AT vintage `p_nom_max` = node share of the national PEMMDB headroom by existing ror capacity |
| Q-P3-01 / Q-P3-02 year factors | per-year pumped-water series (Erz col. 10) and full-load-hour factors with mid-year capacity from `BeStGes-JR_KWEPL.xlsx` |
| Q-P3-05 runoff threshold | `lower_threshold_quantile=None` |
| Q-P3-11, Q-P3-17, Q-P6-16, Q-P3-13, Q-IMPL-06, Q-P2-18, Q-P2-17 | reviewer defaults accepted |
| PR split | main PR (corridor, ror restructure, year factors, threshold, P6-01) plus three small PRs (network sizing P3-03/15/19; corridor units and duals P3-13/P6-10; fleet P2-07/P2-08), all under #312 |
| Runs | implement against the existing `hydro-capacities-update` resources; afterwards a full run under `run.prefix: hydro-capacities-update-complete` |

---

## 4. Implementation status (2026-09-21, working tree of `feat/scale-austrian-hydro-capacities`, uncommitted)

Main chain of todo list 1c, items 1–6 and 9, implemented; items 7 and 8 (P3-03/P3-15/P3-19 and
P2-07/P2-08) and the corridor-unit/dual items (P3-13, P6-10) are left for the side PRs.

| Item | Change | Tests (green) | Numbers from the build harness on the run resources |
|---|---|---|---|
| 1 + 2 year factors | `build_hydro_inflow_targets.py`: Erz columns 8–11 read, `phs_natural = PS generation − published pumped-water generation`; new `read_econtrol_capacity` (sheet `Leistung` of `BeStGes-JR_KWEPL.xlsx`, new input of the rule and of `retrieve_econtrol_bestandsstatistik`), `mid_year_capacity`, `weather_year_factors(econtrol, year, capacity)` on full-load hours for ror and non-PHS storage, ratio for PHS | `test_build_hydro_inflow_targets.py` 38 (fixtures with the real column layouts; fleet-growth test) | 2013 factors ror 1.051 / hydro 1.057 / PHS 1.138; targets ror 33.41, reservoir 9.27, PHS 3.58 TWh, **46.26 TWh** in total (was 48.64) |
| 3 runoff threshold | `build_inflow_profile.py` refactored into `build_inflow_profile()` with `lower_threshold_quantile=None` | new `test_build_inflow_profile.py` 3 (synthetic cutout) | AT130 zero hours 3,234 → 0 (verified on the run after the rebuild) |
| 4 regional corridor | `build_hydro_inflow_targets_at` writes `hydro_catchment_regions_{clusters}.csv` (plant-capacity weights per section and region; 243 of 249 catchments located); `build_klien_hydro_trajectory_at.py` rewritten: per-catchment interpolation, `locate_in_regions`, `marginal_full_load_hours`, `build_regional_ror_corridor`; one row per (year, region) with `existing_ror_mw, delta_c_mw, value, marginal_flh, yield_factor`; `apply_klien_hydro_buildout_at` drops the national row and writes the regional rows | `test_build_klien_hydro_trajectory_at.py` 17, `test_build_trajectories_capacity.py` unit 3 | national sums 7,129 / 7,834 / 9,242 / 9,551 MW = fleet + 0 / 704 / 2,113 / 2,421 MW (share 1.0); AT130 4.6 / 13.9 / 15.5 MW; five plant-less catchments with 0.1 MW dropped with a warning (tolerance 1 MW) |
| 6 ror restructure | `mods/network/hydro.py`: fleet fixed (`p_nom_extendable=False`, `lifetime=inf`, never renamed or carried); `ror_expansion_headroom` (regional rows → the bus, national rows → node share by existing capacity, XK pooled with RS); `add_ror_vintages` adds `{bus} ror-{year}` with `p_nom=0`, `p_nom_max=headroom`, build year set, costs of the horizon; `_apply_ror_vintage_profiles` copies the fleet profile × yield factor; `prepare_sector_network_at` gets `trajectories` and `klien_ror_trajectory` as inputs; `mods/constraints/trajectories.py` skips rows without an extendable component instead of raising | `test_hydro.py` unit 6 (+2 `nc` tests red on the old run, by design) | yield factor 0.46 AT334, 0.51 AT335, 0.83 AT323, 0.90 AT225, 0.95 AT313, 0.99 AT121, 0.55 AT111 (0.02 MW) |
| 9 floor dimension | `mods/utils.py` weights indexed by `name`; `production.py` raises unless `expr.nterm == 1` | `test_constraints.py` term-count unit test | — |
| docs | corridor section, weather-year section and table, E-Control comparison, EAG table (2013: 46.3 TWh delivered, 0.7 TWh missing, 2.4 TWh of corridor energy at the vintage yields; 4 years without buildout, 4 within the corridor, 18 unreachable), vintage note; the figures still show the old factors (note added; regenerate with the notebook after the run) | `mkdocs build --strict` | — |
| config | `run.prefix: hydro-capacities-update-complete`; no new feature keys (share 1.0 and the yield factor are the implementation, not options) | — | — |
| CHANGELOG | two *Changed* and four *Fixed* entries under *Alpha* | — | — |

Full workflow under `hydro-capacities-update-complete` launched 2026-09-21 10:44 (119 jobs). The first attempt failed in the 2025 solve: with no extendable run-of-river component in the base year the trajectory expression was empty and linopy rejected a constant-only constraint. Fixed in `mods/constraints/trajectories.py` (`build_model_expression` returns `None` when no row has a variable, the caller skips the constraint and aligns the limits to the rows kept; two unit tests) and relaunched at 10:57 (`scratchpad/fullrun.log`, 19 remaining jobs). The prepared 2030 network of the first attempt was checked: fleet fixed with infinite lifetime (68 generators, 51.8 GW), 61 vintages with 20.3 GW of headroom (35 Austrian ones with 704 MW), AT335 vintage at 0.507 of the fleet profile, Vienna profile without zero hours, XK vintage 143 MW against 1,617 MW for RS. Open after the run: the `nc` tests (`pytest --result-path=results/hydro-capacities-update-complete/AT_KN2040`),
the evidence scripts with the new prefix, the floor's dual in 2030, regeneration of the four figures and the
residual-plant numbers in the docs, and the three side PRs.

### Results of the complete run (365H, `results/hydro-capacities-update-complete/AT_KN2040`, solved 2026-09-21)

| Quantity | old run (national corridor, generation-ratio factors) | complete run | plan expectation |
|---|---:|---:|---|
| AT natural inflow targets 2013 (ror / reservoir / PHS) | 34.14 / 10.05 / 4.45 = 48.64 TWh | 33.41 / 9.27 / 3.58 = **46.26 TWh** | 46.2–46.6 TWh |
| 2030 hydro floor `production_limit_lower-hydro-AT` | 47 TWh, mu 1e-8 (inert, P6-01) | **binding**, LHS 47.000 TWh (ror 34.18 + reservoir 9.24 + PHS 3.58), **mu 7.79 €/MWh** | binds, feasible |
| 2030 wind floor | mu 1.6e-8 | mu 14.2 €/MWh, AT onwind 17.0 TWh | binds (P6-01 fixed) |
| AT ror additions 2030 / 2040 / 2050 (cumulative) | 472 / 1,415 / 1,621 MW, all in AT130 | **150 / 1,311 / 1,873 MW** over 17 / 25 / 30 regions; AT130 4.6 / 14.0 / 15.6 MW (= its headroom) | AT130 ≤ 5 MW in 2030 |
| largest 2040 additions | AT130 1,415 MW | AT322 246, AT341 141, AT332 109, AT212 88, AT313 66, AT222 65 MW | alpine regions |
| AT334 / AT335 (yield 0.46 / 0.51) | 0 / 0 | 0 / 0 in 2040; 355 / 31 MW in 2050 | — |
| AT ror available energy 2030 / 2040 / 2050 | 37.05 / 42.88 / 44.15 TWh | 34.18 / 38.89 / 40.41 TWh (−2.9 / −4.0 / −3.7 TWh) | −1.2 / −3.5 / −4.1 TWh vs old (the old fleet energy was 34.13; the new fleet delivers 33.40, hence the larger drop) |
| corridor respected | binding nationally | max (built − regional headroom) 0.1 MW = tolerance, every horizon | — |
| `installed_capacity(ror, AT)` 2030 | 14,257 MW | 7,129 MW fleet + 150 MW vintages (`optimal_capacity` 7,279) | 7,600 → fleet + built |
| AT130 profile (2025) | 3 zero snapshots, 12 saturated, 6,188 h | 0 zero, 3 saturated, 6,054 h | zeros 0 |
| fleet vintages | `{bus} ror-2025`, extendable, `p_nom` kept (P3-16/P3-20) | `{bus} ror`, fixed, lifetime inf, present in every horizon | — |
| run-based tests | — | `test_hydro.py` 19 passed (incl. the two new vintage tests), `test_build_trajectories_capacity.py`, `test_trajectories.py`, `test_constraints.py` passed on the new results; the workflow's `validate_pypsa_at` failed once on `test_hydro_capacity_never_decreases` (a 0.013 MW PHS charger vintage dropped by the 2 MW brownfield threshold, now tolerated up to the threshold) and was relaunched | — |

The trajectory GlobalConstraint rows still read constant 0 / mu 0 (P6-10, side PR). The reservoir
inflow delivered in 2030 is 9.24 of 9.27 TWh (AT341 curtailment, P3-15, side PR).

Workflow status: `validate_pypsa_at` passed on the relaunch (36 AT-marked tests), the four
figures of the docs page were regenerated by `.marimo/review-hydro-slides.py` on the complete
run (notebook adapted to the regional corridor file and the capacity workbook) and re-quantized
into `docs-at/assets/hydro/`; `mkdocs build --strict`, `ruff check` and the non-run unit tests
(128 passed) are green. The evaluation export is the last job of the run.
