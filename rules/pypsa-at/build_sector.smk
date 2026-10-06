# SPDX-FileCopyrightText: 2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""
PyPSA-AT sector build rules.
"""


rule build_industrial_demand_overrides_at:
    input:
        nea_at=resources("nea_at.csv"),
        industrial_distribution_key=resources("industrial_distribution_key.csv"),
    output:
        industrial_demand_overrides=resources("industrial_demand_overrides.csv"),
    log:
        logs("build_industrial_demand_overrides_at.log"),
    benchmark:
        benchmarks("build_industrial_demand_overrides_at")
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


# AT-owned adaptation of the (not yet merged) PyPSA-Eur PR #1875 "Temporal
# industry load": builds normalized hourly industry demand profiles (one
# resource file covering all planning horizons) from FfE load-shape data.
# Applied to network Loads by mods/demand/industrial_demand.py during
# compose_network -- see
# docs-at/explanations/data-flows/industrial-demand.md.
# Gated behind `industry.demand_profiles.enable` so the rule (and the FfE
# retrieval it depends on) is only defined when opted in.
if config.get("industry", {}).get("demand_profiles", {}).get("enable", False):

    rule build_industrial_demand_profiles_at:
        input:
            industry_sector_ratios=expand(
                resources("industry_sector_ratios_{horizon}.csv"),
                horizon=config["planning_horizons"],
                allow_missing=True,
            ),
            industrial_production_per_node=expand(
                resources("industrial_production_{horizon}.csv"),
                horizon=config["planning_horizons"],
                allow_missing=True,
            ),
            ffe_profiles=f"{FFE_INDUSTRY_LOAD_PROFILES['folder']}/ffe_industry_load_profiles.json",
            snapshot_weightings=resources("snapshot_weightings.csv"),
        output:
            industrial_demand_profiles=resources("industrial_demand_profiles.csv"),
        log:
            logs("build_industrial_demand_profiles_at.log"),
        benchmark:
            benchmarks("build_industrial_demand_profiles_at")
        threads: 1
        resources:
            mem_mb=2000,
        params:
            planning_horizons=config_provider("planning_horizons"),
            snapshots=config_provider("snapshots"),
            drop_leap_day=config_provider("enable", "drop_leap_day"),
            carrier_mapping=config_provider(
                "industry", "demand_profiles", "carrier_mapping"
            ),
        message:
            "Building normalized hourly industry demand profiles"
        script:
            scripts("pypsa-at/build_industrial_demand_profiles.py")
