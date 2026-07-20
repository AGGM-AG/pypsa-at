# SPDX-FileCopyrightText: 2023-2025 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.

import logging
import random
import sys
from pathlib import Path

import click
import tomllib
import yaml


@click.command(short_help="Overwrite existing values in config/config.at.yaml")
@click.option("--clustering", type=str, required=True)
@click.option("--resolution", type=str, required=True)
@click.option("--solver", type=str, required=True)
@click.option("--scenario", type=str, required=True)
@click.option("--randomize", type=bool, required=True)
def configure(
    clustering: str, resolution: str, solver: str, scenario: str, randomize: bool
) -> None:
    """
    Configure PyPSA-AT model run by updating configuration parameters.

    Overwrites values in config/config.at.yaml with the provided clustering configuration,
    temporal resolution, solver settings, and random seed for reproducible model runs.

    Parameters
    ----------
    clustering : {'AT10DE5', 'AT35DE5', 'AT10DE16', 'AT35DE16'}
        The name of the administrative custom clustering.
    resolution
        The temporal resolution in hours to set as the `sectoral_resolution`.
    solver : {'highs', 'gurobi'}
        The solver to use. Sets `solver_name` and `solver-options` in the configuration.
    scenario {'AT_KN2040'}
        The scenario name to run.
    randomize
        The random seed for the random number generator.

    Returns
    -------
    :
        Updates the configuration file at `config/config.at.yaml`.

    Notes
    -----
    This function is expected to run using pipelines and the dumped
    configuration yaml is not expected to be checked in to VCS.
    """
    # validate inputs
    accepted_solver = ("highs", "gurobi", "hipo")
    if solver not in accepted_solver:
        raise click.BadParameter(
            f"'{solver}' is not a valid solver. Chose from {accepted_solver}."
        )

    available_clustering = ("AT10DE5", "AT35DE5", "AT10DE16", "AT35DE16")
    if clustering not in available_clustering:
        raise click.BadParameter(
            f"'{clustering}' is not valid. Chose from {available_clustering}"
        )

    # sanitize temporal resolution
    resolution = int(resolution.rstrip("H"))
    if resolution < 24 and solver != "gurobi":
        raise ValueError(
            f"Denying to run model with resolution {resolution} and solver '{solver}'."
        )

    config_yaml_fp = Path("config/config.at.yaml")
    pixi_toml_fp = Path("pixi.toml")

    # setting up logger for gitlab CI pipeline
    logging.basicConfig(
        level=logging.INFO,
        format="{levelname} - {name} - {message}",
        datefmt="%Y-%m-%d %H:%M",
        style="{",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    logger = logging.getLogger(__file__)

    with config_yaml_fp.open("r") as fh:
        config = yaml.safe_load(fh)

    with pixi_toml_fp.open("rb") as fh:
        pixi = tomllib.load(fh)

    # Prevent downloading weather data. Snakemake sometimes tries to
    # download them again, although they are present in mounted 'cutouts' volume.
    # only updates retrieve_cutouts key, even if enable key is missing
    config["enable"] = config.get("enable", {}) | {"retrieve_cutout": False}

    logger.info(f"Configuring PyPSA-AT model for clustering {clustering}.")
    config["mods"]["modify_nuts3_shapes"] = clustering

    nuts_at = 2 if "AT10" in clustering else 3  # NUTS3
    nuts_de = 1 if "DE16" in clustering else 3  # DE5
    logger.info(
        f"Setting administrative clustering in AT to "
        f"NUTS level {nuts_at} (={10 if nuts_at == 2 else 35} Regions)"
    )
    config["clustering"]["administrative"]["AT"] = nuts_at
    logger.info(
        f"Setting administrative clustering in DE to "
        f"NUTS level {nuts_de} (={16 if nuts_de == 1 else 5} Regions)"
    )
    config["clustering"]["administrative"]["DE"] = nuts_de

    logger.info(f"Setting temporary resolution to '{resolution}H'")
    config["clustering"]["temporal"]["resolution_sector"] = f"{resolution}H"

    logger.info(f"Setting scenario name to '{scenario}'")
    config["run"]["name"] = [scenario]

    # hotfix for HiPO support in pipelines
    if solver == "hipo":
        solver = "highs"
        solver_options = "highs-hipo"
    else:
        solver_options = f"{solver}-default"

    logger.info(f"Solver name to '{solver}' using options {solver_options}")
    config["solving"]["solver"]["name"] = solver
    config["solving"]["solver"]["options"] = solver_options

    version = pixi["workspace"]["version"]
    logger.info(f"Setting run version to '{version}'")
    config["run"]["prefix"] = version
    # also overwrite the PyPSA-EUR default config version to avoid confusion
    config["version"] = version

    if randomize:
        seed = random.randint(1, 50000)
        logger.info(f"Setting seed to '{seed}'")
        solver_options = config["solving"]["solver"]["options"]

        key = "random_seed" if solver == "highs" else "Seed"  # gurobi
        config["solving"]["solver_options"][solver_options][key] = seed
        # also set duplicated default setting
        config["solving"].setdefault("options", {})
        config["solving"]["options"]["seed"] = seed

    with config_yaml_fp.open("w") as fh:
        yaml.dump(config, fh)


if __name__ == "__main__":
    configure()
