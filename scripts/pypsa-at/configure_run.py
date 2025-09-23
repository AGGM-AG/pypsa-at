import logging
from pathlib import Path

import click
import yaml


@click.command(short_help="Overwrite existing values in config/config.at.yaml")
@click.option("--clustering", "-c", type=str, required=True)
@click.option("--resolution", "-r", type=str, required=True)
@click.option("--solver", "-s", type=str, required=True)
@click.option("--seed", "-e", type=int, required=True)
def configure(clustering: str, resolution: str, solver: str, seed: int) -> None:
    """
    Overwrite values in config.at.yaml during pipeline execution.

    Parameters
    ----------
    clustering : {'AT10DE5', 'AT35DE5', 'AT10DE19', 'AT35DE19'}
        The name of the administrative custom clustering.
    resolution
        The temporal resolution in hours to set as the `sectoral_resolution`.
    solver : {'highs-default', 'gurobi-default'}
        The solver to use. Sets `solver_name` and `solver-options` in the configuration.
    seed
        The random seed for the random number generator.

    Returns
    -------
    :
        Updates the configuration file at `config/config.at.yaml`.
    """
    # validate inputs
    accepted_solver = ("highs-default", "gurobi-default")
    if solver not in accepted_solver:
        raise click.BadParameter(
            f"'{solver}' is not a valid solver. Chose from {accepted_solver}."
        )

    available_clustering = ("AT10DE5", "AT35DE5", "AT10DE19", "AT35DE19")
    if clustering not in available_clustering:
        raise click.BadParameter(
            f"'{clustering}' is not valid. Chose from {available_clustering}"
        )

    file_path = Path("config/config.at.yaml")
    logger = logging.getLogger(__name__)

    with file_path.open("r") as fh:
        config = yaml.safe_load(fh)

    nuts_at = 2 if "AT10" in clustering else 3
    nuts_de = 1 if "DE19" in clustering else 5
    logger.info(f"Setting administrative clustering in AT to NUTS level {nuts_at}")
    config["clustering"]["administrative"]["AT"] = nuts_at
    logger.info(f"Setting administrative clustering in DE to NUTS level {nuts_de}")
    config["clustering"]["administrative"]["DE"] = nuts_de

    # sanitize temporal resolution
    if not resolution.endswith("H"):
        resolution += "H"
    logger.info(f"Setting temporary resolution to '{resolution}'")
    config["clustering"]["temporal"]["resolution_sector"] = resolution

    solver_name = solver.split("-")[0]
    logger.info(
        f"Setting solver name to '{solver_name}' and solver options to '{solver}'"
    )
    config["solving"]["solver"]["name"] = solver_name
    config["solving"]["solver"]["options"] = solver
    key = "random_seed" if solver_name == "highs" else "Seed"  # gurobi
    logger.info(f"Setting seed to '{key}'")
    config["solver_options"][solver][key] = seed

    with file_path.open("w") as fh:
        yaml.dump(config, fh)


if __name__ == "__main__":
    configure()
