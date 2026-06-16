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
            mem_mb=2000,
        message:
            "Filtering built OSM network for AT: removing cross-border lines below 220 kV"
        script:
            scripts("pypsa-at/build_osm_network_at.py")

    def input_base_network(w):
        """Updates the input network to pick up filtered files.

        Patches ``input_base_network()`` in ``rules.build_electricity.smk``.

        Parameters
        ----------
        w:
            The Snakemake workflow wildcards object. Only used in upstream
            function.

        Returns
        -------
        :
            A dictionary with component names as keys and Paths as values.
        """
        components = {"buses", "lines", "links", "converters", "transformers"}
        return {c: resources(f"osm/build-at/{c}.csv") for c in components}


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


rule export_evaluation_pypsa_at:
    input:
        networks=expand(
            RESULTS
            + "networks/base_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}.nc",
            **config["scenario"],
            allow_missing=True,
        ),
    output:
        touch(
            RESULTS + "evaluation/.run_by_snakemake",
        ),
    params:
        rdir=RESULTS,
    message:
        "Runs all evaluations from the evals module to generate aggregated result views."
    shell:
        "pixi run evals {params.rdir}"


rule validate_pypsa_at:
    input:
        expand(
            RESULTS + "evaluation/.run_by_snakemake",
            run=config["run"]["name"],
        ),
    output:
        validity_report=RESULTS + "test_report.html",
    resources:
        mem_mb=16000,
    params:
        clustering=config_provider("clustering"),
        rdir=RESULTS,
    message:
        "Execute pypsa-at modifications layer tests. They are marked as 'AT' and require the `--result-path` extra argument."
    shell:
        'pixi run -e test pytest -m "AT" --html {params.rdir}/test_report.html --result-path={params.rdir}'


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
        h2_imports_tyndp=branch(
            config_provider("sector", "h2_topology_tyndp"),
            resources("h2_import_potentials_{clusters}_{planning_horizons}.csv"),
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
    output:
        powerplants=resources("powerplants_s_{clusters}-overwrite.csv"),
    log:
        logs("powerplants_s_{clusters}-overwrite.log"),
    threads: 1
    resources:
        mem_mb=1000,
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
