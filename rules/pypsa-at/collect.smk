# SPDX-FileCopyrightText: 2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""
PyPSA-AT main rule to run the workflow.
"""


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
    resources:
        mem_mb=8000,
    params:
        rdir=RESULTS,
    message:
        "Runs all evaluations from the evals module to generate aggregated result views."
    shell:
        "pixi run evals {params.rdir}"


rule validate_pypsa_at:
    input:
        networks=expand(
            RESULTS
            + "networks/base_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}.nc",
            **config["scenario"],
            allow_missing=True,
        ),
    output:
        validity_report=RESULTS + "test_report.html",
    resources:
        mem_mb=8000,
    params:
        clustering=config_provider("clustering"),
        rdir=RESULTS,
    message:
        "Execute pypsa-at modifications layer tests. They are marked as 'AT' and require the `--result-path` extra argument."
    shell:
        'pixi run -e test pytest -m "AT" --html {params.rdir}/test_report.html --result-path={params.rdir}'


# On demand only, not part of all_at. The maps show the AT35DE5 ("adm")
# clustering; `expand` fixes the clusters wildcard while keeping the
# `{clusters}` placeholder visible to the shared-resources path provider.
rule plot_model_map_at:
    input:
        regions_onshore=expand(
            resources("regions_onshore_base_s_{clusters}.geojson"),
            clusters="adm",
            allow_missing=True,
        )[0],
        network=resources("networks/base.nc"),
        gas_network=resources("gas_network.csv"),
        powerplants=expand(
            resources("powerplants_s_{clusters}-overwrite.csv"),
            clusters="adm",
            allow_missing=True,
        )[0],
        hotmaps=rules.retrieve_hotmaps_industrial_sites.output["csv"],
    output:
        powerplants=RESULTS + "maps/model_map_powerplants.png",
        industry=RESULTS + "maps/model_map_industry.png",
    log:
        RESULTS + "logs/plot_model_map_at.log",
    resources:
        mem_mb=8000,
    params:
        clustering=config_provider("mods", "modify_nuts3_shapes"),
        plotting=config_provider("plotting"),
        extent=[5.0, 20.0, 44.0, 52.0],
        powerplant_threshold=10.0,
    message:
        "Plotting the model input maps (power plants, industrial sites, grids). On demand only."
    script:
        scripts("pypsa-at/plot_model_map_at.py")


rule all_at:
    default_target: True
    input:
        expand(RESULTS + "test_report.html", run=config["run"]["name"]),
        expand(RESULTS + "evaluation/.run_by_snakemake", run=config["run"]["name"]),
