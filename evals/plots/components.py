# SPDX-FileCopyrightText: 2023-2025 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""
Composable building blocks for ESM chart classes.

Each class encapsulates a single cross-cutting concern (file I/O, layout
styling, bar trace styling, total-sum annotation, or time-series styling)
that was previously inherited from ESMChart. Chart classes instantiate the
components they need rather than inheriting from a shared base.
"""

import json
import logging
import pathlib
import re
import typing

import pandas as pd
from jinja2 import Template
from plotly import express as px
from plotly import graph_objects as go
from plotly.offline.offline import get_plotlyjs

from evals.constants import ALIAS_LOCATION_REV, RUN_META_DATA
from evals.utils import prettify_number

logger = logging.getLogger(__name__)

# Two surgical fixes to Plotly's circular-Sankey layout in the minified bundle,
# both needed so a Sankey *with* a transformation loop looks like one without.
# Each pattern is unique in the bundle (asserted by the tests).
#
# 1. Loop depth: a "bottom" loop is routed to
#    ``Math.max(<plot height>, source.y1, target.y1) + 25 + buffer`` -- pinning
#    it to the diagram bottom regardless of node positions. Dropping the
#    plot-height term makes the loop hug its source/target nodes instead, so the
#    recirculation stays a compact curve while nodes keep their top-alignment.
_CIRCULAR_LOOP_PATTERN = re.compile(
    r"Math\.max\(\w+,(\w+)\.source\.y1,\1\.target\.y1\)"
)
_CIRCULAR_LOOP_REPL = r"Math.max(\1.source.y1,\1.target.y1)"

# 2. Fill height: Plotly scales the nodes to fill the height (function ``Ht``)
#    only ``if(<no top loop> || <no bottom loop>)`` -- so a chart with loops on
#    both sides skips it and leaves white space below the content. Forcing the
#    guard true makes looped charts fill the height like loopless ones.
_FILL_GUARD_PATTERN = re.compile(
    r"\w+==!1\|\|\w+==!1(\)\{var \w+=\w+\.min\(\w+,function\(\w+\)\{return \w+\.y0\})"
)
_FILL_GUARD_REPL = r"!0\1"


def patch_sankey_circular_layout(plotly_js: str) -> str:
    """Make looped Sankeys render like loopless ones (see comments above)."""
    for name, pattern, repl in (
        ("loop depth", _CIRCULAR_LOOP_PATTERN, _CIRCULAR_LOOP_REPL),
        ("fill height", _FILL_GUARD_PATTERN, _FILL_GUARD_REPL),
    ):
        plotly_js, n = pattern.subn(repl, plotly_js)
        if n != 1:
            logger.warning(
                "Could not apply Plotly Sankey '%s' patch (%d matches); looped "
                "diagrams may render poorly. The minified bundle likely changed "
                "-- revisit patch_sankey_circular_layout().",
                name,
                n,
            )
    return plotly_js


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def empty_input(df: pd.DataFrame) -> bool:
    """Return True if *df* is empty or contains only NaN values."""
    return bool(df.empty or df.isna().all().all())


# ---------------------------------------------------------------------------
# FileExporter
# ---------------------------------------------------------------------------


class FileExporter:
    """
    Serialise a Plotly figure to HTML and JSON files.

    Parameters
    ----------
    cfg
        Plot configuration object with ``file_name_template`` and
        ``database_*`` attributes.
    metric_name
        Name of the metric being exported; used to fill the
        ``{metric}`` placeholder in ``file_name_template``.
    """

    def __init__(self, cfg: typing.Any, metric_name: str) -> None:
        self.cfg = cfg
        self.metric_name = metric_name

    def construct_file_name(self, groupby: list[str], idx: typing.Hashable) -> str:
        """
        Construct the file name based on the provided template.

        Parameters
        ----------
        groupby
            List of groupby keys used to fill the template.
        idx
            The data-frame index from the groupby clause.  Scalars of
            any type (str, int, etc.) are wrapped in a tuple so they
            can be zipped with *groupby*.

        Returns
        -------
        :
            The constructed filename string (without extension).
        """
        if not isinstance(idx, (list, tuple)):
            idx = (idx,)
        resolved = {
            g: ALIAS_LOCATION_REV.get(i, i) for g, i in zip(groupby, idx, strict=True)
        }
        return self.cfg.file_name_template.format(metric=self.metric_name, **resolved)

    def to_html(
        self,
        fig: go.Figure,
        output_path: pathlib.Path,
        groupby: list[str],
        idx: typing.Hashable,
    ) -> pathlib.Path:
        """
        Serialise *fig* to an HTML file.

        Parameters
        ----------
        fig
            Plotly figure to serialise.
        output_path
            Folder to save the file under (the ``HTML/`` sub-folder is
            created by the caller).
        groupby
            Groupby keys needed to fill the file-name template.
        idx
            Data-frame index used to fill the file-name template.

        Returns
        -------
        :
            Path of the written file.
        """
        file_name = f"{self.construct_file_name(groupby, idx)}.html"
        file_path = output_path / "HTML" / file_name

        template_html = """\
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<meta name="repo_name" content="{{ repo_name }}" />
<meta name="repo_branch" content="{{ repo_branch }}" />
<meta name="repo_hash" content="{{ repo_hash }}" />
</head>
<body>
    {{ fig }}
