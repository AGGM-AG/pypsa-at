# SPDX-FileCopyrightText: 2023-2025 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""
Command Line Interface to run evaluations.

Commands must be run from project root and with the virtual environment
activated, or via `pixi run`.

Examples
--------
``` shell
# run a single evaluation by name
PYTHONPATH="./" pixi run python evals/cli.py "/opt/data/esm/results" -n "view_demand_fed_sectoral"
```

``` shell
# run multiple evaluations by name
PYTHONPATH="./" pixi run python evals/cli.py  "/opt/data/esm/results" -n "view_balance_electricity" -n "view_capacity_electricity_production"
```

``` shell
# run all evaluations and abort on errors and from with network files in "/opt/data/esm/custom"
PYTHONPATH="./" pixi run python evals/cli.py "/opt/data/esm" --fail_fast=true --sub_directory="custom"
```

``` shell
# run evaluations as a script and from the project root with your virtual env activated
$ pixi shell
(pypsa-at)$ PYTHONPATH="./" python evals/cli.py "results/v2025.02/KN2045_Mix" -n "view_balance_heat"
```
"""

import logging
import sys
from time import time

import click

logging.basicConfig(
    level=logging.INFO,
    format="{levelname} - {name} - {message}",
    datefmt="%Y-%m-%d %H:%M",
    style="{",
)
logger = logging.getLogger(__file__)


@click.command()
@click.argument("result_path", type=click.Path(exists=True), required=True)
@click.option(
    "--sub_directory",
    "-s",
    type=str,
    required=False,
    default="networks",
)
@click.option("--names", "-n", multiple=True, required=False, default=[])
@click.option(
    "--config_override",
    "-c",
    type=click.Path(exists=True),
    multiple=False,
    required=False,
    default=None,
)
@click.option(
    "--fail_fast", "-f", type=bool, multiple=False, required=False, default=False
)
def run_eval(
    result_path: click.Path,
    sub_directory: str,
    names: tuple[str, ...],
    config_override: str | None,
    fail_fast: bool,
) -> None:
    r"""
    Execute evaluation functions from the evals module.

    All evaluation functions are expected to expose the same interface.
    The evaluation function arguments are listed in the evals module
    [reference section](index.md).

    Parameters
    ----------
    result_path
        The path to the result folder, usually ./pypsa-eur-sec/results.
        Note that running on copied result folders might fail
        due to missing resource files.
    sub_directory
        The subdirectory in the results folder that contains the network files.
    names
        A list of evaluation names, e.g. "eval_electricity_amounts",
        optional. Defaults to running all evaluations from
        evals.__all__.
    config_override
        A path to a config.toml file with the same section as
        the config.defaults.toml used to override configurations
        used by view functions.
    fail_fast
        Whether to raise Exceptions or to run all functions, defaults to
        running all functions.

    Returns
    -------
    :
        Exits the program with the number of failed evaluations as exit
        code.

    Examples
    --------
    Run a single evaluation by name:

    >>> run_eval("/opt/data/esm/results", names=("view_balance_electricity",))

    Run multiple evaluations:

    >>> run_eval(
    ...     "/opt/data/esm/results",
    ...     names=("view_balance_electricity", "view_balance_heat")
    ... )

    Run all evaluations with custom config:

    >>> run_eval("/opt/data/esm/results", config_override="custom_config.toml")

    Notes
    -----
    Evaluation functions must be registered under evals.\__init__.\__all__
    to be found by the cli and ultimately be run by this function.
    Keep that in mind when adding new evaluation functions.
    """
    import evals.views as views
    from evals.fileio import read_networks, read_views_config

    eval_functions = [
        getattr(views, fn) for fn in views.__all__ if (not names or fn in names)
    ]
    n_evals = len(eval_functions)

    if n_evals == 0:
        sys.exit(f"Found no evaluation functions named: {names}")
    logger.info(f"Selected {n_evals} evaluation functions.")

    networks = read_networks(result_path, sub_directory=sub_directory)

    # assuming no configuration changes in myopic workflow in the same scenario
    merged_meta = networks["2020"].meta
    merged_meta["wildcards"]["planning_horizons"] = list(networks)
    # additional resources are not used in the dashboard and bloat the runs.json file
    merged_meta.pop("resources", None)

    fails = []
    run_start = time()
    for i, func in enumerate(eval_functions, start=1):
        logger.info(f"({i}/{n_evals}) Start {func.__name__}...")
        eval_start = time()
        try:
            config = read_views_config(func, config_override)
            config["view"]["meta"] = merged_meta
            func(result_path=result_path, networks=networks, config=config)
        except Exception as e:
            logger.exception(f"Exception during {func.__name__}.", exc_info=True)
            fails.append(func.__name__)
            if fail_fast:
                raise e
        else:
            logger.info(
                f"Executing {func.__name__} took {time() - eval_start:.2f} seconds."
            )
        finally:
            logger.info(f"Finished {func.__name__}.")

    logger.info(
        f"Full run took {time() - run_start:.2f} seconds."
        f"\nNumber of Errors: {len(fails)} {fails or ''}"
    )
    sys.exit(len(fails))


if __name__ == "__main__":
    # args = (__file__, "../results/run_prefix/scenario", "-n", "view_balance_electricity")
    run_eval(sys.argv[1:])
