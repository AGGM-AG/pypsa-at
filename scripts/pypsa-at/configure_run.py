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
@click.option("--scenario", "-s", type=str, required=True)
@click.option("--randomize", "-r", type=bool, required=True)
def configure(scenario: str, randomize: bool) -> None:
    """
    Configure PyPSA-AT model run by updating configuration parameters.

    Overwrites values in config/config.at.yaml with the provided clustering configuration,
    temporal resolution, solver settings, and random seed for reproducible model runs.

    Parameters
    ----------
    scenario
    randomize

    Returns
    -------
    :
        Updates the configuration file at `config/config.at.yaml`.

    Notes
    -----
    This function is expected to run using pipelines and the dumped configuration
    yaml is not expected to be checked in to VCS.
    """
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

    # validate config
    resolution = config["clustering"]["temporal"]["resolution_sector"]
    resolution = int(resolution.rstrip("H"))
    # solver configuration ruled by scenario config
    solver_name = config["solving"]["solver"]["name"]
    if resolution < 24 and solver_name != "gurobi":
        raise ValueError(
            f"Denying to run high resolution run with '{resolution}H' and solver '{solver_name}'"
        )

    logger.info(f"Setting scenario name to '{scenario}'")
    config["run"]["name"] = [scenario]

    version = pixi["workspace"]["version"]
    logger.info(f"Setting run version to '{version}'")
    config["run"]["prefix"] = version
    # also overwrite the PyPSA-EUR default config version to avoid confusion
    config["version"] = version

    seed = random.randint(1, 50000) if randomize else 123
    logger.info(f"Setting seed to '{seed}'")
    solver_options = config["solving"]["solver"]["options"]

    key = "random_seed" if solver_name == "highs" else "Seed"  # gurobi
    config["solving"]["solver_options"][solver_options][key] = seed
    # also set duplicated default setting
    config["solving"].setdefault("options", {})
    config["solving"]["options"]["seed"] = seed

    with config_yaml_fp.open("w") as fh:
        yaml.dump(config, fh)


if __name__ == "__main__":
    configure()
