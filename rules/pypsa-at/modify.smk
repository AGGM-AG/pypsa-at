if OSM_DATASET["source"] == "build":

    rule build_osm_network_at:
        message:
            "Filtering built OSM network for AT: removing cross-border lines below 220 kV"
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
    params:
        clustering=config_provider("clustering", "mode"),
        admin_levels=config_provider("clustering", "administrative"),
    input:
        nuts3_shapes=resources("nuts3_shapes-raw.geojson"),
    output:
        nuts3_shapes=resources("nuts3_shapes.geojson"),
    log:
        logs("modify_nuts3_shapes.log"),
    threads: 1
    resources:
        mem_mb=1500,
    script:
        scripts("pypsa-at/modify_nuts3_shapes.py")


rule export_evaluation_pypsa_at:
    message:
        "Runs all evaluations from the evals module to generate aggregated result views."
    params:
        rdir=RESULTS,
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
    shell:
        "pixi run evals {params.rdir}"


rule validate_pypsa_at:
    message:
        "Execute pypsa-at modifications layer tests. They are marked as 'AT' and require the `--result-path` extra argument."
    params:
        clustering=config_provider("clustering"),
        rdir=RESULTS,
    input:
        expand(
            RESULTS + "evaluation/.run_by_snakemake",
            run=config["run"]["name"],
        ),
    output:
        validity_report=RESULTS + "test_report.html",
    resources:
        mem_mb=16000,
    shell:
        'pixi run -e test pytest -m "AT" --html {params.rdir}/test_report.html --result-path={params.rdir}'


rule aggregate_pv_potentials:
    input:
        nuts3_shapes=resources("nuts3_shapes.geojson"),
        pv_buildings=f"{dataset_version('klien_pv_buildings_potential')['folder']}/pv_buildings_potential.geojson",
        pv_ground_sealed=f"{dataset_version('klien_pv_ground_mounted_sealed_potential')['folder']}/pv_ground_sealed_potential.geojson",
        pv_ground_unsealed=f"{dataset_version('klien_pv_ground_mounted_unsealed_potential')['folder']}/pv_ground_unsealed_potential.geojson",
    output:
        nuts3_buildings="data/pypsa-at/pv_potentials/nuts3_pv_buildings.csv",
        nuts3_ground="data/pypsa-at/pv_potentials/nuts3_pv_ground.csv",
        at10_buildings="data/pypsa-at/pv_potentials/at10_pv_buildings.csv",
        at10_ground="data/pypsa-at/pv_potentials/at10_pv_ground.csv",
    log:
        logs("aggregate_pv_potentials.log"),
    threads: 1
    resources:
        mem_mb=2000,
    script:
        scripts("pypsa-at/aggregate_pv_potentials.py")
