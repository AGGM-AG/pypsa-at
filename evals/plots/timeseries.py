# SPDX-FileCopyrightText: 2023-2025 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""ESM time series scatter plots."""

from functools import cached_property
from types import SimpleNamespace

import pandas as pd
from plotly import graph_objects as go

from evals.constants import DataModel
from evals.plots.components import (
    LayoutStyler,
    TimeSeriesStyler,
    empty_figure,
    empty_input,
)
from evals.utils import apply_cutoff, custom_sort


class ESMTimeSeriesChart:
    """
    A class that produces one time series chart.

    Parameters
    ----------
    df
        Metric data frame complying with the evaluation data model.
    cfg
        Plotly configuration object with styling and export settings.
    """

    def __init__(self, df: pd.DataFrame, cfg: SimpleNamespace) -> None:
        self._df = df
        self.cfg = cfg
        self.fig = go.Figure()
        self.unit = self.cfg.unit or df.attrs["unit"]
        self.metric_name = df.attrs["name"]
        self.year = self._df.index.unique("year")[0]
        self.location = self._df.index.unique(DataModel.LOCATION)[0]
        self.col_values = ""

        self.cfg.yaxes_showgrid = self.cfg.yaxes_visible = True

    @cached_property
    def df(self) -> pd.DataFrame:
        """
        Plot data formatted for time series charts.

        Returns
        -------
        :
            The formatted data for creating time series charts.
        """
        df = apply_cutoff(self._df, limit=self.cfg.cutoff, drop=self.cfg.cutoff_drop)
        df = custom_sort(df, by=self.cfg.plot_category, values=self.cfg.category_orders)
        df = self.fix_snapshots(df, int(self.year))
        if set(df.index.names) == {DataModel.YEAR, DataModel.LOCATION}:
            df = df.reset_index(drop=True)
            df.index = [self.cfg.name] * len(df)
        else:
            df = df.droplevel([DataModel.YEAR, DataModel.LOCATION])
        return df.T

    def plot(self) -> None:
        """
        Plot the data to the chart.

        Iterates over data series, adds scatter traces, applies styling,
        and appends footnotes.
        """
        title = self.cfg.title.format(
            location=self.location, year=self.year, unit=self.unit
        )
        if empty_input(self._df):
            self.fig = empty_figure(title)
            return

        stackgroup = None
        for i, (name, series) in enumerate(self.df.items()):
            if self.cfg.stacked:
                stackgroup = "supply" if series.sum() >= 0 else "withdrawal"
            legendrank = 1000 + i if stackgroup == "supply" else 1000 - i
            self.fig.add_trace(
                go.Scatter(
                    x=series.index,
                    y=series.values,
                    hovertemplate="%{y:.2f} " + self.unit,
                    name=name,
                    fill=self.cfg.fill.get(name, "tonexty"),
                    fillpattern_shape=self.cfg.pattern.get(name),
                    line_dash=self.cfg.line_dash.get(name, "solid"),
                    line_width=self.cfg.line_width.get(name, 1),
                    line_color=self.cfg.colors.get(name),
                    line_shape=self.cfg.line_shape,
                    fillcolor=self.cfg.colors.get(name),
                    stackgroup=stackgroup,
                    legendrank=legendrank,
                )
            )

        ts_styler = TimeSeriesStyler(self.cfg)
        layout_styler = LayoutStyler(self.cfg)

        ts_styler.style_inflexible_demand(self.fig)
        layout_styler.set_base_layout(self.fig)
        layout_styler.style_title_and_legend_and_xaxis_label(self.fig)
        ts_styler.style_axes_and_layout(self.fig, title, self.unit)
        layout_styler.append_footnotes(self.fig)

    @staticmethod
    def fix_snapshots(df: pd.DataFrame, year: int) -> pd.DataFrame:
        """
        Correct the year in snapshot timestamp column labels.

        Parameters
        ----------
        df
            The DataFrame with timestamps to be adjusted.
        year
            The correct year to use in the data frame columns.

        Returns
        -------
        :
            The DataFrame with corrected timestamps.
        """
        if isinstance(df.columns, pd.DatetimeIndex):
            df.columns = [s.replace(year=year) for s in df.columns]
        return df
