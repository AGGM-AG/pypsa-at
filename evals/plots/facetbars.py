# SPDX-FileCopyrightText: 2023-2025 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""ESM grouped barcharts."""

from functools import cached_property
from itertools import product
from types import SimpleNamespace

import numpy as np
import pandas as pd
from plotly import express as px
from plotly import graph_objects as go
from plotly.subplots import make_subplots

from evals.constants import DataModel
from evals.plots.components import (
    BarTraceStyler,
    LayoutStyler,
    TotalSumRenderer,
    empty_figure,
    empty_input,
)
from evals.utils import apply_cutoff, custom_sort, prettify_number


class ESMGroupedBarChart:
    """
    A class that produces multiple bar charts in subplots.

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
        self.unit = self.cfg.unit or df.attrs["unit"]
        self.metric_name = df.attrs["name"]
        self.location = self._df.index.unique(DataModel.LOCATION)[0]
        self.col_values = self._df.columns[0]

        ncols = len(self.df[DataModel.BUS_CARRIER].unique())
        ncols = ncols or 1
        column_widths = [0.85 / ncols] * ncols
        self.fig = make_subplots(
            rows=1, cols=ncols, shared_yaxes=True, column_widths=column_widths
        )

    @cached_property
    def df(self) -> pd.DataFrame:
        """
        Plot data formatted for grouped bar charts.

        Returns
        -------
        :
            The formatted data for creating bar charts.
        """
        df = apply_cutoff(self._df, limit=self.cfg.cutoff, drop=False)
        df = df.reset_index()

        fill_values = product(
            df[DataModel.YEAR].unique(),
            df[DataModel.LOCATION].unique(),
            df[DataModel.CARRIER].unique(),
            df[DataModel.BUS_CARRIER].unique(),
        )
        df_fill = pd.DataFrame(columns=DataModel.YEAR_IDX_NAMES, data=fill_values)
        df_fill[self.col_values] = np.nan
        df = pd.concat([df, df_fill], ignore_index=True)

        df_list = []
        for _, df_sector in df.groupby(self.cfg.facet_column, sort=True):
            sorted_sector = custom_sort(
                df_sector,
                by=self.cfg.plot_category,
                values=self.cfg.category_orders,
                ascending=True,
            )
            df_list.append(sorted_sector)
        df = pd.concat(df_list)

        df = df.dropna(how="all", subset=self.col_values)
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
            x=self.cfg.plot_xaxis,
            y=self.col_values,
            facet_col=self.cfg.facet_column,
            facet_col_spacing=0.04,
            pattern_shape=self.cfg.plot_category,
            pattern_shape_map=pattern,
            color=self.cfg.plot_category,
            color_discrete_map=self.cfg.colors,
            text=self.cfg.facet_column,
            title=title,
            custom_data=[self.cfg.plot_category, "display_value"],
        )

        self.fig.for_each_xaxis(self._rename_xaxis)

        total_renderer = TotalSumRenderer(
            col_values=self.col_values,
            plot_xaxis=self.cfg.plot_xaxis,
            unit=self.unit,
        )
        total_renderer.add_subplot_traces(self.fig, self.df, self.cfg.facet_column)

        self.fig.update_annotations(text="")

        layout_styler = LayoutStyler(self.cfg)
        bar_styler = BarTraceStyler(width=0.8)

        layout_styler.set_base_layout(self.fig)
        bar_styler.apply(self.fig, self.unit)
        layout_styler.style_title_and_legend_and_xaxis_label(self.fig)
        layout_styler.append_footnotes(self.fig)

        self.fig.update_xaxes(fixedrange=True)
        self.fig.update_yaxes(fixedrange=True)
        self.fig.for_each_xaxis(self._style_inner_xaxis_labels)

    def _rename_xaxis(self, xaxis: go.layout.XAxis) -> None:
        """
        Update the xaxis labels.

        Parameters
        ----------
        xaxis
            The subplot xaxis (a dictionary).
        """
        layout = self.fig["layout"]
        idx = xaxis["anchor"].lstrip("y")
        for data in self.fig["data"]:
            if data["xaxis"] == f"x{idx}":
                sector = data["text"][0]
                layout[f"xaxis{idx}"]["title"]["text"] = f"<b>{sector}"
                break

    def _style_inner_xaxis_labels(self, xaxis: go.layout.XAxis) -> None:
        """
        Set the font size for inner xaxis labels.

        Parameters
        ----------
        xaxis
            The subplot xaxis (a dictionary-like object).
        """
        xaxis.update(
            tickfont_size=self.cfg.xaxis_font_size,
            categoryorder="category ascending",
        )
