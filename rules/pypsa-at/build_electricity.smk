# SPDX-FileCopyrightText: 2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""
PyPSA-AT electricity build rules.

Overrides of upstream rules in ``rules/build_electricity.smk`` and AT-specific
electricity datasets (OSM network, NUTS3 shapes, power plants, hydro inflow,
costs, capacity trajectories).
"""


use rule process_cost_data as process_cost_data_at with:
    input:
        **{
            **rules.process_cost_data.input,
            "custom_costs": resources("custom_cost_at.csv"),
        },


ruleorder: process_cost_data_at > process_cost_data


# powerplantmatching 0.8.x tags the large German lignite condensing units
# Set="CHP", which the inherited PyPSA-DE powerplants_filter then drops. See
# scripts/pypsa-at/patch_powerplants_set_at.py for the full rationale.
rule patch_powerplants_set_at:
    input:
        powerplants=rules.retrieve_powerplants.output["powerplants"],
    output:
        powerplants=resources_shared("powerplants_set_patched.csv"),
    log:
        logs_shared("patch_powerplants_set_at.log"),
    threads: 1
    resources:
        mem_mb=2000,
    message:
        "Restoring Set=PP on the large German lignite condensing units"
    script:
        scripts("pypsa-at/patch_powerplants_set_at.py")


use rule build_powerplants as build_powerplants_at with:
    input:
        **{
            **rules.build_powerplants.input,
            "powerplants": rules.patch_powerplants_set_at.output["powerplants"],
        },


ruleorder: build_powerplants_at > build_powerplants


rule create_onshore_regions_nuts3:
    input:
        regions=resources("onshore_regions.geojson"),
        shapes=resources("nuts3_shapes.geojson"),
    output:
        regions_nuts3=resources("onshore_regions_nuts3.geojson"),
    log:
        logs("create_onshore_regions_nuts3.log"),
    benchmark:
        benchmarks("create_onshore_regions_nuts3")
    threads: 1
    message:
        "Building NUTS3 onshore regions geojson"
    script:
        scripts("pypsa-at/create_onshore_regions_nuts3.py")


use rule determine_availability_matrix as determine_availability_matrix_onwind_nuts3 with:
    input:
        **{
            **rules.determine_availability_matrix.input,
            "regions": resources("onshore_regions_nuts3.geojson"),
        },
    output:
        nc=resources("availability_matrix_nuts3_{technology}.nc"),
        plot=branch(
            config["atlite"]["plot_availability_matrix"],
            then=resources("availability_matrix_nuts3_{technology}.png"),
        ),
    log:
        logs("determine_availability_matrix_nuts3_{technology}.log"),
    benchmark:
        benchmarks("determine_availability_matrix_nuts3_{technology}")
    wildcard_constraints:
        technology="onwind",
    message:
        "Determining availability matrix for {wildcards.technology} technology for nuts3"


# Without the {clusters} wildcard, upstream's availability_matrix_{technology}
# and profile_{technology} patterns also match the NUTS3 files
# (technology=nuts3_onwind). The AT rules must win for these files.
ruleorder: determine_availability_matrix_onwind_nuts3 > determine_availability_matrix


use rule build_renewable_profiles as build_renewable_profiles_onwind_nuts3 with:
    input:
        **{
            **rules.build_renewable_profiles.input,
            "availability_matrix": resources(
                "availability_matrix_nuts3_{technology}.nc"
            ),
            "distance_regions": resources("onshore_regions_nuts3.geojson"),
            "resource_regions": resources(
                "onshore_regions_nuts3.geojson"  # Input needed by original rule
            ),
        },
    output:
        **{
            **rules.build_renewable_profiles.output,
            "profile": resources("profile_nuts3_{technology}.nc"),
            "class_regions": resources("regions_by_class_nuts3_{technology}.geojson"),
        },
    log:
        logs("build_renewable_profile_nuts3_{technology}.log"),
    benchmark:
        benchmarks("build_renewable_profile_nuts3_{technology}")
    wildcard_constraints:
        technology="onwind",
    message:
        "Building NUTS3 renewable profiles for onwind technology"


ruleorder: build_renewable_profiles_onwind_nuts3 > build_renewable_profiles


def use_klien_onwind(w):
    """Whether the run clusters Austria at NUTS2, where KLIEN weights apply.

    Evaluated per scenario, so runs with different (custom) clusterings can
    share one workflow. ``mods.modify_nuts3_shapes`` AT10* implies NUTS2.
    """
    mode = config_provider("clustering", "mode")(w)
    admin_levels = config_provider("clustering", "administrative")(w)
    return mode == "administrative" and admin_levels.get("AT") == 2


# The upstream onwind profile is written to a "-raw" file. The KLIEN rule
# below turns it into the final profile: KLIEN-weighted NUTS3 profiles for
# Austria at NUTS2, otherwise an unchanged copy.
use rule build_renewable_profiles as build_renewable_profiles_onwind_raw with:
    output:
        **{
            **rules.build_renewable_profiles.output,
            "profile": resources("profile_{technology}-raw.nc"),
            "class_regions": resources("regions_by_class_{technology}.geojson"),
        },
    log:
        logs("build_renewable_profile_{technology}-raw.log"),
    benchmark:
        benchmarks("build_renewable_profile_{technology}-raw")
    wildcard_constraints:
        technology="onwind",
    message:
        "Building raw renewable profiles for onwind technology"


ruleorder: build_renewable_profiles_onwind_raw > build_renewable_profiles


rule build_renewable_profiles_onwind_klien:
    input:
        profile_raw=resources("profile_{technology}-raw.nc"),
        profile_nuts3=branch(
            use_klien_onwind, resources("profile_nuts3_{technology}.nc"), []
        ),
        klien_wind=branch(
            use_klien_onwind, f"{KLIEN_POTENTIALS['folder']}/nuts3_wind.csv", []
        ),
    output:
        profile=resources("profile_{technology}.nc"),
    log:
        logs("build_renewable_profile_{technology}_klien.log"),
    benchmark:
        benchmarks("build_renewable_profile_{technology}_klien")
    wildcard_constraints:
        technology="onwind",
    params:
        apply_klien=use_klien_onwind,
    message:
        "Applying KLIEN-weighted NUTS3 onwind profiles where Austria is at NUTS2"
    script:
        scripts("pypsa-at/build_renewable_profiles_onwind_klien.py")


ruleorder: build_renewable_profiles_onwind_klien > build_renewable_profiles


# --- AT OSM network, base network and NUTS3 shapes ---------------------------


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
            onshore_regions=resources("osm/build-at/networks/regions_onshore.geojson"),
            offshore_regions=resources("osm/build-at/networks/regions_offshore.geojson"),
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
    ``compose_network_at`` pattern.

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


# --- Upstream rule overrides -------------------------------------------------
# Upstream rules are kept pristine (identical to pypsa-de). Instead of editing
# them, we shadow them here so AT can intercept their outputs:
#   use rule X as X_at with:   inherit X's directives, change only what AT needs
#   ruleorder: X_at > X        when both rules could produce the same file, AT wins
# The reverted upstream rule still exists but is fully shadowed and never runs.
#
# Pattern used below: rename an upstream rule's output to a "*-raw"/"*_raw"
# file, then let a dedicated modify_* rule transform raw -> final.


# build_nuts3_shapes: redirect nuts3_shapes to a "-raw" file so modify_nuts3_shapes
# can post-process it into the final nuts3_shapes.geojson.
use rule build_nuts3_shapes as build_nuts3_shapes_at with:
    output:
        nuts3_shapes=resources("nuts3_shapes-raw.geojson"),


ruleorder: build_nuts3_shapes_at > build_nuts3_shapes  # AT wins for the raw shapes


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
        custom_clustering=config_provider("mods", "modify_nuts3_shapes"),
        run_prefix=config_provider("run", "prefix"),
    script:
        scripts("pypsa-at/modify_nuts3_shapes.py")


ruleorder: modify_nuts3_shapes > build_nuts3_shapes  # AT wins for the final nuts3_shapes.geojson


# Overwrite attributes in the power plants resource CSV file
rule overwrite_powerplants_at:
    input:
        powerplants=resources("powerplants.csv"),
        anlagenregister=f"{ANLAGENREGISTER['folder']}/anlagenregister_plants.csv",
        postal_to_nuts="data/pypsa-at/AT-Postal-to-NUTS.csv",
    output:
        powerplants=resources("powerplants-overwrite.csv"),
        biogas_plants=resources("biogas_plants_at.csv"),
    log:
        logs("powerplants-overwrite.log"),
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
        "Overriding power plant attributes."
    script:
        scripts("pypsa-at/overwrite_powerplants.py")


# --- AT electricity datasets -------------------------------------------------


def at_cost_year(w):
    """Cost year for AT power plant aggregation in rules without a horizon.

    Upstream changed ``costs.year`` to default to the requested horizon. The
    AT rules below have no ``{horizon}`` wildcard, so they keep the former
    default and use the last planning horizon unless ``costs.year`` is set.
    """
    return (
        config_provider("costs", "year")(w)
        or config_provider("planning_horizons")(w)[-1]
    )


def use_energiemosaik(w):
    """Whether the Energiemosaik key is configured (the archive is CC BY-NC-SA)."""
    key = config_provider("mods", "electricity_base_load", "distribution_key")(w)
    return key == "energiemosaik"


rule build_electricity_base_load_at:
    input:
        nea_at=resources("nea_at.csv"),
        industrial_distribution_key=resources("industrial_distribution_key.csv"),
        statistik_at_regions=resources("statistik_at_regions.csv"),
        energiemosaik=branch(
            use_energiemosaik,
            f"{ENERGIEMOSAIK_AT['folder']}/Energiemosaik_Datenpaket_AT.zip",
            [],
        ),
        code_files=[
            "mods/demand/electricity.py",
            "mods/clustering/utils.py",
        ],
    output:
        electricity_base_load=resources("electricity_base_load_at.csv"),
    log:
        logs("build_electricity_base_load_at.log"),
    benchmark:
        benchmarks("build_electricity_base_load_at")
    threads: 1
    resources:
        mem_mb=2000,
    params:
        planning_horizons=config_provider("planning_horizons"),
        source_years=config_provider("demand", "source_years"),
        distribution_key=config_provider(
            "mods", "electricity_base_load", "distribution_key"
        ),
        clustering=config_provider("mods", "modify_nuts3_shapes"),
    message:
        "Building the Austrian base electricity load table from NEA and regional keys"
    script:
        scripts("pypsa-at/build_electricity_base_load_at.py")


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
        regions=resources("onshore_regions.geojson"),
    output:
        profile=resources("profile_inflow.nc"),
    log:
        logs("build_inflow_profile.log"),
    benchmark:
        benchmarks("build_inflow_profile")
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
            powerplants=resources("powerplants.csv"),
            hydro_inflows=f"{OPEN_TYNDP_DATASET['folder']}/Hydro Inflows",
            costs=lambda w: resources(f"costs_{at_cost_year(w)}_processed.csv"),
        output:
            totals=resources("inflow_totals_per_region.csv"),
        log:
            logs("inflow_totals_per_region.log"),
        benchmark:
            benchmarks("inflow_totals_per_region")
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
        profile=resources("profile_inflow.nc"),
        totals=resources("inflow_totals_per_region.csv"),
    output:
        inflow=resources("inflow_per_region.nc"),
    log:
        logs("build_inflows_per_region.log"),
    benchmark:
        benchmarks("build_inflows_per_region")
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
        powerplants=resources("powerplants.csv"),
        costs=lambda w: resources(f"costs_{at_cost_year(w)}_processed.csv"),
    output:
        trajectories=resources("trajectories.csv"),
    log:
        logs("trajectories.log"),
    benchmark:
        benchmarks("trajectories")
    resources:
        mem_mb=5000,
    params:
        countries=config_provider("countries"),
        planning_horizons=config_provider("planning_horizons"),
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


if ANLAGENREGISTER["source"] in ("build", "archive"):

    rule build_anlagenregister_at:
        input:
            plants=f"{ANLAGENREGISTER['folder']}/anlagenregister_plants.csv",
            postal_to_nuts="data/pypsa-at/AT-Postal-to-NUTS.csv",
        output:
            nuts3=f"{ANLAGENREGISTER['folder']}/anlagenregister_nuts3.csv",
        log:
            logs_shared("build_anlagenregister_at.log"),
        benchmark:
            benchmarks_shared("build_anlagenregister_at")
        threads: 1
        resources:
            mem_mb=4000,
        message:
            "Aggregating E-Control Anlagenregister plants to NUTS3"
        script:
            scripts("pypsa-at/build_anlagenregister_at.py")


rule build_onwind_brownfield_at:
    input:
        wind_production=f"{WIND_POWER_AT['folder']}/wind_prodction_at.xlsx",
        nuts3_wind=f"{KLIEN_POTENTIALS['folder']}/nuts3_wind.csv",
        costs=lambda w: resources(
            f"costs_{config_provider('planning_horizons',0)(w)}_processed.csv"
        ),
        at_regions=resources("statistik_at_regions.csv"),
    output:
        wind_brownfield=resources("onwind_brownfield_at.csv"),
    log:
        logs("onwind_brownfield_at.log"),
    benchmark:
        benchmarks("onwind_brownfield_at")
    threads: 1
    resources:
        mem_mb=2000,
    params:
        admin_levels=config_provider("clustering", "administrative"),
    message:
        "Building at onwind brownfield capacities"
    script:
        scripts("pypsa-at/build_onwind_brownfield_at.py")
