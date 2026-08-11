# SPDX-FileCopyrightText: 2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""
PyPSA-AT patch to prepare_sector_network rule.
"""


use rule prepare_sector_network as prepare_sector_network_at with:
    input:
        **rules.prepare_sector_network.input,
        powerplants=resources("powerplants_s_{clusters}.csv"),
        inflow=resources("inflow_per_region_{clusters}.nc"),
        hydro_capacities=ancient("data/hydro_capacities.csv"),
        industrial_demand_profiles=branch(
            config_provider("industry", "demand_profiles", "enable"),
            resources(
                "industrial_demand_profiles_base_s_{clusters}_{opts}_{sector_opts}.csv"
            ),
            [],
        ),
        annual_demand_overrides=branch(
            config_provider("industry", "annual_demand_overrides", "enable"),
            resources("industrial_demand_overrides_base_s_{clusters}.csv"),
            [],
        ),
        code_files=[
            "mods/network/common.py",
            "mods/network/electricity.py",
            "mods/network/gas.py",
            "mods/network/h2.py",
            "mods/network/hydro.py",
            "mods/network/potentials.py",
            "mods/network/trajectories.py",
            "mods/demand/industrial_demand.py",
            "mods/demand/annual.py",
            "mods/constants.py",
            "mods/utils.py",
        ],
    params:
        **rules.prepare_sector_network.params,
        consider_efficiency_classes=config_provider(
            "clustering", "consider_efficiency_classes"
        ),
        aggregation_strategies=config_provider("clustering", "aggregation_strategies"),
        exclude_carriers=config_provider("clustering", "exclude_carriers"),
        carrier_to_load_mapping=config_provider("demand", "carrier_to_load_mapping"),
        annual_demand_overrides=config_provider("industry", "annual_demand_overrides"),


rule build_industrial_demand_overrides_at:
    input:
        nea_at=resources("nea_at.csv"),
        industrial_distribution_key=resources(
            "industrial_distribution_key_base_s_{clusters}.csv"
        ),
    output:
        industrial_demand_overrides=resources(
            "industrial_demand_overrides_base_s_{clusters}.csv"
        ),
    log:
        logs("build_industrial_demand_overrides_at_{clusters}.log"),
    benchmark:
        benchmarks("build_industrial_demand_overrides_at/s_{clusters}")
    threads: 1
    resources:
        mem_mb=2000,
    params:
        target_years=config_provider(
            "industry", "annual_demand_overrides", "target_years"
        ),
        source_years=config_provider(
            "industry", "annual_demand_overrides", "source_years"
        ),
        source_category=config_provider(
            "industry", "annual_demand_overrides", "source_category"
        ),
    message:
        "Building annual industrial demand overrides from NEA data"
    script:
        scripts("pypsa-at/build_nea_industry_demand.py")


ruleorder: prepare_sector_network_at > prepare_sector_network


# AT-owned adaptation of the (not yet merged) PyPSA-Eur PR #1875 "Temporal
# industry load": builds normalized hourly industry demand profiles (one
# resource file covering all planning horizons) from FfE load-shape data.
# Applied to network Loads by mods/demand/industrial_demand.py during
# prepare_sector_network -- see
# docs-at/explanations/data-flows/industrial-demand.md.
# Gated behind `industry.demand_profiles.enable` so the rule (and the FfE
# retrieval it depends on) is only defined when opted in.
if config.get("industry", {}).get("demand_profiles", {}).get("enable", False):

    rule build_industrial_demand_profiles_at:
        input:
            industry_sector_ratios=expand(
                resources("industry_sector_ratios_{planning_horizons}.csv"),
                planning_horizons=config["scenario"]["planning_horizons"],
                allow_missing=True,
            ),
            industrial_production_per_node=expand(
                resources(
                    "industrial_production_base_s_{clusters}_{planning_horizons}.csv"
                ),
                planning_horizons=config["scenario"]["planning_horizons"],
                allow_missing=True,
            ),
            ffe_profiles="data/pypsa-at/ffe_industry_load_profiles.json",
            snapshot_weightings=resources(
                "snapshot_weightings_base_s_{clusters}_elec_{opts}_{sector_opts}.csv"
            ),
        output:
            industrial_demand_profiles=resources(
                "industrial_demand_profiles_base_s_{clusters}_{opts}_{sector_opts}.csv"
            ),
        log:
            logs(
                "build_industrial_demand_profiles_at_{clusters}_{opts}_{sector_opts}.log"
            ),
        benchmark:
            benchmarks(
                "build_industrial_demand_profiles_at/s_{clusters}_{opts}_{sector_opts}"
            )
        threads: 1
        resources:
            mem_mb=2000,
        params:
            planning_horizons=config_provider("scenario", "planning_horizons"),
            snapshots=config_provider("snapshots"),
            drop_leap_day=config_provider("enable", "drop_leap_day"),
            carrier_mapping=config_provider(
                "industry", "demand_profiles", "carrier_mapping"
            ),
        message:
            "Building normalized hourly industry demand profiles for {wildcards.clusters} clusters"
        script:
            scripts("pypsa-at/build_industrial_demand_profiles.py")
