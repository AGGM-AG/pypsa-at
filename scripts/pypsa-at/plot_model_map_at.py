# SPDX-FileCopyrightText: 2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""
Snakemake script: plot print-quality maps of the PyPSA-AT model input topology.

Draws four static maps of Austria and its neighbours on a shared base layer
(model regions, electricity grid, gas grid):

- power plants coloured by fuel type and sized by capacity,
- Hotmaps industrial sites coloured by subsector and sized by 2014 emissions,

each once as raw data (exact geometries, one marker per site) and once in the
PyPSA-AT representation (one pie per model region, straight corridors between
the cluster buses). The raw gas grid shows the SciGRID_gas/INET pipelines; the
clustered one shows the model's gas network with the AGGM capacities for
Austria.
"""

import logging

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import LineString

logger = logging.getLogger(__name__)

# powerplantmatching fuel types -> carrier keys in plotting.tech_colors
FUELTYPE_CARRIER = {
    "Solar": "solar",
    "Wind": "onwind",
    "Hydro": "hydro",
    "Natural Gas": "gas",
    "Oil": "oil",
    "Hard Coal": "coal",
    "Lignite": "lignite",
    "Nuclear": "nuclear",
    "Bioenergy": "biomass",
    "Waste": "waste",
    "Geothermal": "geothermal",
    "Battery": "battery",
    "Hydrogen Storage": "H2",
    "Heat Storage": "water tanks",
    "Mechanical Storage": "other",
    "Other": "other",
}

# Map-only override: tech_colors nuclear (#ff8c00) is hard to tell from gas
# (#e05b09). This dark violet keeps CVD Delta E >= 8 and normal-vision
# Delta E >= 15 against all other fuel type colours on the map.
NUCLEAR_COLOR = "#762a83"


def parse_wkt_points(wkt: pd.Series) -> gpd.GeoSeries:
    """
    Parse WKT point strings, with or without an ``SRID=...;`` prefix.

    Parameters
    ----------
    wkt
        Strings like ``"SRID=4326;POINT(15.1 47.2)"`` or ``"POINT (15.1 47.2)"``.

    Returns
    -------
    :
        Points in EPSG:4326 on the same index. Missing strings become ``None``.
    """
    plain = wkt.str.split(";").str[-1]
    return gpd.GeoSeries.from_wkt(plain, crs="EPSG:4326")


def select_reported_sites(hotmaps: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    """
    Keep the sites with reported emissions: ETS 2014, else E-PRTR 2014.

    Parameters
    ----------
    hotmaps
        Sites with ``Subsector``, ``Emissions_ETS_2014`` and
        ``Emissions_EPRTR_2014``.

    Returns
    -------
    :
        The sites with ``emissions`` (t CO2/a), and the number of dropped
        sites without any reported value per subsector.
    """
    emissions = hotmaps["Emissions_ETS_2014"].fillna(hotmaps["Emissions_EPRTR_2014"])
    reported = emissions.notna()
    dropped = hotmaps.loc[~reported, "Subsector"].value_counts().sort_index()
    return hotmaps.loc[reported].assign(emissions=emissions[reported]), dropped


def aggregate_colocated_plants(ppl: pd.DataFrame) -> pd.DataFrame:
    """
    Merge units of the same fuel type at the same location into one plant.

    Stacked markers of equal units (e.g. the reactors of one nuclear site)
    would otherwise draw as rings.

    Parameters
    ----------
    ppl
        Plants with ``lon``, ``lat``, ``Fueltype`` and ``Capacity`` (MW).

    Returns
    -------
    :
        One row per location and fuel type with the summed ``Capacity``.
    """
    keys = [ppl["lon"].round(4), ppl["lat"].round(4), ppl["Fueltype"]]
    return ppl.groupby(keys)["Capacity"].sum().reset_index()


def assign_to_regions(points: gpd.GeoSeries, regions: gpd.GeoDataFrame) -> pd.Series:
    """
    Name the region that contains each point.

    Parameters
    ----------
    points
        Points in EPSG:4326.
    regions
        Regions with a ``name`` column.

    Returns
    -------
    :
        Region names on the index of ``points``; ``NaN`` outside all regions.
    """
    joined = gpd.sjoin(
        gpd.GeoDataFrame(geometry=points),
        regions[["name", "geometry"]],
        how="left",
        predicate="within",
    )["name"]
    return joined.groupby(level=0).first().reindex(points.index)


def sum_by_region(
    df: pd.DataFrame, region: str, category: str, value: str
) -> pd.DataFrame:
    """
    Sum ``value`` per region and category.

    Returns
    -------
    :
        Regions as rows, categories as columns, 0 where a region lacks a
        category. Rows without a region are ignored.
    """
    return df.pivot_table(
        index=region, columns=category, values=value, aggfunc="sum", fill_value=0.0
    ).rename_axis(index=None, columns=None)


def aggregate_corridors(df: pd.DataFrame, value: str) -> pd.DataFrame:
    """
    Sum ``value`` of all strands between the same two buses, in any direction.

    Returns
    -------
    :
        One row per bus pair (``bus0`` < ``bus1``) with the summed ``value``;
        pairs with zero capacity are dropped.
    """
    ordered = df[["bus0", "bus1"]].apply(sorted, axis=1, result_type="expand")
    ordered.columns = ["bus0", "bus1"]
    ordered[value] = df[value]
    out = ordered.groupby(["bus0", "bus1"], as_index=False)[value].sum()
    return out.loc[out[value] > 0].reset_index(drop=True)


def corridor_lines(corridors: pd.DataFrame, buses: pd.DataFrame) -> gpd.GeoDataFrame:
    """Draw each corridor as a straight line between its bus coordinates."""
    xy = buses[["x", "y"]]
    geometry = [
        LineString([tuple(xy.loc[b0]), tuple(xy.loc[b1])])
        for b0, b1 in zip(corridors["bus0"], corridors["bus1"])
    ]
    return gpd.GeoDataFrame(corridors, geometry=geometry, crs="EPSG:4326")


def pie_angles(values: pd.Series) -> list[tuple[float, float]]:
    """
    Start and end angle (degrees) of each non-zero pie slice.

    Slices start at the top (90°) and run counter-clockwise.
    """
    values = values[values > 0]
    edges = 90.0 + 360.0 * values.cumsum() / values.sum()
    starts = [90.0, *edges.iloc[:-1]]
    return [(float(a), float(b)) for a, b in zip(starts, edges)]


def pipeline_capacity(pipes: pd.DataFrame) -> pd.Series:
    """
    Return the pipeline capacity in MW for the map.

    Uses the upstream ``p_nom`` and fills its gaps with the diameter-based
    estimate ``p_nom_diameter``.
    """
    return pipes["p_nom"].fillna(pipes["p_nom_diameter"])


def scale(values, reference: float, size: float, cap: float | None = None):
    """
    Scale ``values`` linearly so that ``reference`` maps to ``size``.

    With ``cap``, larger results are clipped to ``cap``.
    """
    scaled = values / reference * size
    return scaled if cap is None else np.minimum(scaled, cap)


def fueltype_colors(fueltypes, tech_colors: dict) -> dict:
    """
    Look up the tech colour of each powerplantmatching fuel type.

    Raises
    ------
    KeyError
        If a fuel type has no carrier in :data:`FUELTYPE_CARRIER`.
    """
    unknown = sorted(set(fueltypes) - set(FUELTYPE_CARRIER))
    if unknown:
        raise KeyError(f"No tech colour mapping for fuel types: {unknown}")
    colors = {f: tech_colors[FUELTYPE_CARRIER[f]] for f in fueltypes}
    if "Nuclear" in colors:
        colors["Nuclear"] = NUCLEAR_COLOR
    return colors


def filter_powerplants(
    ppl: pd.DataFrame, extent: tuple[float, float, float, float], threshold: float
) -> tuple[pd.DataFrame, float]:
    """
    Keep the plants inside the map extent with at least ``threshold`` MW.

    Parameters
    ----------
    ppl
        Plants with ``lon``, ``lat`` and ``Capacity`` (MW).
    extent
        ``(lon_min, lon_max, lat_min, lat_max)``.
    threshold
        Minimum capacity in MW.

    Returns
    -------
    :
        The kept plants and their share of the capacity inside the extent.
    """
    lon_min, lon_max, lat_min, lat_max = extent
    inside = ppl["lon"].between(lon_min, lon_max) & ppl["lat"].between(lat_min, lat_max)
    ppl = ppl.loc[inside]
    kept = ppl.loc[ppl["Capacity"] >= threshold]
    return kept, kept["Capacity"].sum() / ppl["Capacity"].sum()


# --- plotting ----------------------------------------------------------------

CM = 1 / 2.54  # inch per cm
FIG_WIDTH = 16.5 * CM
DPI = 300

# Okabe-Ito colours plus a marker shape per subsector, so the subsectors stay
# distinguishable with colour vision deficiencies and in greyscale print.
SUBSECTOR_STYLE = {
    "Iron and steel": ("#0072B2", "o"),
    "Cement": ("#E69F00", "s"),
    "Chemical industry": ("#009E73", "^"),
    "Refineries": ("#D55E00", "D"),
    "Paper and printing": ("#56B4E9", "v"),
    "Glass": ("#CC79A7", "P"),
    "Non-metallic mineral products": ("#F0E442", "X"),
    "Non-ferrous metals": ("#000000", "p"),
    "Other non-classified": ("#999999", "h"),
}

INK = "#262626"
INK_MUTED = "#6b6b6b"
LAND = "#eeeeec"  # neutral land fill for all countries except Austria
AUSTRIA = "#e4dcf2"  # Austria: higher modelling detail (AT35 districts)
SEA = "#8fb6d6"
BORDER = "#3a3a3a"
# region boundaries: neutral grey and dashed, never mistaken for a grid line
REGION_EDGE = "#4d4d4d"
REGION_DASH = (0, (2.5, 1.5))

SOURCES = (
    "Data: grid and plant geometries © OpenStreetMap contributors (ODbL); "
    "gas pipelines SciGRID_gas / INET (CC-BY 4.0); "
    "power plants powerplantmatching (MIT) and E-Control "
    "Anlagenregister; industrial sites Hotmaps industrial database, 2014 data "
    "(CC-BY 4.0); regions NUTS3 © EuroGeographics / Eurostat GISCO; "
    "basemap Natural Earth."
)
SOURCES_CLUSTERED = SOURCES.replace(
    "gas pipelines SciGRID_gas / INET (CC-BY 4.0); ",
    "gas corridors SciGRID_gas / INET (CC-BY 4.0) and AGGM (Austria); ",
)


def load_line_geometries(df: pd.DataFrame, crs) -> gpd.GeoDataFrame:
    """Turn a table with a WKT ``geometry`` column into a projected GeoDataFrame."""
    gdf = gpd.GeoDataFrame(
        df.drop(columns="geometry"),
        geometry=gpd.GeoSeries.from_wkt(df["geometry"]),
        crs="EPSG:4326",
    )
    return gdf.to_crs(crs)


# vertical layout in cm, top to bottom: title, map, legends, footer
MARGIN, TITLE_H, GAP_H, LEGEND_H, FOOTER_H = 0.25, 0.9, 0.35, 3.9, 1.3


def fit_layout(fig, ax) -> None:
    """Size the figure to the map aspect ratio and store the legend anchor."""
    x0, x1, y0, y1 = ax.get_extent()
    map_w = FIG_WIDTH / CM - 2 * MARGIN
    map_h = map_w * (y1 - y0) / (x1 - x0)
    height = TITLE_H + map_h + GAP_H + LEGEND_H + FOOTER_H
    fig.set_size_inches(FIG_WIDTH, height * CM)
    bottom = FOOTER_H + LEGEND_H + GAP_H
    ax.set_position(
        [
            MARGIN / (map_w + 2 * MARGIN),
            bottom / height,
            map_w / (map_w + 2 * MARGIN),
            map_h / height,
        ]
    )
    fig.legend_top = (FOOTER_H + LEGEND_H) / height
    fig.title_y = 1 - 0.25 / height


def base_map(regions, lines, links, pipes, extent, scales, clustered=False):
    """
    Draw the shared base layer and return the figure and map axes.

    ``scales`` holds the reference values and widths for the line legends. The
    clustered variant draws all region outlines with the same emphasis.
    """
    import cartopy.crs as ccrs
    import cartopy.feature as cfeature
    import matplotlib.pyplot as plt

    proj = ccrs.LambertAzimuthalEqualArea(central_longitude=12.5, central_latitude=48)
    fig = plt.figure(figsize=(FIG_WIDTH, FIG_WIDTH), dpi=DPI)
    ax = fig.add_axes([0, 0, 1, 1], projection=proj)
    ax.set_extent(extent, crs=ccrs.PlateCarree())
    fit_layout(fig, ax)

    # land fill (Austria distinct), sea on top of it for a crisp coastline
    regions = regions.to_crs(proj.proj4_init)
    austria = regions["name"].str.startswith("AT")
    ax.add_feature(cfeature.LAND.with_scale("10m"), facecolor=LAND, zorder=0)
    regions.plot(ax=ax, facecolor=np.where(austria, AUSTRIA, LAND), zorder=1)
    ax.add_feature(cfeature.OCEAN.with_scale("10m"), facecolor=SEA, zorder=1.5)
    boundaries = regions.boundary
    boundaries[~austria].plot(
        ax=ax, color=REGION_EDGE, linewidth=0.45, linestyle=REGION_DASH, zorder=2
    )
    emphasis = ~austria if clustered else austria
    boundaries[emphasis | austria].plot(
        ax=ax, color=REGION_EDGE, linewidth=0.7, linestyle=REGION_DASH, zorder=2
    )
    ax.add_feature(
        cfeature.BORDERS.with_scale("10m"), edgecolor=BORDER, linewidth=0.8, zorder=2
    )
    ax.add_feature(
        cfeature.COASTLINE.with_scale("10m"), edgecolor=BORDER, linewidth=0.4, zorder=2
    )

    e_ref, e_width = scales["electricity"]
    # summed corridors of the clustered grid would cover the map: cap them
    e_cap = scales["electricity_cap_clustered"] if clustered else None
    lines.to_crs(proj.proj4_init).plot(
        ax=ax,
        color=scales["colors"]["AC"],
        linewidth=scale(lines["s_nom"], e_ref, e_width, cap=e_cap),
        alpha=0.8,
        capstyle="round",
        zorder=3,
    )
    if links is not None and not links.empty:
        links.to_crs(proj.proj4_init).plot(
            ax=ax,
            color=scales["colors"]["DC"],
            linewidth=scale(links["p_nom"], e_ref, e_width),
            alpha=0.8,
            zorder=3,
        )

    g_ref, g_width, g_cap = scales["gas"]
    pipes.to_crs(proj.proj4_init).plot(
        ax=ax,
        color=scales["colors"]["gas"],
        linewidth=scale(pipes["p_nom_map"], g_ref, g_width, cap=g_cap),
        alpha=0.9,
        capstyle="round",
        zorder=4,
    )
    return fig, ax, proj


def line_legend_handles(scales: dict, clustered=False) -> tuple[list, list, list]:
    """Build the legends for the model regions and the grid line widths."""
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch

    e_ref, e_width = scales["electricity"]
    e_cap = scales["electricity_cap_clustered"] if clustered else None
    e_capped = np.inf if e_cap is None else e_cap / e_width * e_ref
    g_ref, g_width, g_cap = scales["gas"]
    colors = scales["colors"]
    electricity = [
        Line2D(
            [],
            [],
            color=colors["AC"],
            lw=scale(v, e_ref, e_width, cap=e_cap),
            label=f"{'≥ ' if v >= e_capped else ''}{v:,.0f} MVA",
        )
        for v in scales[
            "electricity_legend_clustered" if clustered else "electricity_legend"
        ]
    ]
    if not clustered:
        electricity.append(
            Line2D([], [], color=colors["DC"], lw=1.5, label="HVDC link")
        )
    capped = g_cap / g_width * g_ref
    gas = [
        Line2D(
            [],
            [],
            color=colors["gas"],
            lw=scale(v, g_ref, g_width, cap=g_cap),
            label=f"{'≥ ' if v >= capped else ''}{v:,.0f} MW",
        )
        for v in scales["gas_legend"]
    ]
    region = dict(edgecolor=REGION_EDGE, lw=0.5, ls=(0, (2.5, 1.5)))
    regions = [
        Patch(facecolor=AUSTRIA, label="Austria (NUTS3)", **region),
        Patch(facecolor=LAND, label="Other countries", **region),
        Line2D(
            [],
            [],
            color=REGION_EDGE,
            lw=0.6,
            ls=REGION_DASH,
            label="Model regions" if clustered else "Model region",
        ),
        Line2D([], [], color=BORDER, lw=0.9, label="Country border"),
    ]
    return regions, electricity, gas


def size_legend_handles(values, reference, area, fmt, color=INK_MUTED):
    """Build reference circles for a marker-area legend."""
    from matplotlib.lines import Line2D

    return [
        Line2D(
            [],
            [],
            ls="",
            marker="o",
            markerfacecolor="none",
            markeredgecolor=color,
            markersize=np.sqrt(scale(v, reference, area)),
            label=fmt(v),
        )
        for v in values
    ]


def add_legends(fig, groups: list[tuple[str, list, float, dict]]):
    """Place legend groups side by side at the given x positions below the map."""
    for title, handles, x, kwargs in groups:
        options = {
            "loc": "upper left",
            "bbox_to_anchor": (x, fig.legend_top),
            "frameon": False,
            "fontsize": 6,
            "title_fontsize": 6.5,
            "alignment": "left",
            "handlelength": 2.2,
            "labelspacing": 0.6,
            "borderaxespad": 0,
        }
        leg = fig.legend(handles=handles, title=title, **(options | kwargs))
        leg.get_title().set_fontweight("bold")


def finish(fig, title: str, note: str, path: str, sources: str = SOURCES) -> None:
    """Add the title and the source footer, then save the figure."""
    import textwrap

    fig.text(
        0.015, fig.title_y, title, fontsize=9, fontweight="bold", color=INK, va="top"
    )
    footer = "\n".join(textwrap.wrap(f"{note} {sources}", 165))
    fig.text(
        0.015,
        0.2 / (fig.get_figheight() / CM),
        footer,
        fontsize=5,
        color=INK_MUTED,
        va="bottom",
    )
    fig.savefig(path, dpi=DPI)


TITLE_POWERPLANTS = "PyPSA-AT model input: power plants and energy grids"
TITLE_INDUSTRY = "PyPSA-AT model input: industrial sites and energy grids"


def fuel_legend_handles(capacity: pd.Series, colors: dict) -> list:
    """Colour legend of the fuel types, ordered by total capacity."""
    from matplotlib.lines import Line2D

    order = capacity.groupby(level=0).sum().sort_values(ascending=False)
    return [
        Line2D(
            [],
            [],
            ls="",
            marker="o",
            markersize=5,
            markerfacecolor=colors[f],
            markeredgecolor="white",
            markeredgewidth=0.3,
            label=f,
        )
        for f in order.index
    ]


def plot_powerplants(base, ppl, share, threshold, colors, scales, path):
    """Map 1: power plants coloured by fuel type, area proportional to capacity."""
    import cartopy.crs as ccrs
    import matplotlib.pyplot as plt

    fig, ax, _ = base()
    p_ref, p_area = scales["powerplants"]
    ppl = ppl.sort_values("Capacity", ascending=False)
    ax.scatter(
        ppl["lon"],
        ppl["lat"],
        s=scale(ppl["Capacity"], p_ref, p_area),
        c=ppl["Fueltype"].map(colors),
        edgecolors="white",
        linewidths=0.25,
        alpha=0.9,
        transform=ccrs.PlateCarree(),
        zorder=5,
    )
    fuel = fuel_legend_handles(ppl.set_index("Fueltype")["Capacity"], colors)
    sizes = size_legend_handles(
        scales["powerplants_legend"], p_ref, p_area, lambda v: f"{v:,.0f} MW"
    )
    regions, electricity, gas = line_legend_handles(scales)
    add_legends(
        fig,
        [
            ("Fuel type", fuel, 0.01, {"ncol": 2, "columnspacing": 0.8}),
            ("Capacity", sizes, 0.33, {"labelspacing": 1.4, "borderpad": 0.6}),
            ("Map", regions, 0.49, {}),
            ("Electricity grid", electricity, 0.67, {}),
            ("Gas grid", gas, 0.84, {}),
        ],
    )
    note = (
        f"Power plants ≥ {threshold:.0f} MW shown ({share:.0%} of installed "
        "capacity in the map extent); circle area proportional to capacity. "
        "Line width proportional to capacity (gas capped at the largest legend "
        "value). Dashed lines: model region boundaries."
    )
    finish(fig, f"{TITLE_POWERPLANTS} – raw data", note, path)
    plt.close(fig)


def plot_industry(base, sites, scales, path):
    """Map 2: Hotmaps industrial sites by subsector, area proportional to emissions."""
    import cartopy.crs as ccrs
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D

    fig, ax, _ = base()
    i_ref, i_area = scales["industry"]
    sites = sites.assign(size=scale(sites["emissions"], i_ref, i_area))
    sites = sites.sort_values("size", ascending=False)
    for subsector, (color, marker) in SUBSECTOR_STYLE.items():
        s = sites[sites["Subsector"] == subsector]
        ax.scatter(
            s.geometry.x,
            s.geometry.y,
            s=s["size"],
            marker=marker,
            facecolors=color,
            edgecolors=INK,
            linewidths=0.2,
            alpha=0.9,
            transform=ccrs.PlateCarree(),
            zorder=5,
        )
    style = [
        Line2D(
            [],
            [],
            ls="",
            marker=m,
            markersize=5,
            markerfacecolor=c,
            markeredgecolor=INK,
            markeredgewidth=0.2,
            label=name,
        )
        for name, (c, m) in SUBSECTOR_STYLE.items()
    ]
    sizes = size_legend_handles(
        scales["industry_legend"], i_ref, i_area, lambda v: f"{v / 1e6:g} Mt CO₂/a"
    )
    regions, electricity, gas = line_legend_handles(scales)
    add_legends(
        fig,
        [
            ("Subsector", style, 0.01, {}),
            (
                "ETS emissions 2014",
                sizes,
                0.28,
                {"labelspacing": 1.2, "borderpad": 0.6},
            ),
            ("Map", regions, 0.49, {}),
            ("Electricity grid", electricity, 0.67, {}),
            ("Gas grid", gas, 0.84, {}),
        ],
    )
    note = (
        "Industrial sites sized by 2014 ETS emissions (E-PRTR where ETS missing); "
        "sites without reported emissions omitted. Line width proportional to "
        "capacity (gas capped at the largest legend value). Dashed lines: model "
        "region boundaries."
    )
    finish(fig, f"{TITLE_INDUSTRY} – raw data", note, path)
    plt.close(fig)


def draw_pies(ax, proj, shares: pd.DataFrame, buses, colors: dict, reference, area):
    """
    Draw one pie per region at its bus, area proportional to the row total.

    ``shares`` holds regions as rows and categories as columns. Pies whose bus
    lies outside the map are skipped and logged.
    """
    import cartopy.crs as ccrs
    from matplotlib.patches import Wedge

    x0, x1, y0, y1 = ax.get_extent()
    bbox = ax.get_window_extent()
    width_pt = bbox.width / ax.figure.dpi * 72
    data_per_pt = (x1 - x0) / width_pt

    totals = shares.sum(axis=1).sort_values(ascending=False)
    skipped = []
    for region, total in totals.items():
        x, y = proj.transform_point(*buses.loc[region, ["x", "y"]], ccrs.PlateCarree())
        if not (x0 <= x <= x1 and y0 <= y <= y1):
            skipped.append(region)
            continue
        radius = np.sqrt(scale(total, reference, area) / np.pi) * data_per_pt
        row = shares.loc[region]
        row = row[row > 0]
        for category, (theta1, theta2) in zip(row.index, pie_angles(row)):
            ax.add_patch(
                Wedge(
                    (x, y),
                    radius,
                    theta1,
                    theta2,
                    facecolor=colors[category],
                    edgecolor="white",
                    linewidth=0.3,
                    zorder=5,
                )
            )
    if skipped:
        logger.info(f"Pies with bus outside the map extent skipped: {skipped}")


def plot_powerplants_clustered(base, shares, buses, threshold, colors, scales, path):
    """Map 3: power plant capacity per model region as fuel type pies."""
    import matplotlib.pyplot as plt

    fig, ax, proj = base()
    p_ref, p_area = scales["powerplants"]
    draw_pies(ax, proj, shares, buses, colors, p_ref, p_area)
    fuel = fuel_legend_handles(shares.sum(), colors)
    sizes = size_legend_handles(
        scales["powerplants_legend_clustered"],
        p_ref,
        p_area,
        lambda v: f"{v:,.0f} MW",
    )
    regions, electricity, gas = line_legend_handles(scales, clustered=True)
    add_legends(
        fig,
        [
            ("Fuel type", fuel, 0.01, {"ncol": 2, "columnspacing": 0.8}),
            (
                "Capacity",
                sizes,
                0.33,
                {
                    "labelspacing": 3.0,
                    "borderpad": 1.4,
                    "handlelength": 3.2,
                    "handletextpad": 1.4,
                },
            ),
            ("Map", regions, 0.49, {}),
            ("Electricity (AC + DC)", electricity, 0.67, {}),
            ("Gas grid", gas, 0.84, {}),
        ],
    )
    note = (
        f"One pie per model region at its bus: capacity of the power plants "
        f"≥ {threshold:.0f} MW shown on the raw-data map, split by fuel type; pie "
        "area proportional to capacity (same scale as the raw-data map). Lines "
        "connect the region buses, width proportional to the summed capacity per "
        "corridor (both grids capped at the largest legend value); gas from the "
        "model's "
        "clustered gas network. Dashed lines: model region boundaries."
    )
    finish(
        fig,
        f"{TITLE_POWERPLANTS} – PyPSA-AT representation",
        note,
        path,
        SOURCES_CLUSTERED,
    )
    plt.close(fig)


def plot_industry_clustered(base, shares, buses, scales, path):
    """Map 4: industrial emissions per model region as subsector pies."""
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch

    fig, ax, proj = base()
    i_ref, i_area = scales["industry"]
    colors = {name: color for name, (color, _) in SUBSECTOR_STYLE.items()}
    draw_pies(ax, proj, shares, buses, colors, i_ref, i_area)
    style = [
        Patch(facecolor=color, edgecolor="white", lw=0.3, label=name)
        for name, color in colors.items()
    ]
    sizes = size_legend_handles(
        scales["industry_legend_clustered"],
        i_ref,
        i_area,
        lambda v: f"{v / 1e6:g} Mt CO₂/a",
    )
    regions, electricity, gas = line_legend_handles(scales, clustered=True)
    add_legends(
        fig,
        [
            ("Subsector", style, 0.01, {}),
            (
                "ETS emissions 2014",
                sizes,
                0.28,
                {
                    "labelspacing": 3.0,
                    "borderpad": 1.4,
                    "handlelength": 3.2,
                    "handletextpad": 1.4,
                },
            ),
            ("Map", regions, 0.49, {}),
            ("Electricity (AC + DC)", electricity, 0.67, {}),
            ("Gas grid", gas, 0.84, {}),
        ],
    )
    note = (
        "One pie per model region at its bus: summed 2014 ETS emissions (E-PRTR "
        "where ETS missing) of the industrial sites shown on the raw-data map, "
        "split by subsector; pie area proportional to emissions (same scale as the "
        "raw-data map). Lines connect the region buses, width proportional to the "
        "summed capacity per corridor (both grids capped at the largest legend "
        "value); "
        "gas from the model's clustered gas network. Dashed lines: model region "
        "boundaries."
    )
    finish(
        fig,
        f"{TITLE_INDUSTRY} – PyPSA-AT representation",
        note,
        path,
        SOURCES_CLUSTERED,
    )
    plt.close(fig)


def clip_to_extent(gdf: gpd.GeoDataFrame, extent) -> gpd.GeoDataFrame:
    """Keep the features of a EPSG:4326 frame that intersect the extent (+2°)."""
    lon_min, lon_max, lat_min, lat_max = extent
    return gdf.cx[lon_min - 2 : lon_max + 2, lat_min - 2 : lat_max + 2]


if __name__ == "__main__":
    if "snakemake" not in globals():
        from scripts._helpers import mock_snakemake

        snakemake = mock_snakemake("plot_model_map_at", clusters="adm", run="AT_KN2040")

    import pypsa

    from scripts._helpers import configure_logging

    configure_logging(snakemake)

    extent = tuple(snakemake.params.extent)
    tech_colors = snakemake.params.plotting["tech_colors"]
    threshold = snakemake.params.powerplant_threshold

    regions = gpd.read_file(snakemake.input.regions_onshore)

    # electricity grid
    n = pypsa.Network(snakemake.input.network)
    lines = clip_to_extent(
        load_line_geometries(n.lines[["s_nom", "geometry"]], 4326), extent
    )
    links = n.links.query("carrier == 'DC'")[["p_nom", "geometry"]]
    links = clip_to_extent(load_line_geometries(links, 4326), extent)

    # gas grid: SciGRID_gas/INET pipelines for all countries
    pipes = pd.read_csv(snakemake.input.gas_network, index_col=0)
    pipes["p_nom_map"] = pipeline_capacity(pipes)
    n_filled = int(pipes["p_nom"].isna().sum())
    logger.info(f"Filled {n_filled} missing pipeline p_nom with p_nom_diameter.")
    pipes = clip_to_extent(load_line_geometries(pipes, 4326), extent)

    colors = {
        "AC": tech_colors["AC"],
        "DC": tech_colors["DC"],
        "gas": tech_colors["gas pipeline new"],
    }
    scales = {
        "colors": colors,
        "electricity": (2000.0, 1.0),  # MVA -> pt
        "electricity_legend": [500, 2000, 5000],
        "electricity_cap_clustered": 4.0,  # pt, reached at 8,000 MVA
        "electricity_legend_clustered": [500, 2000, 8000],
        "gas": (10000.0, 1.8, 1.8),  # MW -> pt, capped at 1.8 pt (10 GW)
        "gas_legend": [1500, 5000, 10000],
        "powerplants": (1000.0, 40.0),  # MW -> pt²
        "powerplants_legend": [100, 500, 2000],
        "powerplants_legend_clustered": [1000, 5000, 20000],
        "industry": (1e6, 40.0),  # t CO2/a -> pt²
        "industry_legend": [1e5, 1e6, 5e6],
        "industry_legend_clustered": [1e6, 5e6, 2e7],
    }

    def base():
        return base_map(regions, lines, links, pipes, extent, scales)

    # clustered grids: straight corridors between the cluster buses
    nc = pypsa.Network(snakemake.input.network_clustered)
    buses = nc.buses[["x", "y"]]
    electricity = pd.concat(
        [
            nc.lines[["bus0", "bus1", "s_nom"]],
            nc.links.query("carrier == 'DC'")[["bus0", "bus1", "p_nom"]].rename(
                columns={"p_nom": "s_nom"}
            ),
        ]
    )
    lines_clustered = corridor_lines(aggregate_corridors(electricity, "s_nom"), buses)
    gas_clustered = pd.read_csv(snakemake.input.gas_network_clustered, index_col=0)
    pipes_clustered = corridor_lines(
        aggregate_corridors(gas_clustered, "p_nom"), buses
    ).rename(columns={"p_nom": "p_nom_map"})
    logger.info(
        "Largest clustered gas corridors (MW): "
        f"{pipes_clustered.nlargest(5, 'p_nom_map')[['bus0', 'bus1', 'p_nom_map']].to_dict('records')}"
    )

    def base_clustered():
        return base_map(
            regions,
            clip_to_extent(lines_clustered, extent),
            None,
            clip_to_extent(pipes_clustered, extent),
            extent,
            scales,
            clustered=True,
        )

    # map 1: power plants
    ppl = pd.read_csv(snakemake.input.powerplants, index_col=0)
    ppl, share = filter_powerplants(ppl, extent, threshold)
    n_units = len(ppl)
    ppl = aggregate_colocated_plants(ppl)
    logger.info(
        f"Plotting {n_units} power plants ≥ {threshold} MW ({share:.1%}) at "
        f"{len(ppl)} sites (co-located units of one fuel type merged)."
    )
    ppl_colors = fueltype_colors(ppl["Fueltype"].unique(), tech_colors)
    plot_powerplants(
        base,
        ppl,
        share,
        threshold,
        ppl_colors,
        scales,
        snakemake.output.powerplants_raw,
    )

    # map 3: power plants per model region
    ppl["region"] = assign_to_regions(
        gpd.GeoSeries(gpd.points_from_xy(ppl["lon"], ppl["lat"]), crs="EPSG:4326"),
        regions,
    ).to_numpy()
    n_outside = int(ppl["region"].isna().sum())
    if n_outside:
        logger.info(f"{n_outside} power plants lie outside all model regions.")
    plot_powerplants_clustered(
        base_clustered,
        sum_by_region(ppl, "region", "Fueltype", "Capacity"),
        buses,
        threshold,
        ppl_colors,
        scales,
        snakemake.output.powerplants_clustered,
    )

    # map 2: industrial sites
    hotmaps = pd.read_csv(snakemake.input.hotmaps, sep=";", index_col=0)
    sites = gpd.GeoDataFrame(hotmaps, geometry=parse_wkt_points(hotmaps["geom"]))
    sites = sites[sites.geometry.notna()]
    sites["region"] = assign_to_regions(sites.geometry, regions)
    sites = sites[sites["region"].notna()]
    # exactly the sites visible on the map, so the regional pies sum the same set
    lon_min, lon_max, lat_min, lat_max = extent
    sites = sites.cx[lon_min:lon_max, lat_min:lat_max]
    sites, dropped = select_reported_sites(sites)
    logger.info(
        f"Plotting {len(sites)} industrial sites. Dropped sites without reported "
        f"emissions per subsector: {dropped.to_dict()}"
    )
    plot_industry(base, sites, scales, snakemake.output.industry_raw)

    # map 4: industrial emissions per model region
    plot_industry_clustered(
        base_clustered,
        sum_by_region(sites, "region", "Subsector", "emissions"),
        buses,
        scales,
        snakemake.output.industry_clustered,
    )
