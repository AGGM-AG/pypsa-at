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
        mem_mb=4000,
    params:
        clustering=config_provider("clustering"),
        rdir=RESULTS,
    message:
        "Execute pypsa-at modifications layer tests. They are marked as 'AT' and require the `--result-path` extra argument."
    shell:
        'pixi run -e test pytest -m "AT" --html {params.rdir}/test_report.html --result-path={params.rdir}'


rule all_at:
    default_target: True
    input:
        expand(RESULTS + "test_report.html", run=config["run"]["name"]),
        lambda w: balance_map_paths("interactive", w),
        RESULTS + "evaluation/.run_by_snakemake",
