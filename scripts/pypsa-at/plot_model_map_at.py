# SPDX-FileCopyrightText: 2026 Austrian Gas Grid Management AG
#
# SPDX-License-Identifier: MIT
# For license information, see the LICENSE.txt file in the project root.
"""
Snakemake script: plot print-quality maps of the PyPSA-AT model input topology.

Draws two static maps of Austria and its neighbours on a shared base layer
(administrative clustering, electricity grid, gas grid):

- power plants coloured by fuel type and sized by capacity,
- Hotmaps industrial sites coloured by subsector and sized by 2014 emissions.

The gas grid shows the SciGRID_gas/INET pipelines of all countries.
"""

import logging

import geopandas as gpd
import numpy as np
import pandas as pd

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


def fill_hotmaps_emissions(hotmaps: pd.DataFrame) -> pd.DataFrame:
    """
    Fill site emissions like ``scripts/build_industrial_distribution_key.py``.

    Uses ``Emissions_ETS_2014``, else ``Emissions_EPRTR_2014``, else the 20 %
    quantile of the sites in the same country and subsector.

    Parameters
    ----------
    hotmaps
        Sites with ``country``, ``Subsector``, ``Emissions_ETS_2014`` and
        ``Emissions_EPRTR_2014``.

    Returns
    -------
    :
        A copy with ``emissions`` (t CO2/a) and ``filled`` (``True`` if the
        quantile was used). Groups without any reported value stay ``NaN``.
    """
    hotmaps = hotmaps.copy()
    reported = hotmaps["Emissions_ETS_2014"].fillna(hotmaps["Emissions_EPRTR_2014"])
    quantile = reported.groupby([hotmaps["country"], hotmaps["Subsector"]]).transform(
        lambda s: s.quantile(0.2)
    )
    hotmaps["emissions"] = reported.fillna(quantile)
    hotmaps["filled"] = reported.isna()
    return hotmaps


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
    return {f: tech_colors[FUELTYPE_CARRIER[f]] for f in fueltypes}


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


