# SPDX-FileCopyrightText: 2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""
Solve rule extensions for AT-specific datasets.
"""

RESOURCE_META = {
    "inflow_data": resources("inflow_per_region_{clusters}.nc"),
    "co2_totals": resources("co2_totals.csv"),
}
INPUT_META = [
    "energy_totals",
]

if config["foresight"] == "overnight":

    use rule solve_sector_network as solve_sector_network_at with:
        input:
            **rules.solve_sector_network.input,
            **RESOURCE_META,
            tyndp_trajectories=resources("tyndp_trajectories.csv"),
            tyndp_transmission_trajectories=resources(
                "tyndp_transmission_trajectories.csv"
            ),
            code_files=[
                "mods/utils.py",
            ],
        params:
            **rules.solve_sector_network.params,
            resource_meta=lambda wildcards, input: {
                key: value
                for key, value in input.items()
                if (key in RESOURCE_META or key in INPUT_META)
            },

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
            code_files=[
                "mods/utils.py",
            ],
        params:
            **rules.solve_sector_network_myopic.params,
            resource_meta=lambda wildcards, input: {
                key: value
                for key, value in input.items()
                if (key in RESOURCE_META or key in INPUT_META)
            },

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
            code_files=[
                "mods/utils.py",
            ],
        params:
            **rules.solve_sector_network_perfect.params,
            resource_meta=lambda wildcards, input: {
                key: value
                for key, value in input.items()
                if (key in RESOURCE_META or key in INPUT_META)
            },

    ruleorder: solve_sector_network_perfect_at > solve_sector_network_perfect
