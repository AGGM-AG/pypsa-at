# SPDX-FileCopyrightText: 2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""
Build rules for AT-specific datasets.
"""


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


rule build_inflow_profile:
    input:
        cutout=lambda w: input_cutout(
            w, config_provider("renewable", "hydro", "cutout")(w)
        ),
        regions=resources("regions_onshore_base_s_{clusters}.geojson"),
    output:
        profile=resources("profile_inflow_{clusters}.nc"),
    log:
        logs("build_inflow_profile_{clusters}.log"),
    benchmark:
        benchmarks("build_inflow_profile_{clusters}")
    resources:
        mem_mb=5000,
    params:
        snapshots=config_provider("snapshots"),
        drop_leap_day=config_provider("enable", "drop_leap_day"),
    message:
        "Building hydropower inflow profile"
    script:
        scripts("pypsa-at/build_inflow_profile.py")


if (OPEN_TYNDP_DATASET := dataset_version("tyndp"))["source"] in [
    "primary",
    "archive",
]:

    rule build_inflow_totals_per_region:
        input:
            powerplants=resources("powerplants_s_{clusters}.csv"),
            hydro_inflows=directory(f"{OPEN_TYNDP_DATASET['folder']}/Hydro Inflows"),
            costs=lambda w: resources(
                f"costs_{config_provider('costs', 'year')(w)}_processed.csv"
            ),
        output:
            totals=resources("inflow_totals_per_region_{clusters}.csv"),
        log:
            logs("inflow_totals_per_region_{clusters}.log"),
        benchmark:
            benchmarks("inflow_totals_per_region_{clusters}")
        resources:
            mem_mb=5000,
        params:
            consider_efficiency_classes=config_provider(
                "clustering", "consider_efficiency_classes"
            ),
            aggregation_strategies=config_provider(
                "clustering", "aggregation_strategies"
            ),
            exclude_carriers=config_provider("clustering", "exclude_carriers"),
            hydro=config_provider("renewable", "hydro"),
        message:
            "Building hydropower inflow totals per region"
        script:
            scripts("pypsa-at/build_inflow_totals_per_region.py")


rule build_inflows_per_region:
    input:
        profile=resources("profile_inflow_{clusters}.nc"),
        totals=resources("inflow_totals_per_region_{clusters}.csv"),
    output:
        inflow=resources("inflow_per_region_{clusters}.nc"),
    log:
        logs("build_inflows_per_region_{clusters}.log"),
    benchmark:
        benchmarks("build_inflows_per_region_{clusters}")
    resources:
        mem_mb=5000,
    message:
        "Building hydropower inflows per region"
    script:
        scripts("pypsa-at/build_inflows_per_region.py")