def base_map(regions, lines, links, pipes, extent, scales):
    """
    Draw the shared base layer and return the figure and map axes.

    ``scales`` holds the reference values and widths for the line legends.
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
    regions.boundary.plot(
        ax=ax, color=REGION_EDGE, linewidth=0.45, linestyle=REGION_DASH, zorder=2
    )
    ax.add_feature(
        cfeature.BORDERS.with_scale("10m"), edgecolor=BORDER, linewidth=0.8, zorder=2
    )
    ax.add_feature(
        cfeature.COASTLINE.with_scale("10m"), edgecolor=BORDER, linewidth=0.4, zorder=2
    )

    e_ref, e_width = scales["electricity"]
    lines.to_crs(proj.proj4_init).plot(
        ax=ax,
        color=scales["colors"]["AC"],
        linewidth=scale(lines["s_nom"], e_ref, e_width),
        alpha=0.8,
        zorder=3,
    )
    if not links.empty:
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


def line_legend_handles(scales: dict, clustering: str) -> tuple[list, list, list]:
    """Build the legends for the model regions and the grid line widths."""
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch

    e_ref, e_width = scales["electricity"]
    g_ref, g_width, g_cap = scales["gas"]
    colors = scales["colors"]
    electricity = [
        Line2D(
            [],
            [],
            color=colors["AC"],
            lw=scale(v, e_ref, e_width),
            label=f"{v:,.0f} MVA",
        )
        for v in scales["electricity_legend"]
    ]
    electricity.append(Line2D([], [], color=colors["DC"], lw=1.5, label="HVDC link"))
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
        Patch(facecolor=AUSTRIA, label=f"Austria\n({clustering})", **region),
        Patch(facecolor=LAND, label="Other countries", **region),
        Line2D([], [], color=REGION_EDGE, lw=0.6, ls=REGION_DASH, label="Model region"),
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


def finish(fig, title: str, note: str, path: str) -> None:
    """Add the title and the source footer, then save the figure."""
    import textwrap

    fig.text(
        0.015, fig.title_y, title, fontsize=9, fontweight="bold", color=INK, va="top"
    )
    footer = "\n".join(textwrap.wrap(f"{note} {SOURCES}", 165))
    fig.text(
        0.015,
        0.2 / (fig.get_figheight() / CM),
        footer,
        fontsize=5,
        color=INK_MUTED,
        va="bottom",
    )
    fig.savefig(path, dpi=DPI)


def plot_powerplants(base, ppl, share, threshold, colors, scales, clustering, path):
    """Map 1: power plants coloured by fuel type, area proportional to capacity."""
    import cartopy.crs as ccrs
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D

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
    order = ppl.groupby("Fueltype")["Capacity"].sum().sort_values(ascending=False)
    fuel = [
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
    sizes = size_legend_handles(
        scales["powerplants_legend"], p_ref, p_area, lambda v: f"{v:,.0f} MW"
    )
    regions, electricity, gas = line_legend_handles(scales, clustering)
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
    finish(fig, "PyPSA-AT model input: power plants and energy grids", note, path)
    plt.close(fig)


def plot_industry(base, sites, scales, clustering, path):
    """Map 2: Hotmaps industrial sites by subsector, area proportional to emissions."""
    import cartopy.crs as ccrs
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D

    fig, ax, _ = base()
    i_ref, i_area = scales["industry"]
    smallest = min(scales["industry_legend"])
    sites = sites.assign(size=scale(sites["emissions"].fillna(smallest), i_ref, i_area))
    sites = sites.sort_values("size", ascending=False)
    for subsector, (color, marker) in SUBSECTOR_STYLE.items():
        for filled, face in ((False, color), (True, "none")):
            s = sites[(sites["Subsector"] == subsector) & (sites["filled"] == filled)]
            if s.empty:
                continue
            ax.scatter(
                s.geometry.x,
                s.geometry.y,
                s=s["size"],
                marker=marker,
                facecolors=face,
                edgecolors=color if filled else INK,
                linewidths=0.6 if filled else 0.2,
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
    sizes.append(
        Line2D(
            [],
            [],
            ls="",
            marker="o",
            markersize=5,
            markerfacecolor="none",
            markeredgecolor=INK_MUTED,
            markeredgewidth=0.6,
            label="hollow: not reported,\n20 % quantile of\ncountry & subsector",
        )
    )
    regions, electricity, gas = line_legend_handles(scales, clustering)
    add_legends(
        fig,
        [
            ("Subsector (Hotmaps)", style, 0.01, {}),
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
        "Industrial sites sized by 2014 ETS emissions (proxy for production), "
        "else E-PRTR emissions. Line width proportional to capacity (gas capped "
        "at the largest legend value). Dashed lines: model region boundaries."
    )
    finish(fig, "PyPSA-AT model input: industrial sites and energy grids", note, path)
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

    clustering = snakemake.params.clustering
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
        "gas": (10000.0, 1.8, 1.8),  # MW -> pt, capped at 1.8 pt (10 GW)
        "gas_legend": [1500, 5000, 10000],
        "powerplants": (1000.0, 40.0),  # MW -> pt²
        "powerplants_legend": [100, 500, 2000],
        "industry": (1e6, 40.0),  # t CO2/a -> pt²
        "industry_legend": [1e5, 1e6, 5e6],
    }

    def base():
        return base_map(regions, lines, links, pipes, extent, scales)

    # map 1: power plants
    ppl = pd.read_csv(snakemake.input.powerplants, index_col=0)
    ppl, share = filter_powerplants(ppl, extent, threshold)
    logger.info(f"Plotting {len(ppl)} power plants ≥ {threshold} MW ({share:.1%}).")
    plot_powerplants(
        base,
        ppl,
        share,
        threshold,
        fueltype_colors(ppl["Fueltype"].unique(), tech_colors),
        scales,
        clustering,
        snakemake.output.powerplants,
    )

    # map 2: industrial sites
    hotmaps = pd.read_csv(snakemake.input.hotmaps, sep=";", index_col=0)
    sites = gpd.GeoDataFrame(hotmaps, geometry=parse_wkt_points(hotmaps["geom"]))
    sites = sites[sites.geometry.notna()]
    sites = gpd.sjoin(
        sites, regions[["name", "geometry"]], how="inner", predicate="within"
    )
    sites = sites[~sites.index.duplicated()]
    sites["country"] = sites["name"].str[:2]
    sites = fill_hotmaps_emissions(clip_to_extent(sites, extent))
    logger.info(
        f"Plotting {len(sites)} industrial sites, {int(sites['filled'].sum())} with "
        "filled emissions."
    )
    plot_industry(base, sites, scales, clustering, snakemake.output.industry)