</body>
</html>"""

        div = fig.to_html(include_plotlyjs="directory", full_html=False)
        with file_path.open("w", encoding="utf-8") as fh:
            fh.write(Template(template_html).render(fig=div, **RUN_META_DATA))

        bundle_path = file_path.parent / "plotly.min.js"
        if not bundle_path.exists():
            bundle_path.write_text(
                patch_sankey_circular_layout(get_plotlyjs()), encoding="utf-8"
            )

        return file_path

    def to_json(
        self,
        fig: go.Figure,
        location: str,
        year: typing.Any,
        output_path: pathlib.Path,
        groupby: list[str],
        idx: typing.Hashable,
    ) -> pathlib.Path:
        """
        Serialise *fig* to a JSON file.

        Parameters
        ----------
        fig
            Plotly figure to serialise.
        location
            Geographic location label stored in the JSON payload.
        year
            Year label stored in the JSON payload (``None`` when the
            view does not group by year).
        output_path
            Folder to save the file under.
        groupby
            Groupby keys needed to fill the file-name template.
        idx
            Data-frame index used to fill the file-name template.

        Returns
        -------
        :
            Path of the written file.
        """
        file_name = f"{self.construct_file_name(groupby, idx)}.json"
        file_path = output_path / "JSON" / file_name

        with file_path.open("w", encoding="utf-8") as fh:
            json_content = {
                "location": location,
                "year": year,
                "plot_type": self.cfg.database_plot_type,
                "bus_carrier": self.cfg.database_bus_carrier,
                "specifier": self.cfg.database_specifier,
                "plotly_dict": fig.to_json(),
            }
            json.dump(json_content, fh)

        return file_path


# ---------------------------------------------------------------------------
# LayoutStyler
# ---------------------------------------------------------------------------


class LayoutStyler:
    """
    Apply common Plotly layout, title, legend, and footnote styling.

    Parameters
    ----------
    cfg
        Plot configuration object with ``legend_header``,
        ``title_font_size``, ``font_size``, ``legend_font_size``,
        ``xaxis_title``, ``yaxes_showgrid``, ``yaxes_visible``, and
        ``footnotes`` attributes.
    """

    def __init__(self, cfg: typing.Any) -> None:
        self.cfg = cfg

    def set_base_layout(self, fig: go.Figure) -> None:
        """Apply base figure properties (size, fonts, grid, zero-line)."""
        fig.update_layout(
            height=800,
            font_family="Calibri",
            plot_bgcolor="#ffffff",
            legend_title_text=self.cfg.legend_header,
        )
        fig.update_yaxes(
            showgrid=self.cfg.yaxes_showgrid, visible=self.cfg.yaxes_visible
        )
        fig.add_hline(y=0.0)
        fig.update_xaxes(
            showgrid=False,
            tickprefix="<b>",
            ticksuffix="</b>",
            tickfont_size=20,
            title_font={"size": 20},
        )
        fig.update_layout(
            xaxis={"categoryorder": "category ascending"},
            hovermode="x",
        )
        fig.update_layout(legend={"traceorder": "reversed"})

    def style_title_and_legend_and_xaxis_label(self, fig: go.Figure) -> None:
        """Update figure title font, legend position, and x-axis label."""
        fig.update_layout(
            title_font_size=self.cfg.title_font_size,
            font_size=self.cfg.font_size,
            legend={
                "x": 1,
                "y": 1,
                "font": {"size": self.cfg.legend_font_size},
            },
        )
        if self.cfg.xaxis_title:
            fig.update_layout(xaxis_title=self.cfg.xaxis_title)

    def count_footnote_lines(self) -> int:
        """Return the number of ``<br>`` line-breaks across all footnote texts."""
        return "".join(self.cfg.footnotes).count("<br>")

    def append_footnote(
        self,
        fig: go.Figure,
        footnote_text: str,
        y: float = -0.17,
        align: str = None,
    ) -> None:
        """
        Append a single footnote annotation at the bottom of *fig*.

        Parameters
        ----------
        fig
            Target figure.
        footnote_text
            Text to display.
        y
            Vertical position (negative values move the footnote down).
        align
            Text alignment mode.
        """
        if footnote_text:
            fig.add_annotation(
                text=footnote_text,
                xref="paper",
                yref="paper",
                xanchor="left",
                yanchor="top",
                x=0,
                y=y,
                showarrow=False,
                font={"size": 15},
                align=align,
            )

    def append_footnotes(self, fig: go.Figure) -> None:
        """Append both configured footnotes and adjust the bottom margin."""
        self.append_footnote(fig, self.cfg.footnotes[0], align="left")
        self.append_footnote(fig, self.cfg.footnotes[1], y=-0.2)
        if lines := self.count_footnote_lines():
            fig.update_layout(margin={"b": 125 + 50 * lines})

    def apply(self, fig: go.Figure, unit: str = "", location: str = "") -> None:
        """
        Apply the full standard layout sequence to *fig*.

        Calls :meth:`set_base_layout`,
        :meth:`style_title_and_legend_and_xaxis_label`, and
        :meth:`append_footnotes` in order.

        Parameters
        ----------
        fig
            Target figure.
        unit
            Display unit (currently unused here; available for subclasses).
        location
            Geographic location (currently unused here; available for
            subclasses).
        """
        self.set_base_layout(fig)
        self.style_title_and_legend_and_xaxis_label(fig)
        self.append_footnotes(fig)


# ---------------------------------------------------------------------------
# BarTraceStyler
# ---------------------------------------------------------------------------


class BarTraceStyler:
    """
    Apply consistent styling to bar traces in a Plotly figure.

    Merges the formerly duplicated ``_style_bars`` (width=0.6) and
    ``_style_grouped_bars`` (width=0.8) methods into one class
    parameterised by bar width.

    Parameters
    ----------
    width
        Bar width passed to ``update_traces``.  Use ``0.6`` for plain
        bar charts and ``0.8`` for grouped (faceted) bar charts.
    """

    def __init__(self, width: float) -> None:
        self.width = width

    def apply(self, fig: go.Figure, unit: str) -> None:
        """
        Apply bar-trace styling to all bar traces in *fig*.

        Parameters
        ----------
        fig
            Target figure.
        unit
            Unit string appended to the hover template.
        """
        fig.update_traces(
            selector={"type": "bar"},
            width=self.width,
            textposition="inside",
            insidetextanchor="middle",
            texttemplate="<b>%{customdata[1]}</b>",
            insidetextfont={"size": 16},
            textangle=0,
            hovertemplate="%{customdata[0]}: %{customdata[1]} " + unit,
            hoverlabel={"namelength": 0},
        )


# ---------------------------------------------------------------------------
# TotalSumRenderer
# ---------------------------------------------------------------------------


class TotalSumRenderer:
    """
    Add total-sum scatter annotations on top of stacked bar charts.

    Parameters
    ----------
    col_values
        Name of the column containing numeric values (e.g. the metric
        column returned by the chart's ``df`` property).
    plot_xaxis
        Name of the column used as the x-axis (typically ``DataModel.YEAR``).
    unit
        Unit string appended to the text template.
    """

    def __init__(self, col_values: str, plot_xaxis: str, unit: str) -> None:
        self.col_values = col_values
        self.plot_xaxis = plot_xaxis
        self.unit = unit

    def add_sum_trace(
        self,
        fig: go.Figure,
        df: pd.DataFrame,
        orientation: str = None,
        name_trace: str = "Sum",
    ) -> None:
        """
        Add a scatter trace for total-sum labels on a plain bar chart.

        Parameters
        ----------
        fig
            Target figure.
        df
            Data frame in the same format as ``ESMBarChart.df``.
        orientation
            ``"up"`` for positive values, ``"down"`` for negative
            values, ``None`` for stacked (all values).
        name_trace
            Trace name (used for identification in the JSON output).
        """
        sign = 1
        if orientation == "up":
            values = df[df[self.col_values].gt(0)]
        elif orientation == "down":
            sign = -1
            values = df[df[self.col_values].le(0)]
        else:
            values = df

        totals = values.groupby(self.plot_xaxis).sum(numeric_only=True)
        totals["display_value"] = totals[self.col_values].apply(prettify_number)
        y_offset = totals[self.col_values].abs().max() / 100 * sign

        scatter = go.Scatter(
            x=totals.index,
            y=totals[self.col_values] + y_offset,
            text=totals["display_value"],
            texttemplate="<b> %{text} " + self.unit + "</b>",
            mode="text",
            textposition=f"{'bottom' if orientation == 'down' else 'top'} center",
            showlegend=False,
            name=name_trace,
            textfont={"size": 18},
            hoverinfo="skip",
        )
        fig.add_trace(scatter)

    def add_subplot_traces(
        self,
        fig: go.Figure,
        df: pd.DataFrame,
        facet_column: str,
    ) -> None:
        """
        Add total-sum scatter traces for every subplot in a faceted bar chart.

        Parameters
        ----------
        fig
            Target figure (must have been built with ``make_subplots``).
        df
            Data frame in the same format as ``ESMGroupedBarChart.df``.
        facet_column
            Column name used for faceting (e.g. ``DataModel.BUS_CARRIER``).
        """

        def _add_for_xaxis(xaxis: go.layout.XAxis) -> None:
            idx = xaxis["anchor"].lstrip("y")
            sector = xaxis["title"]["text"].lstrip("<b>")
            values = df[df[facet_column] == sector].copy()

            values["pos"] = values[self.col_values].where(values[self.col_values].gt(0))
            values["neg"] = values[self.col_values].where(values[self.col_values].le(0))

            totals = values.groupby(self.plot_xaxis).sum(numeric_only=True)
            totals["pos_display"] = totals["pos"].apply(prettify_number)
            totals["neg_display"] = totals["neg"].apply(prettify_number)

            col = int(idx) if idx else 1

            if totals["pos"].sum() > 0:
                fig.add_trace(
                    go.Scatter(
                        x=totals.index,
                        y=totals["pos"] + totals["pos"].abs().max() / 100,
                        text=totals["pos_display"],
                        texttemplate="<b>%{text}</b>",
                        mode="text",
                        textposition="top center",
                        showlegend=False,
                        name="Sum",
                        textfont={"size": 18},
                        hoverinfo="skip",
                    ),
                    col=col,
                    row=1,
                )

            if totals["neg"].sum() < 0:
                fig.add_trace(
                    go.Scatter(
                        x=totals.index,
                        y=totals["neg"] - totals["neg"].abs().max() / 100,
                        text=totals["neg_display"],
                        texttemplate="<b>%{text}</b>",
                        mode="text",
                        textposition="bottom center",
                        showlegend=False,
                        name="Sum",
                        textfont={"size": 18},
                        hoverinfo="skip",
                    ),
                    col=col,
                    row=1,
                )

        fig.for_each_xaxis(_add_for_xaxis)


# ---------------------------------------------------------------------------
# TimeSeriesStyler
# ---------------------------------------------------------------------------


class TimeSeriesStyler:
    """
    Apply time-series-specific Plotly styling.

    Parameters
    ----------
    cfg
        Plot configuration object with ``yaxis_color`` attribute.
    """

    def __init__(self, cfg: typing.Any) -> None:
        self.cfg = cfg

    def style_inflexible_demand(self, fig: go.Figure) -> None:
        """Override trace style for the 'Inflexible Demand' series."""
        fig.update_traces(
            selector={"name": "Inflexible Demand"},
            fillcolor=None,
            fill=None,
            stackgroup=None,
            legendrank=2000,
        )

    def style_axes_and_layout(self, fig: go.Figure, title: str, unit: str) -> None:
        """
        Update axes and layout for time-series figures.

        Parameters
        ----------
        fig
            Target figure.
        title
            Figure title string.
        unit
            Unit label for the y-axis title.
        """
        fig.update_yaxes(
            tickprefix="<b>",
            ticksuffix="</b>",
            tickfont_size=15,
            color=self.cfg.yaxis_color,
            title_font_size=15,
            tickformat=".0f",
            gridwidth=1,
            gridcolor="gainsboro",
        )
        fig.update_xaxes(ticklabelmode="period")
        fig.update_layout(
            title=title,
            yaxis_title=unit,
            hovermode="x",
        )


# ---------------------------------------------------------------------------
# Shared figure utilities
# ---------------------------------------------------------------------------


def empty_figure(title: str) -> go.Figure:
    """
    Return an empty graph with explanation text.

    Parameters
    ----------
    title
        The figure title displayed at the top of the graph.

    Returns
    -------
    :
        The plotly figure with a text that explains that there is no
        data available for this view.
    """
    fig = px.bar(pd.DataFrame(), title=title)
    fig.add_annotation(
        text="No Values to be displayed",
        xref="paper",
        yref="paper",
        xanchor="center",
        yanchor="middle",
        x=0.5,
        y=0.5,
        showarrow=False,
        font={"size": 20},
    )
    fig.update_xaxes(showgrid=False, showticklabels=False)
    fig.update_yaxes(showgrid=False, showticklabels=False)
    fig.update_layout(xaxis_title="", yaxis_title="", plot_bgcolor="white")
    fig.update_layout(meta=[RUN_META_DATA])
    return fig
