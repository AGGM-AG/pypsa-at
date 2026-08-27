# SPDX-FileCopyrightText: 2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""
PyPSA-AT model layer modification rules.
"""

if OSM_DATASET["source"] == "build":

    rule build_osm_network_at:
        input:
            buses=resources("osm/build/buses.csv"),
            lines=resources("osm/build/lines.csv"),
            links=resources("osm/build/links.csv"),
            converters=resources("osm/build/converters.csv"),
            transformers=resources("osm/build/transformers.csv"),
            # Raw Overpass JSON carries the `operator` and unmodified `frequency`
            # tags that `clean_osm_data` drops and overwrites respectively.
            cables_way=expand(
                f"{OSM_DATASET['folder']}/{{country}}/cables_way.json",
                country=config_provider("countries"),
            ),
            lines_way=expand(
                f"{OSM_DATASET['folder']}/{{country}}/lines_way.json",
                country=config_provider("countries"),
            ),
            routes_relation=expand(
                f"{OSM_DATASET['folder']}/{{country}}/routes_relation.json",
                country=config_provider("countries"),
            ),
            substations_way=expand(
                f"{OSM_DATASET['folder']}/{{country}}/substations_way.json",
                country=config_provider("countries"),
            ),
            substations_relation=expand(
                f"{OSM_DATASET['folder']}/{{country}}/substations_relation.json",
                country=config_provider("countries"),
            ),
        output:
            buses=resources("osm/build-at/buses.csv"),
            lines=resources("osm/build-at/lines.csv"),
            links=resources("osm/build-at/links.csv"),
            converters=resources("osm/build-at/converters.csv"),
            transformers=resources("osm/build-at/transformers.csv"),
        log:
            logs("build_osm_network_at.log"),
        threads: 1
        resources:
            # Matches clean_osm_data, which parses the same raw JSON files.
            mem_mb=4000,
        message:
            "Filtering built OSM network for AT: removing cross-border lines below 220 kV and recovering OSM operators"
        script:
            scripts("pypsa-at/build_osm_network_at.py")

    # The Zenodo map must show the archive contents. resources/networks/base.nc
    # is corridor-filtered (filter_osm_lines_at), so the map gets its own base
    # network built from the unfiltered build-at files instead.
    def input_base_network_release(w):
        components = {"buses", "lines", "links", "converters", "transformers"}
        return {c: resources(f"osm/build-at/{c}.csv") for c in components}

    use rule base_network as base_network_release with:
        input:
            unpack(input_base_network_release),
            nuts3_shapes=resources("nuts3_shapes.geojson"),
            country_shapes=resources("country_shapes.geojson"),
            offshore_shapes=resources("offshore_shapes.geojson"),
            europe_shape=resources("europe_shape.geojson"),
        output:
            base_network=resources("osm/build-at/networks/base.nc"),
            regions_onshore=resources("osm/build-at/networks/regions_onshore.geojson"),
            regions_offshore=resources("osm/build-at/networks/regions_offshore.geojson"),
            admin_shapes=resources("osm/build-at/networks/admin_shapes.geojson"),
        log:
            logs("base_network_release.log"),
        benchmark:
            benchmarks("base_network_release")
        message:
            "Building unfiltered base network of the AT OSM archive for the release map"

    rule map_osm_network_at:
        input:
            base_network=resources("osm/build-at/networks/base.nc"),
        output:
            map=resources("osm/build-at/map.html"),
        log:
            logs("map_osm_network_at.log"),
        threads: 1
        resources:
            mem_mb=4000,
        params:
            line_types=config["lines"]["types"],
            # Shown in the map title; bump together with the Zenodo release.
            release_version="0.3-at",
            include_polygons=False,
            export=False,
        message:
            "Preparing interactive map of the AT OSM archive for the Zenodo release."
        script:
            scripts("prepare_osm_network_release.py")


def osm_at_component(component):
    """Path of one AT OSM component CSV, for either data source.

    ``build`` reads the freshly built ``resources/osm/build-at/`` files,
    ``archive`` the retrieved ``data/osm/archive/{version}/`` files.
    """
    if OSM_DATASET["source"] == "build":
        return resources(f"osm/build-at/{component}.csv")
    return f"{OSM_DATASET['folder']}/{component}.csv"


rule filter_osm_lines_at:
    input:
        lines=osm_at_component("lines"),
        buses=osm_at_component("buses"),
        nuts3_shapes=resources("nuts3_shapes.geojson"),
        electricity_network_overrides="data/pypsa-at/electricity_network_overrides.csv",
    output:
        lines=resources("osm/model/lines.csv"),
        buses=resources("osm/model/buses.csv"),
        report=resources("osm/model/line_rules.csv"),
    log:
        logs("filter_osm_lines_at.log"),
    threads: 1
    resources:
        mem_mb=2000,
    message:
        "Filtering inter-regional 110 kV corridors from the AT OSM lines"
    script:
        scripts("pypsa-at/filter_osm_lines_at.py")


def input_base_network_at(w):
    """Route the base network onto the corridor-filtered AT OSM files.

    Lines and buses come from ``filter_osm_lines_at``, which also strips the
    archive provenance columns (they crash the clustering aggregation); the
    remaining components are passed through from the configured OSM data
    source unchanged.

    Redefining upstream ``input_base_network()`` does not work: the
    ``base_network`` rule captures the function object at parse time, long
    before this file is included. The rule itself is therefore shadowed
    below via ``use rule`` + ``ruleorder``, mirroring the
    ``modify_prenetwork_at`` pattern.

    Parameters
    ----------
    w:
        The Snakemake workflow wildcards object. Unused.

    Returns
    -------
    :
        A dictionary with component names as keys and Paths as values.
    """
    components = {"links", "converters", "transformers"}
    inputs = {c: osm_at_component(c) for c in components}
    inputs["lines"] = resources("osm/model/lines.csv")
    inputs["buses"] = resources("osm/model/buses.csv")
    return inputs


use rule base_network as base_network_at with:
    input:
        unpack(input_base_network_at),
        nuts3_shapes=resources("nuts3_shapes.geojson"),
        country_shapes=resources("country_shapes.geojson"),
        offshore_shapes=resources("offshore_shapes.geojson"),
        europe_shape=resources("europe_shape.geojson"),
    message:
        "Building base network from the corridor-filtered AT OSM dataset"


ruleorder: base_network_at > base_network


rule modify_nuts3_shapes:
    input:
        nuts3_shapes=resources("nuts3_shapes-raw.geojson"),
    output:
        nuts3_shapes=resources("nuts3_shapes.geojson"),
    log:
        logs("modify_nuts3_shapes.log"),
    threads: 1
    resources:
        mem_mb=1500,
    params:
        clustering=config_provider("clustering", "mode"),
        admin_levels=config_provider("clustering", "administrative"),
    script:
        scripts("pypsa-at/modify_nuts3_shapes.py")


# modify_prenetwork: keep the upstream pypsa-de rule pristine and shadow it here
# to inject the AT-specific inputs (KLIEN potentials, TYNDP trajectories, Ukrainian
# gas transit) and params. The `**rules.modify_prenetwork.input/params` splats pull
# in all upstream directives; only the AT additions are listed.
use rule modify_prenetwork as modify_prenetwork_at with:
    input:
        **rules.modify_prenetwork.input,
        tyndp_trajectories=branch(
            config_provider("mods", "PEMMDB_trajectories", "enable"),
            resources("tyndp_trajectories.csv"),
            [],
        ),
        tyndp_transmission_trajectories=branch(
            config_provider("mods", "tyndp_lower_bounds", "enable"),
            resources("tyndp_transmission_trajectories.csv"),
            [],
        ),
        nuts3_buildings=f"{KLIEN_POTENTIALS['folder']}/nuts3_pv_buildings.csv",
        nuts3_ground=f"{KLIEN_POTENTIALS['folder']}/nuts3_pv_ground.csv",
        nuts3_wind=f"{KLIEN_POTENTIALS['folder']}/nuts3_wind.csv",
        gas_input_nodes_simplified=resources(
            "gas_input_locations_s_{clusters}_simplified.csv"
        ),
        gas_storage_capacities="data/pypsa-at/gas_input_locations_s_AT35DE16_updated.csv",
        h2_imports_tyndp=branch(
            config_provider("sector", "h2_topology_tyndp"),
            resources("h2_import_potentials_{clusters}_{planning_horizons}.csv"),
            [],
        ),
        heat_demand_nea_at=branch(
            config_provider("demand", "heat", "apply_at_demand"),
            resources("heat_demand_nea_at_{clusters}.csv"),
            [],
           ),
    params:
        **rules.modify_prenetwork.params,
        klien_potential_limits_technologies=config_provider(
            "mods", "klien_potential_limits", "technologies"
        ),
        klien_potential_limits_use_technical_potentials=config_provider(
            "mods", "klien_potential_limits", "use_technical_potentials"
        ),
        klien_potential_limits_climate_scenario=config_provider(
            "mods", "klien_potential_limits", "climate_scenario"
        ),
        klien_potential_limits_year=config_provider(
            "mods", "klien_potential_limits", "year"
        ),
        klien_potential_limits_ambition=config_provider(
            "mods", "klien_potential_limits", "ambition"
        ),
        block_russian_gas_imports=config_provider("mods", "block_russian_gas_imports"),
        sector=config_provider("sector"),
        admin_levels=config_provider("clustering", "administrative"),
        custom_clustering=config_provider("mods", "modify_nuts3_shapes"),
        apply_at_heat_demand=config_provider("demand", "heat", "apply_at_demand"),


ruleorder: modify_prenetwork_at > modify_prenetwork  # AT wins for the final .nc


rule modify_brownfield_gas_network_AT:
    input:
        clustered_gas_network_raw=resources("gas_network_base_s_{clusters}_raw.csv"),
        brownfield_gas_network_AT10=("data/pypsa-at/AGGM_gas_network_base_AT10.csv"),
        brownfield_gas_network_AT35=("data/pypsa-at/AGGM_gas_network_base_AT35.csv"),
    output:
        clustered_gas_network=resources("gas_network_base_s_{clusters}.csv"),
    log:
        logs("modify_brownfield_gas_network_AT_{clusters}.log"),
    resources:
        mem_mb=4000,
    script:
        scripts("pypsa-at/modify_brownfield_gas_network_AT.py")


# --- Upstream rule overrides -------------------------------------------------
# Upstream rules are kept pristine (identical to pypsa-de). Instead of editing
# them, we shadow them here so AT can intercept their outputs:
#   use rule X as X_at with:   inherit X's directives, change only what AT needs
#   ruleorder: X_at > X        when both rules could produce the same file, AT wins
# The reverted upstream rule still exists but is fully shadowed and never runs.
#
# Pattern used below: rename an upstream rule's output to a "*-raw"/"*_raw"
# file, then let a dedicated modify_* rule (defined above) transform raw -> final.


# build_shapes: redirect nuts3_shapes to a "-raw" file so modify_nuts3_shapes
# can post-process it into the final nuts3_shapes.geojson. The dict-literal merge
# overrides just that one output path; the other shape outputs are inherited.
use rule build_shapes as build_shapes_at with:
    output:
        **{
            **rules.build_shapes.output,
            "nuts3_shapes": resources("nuts3_shapes-raw.geojson"),
        },


ruleorder: build_shapes_at > build_shapes  # AT wins for the shared shape outputs


ruleorder: modify_nuts3_shapes > build_shapes  # AT wins for the final nuts3_shapes.geojson


# cluster_gas_network: redirect the clustered gas network to a "_raw" file so
# modify_brownfield_gas_network_AT can merge in the AGGM brownfield network.
use rule cluster_gas_network as cluster_gas_network_at with:
    output:
        clustered_gas_network=resources("gas_network_base_s_{clusters}_raw.csv"),


ruleorder: modify_brownfield_gas_network_AT > cluster_gas_network  # AT wins for the final .csv


# Overwrite attributes in the power plants resource CSV file
rule overwrite_powerplants_at:
    input:
        powerplants=resources("powerplants_s_{clusters}.csv"),
        anlagenregister="data/pypsa-at/Anlagenregister_electricity_from_renewable_gas_AT.csv",
        postal_to_nuts="data/pypsa-at/AT-Postal-to-NUTS.csv",
    output:
        powerplants=resources("powerplants_s_{clusters}-overwrite.csv"),
    log:
        logs("powerplants_s_{clusters}-overwrite.log"),
    threads: 1
    resources:
        mem_mb=1000,
    params:
        add_biogas_to_power_plants_AT=config_provider(
            "mods", "existing_capacities", "add_biogas_to_power_plants_AT"
        ),
        threshold_capacity=config_provider("existing_capacities", "threshold_capacity"),
        clustering=config_provider("mods", "modify_nuts3_shapes"),
    message:
        "Overriding power plant attributes for {wildcards.clusters} clusters."
    script:
        scripts("pypsa-at/overwrite_powerplants.py")


if config["foresight"] == "myopic":

    # redirect powerplants input file to the patched file
    use rule add_existing_baseyear as add_existing_baseyear_at with:
        input:
            **{
                **rules.add_existing_baseyear.input,
                "powerplants": resources("powerplants_s_{clusters}-overwrite.csv"),
            },

    ruleorder: add_existing_baseyear_at > add_existing_baseyear
    # The new rule also needs to override `add_brownfield` instead of
    # `add_existing_baseyear` for myopic years
    ruleorder: add_existing_baseyear_at > add_brownfield
