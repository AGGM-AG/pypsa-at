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
