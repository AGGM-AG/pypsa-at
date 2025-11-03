# SPDX-FileCopyrightText: 2023-2025 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""Module to collect configuration items and their default values."""

from dataclasses import dataclass, field

from evals.constants import COLOUR_SCHEME, DataModel, Group


@dataclass()
class PlotConfig:
    """
    Configuration for Plotly figure generation and styling.

    This dataclass holds all configuration parameters for creating
    interactive Plotly charts including layout, colors, patterns,
    and export settings.

    Attributes
    ----------
    title
        Figure title template with placeholders for location and unit.
    chart
        Chart class instance (ESMBarChart, ESMGroupedBarChart, etc.).
    file_name_template
        Template for output file names with placeholder fields.
    unit
        Display unit for the metric, defaults to metric.df.attrs["unit"].
    plotby
        Index levels to group by before plotting. One figure per group.
    pivot_index
        Index levels to keep when pivoting the data frame.
    pivot_columns
        Column levels to create when pivoting the data frame.
    plot_category
        Index level name used for color/pattern assignment.
    plot_xaxis
        Index level name for the x-axis.
    facet_column
        Index level for creating subplot panels in GroupedBarChart.
    category_orders
        Tuple defining the display order of categories in legend.
    colors
        Dictionary mapping category names to hex color codes.
    pattern
        Dictionary mapping category names to fill patterns.
    fill
        Dictionary mapping category names to fill modes.
    stacked
        Whether to stack bars/areas in the chart.
    line_dash
        Dictionary mapping category names to line dash styles.
    line_width
        Dictionary mapping category names to line widths.
    line_shape
        Line interpolation shape ('hv', 'linear', 'spline').
    legend_header
        Text for the legend title.
    xaxis_title
        Text for the x-axis label.
    yaxis_color
        Color for y-axis elements.
    footnotes
        Tuple of two footnote strings for bottom annotations.
    cutoff
        Minimum absolute value threshold for displaying data.
    cutoff_drop
        Whether to drop values below cutoff (only for BarCharts).
    legend_font_size
        Font size for legend text in points.
    title_font_size
        Font size for figure title in points.
    font_size
        Base font size for figure text in points.
    xaxis_font_size
        Font size for x-axis labels in points.
    yaxes_showgrid
        Whether to display y-axis gridlines.
    yaxes_visible
        Whether y-axis is visible.

    Examples
    --------
    Create a custom configuration:

    >>> cfg = PlotConfig(
    ...     title="Energy Balance {location}",
    ...     unit="TWh",
    ...     stacked=True,
    ...     cutoff=0.01
    ... )
    """

    title: str = None
    chart = None  # ESMBarChart | ESMGroupedBarChart | ESMTimeSeriesChart
    file_name_template: str = "{metric}_{year}_{location}"
    unit: str = ""  # default is metric.df.attrs["unit"]

    # database column mapping picked up from config.toml
    database_plot_type: str = ""
    database_specifier: str = ""
    database_bus_carrier: str = ""

    # the metric data frame is grouped this index level before plotting.
    # One html figure is created per resulting group.
    plotby: list = field(default_factory=lambda: [DataModel.LOCATION])

    # Used to pivot the data frame before sending it to the plotter. The
    # specified index/column levels will be in the plot data frame. The
    # rest is aggregated (summed up).
    pivot_index: list = field(default_factory=lambda: DataModel.YEAR_IDX_NAMES)
    pivot_columns: list = field(default_factory=lambda: [])

    plot_category: str = DataModel.CARRIER
    plot_xaxis: str = DataModel.YEAR

    # defines the subplots in GroupedBarChart
    facet_column: str = DataModel.BUS_CARRIER

    category_orders: tuple = ()
    colors: dict = field(default_factory=lambda: COLOUR_SCHEME)
    pattern: dict = field(
        default_factory=lambda: dict.fromkeys(
            [
                Group.import_foreign,
                Group.export_foreign,
                Group.import_domestic,
                Group.export_domestic,
                Group.import_net,
                Group.export_net,
                Group.import_global,
            ],
            "/",
        )
    )
    fill: dict = field(default_factory=dict)
    stacked: bool = True
    line_dash: dict = field(default_factory=dict)
    line_width: dict = field(default_factory=dict)
    line_shape: str = "hv"
    legend_header: str = "Categories"
    xaxis_title: str = "<b>Years</b>"
    yaxis_color: str = "DarkSlateGrey"
    footnotes: tuple = ("", "")
    cutoff: float = 0.0001  # needs update depending on unit
    cutoff_drop: bool = True  # only effective in BarCharts

    legend_font_size: int = 20
    title_font_size: int = 30
    font_size: int = 20
    xaxis_font_size: int = 20
    yaxes_showgrid: bool = False
    yaxes_visible: bool = False


@dataclass()
class ExcelConfig:
    """
    Configuration for Excel file generation and formatting.

    Holds settings for Excel workbook creation including chart types,
    styling, pivot table layouts, and color schemes.

    Attributes
    ----------
    axis_labels
        Labels for chart axes [x-axis, y-axis]. Defaults to
        [metric.name, metric.unit].
    chart
        Chart type: 'stacked', 'clustered', 'standard',
        'percentStacked', or None for no chart.
    chart_title
        Title displayed on the Excel chart.
    chart_width
        Chart width in centimeters.
    chart_switch_axis
        Whether to swap categories with x-axis values.
    chart_colors
        Dictionary mapping category names to hex color codes
        (without '#' prefix for Excel).
    pivot_index
        Index level(s) for pivot table rows.
    pivot_columns
        Index level(s) for pivot table columns.
    """

    axis_labels: list = None
    chart: str = "stacked"  # 'stacked', 'clustered', 'standard', 'percentStacked', None
    chart_title: str = None
    chart_width: int = 20  # cm
    chart_switch_axis: bool = False  # switch categories with x-axis
    chart_colors: dict = field(
        default_factory=lambda: {k: v.lstrip("#") for k, v in COLOUR_SCHEME.items()}
    )
    # pivot tables to use the following labels as index or column
    pivot_index: str | list = field(
        default_factory=lambda: [DataModel.LOCATION, DataModel.CARRIER]
    )
    pivot_columns: str | list = DataModel.YEAR


@dataclass()
class ViewDefaults:
    """
    Default configuration container for metric export operations.

    Holds separate configuration spaces for Excel and Plotly exports,
    allowing independent customization of each export format. Both
    configurations are processed by their respective export methods.

    Attributes
    ----------
    excel
        Configuration for Excel file generation and formatting.
    plotly
        Configuration for Plotly chart generation and styling.

    Notes
    -----
    The 'excel' and 'plotly' fields are kept separate to reduce
    variable namespace complexity during export operations.

    Examples
    --------
    Create defaults with custom Excel configuration:

    >>> defaults = ViewDefaults()
    >>> defaults.excel.chart = "clustered"
    >>> defaults.plotly.cutoff = 0.1
    """

    excel: ExcelConfig = field(default_factory=lambda: ExcelConfig())
    plotly: PlotConfig = field(default_factory=lambda: PlotConfig())
