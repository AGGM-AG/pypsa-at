# SPDX-FileCopyrightText: 2023-2025 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""
Command Line Interface to run evaluations.

The recommended way to invoke this CLI is via the ``pixi run evals`` task,
which sets up ``PYTHONPATH`` correctly and runs from the project root:

``` shell
pixi run evals --help
```

Examples
--------
``` shell
# run a single evaluation by name
pixi run evals "results/v2025.02/KN2045_Mix" -n "view_demand_fed_sectoral"
```

``` shell
# run multiple evaluations by name
pixi run evals "results/v2025.02/KN2045_Mix" -n "view_balance_electricity,view_capacity_electricity_production"
```

``` shell
# run all evaluations and abort on errors with network files in a custom sub-directory
pixi run evals "results/v2025.02/KN2045_Mix" --fail_fast=true --sub_directory="custom"
```

``` shell
# alternatively, activate the virtual environment and invoke directly
$ pixi shell
(pypsa-at)$ PYTHONPATH="./" python evals/cli.py run-eval "results/v2025.02/KN2045_Mix" -n "view_balance_heat"
```
"""

import copy
import logging
import sys
from pathlib import Path
from time import time

import click


class ViewNames(click.ParamType):
    """
    Accept a single view name or a comma-separated list of view names.

    Examples::

        -n view_balance_electricity
        -n "view_balance_electricity,view_balance_heat"
    """

    name = "names"

    def convert(self, value, param, ctx):
        if isinstance(value, list):
            return value
        return [v.strip() for v in value.split(",") if v.strip()]


logging.basicConfig(
    level=logging.INFO,
    format="{levelname} - {name} - {message}",
    datefmt="%Y-%m-%d %H:%M",
    style="{",
)
logger = logging.getLogger(__file__)


@click.group()
def cli() -> None:
    """Evals CLI — run and manage PyPSA-AT evaluation functions."""


@cli.command()
@click.argument(
    "result_path", type=click.Path(path_type=Path, exists=True), required=False
)
@click.option(
    "--sub_directory",
    "-s",
    type=str,
    required=False,
    default="networks",
)
@click.option("--names", "-n", type=ViewNames(), required=False, default=[])
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
    result_path: click.Path | None,
    sub_directory: str,
    names: list[str],
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
        The path to the result folder, usually ./pypsa-at/results. Optional
        — defaults to the most recently modified scenario folder below
        ``./results``.
    sub_directory
        The subdirectory in the results folder that contains the network files.
    names
        A single view name or a comma-separated list of view names,
        e.g. ``"view_balance_electricity"`` or
        ``"view_balance_electricity,view_balance_heat"``.
        Optional — defaults to running all evaluations from ``evals.__all__``.
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
    ...     names=["view_balance_electricity", "view_balance_heat"]
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
    from evals.utils import get_latest_results_folder

    result_path = result_path or get_latest_results_folder()
    logger.info(f"Running evaluations on results folder: {result_path.resolve()}")

    eval_functions = [
        getattr(views, fn) for fn in views.__all__ if (not names or fn in names)
    ]
    n_evals = len(eval_functions)

    if n_evals == 0:
        sys.exit(f"Found no evaluation functions named: {names}")
    logger.info(f"Selected {n_evals} evaluation functions.")

    nc = read_networks(result_path, sub_directory=sub_directory)

    # assuming no configuration changes in myopic workflow in the same scenario
    # Use deepcopy to avoid mutating the network's meta dict in place (pop below
    # would otherwise remove "resources" from the live network object, breaking
    # downstream views that access nc[year].meta["resources"] directly).
    _first_year = nc.index[0]
    merged_meta = copy.deepcopy(nc[_first_year].meta)
    merged_meta["wildcards"]["planning_horizons"] = nc.index.tolist()
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
            func(result_path=result_path, nc=nc, config=config)
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

    info = f"Full run took {time() - run_start:.2f} seconds."
    if fails:
        info += f"\nNumber of Errors: {len(fails)} {fails or ''}"
        info += f"\nRun \"pixi run evals {result_path} -n '{','.join(fails)}'\" to execute failed evaluations."
    else:
        info += "\nAll Evaluations passed without Errors. Review your results now."
    logger.info(info)

    sys.exit(len(fails))


if __name__ == "__main__":
    # args = (__file__, "run-eval", "../results/run_prefix/scenario", "-n", "view_balance_electricity")
    cli(sys.argv[1:])
