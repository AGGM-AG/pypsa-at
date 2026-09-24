# Changelog

All notable changes to PyPSA-AT are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [Planned]

### Added
- `patch_powerplants_set_at` rule restoring `Set="PP"` on the large German lignite condensing units, which powerplantmatching 0.8.x tags `Set="CHP"` and the inherited PyPSA-DE `powerplants_filter` then drops (19,965 MW → 0 MW of German lignite)

### Fixed
- H2 pipeline retrofitting is coupled to the fixed Austrian gas grid: gas pipelines stay extendable within their AGGM target capacity from the retrofit start year (`first_technology_occurrence`, 2030) up to the threshold year, so gas plus retrofitted H2 capacity per corridor cannot exceed the target; retrofits carried over from earlier horizons are deducted from the gas grid, which the upstream `add_brownfield` mapping misses; asymmetric corridors are restored only before the retrofit start year; gas pipelines without an extendable retrofit candidate are fixed so the positional pairing of the upstream retrofit constraint holds, guarded by `check_retrofit_pairing` ([#294](https://github.com/AGGM-AG/pypsa-at-planning/issues/294))

### Changed
- Bumped `powerplantmatching` to 0.8.0 and the `powerplants` dataset to 0.8.1. 0.8.0 fixes the IRENASTAT download, which previously fetched a Zenodo 403 HTML page and failed in `add_existing_baseyear`; 0.8.1 is not usable as a package because it caps `pandas <3`
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
- Added Austrian onshore-wind brownfield capacity vintages based on historical generation and KLIEN potentials ([#208](https://github.com/AGGM-AG/pypsa-at/pull/208))

### Changed
- Merged PyPSA-DE main (incl. PyPSA-Eur 2026.08): pandas 3, PyPSA 1.3; ppm 0.6.1
- Blocked imports of Russian methane via Ukraine and TurkStream ([#129](https://github.com/AGGM-AG/pypsa-at/pull/129))
- modified Austrian brownfield gas grid with AGGM expert data; disabled expansion of pipelines until 2040; disabled building of new methane pipelines in the model ([#91](https://github.com/AGGM-AG/pypsa-at/pull/91))
- Updated gas storage capacities from AGSI and AT-specific data sources ([#111](https://github.com/AGGM-AG/pypsa-at/pull/111))
- Updated README features section and restructured CHANGELOG to Keep a Changelog format ([#124](https://github.com/AGGM-AG/pypsa-at/pull/124))
- Updated PHS modeling by exchanging StorageUnits with 2x Links + Bus + Store + Generator ([#131](https://github.com/AGGM-AG/pypsa-at/pull/131))
- Changed Inflow data source to PEMMDB data with ERA5 profiles ([#146](https://github.com/AGGM-AG/pypsa-at/pull/146))
- Added Austrian biogas-to-power plants from Anlagenregister as brownfield capacities ([#157](https://github.com/AGGM-AG/pypsa-at/pull/157/))
- Updated Austrian brownfield gas grid data ([#207](https://github.com/AGGM-AG/pypsa-at/pull/207))

