# SPDX-FileCopyrightText: 2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""
Solve rule extensions for AT-specific datasets.
"""

OPEN_TYNDP_DATASET = dataset_version("tyndp")
RESOURCE_META = {
    "inflow_data": resources("inflow_per_region.nc"),
    "co2_totals": resources("co2_totals.csv"),
    "open_tyndp_hydro": f"{OPEN_TYNDP_DATASET['folder']}/Hydro Inflows",
    "powerplants": resources("powerplants.csv"),
    "onwind_brownfield": resources("onwind_brownfield_at.csv"),
    "aggm_gas_pipeline_data": resources("gas_network_clustered.csv"),
    "industrial_demand_profiles": resources("industrial_demand_profiles.csv"),
    "industrial_demand_overrides": resources("industrial_demand_overrides.csv"),
    "heat_demand_nea_at": resources("heat_demand_nea_at.csv"),
    "electricity_base_load_at": branch(
        config_provider("mods", "electricity_base_load", "enable"),
        resources("electricity_base_load_at.csv"),
        [],
    ),
    "transport_data_at": branch(
        config_provider("demand", "transport", "use_nea_demand"),
        resources("transport_data_raw_at.csv"),
        [],
    ),
}
INPUT_META = ["energy_totals", "trajectories"]


use rule solve_network as solve_network_at with:
    input:
        **rules.solve_network.input,
        **RESOURCE_META,
        tyndp_trajectories=resources("tyndp_trajectories.csv"),
        tyndp_transmission_trajectories=resources("tyndp_transmission_trajectories.csv"),
        trajectories=resources("trajectories.csv"),
        costs=lambda w: resources(f"costs_{at_cost_year(w)}_processed.csv"),
        code_files=[
            "mods/utils.py",
        ],
    params:
        **rules.solve_network.params,
        apply_trajectories=config_provider("mods", "trajectories", "apply_trajectories"),
        trajectories_tol=config_provider("mods", "trajectories", "tol"),
        resource_meta=lambda wildcards, input: {
            key: value
            for key, value in input.items()
            if (key in RESOURCE_META or key in INPUT_META) and value
        },
        consider_efficiency_classes=config_provider(
            "clustering", "consider_efficiency_classes"
        ),
        aggregation_strategies=config_provider("clustering", "aggregation_strategies"),
        exclude_carriers=config_provider("clustering", "exclude_carriers"),
        admin_levels=config_provider("clustering", "administrative"),
        custom_clustering=config_provider("mods", "modify_nuts3_shapes"),


ruleorder: solve_network_at > solve_network
