# SPDX-FileCopyrightText: 2023-2025 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""Input - Output related functions."""

import getpass
import json
import logging
import re
from collections.abc import Callable
from functools import cached_property, partial
from importlib import resources
from pathlib import Path

import pandas as pd
import pypsa
import tomllib
from pydantic.v1.utils import deep_update
from pypsa import NetworkCollection
from pypsa.statistics import (
    groupers,
)

from evals import plots as plots
from evals.constants import (
    COLOUR_SCHEME,
    NOW,
    RUN_META_DATA,
    TITLE_SUFFIX,
    DataModel,
    Regex,
)
from evals.plots.components import FileExporter
from evals.statistic import ESMStatistics
from evals.utils import (
    build_plot_config,
    combine_statistics,
    get_location,
    rename_aggregate,
    to_duration_curve,
)

logger = logging.getLogger(__name__)


# Configure PyPSA statistics defaults once at import time.
pypsa.options.params.statistics.nice_names = False
pypsa.options.params.statistics.drop_zero = True


def get_location_from_name_at_port(
    n: pypsa.Network, c: str, location_port: str = ""
) -> pd.Series:
    """
    Return the location from the component name.

    Parameters
    ----------
    n
        The network to evaluate.
    c
        The component name, e.g. 'Load', 'Generator', 'Link', etc.
    location_port
        Limit results to this branch port.

    Returns
    -------
    :

    """
    group = f"({Regex.region.pattern})"
    return (
        n.static(c)[f"bus{location_port}"]
        .str.extract(group, expand=False)
        .str.strip()  # some white spaces still go through regex
        .rename(f"bus{location_port}")
    )


# Register custom groupers once, after the grouper functions are defined.
groupers.add_grouper("location", get_location)
groupers.add_grouper(
    "loc_bus0", partial(get_location_from_name_at_port, location_port="0")
)
groupers.add_grouper(
    "loc_bus1", partial(get_location_from_name_at_port, location_port="1")
)


def read_networks(
    result_path: str | Path | list[str | Path], sub_directory: str = "networks"
) -> NetworkCollection:
    """
    Read network results from NetCDF (.nc) files.

    The function returns a dictionary of data frames. The planning
    horizon (year) is used as dictionary key and added to the network
    as an attribute to associate the year with it. Network snapshots
    are equal for all networks, although the year changes. This is
    required to align timestamp columns in a data frame. Snapshots
    will become fixed late in the evaluation process (just before
    export to file).

    In addition, the function patches the statistics accessor attached
    to loaded networks and adds the configuration under n.meta if it is
    missing.

    Parameters
    ----------
    result_path
        Absolute or relative path to the run results folder that
        contains all model results (typically ends with "results",
        or is a time-stamp), or list of .nc file paths to load.
    sub_directory
        The subdirectory name to read files from relative to the
        result folder.

    Returns
    -------
    :
        A NetworkCollection keyed by planning horizon year (str),
        with each network's statistics accessor patched to ESMStatistics.

    Raises
    ------
    FileNotFoundError
        If no network files are found in the specified location.

    Examples
    --------
    Load networks from a results directory:

    >>> networks = read_networks("results/scenario_2030")
    >>> networks.index.tolist()
    ['2030', '2040', '2050']

    Load specific network files:

    >>> networks = read_networks([
    ...     "results/elec_s_37_2030.nc",
    ...     "results/elec_s_37_2040.nc"
    ... ])
    """
    if isinstance(result_path, list):
        # expecting snakemake.input.networks
        file_paths = [Path(p) for p in result_path]
    else:
        input_path = Path(result_path) / sub_directory
        file_paths = input_path.glob(r"*[0-9].nc")

    file_paths = [*file_paths]  # store paths in a list for error messages
    networks = {}
    for file_path in file_paths:
        year = re.search(Regex.year, file_path.stem).group()
        n = pypsa.Network(file_path)
        n.statistics = ESMStatistics(n)  # register custom statistics
        n.year = year  # for convenience
        networks[year] = n

    if not networks:
        raise FileNotFoundError(f"No networks found in {file_paths}.")

    # needed to make NetworkCollections work
    nc = NetworkCollection(networks)
    nc.statistics = ESMStatistics(nc)

    return nc


