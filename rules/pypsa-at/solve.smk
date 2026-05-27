# SPDX-FileCopyrightText: 2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""
Solve rule extensions for AT-specific datasets.
"""

if config["foresight"] == "overnight":

    use rule solve_sector_network as solve_sector_network_at with:
        input:
            **rules.solve_sector_network.input,
            tyndp_trajectories=resources("tyndp_trajectories.csv"),
            tyndp_transmission_trajectories=resources(
                "tyndp_transmission_trajectories.csv"
            ),

    ruleorder: solve_sector_network_at > solve_sector_network


if config["foresight"] == "myopic":

    use rule solve_sector_network_myopic as solve_sector_network_myopic_at with:
        input:
            **rules.solve_sector_network_myopic.input,
            tyndp_trajectories=resources("tyndp_trajectories.csv"),
            tyndp_transmission_trajectories=resources(
                "tyndp_transmission_trajectories.csv"
            ),

    ruleorder: solve_sector_network_myopic_at > solve_sector_network_myopic


if config["foresight"] == "perfect":

    use rule solve_sector_network_perfect as solve_sector_network_perfect_at with:
        input:
            **rules.solve_sector_network_perfect.input,
            tyndp_trajectories=resources("tyndp_trajectories.csv"),
            tyndp_transmission_trajectories=resources(
                "tyndp_transmission_trajectories.csv"
            ),

    ruleorder: solve_sector_network_perfect_at > solve_sector_network_perfect
