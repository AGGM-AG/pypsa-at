# SPDX-FileCopyrightText: 2025-2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""
Build rules for Open-TYNDP derived data products.

Covers the full build_tyndp_* and clean_tyndp_* pipeline vendored from
open-tyndp into scripts/open-tyndp/. All rules reference
rules.retrieve_open_tyndp.output.* (AT retrieve rule).

Unconditional rules:
  build_pemmdb_data, build_tyndp_trajectories, build_tyndp_gas_demand,
  build_tyndp_h2_demand, clean_tyndp_hydro_inflows, build_tyndp_hydro_profile,
  build_tyndp_transmission_projects

Conditional on sector.h2_topology_tyndp:
  build_tyndp_h2_network, clean_tyndp_h2_storages

Conditional on sector.offshore_hubs_tyndp:
  build_tyndp_offshore_hubs

Conditional on sector coupling (either flag):
  clean_tyndp_h2_imports, build_tyndp_h2_imports, clean_tyndp_smr
"""

# safe_pyear is used in _input_hydro_inflows below.
from scripts._tyndp_helpers import safe_pyear


def _pemmdb_techs(w):
    if config_provider("electricity", "pemmdb_capacities", "enable")(w):
        return config_provider("electricity", "pemmdb_capacities", "technologies")(w)
    return []


rule build_pemmdb_data:
    input:
        pemmdb_dir=rules.retrieve_open_tyndp.output.pemmdb,
        carrier_mapping="data/pypsa-at/tyndp_technology_map.csv",
    output:
        pemmdb_capacities=resources("pemmdb_capacities_{planning_horizons}.csv"),
        pemmdb_profiles=resources("pemmdb_profiles_{planning_horizons}.nc"),
    log:
        logs("build_pemmdb_data_{planning_horizons}.log"),
    benchmark:
        benchmarks("build_pemmdb_data/{planning_horizons}")
    threads: config_provider("electricity", "pemmdb_capacities", "nprocesses", default=4)
    resources:
        mem_mb=16000,
    params:
        pemmdb_techs=_pemmdb_techs,
        snapshots=config_provider("snapshots"),
        drop_leap_day=config_provider("enable", "drop_leap_day"),
        available_years=config_provider(
            "electricity", "pemmdb_capacities", "available_years"
        ),
        tyndp_scenario=config_provider("mods", "PEMMDB_trajectories", "tyndp_scenario"),
        countries=config_provider("countries"),
    message:
        "Building PEMMDB v2.4 capacity table and hourly profiles for {wildcards.planning_horizons}"
    script:
        scripts("open-tyndp/build_pemmdb_data.py")


rule build_tyndp_gas_demand:
    input:
        supply_tool=rules.retrieve_open_tyndp.output.supply_tool,
    output:
        gas_demand=resources("gas_demand_tyndp_{planning_horizons}.csv"),
    log:
        logs("build_tyndp_gas_demand_{planning_horizons}.log"),
    benchmark:
        benchmarks("build_tyndp_gas_demand/{planning_horizons}")
    threads: 1
    resources:
        mem_mb=1000,
    params:
        scenario=config_provider("mods", "tyndp_scenario"),
        planning_horizons=config_provider("scenario", "planning_horizons"),
    message:
        "Building TYNDP gas demand for {wildcards.planning_horizons}"
    script:
        scripts("open-tyndp/build_tyndp_gas_demand.py")


rule build_tyndp_h2_demand:
    input:
        h2_demand=rules.retrieve_open_tyndp.output.demand_profiles,
    output:
        h2_demand=resources("h2_demand_tyndp_{planning_horizons}.csv"),
    log:
        logs("build_tyndp_h2_demand_{planning_horizons}.log"),
    benchmark:
        benchmarks("build_tyndp_h2_demand/{planning_horizons}")
    threads: 1
    resources:
        mem_mb=1000,
    params:
        snapshots=config_provider("snapshots"),
        drop_leap_day=config_provider("enable", "drop_leap_day"),
        scenario=config_provider("mods", "tyndp_scenario"),
    message:
        "Building TYNDP H2 demand for {wildcards.planning_horizons}"
    script:
        scripts("open-tyndp/build_tyndp_h2_demand.py")


def _input_hydro_inflows(w):
    """Collect hydro inflow intermediate files across safe years and technologies."""
    available_years = config_provider(
        "electricity", "pemmdb_hydro_profiles", "available_years"
    )(w)
    technologies = config_provider(
        "electricity", "pemmdb_hydro_profiles", "technologies"
    )(w)
    planning_horizons = config_provider("scenario", "planning_horizons")(w)
    safe_years = {safe_pyear(int(y), available_years) for y in planning_horizons}
    return {
        f"hydro_inflows_{tech}_{year}": resources(
            f"hydro_inflows_tyndp_{tech}_{year}.csv"
        )
        for year in safe_years
        for tech in technologies
    }


rule clean_tyndp_hydro_inflows:
    input:
        hydro_inflows_dir=rules.retrieve_open_tyndp.output.hydro_inflows,
        busmap=resources("busmap_base_s_all.csv"),
    output:
        hydro_inflows_tyndp="resources/hydro_inflows_tyndp_{tech}_{planning_horizons}.csv",
    log:
        "logs/clean_tyndp_hydro_inflows_{tech}_{planning_horizons}.log",
    benchmark:
        "benchmarks/clean_tyndp_hydro_inflows/{tech}_{planning_horizons}"
    threads: 1
    resources:
        mem_mb=2000,
    params:
        snapshots=config_provider("snapshots"),
        drop_leap_day=config_provider("enable", "drop_leap_day"),
        available_years=config_provider(
            "electricity", "pemmdb_hydro_profiles", "available_years"
        ),
    message:
        "Preprocessing TYNDP hydro inflows for {wildcards.tech} / {wildcards.planning_horizons}"
    script:
        scripts("open-tyndp/clean_tyndp_hydro_inflows.py")


rule build_tyndp_hydro_profile:
    input:
        unpack(_input_hydro_inflows),
        carrier_mapping="data/pypsa-at/tyndp_technology_map.csv",
    output:
        profile=resources("profile_pemmdb_hydro.nc"),
    log:
        logs("build_tyndp_hydro_profile.log"),
    benchmark:
        benchmarks("build_tyndp_hydro_profile")
    resources:
        mem_mb=5000,
    params:
        snapshots=config_provider("snapshots"),
        drop_leap_day=config_provider("enable", "drop_leap_day"),
        planning_horizons=config_provider("scenario", "planning_horizons"),
        available_years=config_provider(
            "electricity", "pemmdb_hydro_profiles", "available_years"
        ),
        technologies=config_provider(
            "electricity", "pemmdb_hydro_profiles", "technologies"
        ),
    message:
        "Building TYNDP hydro inflow profile"
    script:
        scripts("open-tyndp/build_tyndp_hydro_profile.py")


rule build_tyndp_transmission_projects:
    input:
        buses_elec=rules.build_tyndp_network.output.substations_geojson,
        buses_h2=rules.build_tyndp_network.output.substations_h2_geojson,
        invest_grid=rules.retrieve_open_tyndp.output.invest_grid,
    output:
        new_links_elec=resources("tyndp/new_links_{planning_horizons}.csv"),
        new_links_h2=resources("tyndp/new_links_h2_{planning_horizons}.csv"),
    log:
        logs("build_tyndp_transmission_projects_{planning_horizons}.log"),
    benchmark:
        benchmarks("build_tyndp_transmission_projects/{planning_horizons}")
    threads: 1
    resources:
        mem_mb=1000,
    params:
        build_years_elec=config_provider("tyndp_investment_candidates", "elec_projects"),
        build_years_h2=config_provider("tyndp_investment_candidates", "h2_projects"),
    message:
        "Building TYNDP transmission investment projects for {wildcards.planning_horizons}"
    script:
        scripts("open-tyndp/build_tyndp_transmission_projects.py")


rule build_tyndp_transmission_trajectories:
    input:
        invest_grid=rules.retrieve_open_tyndp.output.invest_grid,
        elec_reference_grid=rules.retrieve_open_tyndp.output.elec_reference_grid,
    output:
        tyndp_transmission_trajectories=resources("tyndp_transmission_trajectories.csv"),
    log:
        logs("build_tyndp_transmission_trajectories.log"),
    benchmark:
        benchmarks("build_tyndp_transmission_trajectories")
    threads: 1
    resources:
        mem_mb=1000,
    params:
        admin_levels=config_provider("clustering", "administrative"),
        custom_clustering=config_provider("mods", "modify_nuts3_shapes"),
    message:
        "Building TYNDP transmission capacity trajectories"
    script:
        scripts("pypsa-at/build_tyndp_transmission_trajectories.py")


if config.get("sector", {}).get("h2_topology_tyndp", False):

    rule build_tyndp_h2_network:
        input:
            h2_reference_grid=rules.retrieve_open_tyndp.output.h2_reference_grid,
        output:
            h2_grid_prepped=resources("h2_reference_grid_tyndp_{planning_horizons}.csv"),
            interzonal_prepped=resources("h2_interzonal_tyndp_{planning_horizons}.csv"),
        log:
            logs("build_tyndp_h2_network_{planning_horizons}.log"),
        benchmark:
            benchmarks("build_tyndp_h2_network/{planning_horizons}")
        threads: 1
        resources:
            mem_mb=4000,
        params:
            snapshots=config_provider("snapshots"),
            scenario=config_provider("mods", "tyndp_scenario"),
        message:
            "Building TYNDP H2 network for {wildcards.planning_horizons}"
        script:
            scripts("open-tyndp/build_tyndp_h2_network.py")

    rule clean_tyndp_h2_storages:
        input:
            h2_storages=rules.retrieve_open_tyndp.output.h2_storages,
        output:
            h2_storages_prepped=resources("h2_storages_prepped_{planning_horizons}.csv"),
        log:
            logs("clean_tyndp_h2_storages_{planning_horizons}.log"),
        benchmark:
            benchmarks("clean_tyndp_h2_storages/{planning_horizons}")
        threads: 1
        resources:
            mem_mb=2000,
        message:
            "Preprocessing TYNDP H2 storages for {wildcards.planning_horizons}"
        script:
            scripts("open-tyndp/clean_tyndp_h2_storages.py")

    rule clean_tyndp_h2_imports:
        input:
            import_potentials_raw=rules.retrieve_open_tyndp.output.h2_imports,
            countries_centroids="data/countries_centroids.geojson",
        output:
            import_potentials_prepped=resources("h2_import_potentials_prepped.csv"),
        log:
            logs("clean_tyndp_h2_imports.log"),
        benchmark:
            benchmarks("clean_tyndp_h2_imports")
        threads: 1
        resources:
            mem_mb=2000,
        message:
            "Preprocessing TYNDP H2 import potentials"
        script:
            scripts("open-tyndp/clean_tyndp_h2_imports.py")

    rule build_tyndp_h2_imports:
        input:
            import_potentials_prepped=rules.clean_tyndp_h2_imports.output.import_potentials_prepped,
            busmap=resources("busmap_base_s_{clusters}.csv"),
        output:
            h2_import_potentials=resources(
                "h2_import_potentials_{clusters}_{planning_horizons}.csv"
            ),
        log:
            logs("build_tyndp_h2_imports_{clusters}_{planning_horizons}.log"),
        benchmark:
            benchmarks("build_tyndp_h2_imports/{clusters}_{planning_horizons}")
        threads: 1
        resources:
            mem_mb=2000,
        params:
            scenario=config_provider("mods", "tyndp_h2_import_scenario"),
            countries=config_provider("countries"),
            admin_levels=config_provider("clustering", "administrative"),
        message:
            "Building TYNDP H2 import capacities for {wildcards.planning_horizons}"
        script:
            scripts("open-tyndp/build_tyndp_h2_imports.py")

    rule clean_tyndp_smr:
        input:
            smr=rules.retrieve_open_tyndp.output.smr,
        output:
            smr_prepped=resources("smr_data_prepped_{planning_horizons}.csv"),
        log:
            logs("clean_tyndp_smr_{planning_horizons}.log"),
        benchmark:
            benchmarks("clean_tyndp_smr/{planning_horizons}")
        threads: 1
        resources:
            mem_mb=2000,
        params:
            tyndp_scenario=config_provider(
                "mods", "PEMMDB_trajectories", "tyndp_scenario"
            ),
        message:
            "Preprocessing TYNDP SMR data for {wildcards.planning_horizons}"
        script:
            scripts("open-tyndp/clean_tyndp_smr.py")


if config.get("sector", {}).get("offshore_hubs_tyndp", False):

    rule build_tyndp_offshore_hubs:
        input:
            nodes=rules.retrieve_open_tyndp.output.offshore_nodes,
            grid=rules.retrieve_open_tyndp.output.offshore_grid,
            electrolysers=rules.retrieve_open_tyndp.output.offshore_electrolysers,
            generators=rules.retrieve_open_tyndp.output.offshore_generators,
        output:
            offshore_buses=resources("offshore_buses.csv"),
            offshore_grid=resources("offshore_grid.csv"),
            offshore_electrolysers=resources("offshore_electrolysers.csv"),
            offshore_generators=resources("offshore_generators.csv"),
            offshore_zone_trajectories=resources("offshore_zone_trajectories.csv"),
        log:
            logs("build_tyndp_offshore_hubs.log"),
        benchmark:
            benchmarks("build_tyndp_offshore_hubs")
        threads: 1
        resources:
            mem_mb=4000,
        params:
            planning_horizons=config_provider("scenario", "planning_horizons"),
            scenario=config_provider("mods", "tyndp_scenario"),
            countries=config_provider("countries"),
            offshore_hubs_tyndp=config_provider("sector", "offshore_hubs_tyndp"),
            extendable_carriers=config_provider("electricity", "extendable_carriers"),
            h2_zones_tyndp=config_provider("sector", "h2_zones_tyndp"),
        message:
            "Building TYNDP offshore hub topology"
        script:
            scripts("open-tyndp/build_tyndp_offshore_hubs.py")
