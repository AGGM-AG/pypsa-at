# SPDX-FileCopyrightText: 2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""
Build rules for AT-specific datasets.
"""

from mods.constants import NUTS2_CODES

BUNDESLAENDER = list(NUTS2_CODES.keys())


rule build_custom_cost_at:
    input:
        custom_cost_files=branch(
            config_provider("costs", "use_list"),
            config_provider("costs", "custom_cost_fn_list"),
            lambda w: [config_provider("costs", "custom_cost_fn")(w)],
        ),
    output:
        custom_cost_fn=resources("custom_cost_at.csv"),
    log:
        logs("build_custom_cost_at.log"),
    benchmark:
        benchmarks("build_custom_cost_at")
    threads: 1
    resources:
        mem_mb=4000,
    params:
        costs=config_provider("costs"),
    script:
        scripts("pypsa-at/build_custom_cost_at.py")


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
            hydro_inflows=f"{OPEN_TYNDP_DATASET['folder']}/Hydro Inflows",
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
            snapshots=config_provider("snapshots"),
            drop_leap_day=config_provider("enable", "drop_leap_day"),
            admin_levels=config_provider("clustering", "administrative"),
            custom_clustering=config_provider("mods", "modify_nuts3_shapes"),
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


rule build_capacity_trajectories:
    input:
        hydro_inflows=f"{OPEN_TYNDP_DATASET['folder']}/Hydro Inflows",
        code_files=[
            "mods/constants.py",
            "scripts/_helpers.py",
        ],
        powerplants=resources("powerplants_s_{clusters}.csv"),
        costs=lambda w: resources(
            f"costs_{config_provider('costs', 'year')(w)}_processed.csv"
        ),
    output:
        trajectories=resources("trajectories_{clusters}.csv"),
    log:
        logs("trajectories_{clusters}.log"),
    benchmark:
        benchmarks("trajectories_{clusters}")
    resources:
        mem_mb=5000,
    params:
        countries=config_provider("countries"),
        planning_horizons=config_provider("scenario", "planning_horizons"),
        consider_efficiency_classes=config_provider(
            "clustering", "consider_efficiency_classes"
        ),
        aggregation_strategies=config_provider("clustering", "aggregation_strategies"),
        exclude_carriers=config_provider("clustering", "exclude_carriers"),
        admin_levels=config_provider("clustering", "administrative"),
        custom_clustering=config_provider("mods", "modify_nuts3_shapes"),
    message:
        "Building capacity trajectories"
    script:
        scripts("pypsa-at/build_capacity_trajectories.py")


if NEA_AT["source"] == "primary":

    rule build_nea_at:
        input:
            **{b: f"{NEA_AT['folder']}/NEA{b}Daten.ods" for b in BUNDESLAENDER},
        output:
            nea_at=resources("nea_at.csv"),
        log:
            logs("build_nea_at.log"),
        benchmark:
            benchmarks("build_nea_at")
        resources:
            mem_mb=5000,
        message:
            "Building stacked Statistik Austria NEA .csv"
        script:
            scripts("pypsa-at/build_nea_at.py")


if STATISTIK_AT_REGIONS["source"] in ["primary", "archive"]:

    rule build_statistik_at_regions:
        input:
            ods=rules.retrieve_statistik_at_regions.output["ods"],
            nuts3_shapes=resources("nuts3_shapes.geojson"),
        output:
            regional_data=resources("statistik_at_regions.csv"),
        log:
            logs("build_statistik_at_regions.log"),
        benchmark:
            benchmarks("build_statistik_at_regions")
        threads: 1
        resources:
            mem_mb=2000,
        message:
            "Building general Statistik Austria regional data CSV"
        script:
            scripts("pypsa-at/build_statistik_at_regions.py")


if KFZ_BESTAND_AT["source"] in ["primary", "archive"]:

    rule build_kfz_bestand_at:
        input:
            ods=rules.retrieve_kfz_bestand_at.output["ods"],
            regional_data=rules.build_statistik_at_regions.output["regional_data"],
            transport_data_in=resources("transport_data.csv"),
        output:
            transport_data_out=resources("transport_data_{clusters}_at.csv"),
        log:
            logs("build_kfz_bestand_{clusters}.log"),
        benchmark:
            benchmarks("build_kfz_bestand_{clusters}")
        threads: 1
        resources:
            mem_mb=2000,
        params:
            clustering=config_provider("mods", "modify_nuts3_shapes"),
            energy_totals_year=config_provider("energy", "energy_totals_year"),
        message:
            "Building regional Statistik Austria vehicle stock data"
        script:
            scripts("pypsa-at/build_kfz_bestand_at.py")


use rule build_transport_demand as build_transport_demand_at with:
    input:
        **{
            **rules.build_transport_demand.input,
            "transport_data": resources("transport_data_{clusters}_at.csv"),
        },


ruleorder: build_transport_demand_at > build_transport_demand


rule patch_transport_demand_at:
    input:
        transport_demand=resources("transport_demand_s_{clusters}.csv"),
        nea_at=resources("nea_at.csv"),
        temp_air_total=resources("temp_air_total_base_s_{clusters}.nc"),
        clustered_pop_layout=resources("pop_layout_base_s_{clusters}.csv"),
    output:
        transport_demand_patched=resources("transport_demand_s_{clusters}_at.csv"),
    log:
        logs("patch_transport_demand_at_{clusters}.log"),
    benchmark:
        benchmarks("patch_transport_demand_at_{clusters}")
    threads: 1
    resources:
        mem_mb=2000,
    params:
        planning_horizons=config_provider("scenario", "planning_horizons"),
        sector=config_provider("sector"),
    message:
        "Patching transport demand using Statistik Austria Nutzenergieanalyse"
    script:
        scripts("pypsa-at/patch_transport_demand_at.py")