def read_views_config(
    func: Callable, config_override: str | None = "config.override.toml"
) -> dict:
    """
    Return the configuration for a view function.

    The function reads the default configuration from the
    TOML file and optionally updates it using the configuration
    items in the override file. The configuration returned
    is stripped down to the relevant parts that matter for the
    called view function.

    Parameters
    ----------
    func
        The view function to be called by the CLI module.
    config_override
        A file name as a string as passed to the CLI module, or None
        to use only default configuration.

    Returns
    -------
    :
        Dictionary containing 'global' and 'view' configuration sections
        with optional overrides applied from the second configuration file.

    Examples
    --------
    >>> config = read_views_config(view_balance_electricity)
    >>> config.keys()
    dict_keys(['global', 'view'])
    """
    default_fp = resources.files("evals") / "config.default.toml"
    default = tomllib.load(default_fp.open("rb"))
    default_global = default["global"]
    default_view = default[func.__name__]

    if config_override:
        override_fp = Path(resources.files("evals")) / config_override
        override = tomllib.load(override_fp.open("rb"))
        default_global = deep_update(default_global, override["global"])

        if override_view := override.get(func.__name__, {}):
            default_view = deep_update(default_view, override_view)

    # inject global config into view dict so Exporter can access it without
    # requiring callers to change the view_config=config["view"] call pattern
    default_view["_global"] = default_global
    config = {"global": default_global, "view": default_view}

    logger = logging.getLogger()
    logger.debug(f"Configuration items: {config}")

    return config


