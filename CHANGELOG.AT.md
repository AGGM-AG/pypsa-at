# Changelog

- https://github.com/AGGM-AG/pypsa-at/pull/91: modified Austrian brownfield gas grid with AGGM expert data; disabled expansion of pipelines until 2040; disabled building of new methane pipelines in the model 
- https://github.com/AGGM-AG/pypsa-at/pull/89: enforced Open-TYNDP capacity trajectories as `p_nom_min` / `p_nom_max` bounds for EU countries (onwind, solar, solar-hsat, battery, home battery, H2 electrolysis)
- https://github.com/AGGM-AG/pypsa-at/pull/95: added solar capacity constraints based on KLIEN study
- https://github.com/AGGM-AG/pypsa-at/pull/98: added wind capacity constraints based on KLIEN study
- https://github.com/AGGM-AG/pypsa-at/pull/101: Fixed double subtraction of brownfield capacities in `modify_prenetwork` and `solve_network` and added a new test for this case.
- https://github.com/AGGM-AG/pypsa-at/pull/100: New statistics for `remaining_capacity` and `technical_potentials`
- https://github.com/AGGM-AG/pypsa-at/pull/102: New `H2 for industry` bus to support industrial on-site conversion technologies; models `Methane Pyrolysis - Plasma` as on-site H2 production pathway  
- https://github.com/AGGM-AG/pypsa-at/pull/105: Fixed bidirectional links of gaseous energy carriers via config.at.yaml. Will be in an upstream merge to PyPSA-Eur to fix there.