# SPDX-FileCopyrightText: 2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""
PyPSA-AT sector build rules.

Overrides of upstream rules in ``rules/build_sector.smk`` and AT-specific
sector datasets (gas network, heat demand, energy balances, transport).
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


# --- AT gas network ----------------------------------------------------------


rule modify_brownfield_gas_network_AT:
    input:
        clustered_gas_network_raw=resources("gas_network_clustered_raw.csv"),
        brownfield_gas_network_AT35=("data/pypsa-at/AGGM_gas_network_base_AT35.csv"),
        regions_onshore=resources("onshore_regions.geojson"),
        regions_offshore=resources("offshore_regions.geojson"),
    output:
        clustered_gas_network=resources("gas_network_clustered.csv"),
    log:
        logs("modify_brownfield_gas_network_AT.log"),
    resources:
        mem_mb=4000,
    params:
        length_factor=config_provider("links", "length_factor"),
        custom_clustering=config_provider("mods", "modify_nuts3_shapes"),
        modify_brownfield_gas_network_AT=config_provider(
            "mods", "modify_brownfield_gas_network_AT"
        ),
    script:
        scripts("pypsa-at/modify_brownfield_gas_network_AT.py")


# cluster_gas_network: redirect the clustered gas network to a "_raw" file so
# modify_brownfield_gas_network_AT can merge in the AGGM brownfield network.
use rule cluster_gas_network as cluster_gas_network_at with:
    output:
        clustered_gas_network=resources("gas_network_clustered_raw.csv"),


ruleorder: modify_brownfield_gas_network_AT > cluster_gas_network  # AT wins for the final .csv


# --- AT heat, energy balance and transport datasets ---------------------------


def heat_demand_at_raster_path(scenario, year):
    return f"{HEAT_DEMAND_DATASET['folder']}/{HEAT_DEMAND_DATASETS[scenario][year]}"


def heat_demand_at_inputs(w):
    scenario = config_provider("sector", "heat_demand_scenario")(w)
    return [
        heat_demand_at_raster_path("WEM", 2021),
        heat_demand_at_raster_path(scenario, 2030),
        heat_demand_at_raster_path(scenario, 2050),
    ]


rule build_heat_demand_at:
    input:
        nuts3_shapes=resources("nuts3_shapes.geojson"),
        heatmaps=heat_demand_at_inputs,
    output:
        heat_demand=resources("heat_demand_at.csv"),
    log:
        logs("build_heat_demand_at.log"),
    benchmark:
        benchmarks("build_heat_demand_at")
    threads: 1
    resources:
        mem_mb=4000,
    params:
        planning_horizons=config_provider("planning_horizons"),
        clustering=config_provider("mods", "modify_nuts3_shapes"),
    message:
        "Building Austrian NUTS3 heat demand from heatmaps"
    script:
        scripts("pypsa-at/build_heat_demand_at.py")


rule recalibrate_heat_demand_at:
    input:
        heat_demand=resources("heat_demand_at.csv"),
        nea_at=resources("nea_at.csv"),
        nuts3_shapes=resources("nuts3_shapes.geojson"),
        urban_fraction=lambda w: [
            resources("district_heat_share_{horizon}-modified.csv").format(
                run=w.run, horizon=year
            )
            for year in config_provider("planning_horizons")(w)
        ],
    output:
        heat_demand=resources("heat_demand_nea_at.csv"),
        urban_fraction_at=resources("urban_fraction_at.csv"),
    log:
        logs("recalibrate_heat_demand_at.log"),
    benchmark:
        benchmarks("recalibrate_heat_demand_at")
    threads: 1
    resources:
        mem_mb=2000,
    params:
        source_years=config_provider("demand", "source_years"),
        planning_horizons=config_provider("planning_horizons"),
        cluster_heat_buses=config_provider("sector", "cluster_heat_buses"),
        modify_nuts3_shapes=config_provider("mods", "modify_nuts3_shapes"),
    message:
        "Recalibrating Austrian household and service heat demand against NEA data"
    script:
        scripts("pypsa-at/recalibrate_heat_demand_at.py")


rule modify_district_heat_share_at:
    input:
        urban_fraction_at=resources("urban_fraction_at.csv"),
        district_heat_share=resources("district_heat_share_{horizon}-modified.csv"),
    output:
        district_heat_share=resources("district_heat_share_{horizon}-modified_at.csv"),
    log:
        logs("modify_district_heat_share_at_{horizon}.log"),
    benchmark:
        benchmarks("modify_district_heat_share_at_{horizon}")
    threads: 1
    resources:
        mem_mb=1000,
    message:
        "Replacing Austrian urban fractions for one planning horizon."
    script:
        scripts("pypsa-at/modify_district_heat_share_at.py")


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
        params:
            planning_horizons=config_provider("planning_horizons"),
        message:
            "Building general Statistik Austria regional data CSV"
        script:
            scripts("pypsa-at/build_statistik_at_regions.py")


if KFZ_BESTAND_AT["source"] in ["primary", "archive"]:

    rule build_kfz_bestand_at:
        input:
            ods=rules.retrieve_kfz_bestand_at.output["ods"],
            regional_data=rules.build_statistik_at_regions.output["regional_data"],
            transport_data_in=resources("transport_data_raw.csv"),
        output:
            transport_data_out=resources("transport_data_raw_at.csv"),
        log:
            logs("build_kfz_bestand.log"),
        benchmark:
            benchmarks("build_kfz_bestand")
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
            "transport_data_raw": resources("transport_data_raw_at.csv"),
        },
    output:
        transport_demand=resources("transport_demand_at_unpatched.csv"),
        transport_data=resources("transport_data_at.csv"),
        avail_profile=resources("avail_profile_at.csv"),
        dsm_profile=resources("dsm_profile_at.csv"),
    log:
        logs("build_transport_demand_at.log"),
    benchmark:
        benchmarks("build_transport_demand_at")


rule patch_transport_demand_at:
    input:
        transport_demand=resources("transport_demand_at_unpatched.csv"),
        nea_at=resources("nea_at.csv"),
        temp_air_total=resources("temp_air_total.nc"),
        clustered_pop_layout=resources("pop_layout.csv"),
    output:
        transport_demand_patched=resources("transport_demand_at.csv"),
    log:
        logs("patch_transport_demand_at.log"),
    benchmark:
        benchmarks("patch_transport_demand_at")
    threads: 1
    resources:
        mem_mb=2000,
    params:
        planning_horizons=config_provider("planning_horizons"),
        source_years=config_provider("demand", "source_years"),
        sector=config_provider("sector"),
    message:
        "Patching transport demand using Statistik Austria Nutzenergieanalyse"
    script:
        scripts("pypsa-at/patch_transport_demand_at.py")