class Exporter:
    """
    A class to export statistics.

    The exporter data frame consists of multiple joined statistics,
    aggregated to countries and scaled to a specified unit. The
    data frame format is verified and expected by export functions.

    Parameters
    ----------
    statistics
        A list of Series for time aggregated statistics or list of
        data frames for statistics with snapshots as columns.
    view_config
        The merged view configuration dictionary from
        :func:`read_views_config`.
    """

    def __init__(
        self,
        statistics: list,
        view_config: dict,
    ):
        self.statistics = statistics
        units = {stat.attrs["unit"] for stat in statistics}
        if len(units) != 1:
            raise ValueError(f"Mixed units cannot be exported: {units}.")
        self.is_unit = units.pop()
        self.metric_name = view_config["name"]
        self.to_unit = view_config["unit"]
        self.view_config = view_config

        # keep_regions and region_nice_names come from global TOML config
        global_cfg = view_config["_global"]
        self.keep_regions = tuple(global_cfg["keep_regions"])
        self.region_nice_names = global_cfg["region_nice_names"]

        # build the plot config namespace from TOML global defaults
        self.defaults = build_plot_config(global_cfg)

        # apply per-view overrides from the view config
        title = view_config["name"] + TITLE_SUFFIX
        self.defaults.title = title
        self.defaults.name = view_config["name"]
        self.defaults.file_name_template = view_config["file_name"]
        self.defaults.cutoff = view_config["cutoff"]
        self.defaults.category_orders = view_config["legend_order"]
        self.defaults.database_plot_type = view_config["database_plot_type"]
        self.defaults.database_bus_carrier = view_config["database_bus_carrier"]
        self.defaults.database_specifier = view_config["database_specifier"]
        if "global_override" in view_config.keys():
            vars(self.defaults).update(view_config["global_override"])

    @cached_property
    def df(self) -> pd.DataFrame:
        """
        Build the metric and store it as a cached property.

        (This is useful, because users do not need to remember
        building the metric data frame. It will be built once if needed)

        Returns
        -------
        :
            The cached metric data frame.
        """
        return combine_statistics(
            self.statistics,
            self.metric_name,
            self.is_unit,
            self.to_unit,
            self.keep_regions,
            self.region_nice_names,
        )

    @staticmethod
    def write_run_json(output_path: Path, run_config: dict) -> None:
        """
        Serialize the run attributes to a JSON file.

        The run.json file holds all attributes required to identify a
        run in the Run table of the database data model. All views and
        variables will be associated with this run database object.

        Parameters
        ----------
        output_path
            The path to the evaluation folder in a scenario run.
        run_config
            The merged run configuration dictionary with all scenario data.

        Returns
        -------
        :
        """
        scenario_name = output_path.parent.name
        resolution_space = run_config.get("mods", {}).get("modify_nuts3_shapes", "")
        resolution_time = run_config["clustering"]["temporal"]["resolution_sector"]

        with Path("pixi.toml").open("rb") as fh:
            project_settings = tomllib.load(fh)

        run_data = {
            "model": "PyPSA-AT",
            "scenario": f"{scenario_name} - {resolution_space} {resolution_time}",
            "version": project_settings["workspace"]["version"],
            "description": run_config.get("description", ""),
            "author": getpass.getuser(),
            "custom_metadata": RUN_META_DATA | run_config,
        }
        run_file_path = output_path / "JSON" / "run.json"
        with run_file_path.open("w", encoding="utf-8") as fh:
            json.dump(run_data, fh, indent=4)

    def export_views(self, output_path: Path) -> None:
        """
        Create the plotly figure and export it as HTML and JSON.

        Parameters
        ----------
        output_path
            The path to the folder where HTML, JSON and
            CSV subdirectories are created.
        """
        cfg = self.defaults
        df = rename_aggregate(
            self.df, level=cfg.plot_category, mapper=self.view_config["categories"]
        )

        df_plot = df.pivot_table(
            index=cfg.pivot_index, columns=cfg.pivot_columns, aggfunc="sum"
        )

        if hasattr(cfg, "is_duration_curve") and cfg.is_duration_curve:
            df_plot = to_duration_curve(df_plot)

        # needed for upload API data bundle ingestion
        # Disabled because DB upload not supported
        # self.write_run_json(output_path, self.view_config["meta"])

        for idx, data in df_plot.groupby(cfg.plotby):
            chart = cfg.chart(data, cfg)
            chart.plot()
            exporter = FileExporter(cfg, chart.metric_name)
            exporter.to_html(chart.fig, output_path, cfg.plotby, idx)
            year = None
            if DataModel.YEAR in cfg.plotby:
                if DataModel.YEAR in data.index.names:
                    year = data.index.unique(DataModel.YEAR).item()
                else:
                    year = getattr(chart, "year", None)
            exporter.to_json(
                chart.fig,
                chart.location,
                year,
                output_path,
                cfg.plotby,
                idx,
            )

    def export_csv(self, output_path: Path) -> None:
        """
        Encode the metric data frame to a CSV file.

        Parameters
        ----------
        output_path
            The path to the CSV folder where all the csv files are
            stored.

        Returns
        -------
        :
            Writes the metric to a CSV file.
        """
        file_name = self.defaults.file_name_template.split("_{", maxsplit=1)[0]
        file_path = output_path / "CSV" / f"{file_name}_{NOW}.csv"
        self.df.to_csv(file_path, encoding="utf-8")

    def export(self, result_path: Path, subdir: str) -> None:
        """
        Export the metric to formats specified in the config.

        Parameters
        ----------
        result_path
            The path to the results folder.
        subdir
            The subdirectory inside the results folder to store evaluation results under.

        Returns
        -------
        :
        """
        # apply configuration switches that depend on the requested chart
        chart_class = getattr(plots, self.view_config["chart"])
        self.defaults.chart = chart_class

        if chart_class == plots.ESMGroupedBarChart:
            self.defaults.xaxis_title = ""
        elif chart_class == plots.ESMTimeSeriesChart:
            self.defaults.plotby = [DataModel.YEAR, DataModel.LOCATION]
        elif (
            chart_class == plots.ESMBarChart
            and self.defaults.plot_category == DataModel.CARRIER
        ):
            # combine bus carrier to export netted technologies, although
            # they have difference bus_carrier in index, e.g.
            # electricity distribution grid, (AC, low voltage)
            first_bus_carrier = self.statistics[0].index.unique("bus_carrier")[0]
            self.statistics = [
                rename_aggregate(stat, first_bus_carrier, level=DataModel.BUS_CARRIER)
                for stat in self.statistics
            ]

        output_path = self.make_evaluation_result_directories(result_path, subdir)

        self.export_views(output_path)

        export_formats = self.view_config.get("exports", [])
        if "csv" in export_formats:
            self.export_csv(output_path)

        # always run tests after the export
        self.consistency_checks()

    def consistency_checks(self) -> None:
        """
        Run plausibility and consistency checks on a metric.

        The method typically is called after exporting the metric.
        Unmapped categories do not cause evaluations to fail, but
        the evaluation function should return in error state to obviate
        missing entries in the mapping.

        Parameter
        ---------
        config_checks
            A dictionary with flags for every test to run.

        Returns
        -------
        :

        Raises
        ------
        AssertionError
            In case one of the checks fails.
        """
        self.default_checks()

        if "balances_almost_zero" in self.view_config.get("checks", []):
            groups = [DataModel.YEAR, DataModel.LOCATION]
            yearly_sum = self.df.groupby(groups).sum().abs()
            balanced = yearly_sum < self.view_config["cutoff"]
            if isinstance(balanced, pd.DataFrame):
                if not balanced.all().all():
                    raise ValueError(
                        f"Imbalances detected: {yearly_sum[balanced == False].dropna(how='all').sort_values(by=balanced.columns[0], na_position='first').tail()}"
                    )
            else:  # Series
                if not balanced.all().item():
                    raise ValueError(
                        f"Imbalances detected: {yearly_sum[balanced.squeeze() == False].squeeze().sort_values().tail()}"
                    )

    def default_checks(self) -> None:
        """Perform integrity checks for views."""
        if self.view_config.get("skip_default_checks", False):
            return  # bypass all checks, because view has its own set of assertions

        category = self.defaults.plot_category
        categories = self.view_config["categories"]

        if not self.df.index.unique(category).isin(categories.keys()).all():
            missing_cats = self.df.index.unique(category).difference(categories.keys())
            raise ValueError(
                f"Incomplete categories detected. There are technologies in the metric "
                f"data frame that are not assigned to a group (nice name)."
                f"\nMissing items: {missing_cats}"
            )

        superfluous_categories = self.df.index.unique(category).difference(
            categories.keys()
        )
        if len(superfluous_categories) > 0:
            logger.warning(f"Superfluous categories defined: {superfluous_categories}")

        a = set(self.view_config["legend_order"])
        b = set(categories.values())
        additional = a.difference(b)
        if additional:
            raise ValueError(
                f"Superfluous categories defined in legend order: {additional}"
            )
        missing = b.difference(a)
        if missing:
            raise ValueError(
                f"Some categories are not defined in legend order: {missing}"
            )

        no_color = [c for c in categories.values() if c not in COLOUR_SCHEME]
        if no_color:
            raise ValueError(
                f"Some categories used in the view do not have a color assigned: {no_color}"
            )

    def make_evaluation_result_directories(
        self, result_path: Path, subdir: Path | str
    ) -> Path:
        """
        Create all directories needed to store evaluations results.

        Parameters
        ----------
        result_path
            The path of the result folder.
        subdir
            A relative path inside the result folder.

        Returns
        -------
        :
            The joined path: result_dir / subdir.
        """
        output_path = self.make_directory(result_path, subdir)
        self.make_directory(output_path, "HTML")
        self.make_directory(output_path, "JSON")
        self.make_directory(output_path, "CSV")

        return output_path

    @staticmethod
    def make_directory(base: Path, subdir: Path | str) -> Path:
        """
        Create a directory and return its path.

        Parameters
        ----------
        base
            The path to base of the new folder.
        subdir
            A relative path inside the base folder.

        Returns
        -------
        :
            The joined path: result_dir / subdir / now.
        """
        base = Path(base).resolve()
        if not base.is_dir():
            raise NotADirectoryError(f"Base path does not exist: {base}.")
        directory_path = base / subdir
        directory_path.mkdir(parents=True, exist_ok=True)

        return directory_path
