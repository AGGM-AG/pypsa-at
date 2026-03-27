# SPDX-FileCopyrightText: 2023-2025 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""ESM bar charts."""

from functools import cached_property
from types import SimpleNamespace

import numpy as np
import pandas as pd
from plotly import express as px
from plotly import graph_objects as go

from evals.constants import DataModel
from evals.plots.components import (
    BarTraceStyler,
    LayoutStyler,
    TotalSumRenderer,
    empty_figure,
    empty_input,
)
from evals.utils import apply_cutoff, custom_sort, prettify_number


class ESMBarChart:
    """
    The ESM Bar Chart exports metrics as plotly HTML file.

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
        self.location = self._df.index.unique(DataModel.LOCATION)[0]
        self.col_values = self._df.columns[0]

    @cached_property
    def barmode(self) -> str:
        """
        Determine the barmode for the bar chart.

        Returns
        -------
        :
            ``"relative"`` if both negative and positive values are
            present, otherwise ``"stack"``.
        """
        return "relative" if self._has_negatives and self._has_positives else "stack"

    @cached_property
    def _has_negatives(self) -> bool:
        return self._df.lt(0).to_numpy().any()

    @cached_property
    def _has_positives(self) -> bool:
        return self._df.ge(0).to_numpy().any()

    @cached_property
    def df(self) -> pd.DataFrame:
        """
        Plot data formatted for bar charts.

        Returns
        -------
        :
            The formatted data for creating bar charts.
        """
        df = apply_cutoff(self._df, limit=self.cfg.cutoff, drop=self.cfg.cutoff_drop)
        df = custom_sort(
            df.reset_index(),
            by=self.cfg.plot_category,
            values=self.cfg.category_orders,
            ascending=True,
        )
        df["display_value"] = df[self.col_values].apply(prettify_number)
        return df

    def plot(self) -> None:
        """Create the bar chart."""
        title = self.cfg.title.format(location=self.location, unit=self.unit)

        if empty_input(self._df) or self.df[self.col_values].isna().all():
            self.fig = empty_figure(title)
            return

        pattern = {
            col: self.cfg.pattern.get(col, "")
            for col in self.df[self.cfg.plot_category].unique()
        }
        self.fig = px.bar(
            self.df,
            color_discrete_map=self.cfg.colors,
            pattern_shape=self.cfg.plot_category,
            pattern_shape_map=pattern,
            barmode=self.barmode,
            x=self.cfg.plot_xaxis,
            y=self.col_values,
            color=self.cfg.plot_category,
            text=self.col_values,
            title=title,
            labels={
                self.col_values: "<b>" + self.unit + "</b>",
                self.cfg.plot_category: self.cfg.legend_header,
            },
            custom_data=[self.cfg.plot_category, "display_value"],
        )

        layout_styler = LayoutStyler(self.cfg)
        bar_styler = BarTraceStyler(width=0.6)
        total_renderer = TotalSumRenderer(
            col_values=self.col_values,
            plot_xaxis=self.cfg.plot_xaxis,
            unit=self.unit,
        )

        layout_styler.set_base_layout(self.fig)
        bar_styler.apply(self.fig, self.unit)
        layout_styler.style_title_and_legend_and_xaxis_label(self.fig)
        layout_styler.append_footnotes(self.fig)

        self.fig.update_xaxes(fixedrange=True)
        self.fig.update_yaxes(fixedrange=True)
        self.fig.for_each_trace(self._set_legend_rank, selector={"type": "bar"})

        if self.barmode == "relative":
            self.fig.add_hline(y=0)
            total_renderer.add_sum_trace(
                self.fig, self.df, orientation="down", name_trace="Lower Sum"
            )
            total_renderer.add_sum_trace(
                self.fig, self.df, orientation="up", name_trace="Upper Sum"
            )
        elif self._has_negatives and not self._has_positives:
            total_renderer.add_sum_trace(
                self.fig, self.df, orientation="down", name_trace="Lower Sum"
            )
            self.fig.update_xaxes(side="top")
            self.fig.update_layout(margin=dict(t=150))
        elif self.barmode == "stack":
            total_renderer.add_sum_trace(self.fig, self.df)
        else:
            raise ValueError(f"Unexpected barmode: {self.barmode}")

    def _set_legend_rank(self, trace: go.Bar) -> go.Bar:
        """
        Set the legendrank attribute for bar traces.

        Parameters
        ----------
        trace
            The trace object to set the legendrank for.

        Returns
        -------
        :
            The updated bar trace, or the original bar trace.
        """
        if trace["name"] in self.cfg.category_orders:
            y = trace["y"]
            trace_sum = y[np.isfinite(y)].sum()
            sign = -1 if trace_sum < 0 else 1
            pos = self.cfg.category_orders.index(trace["name"])
            trace = trace.update(legendrank=1000 + pos * sign)
        return trace
