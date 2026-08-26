# SPDX-FileCopyrightText: 2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""
Solve rule extensions for AT-specific datasets.
"""

OPEN_TYNDP_DATASET = dataset_version("tyndp")
RESOURCE_META = {
    "inflow_data": resources("inflow_per_region_{clusters}.nc"),
    "co2_totals": resources("co2_totals.csv"),
    "open_tyndp_hydro": f"{OPEN_TYNDP_DATASET['folder']}/Hydro Inflows",
    "powerplants": resources("powerplants_s_{clusters}.csv"),
    "aggm_gas_pipeline_data": resources("gas_network_base_s_{clusters}.csv"),
    "industrial_demand_profiles": resources(
        "industrial_demand_profiles_base_s_{clusters}_{opts}_{sector_opts}.csv"
    ),
    "industrial_demand_overrides": resources(
        "industrial_demand_overrides_base_s_{clusters}.csv"
    ),
}
INPUT_META = ["energy_totals", "trajectories"]

if config["foresight"] == "overnight":

    use rule solve_sector_network as solve_sector_network_at with:
        input:
            **rules.solve_sector_network.input,
            **RESOURCE_META,
            tyndp_trajectories=resources("tyndp_trajectories.csv"),
            tyndp_transmission_trajectories=resources(
                "tyndp_transmission_trajectories.csv"
            ),
            trajectories=resources("trajectories_{clusters}.csv"),
            costs=lambda w: resources(
                f"costs_{config_provider('costs', 'year')(w)}_processed.csv"
            ),
            code_files=[
                "mods/utils.py",
            ],
        params:
            **rules.solve_sector_network.params,
            apply_trajectories=config_provider(
                "mods", "trajectories", "apply_trajectories"
            ),
            trajectories_tol=config_provider("mods", "trajectories", "tol"),
            resource_meta=lambda wildcards, input: {
                key: value
                for key, value in input.items()
                if (key in RESOURCE_META or key in INPUT_META)
            },
            consider_efficiency_classes=config_provider(
                "clustering", "consider_efficiency_classes"
            ),
            aggregation_strategies=config_provider(
                "clustering", "aggregation_strategies"
            ),
            exclude_carriers=config_provider("clustering", "exclude_carriers"),
            admin_levels=config_provider("clustering", "administrative"),
            custom_clustering=config_provider("mods", "modify_nuts3_shapes"),

    ruleorder: solve_sector_network_at > solve_sector_network


if config["foresight"] == "myopic":

    use rule solve_sector_network_myopic as solve_sector_network_myopic_at with:
        input:
            **rules.solve_sector_network_myopic.input,
            **RESOURCE_META,
            tyndp_trajectories=resources("tyndp_trajectories.csv"),
            tyndp_transmission_trajectories=resources(
                "tyndp_transmission_trajectories.csv"
            ),
            trajectories=resources("trajectories_{clusters}.csv"),
            costs=lambda w: resources(
                f"costs_{config_provider('costs', 'year')(w)}_processed.csv"
            ),
            code_files=[
                "mods/utils.py",
            ],
        params:
            **rules.solve_sector_network_myopic.params,
            apply_trajectories=config_provider(
                "mods", "trajectories", "apply_trajectories"
            ),
            trajectories_tol=config_provider("mods", "trajectories", "tol"),
            resource_meta=lambda wildcards, input: {
                key: value
                for key, value in input.items()
                if (key in RESOURCE_META or key in INPUT_META)
            },
            consider_efficiency_classes=config_provider(
                "clustering", "consider_efficiency_classes"
            ),
            aggregation_strategies=config_provider(
                "clustering", "aggregation_strategies"
            ),
            exclude_carriers=config_provider("clustering", "exclude_carriers"),
            admin_levels=config_provider("clustering", "administrative"),
            custom_clustering=config_provider("mods", "modify_nuts3_shapes"),

    ruleorder: solve_sector_network_myopic_at > solve_sector_network_myopic


if config["foresight"] == "perfect":

    use rule solve_sector_network_perfect as solve_sector_network_perfect_at with:
        input:
            **rules.solve_sector_network_perfect.input,
            **RESOURCE_META,
            tyndp_trajectories=resources("tyndp_trajectories.csv"),
            tyndp_transmission_trajectories=resources(
                "tyndp_transmission_trajectories.csv"
            ),
            trajectories=resources("trajectories_{clusters}.csv"),
            costs=lambda w: resources(
                f"costs_{config_provider('costs', 'year')(w)}_processed.csv"
            ),
            code_files=[
                "mods/utils.py",
            ],
        params:
            **rules.solve_sector_network_perfect.params,
            apply_trajectories=config_provider(
                "mods", "trajectories", "apply_trajectories"
            ),
            trajectories_tol=config_provider("mods", "trajectories", "tol"),
            resource_meta=lambda wildcards, input: {
                key: value
                for key, value in input.items()
                if (key in RESOURCE_META or key in INPUT_META)
            },
            consider_efficiency_classes=config_provider(
                "clustering", "consider_efficiency_classes"
            ),
            aggregation_strategies=config_provider(
                "clustering", "aggregation_strategies"
            ),
            exclude_carriers=config_provider("clustering", "exclude_carriers"),
            admin_levels=config_provider("clustering", "administrative"),
            custom_clustering=config_provider("mods", "modify_nuts3_shapes"),

    ruleorder: solve_sector_network_perfect_at > solve_sector_network_perfect
