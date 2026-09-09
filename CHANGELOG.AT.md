# Changelog

All notable changes to PyPSA-AT are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [Planned]

### Added
- Differentiation of open- and closed-loop PHS, reservoirs with and without inflows; improved Austrian hydro inflow time series
- Carbon cycle model coupling for improved biomass sector accuracy
- Optimised production paths for industry sub-sectors, replacing exogenous energy modal splits
- Updated demand profiles for industry, transport, residential, commercial, and agriculture sectors at NUTS3 resolution
- First-appearance year restrictions for technologies such as V2G, synthetic gas, and pyrolysis
- Austrian wet and solid biomass potentials from UBA and BeST
- Baseline scenario validation against Eurostat Energy Balance

### Changed
- Updated 380 kV network topology with improved resolution of electricity transmission grid for Austrian regions
- Calibrated heat sector including existing capacities per heat system, demand profiles, and building thermal retrofitting

## [Alpha]

### Added
- Retrieval of the E-Control Anlagenregister (Strom + Gas, all Bundesländer) via the website search endpoint and NUTS3 aggregation ([#198](https://github.com/AGGM-AG/pypsa-at/pull/198))
- NUTS2 and NUTS3 administrative clustering with 1H/3H temporal resolution in the myopic workflow ([#55](https://github.com/AGGM-AG/pypsa-at/pull/55))
- National CO₂ budget constraints for Austria following KSG targets; net-zero by 2040
- Methane pyrolysis (plasma) as configurable H₂ production pathway; CH₄ split into H₂ and solid carbon black with no CO₂ emissions ([#73](https://github.com/AGGM-AG/pypsa-at/pull/73))
- enforced Open-TYNDP capacity trajectories as `p_nom_min` / `p_nom_max` bounds for EU countries (onwind, solar, solar-hsat, battery, home battery, H2 electrolysis, nuclear) ([#89](https://github.com/AGGM-AG/pypsa-at/pull/89), [#128](https://github.com/AGGM-AG/pypsa-at/pull/128))
- added solar capacity constraints based on KLIEN study ([#95](https://github.com/AGGM-AG/pypsa-at/pull/95))
- added wind capacity constraints based on KLIEN study ([#98](https://github.com/AGGM-AG/pypsa-at/pull/98))
- New statistics for `remaining_capacity` and `technical_potentials` ([#100](https://github.com/AGGM-AG/pypsa-at/pull/100))
- New `H2 for industry` bus to support industrial on-site conversion technologies; models `Methane Pyrolysis - Plasma` as on-site H2 production pathway ([#102](https://github.com/AGGM-AG/pypsa-at/pull/102))
- EAG §4(2) net-zero country level electricity balance constraint ([#104](https://github.com/AGGM-AG/pypsa-at/pull/104))
- Limit cross-country electricity flows by NTCs (TYNDP) ([#112](https://github.com/AGGM-AG/pypsa-at/pull/112))
- Added H2 imports from countries that are not in the model based on tyndp data ([#126](https://github.com/AGGM-AG/pypsa-at/pull/126))
- Added Know-How document for hydro power ([#135](https://github.com/AGGM-AG/pypsa-at/pull/135))
- Added trajectories for hydro power components ([#147](https://github.com/AGGM-AG/pypsa-at/pull/147))
- Added file list configuration for custom cost files ([#148](https://github.com/AGGM-AG/pypsa-at/pull/148))
- Added files for biogas-to-power plants from Austrian Anlagenregister ([#157](https://github.com/AGGM-AG/pypsa-at/pull/157/)) 
- Added `AT-Postal-to-NUTS3` file to map Austrian postal codes to NUTS3 region names ([#157](https://github.com/AGGM-AG/pypsa-at/pull/157/)) 
- New `loss` statistic, residual load views, and duration curve support in evals ([#161](https://github.com/AGGM-AG/pypsa-at/pull/161))
- Data retrieval and preparation for Statistik Austria Nutzenergieanalyse ([#174](https://github.com/AGGM-AG/pypsa-at/pull/174))
- Added regional industrial demand overrides from Statistik Austria NEA data ([#177](https://github.com/AGGM-AG/pypsa-at/pull/177))
- EAG limits for solar, wind, hydro and bioass added ([#179](https://github.com/AGGM-AG/pypsa-at/pull/179))
- Added Austrian regional vehicle-stock and NEA-based road transport demand data ([#188](https://github.com/AGGM-AG/pypsa-at/pull/188))
- Heat demand totals based on NEA data and spatial disaggregation based on austrian heatmap ([#182](https://github.com/AGGM-AG/pypsa-at/pull/182))
- Calibrated Austrian hydro fleet: powerplantmatching duplicates dropped, technology reclassification of the large river chains, operator-sourced capacity corrections and relocations, Grenzkraftwerke treaty shares, missing plants above 10 MW (Kamp, Lech, Salzach, Sill, Traun, Enns, Große Mühl, Großarl, Kleinarl, Rauris, Trisanna, Defereggen, Stubai, Ill, Lutz, Alfenz and Stubach, incl. the ÖBB railway plants and industrial self-suppliers), and the Anlagenregister *Kleinwasserkraft* fleet scaled to the E-Control Bestandsstatistik
- KLIEN-scaled Austrian run-of-river capacity corridor (`build_klien_hydro_trajectory_at`) replacing the PEMMDB upper bound; new datasets `econtrol-bestandsstatistik` and `klien_potentials` 2026-v3 with the hydro catchment table
- Anlagenregister small hydro plants receive the coordinates of their postal code centroid (new dataset `geonames-postal-codes-at`, GeoNames CC BY 4.0), so the KLIEN inflow allocation places them in their river catchment instead of spreading them over the region by area
- Curated KLIEN catchment corrections (`data/pypsa-at/hydro_catchment_corrections_AT.csv`) replace the study's capacity and energy where operator data proves them wrong (lower Enns company total, Bavarian Nußdorf plant on the Inn border)
- EAG hydro production floor for 2030 set to 43.5 TWh: the 47 TWh target minus a fixed 3.5 TWh credit for generation from pumped water (E-Control 2013–2025 average), which E-Control counts but the model's natural-inflow expression excludes; the inflow generators in the production expression are now weighted by the turbine efficiency of their store, so the floor is stated in delivered electricity
- KLIEN-calibrated Austrian hydro inflow targets (`build_hydro_inflow_targets_at`): catchment energy allocated to plants by location, shared with the German Grenzkraftwerke halves, scaled to the weather year with the E-Control Betriebsstatistik (new dataset `econtrol-betriebsstatistik`), replacing the Austrian run-of-river and reservoir totals in `build_inflow_totals_per_region`; reservoir inflow rises from ≈ 2.6 TWh to ≈ 10 TWh

### Changed
- `overwrite_powerplants_at` now writes the calibrated fleet as `powerplants_s_{clusters}.csv` and the untouched powerplantmatching output moves to `powerplants_s_{clusters}-raw.csv`, so every rule reads the calibrated table without per-rule overrides; Austrian run-of-river inflow rises from ≈ 13 TWh to ≈ 35 TWh because the ror normalisation now sees the full fleet
- Hydro plant corrections may relocate a plant (`bus_new`, `lat_new`, `lon_new`); the Ennskraftwerk St. Pantaleon moves from the Salzach (AT311) to the Enns (AT121)
- Austrian reservoir and pumped-storage store volumes are fixed at the existing capacity (`mods.update_hydro_capacities_AT.fix_store_volumes`): the new store vintages get `e_nom_max = 0`, turbine and pump links stay extendable
- PEMMDB storage volumes (GWh) are converted to MWh in the capacity trajectories; the `Store-e_nom` corridors were a thousand times too small and blocked every storage-volume expansion
- Austrian pumped-storage natural inflow taken from the E-Control Betriebsstatistik (generation of pumped-storage plants minus generation from pumped water, reference-period mean scaled to the weather year, spread by pumped-storage capacity) instead of the PEMMDB *PS Open* value, which was about twice as high
- Reservoir and pumped-storage inflow is grossed up by the turbine efficiency of the store when patched into the network, so the delivered electricity equals the calibrated (PEMMDB / KLIEN) energy instead of falling 10–13 % short
- `_redistribute_peaks` iterates per region, falls back to a headroom waterfill for near-saturated regions, raises on regions whose inflow exceeds `p_nom × hours` instead of spilling silently
- Anlagenregister aggregation drops duplicate registrations of large water plants (one entry per marketing contract)
- Blocked imports of Russian methane via Ukraine and TurkStream ([#129](https://github.com/AGGM-AG/pypsa-at/pull/129))
- modified Austrian brownfield gas grid with AGGM expert data; disabled expansion of pipelines until 2040; disabled building of new methane pipelines in the model ([#91](https://github.com/AGGM-AG/pypsa-at/pull/91))
- Updated gas storage capacities from AGSI and AT-specific data sources ([#111](https://github.com/AGGM-AG/pypsa-at/pull/111))
- Updated README features section and restructured CHANGELOG to Keep a Changelog format ([#124](https://github.com/AGGM-AG/pypsa-at/pull/124))
- Updated PHS modeling by exchanging StorageUnits with 2x Links + Bus + Store + Generator ([#131](https://github.com/AGGM-AG/pypsa-at/pull/131))
- Changed Inflow data source to PEMMDB data with ERA5 profiles ([#146](https://github.com/AGGM-AG/pypsa-at/pull/146))
- Added Austrian biogas-to-power plants from Anlagenregister as brownfield capacities ([#157](https://github.com/AGGM-AG/pypsa-at/pull/157/)) 

### Fixed
- Fixed double subtraction of brownfield capacities in `modify_prenetwork` and `solve_network` and added a new test for this case. ([#101](https://github.com/AGGM-AG/pypsa-at/pull/101))
- Fixed bidirectional links of gaseous energy carriers via config.at.yaml. Will be in an upstream merge to PyPSA-Eur to fix there. ([#105](https://github.com/AGGM-AG/pypsa-at/pull/105))
- Fixed issues with wrong bus matching for h2 imports ([#134](https://github.com/AGGM-AG/pypsa-at/pull/134))
- Fixed tests for integration of brownfield gas pipeline data ([#159](https://github.com/AGGM-AG/pypsa-at/pull/159))
