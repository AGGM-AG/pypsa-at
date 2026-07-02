# SPDX-FileCopyrightText: 2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""
Build rules for AT-specific datasets.
"""
rule build_custom_cost_fn:
    output:
        custom_cost_fn = resources("custom_cost_fn.csv"),
    log:
        logs("build_custom_cost_fn.log"),
    benchmark:
        benchmarks("build_custom_cost_fn")
    threads: 1
    resources:
        mem_mb=4000,
    params:
        costs=config_provider("costs"),
    script:
        scripts("pypsa-at/build_custom_cost_fn.py")


rule build_tyndp_trajectories:
    input:
        trajectories=rules.retrieve_open_tyndp.output.trajectories,
        carrier_mapping="data/pypsa-at/tyndp_technology_map.csv",
    output:
        tyndp_trajectories=resources("tyndp_trajectories.csv"),
    log:
        logs("build_tyndp_trajectories.log"),
    benchmark:
        benchmarks("build_tyndp_trajectories")
    threads: 1
    params:
        tyndp_scenario=config_provider("mods", "PEMMDB_trajectories", "tyndp_scenario"),
    message:
        "Building TYNDP capacity trajectories (p_nom_min/p_nom_max)"
    script:
        scripts("open-tyndp/build_tyndp_trajectories.py")
