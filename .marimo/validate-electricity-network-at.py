import marimo

__generated_with = "0.23.13"
app = marimo.App(width="medium")


@app.cell
def _():
    from pathlib import Path

    import geopandas as gpd
    import marimo as mo
    import matplotlib.patches as mpatches
    import matplotlib.pyplot as plt
    import pandas as pd
    from shapely import wkt

    return Path, gpd, mo, mpatches, pd, plt, wkt


@app.cell(hide_code=True)
def _(mo):
    mo.md("""
    # Validate the Austrian Electricity Grid from OSM data source including 110 kV levels

    This notebook overlays the Austrian NUTS3 administrative regions with the
    110 kV transmission network extracted from OpenStreetMap (OSM) data.
    """)
    return


@app.cell
def _(mo):
    mo.md("""
    ## 1. NUTS3 Regions
    """)
    return


@app.cell
def _(Path, gpd):
    nuts3_path = Path(
        "data/eu_nuts2021/archive/2021-01-01/ref-nuts-2021-01m.geojson"
        "/NUTS_RG_01M_2021_4326_LEVL_3.geojson"
    )
    nuts3_all = gpd.read_file(nuts3_path)
    nuts3_at = nuts3_all[nuts3_all["CNTR_CODE"] == "AT"].copy()
    nuts3_at = nuts3_at.reset_index(drop=True)
    nuts3_at[["NUTS_ID", "NAME_LATN", "geometry"]]
    return nuts3_all, nuts3_at


@app.cell
def _(mo):
    mo.md("""
    ## 2. OSM 110 kV Network
    """)
    return


@app.cell
def _(Path, gpd, pd, wkt):
    osm_dir = Path("data/osm/archive/0.3-at")

    buses_raw = pd.read_csv(osm_dir / "buses.csv", quotechar="'")

    # --- Buses 110 kV ---
    buses_at_110 = buses_raw[
        (buses_raw["country"] == "AT") & (buses_raw["voltage"] == 110.0)
    ].copy()
    buses_at_110["geometry"] = buses_at_110["geometry"].apply(wkt.loads)
    buses_gdf = gpd.GeoDataFrame(buses_at_110, geometry="geometry", crs="EPSG:4326")

    # --- Lines 110 kV---
    lines_raw = pd.read_csv(osm_dir / "lines.csv", quotechar="'")
    at_bus_ids = set(buses_at_110["bus_id"])
    lines_at_110 = lines_raw[
        (lines_raw["voltage"] >= 65.0)
        & (lines_raw["bus0"].isin(at_bus_ids) | lines_raw["bus1"].isin(at_bus_ids))
    ].copy()
    lines_at_110["geometry"] = lines_at_110["geometry"].apply(wkt.loads)
    lines_gdf = gpd.GeoDataFrame(lines_at_110, geometry="geometry", crs="EPSG:4326")

    print(f"Buses (AT, 110 kV): {len(buses_gdf)}")
    print(f"Lines  (AT, 110 kV): {len(lines_gdf)}")
    return buses_gdf, lines_gdf, osm_dir


@app.cell
def _(mo):
    mo.md("""
    ## 3. Map — NUTS3 Regions + 110 kV Grid
    """)
    return


@app.cell
def _(buses_gdf, lines_gdf, mpatches, nuts3_at, plt):
    fig, ax = plt.subplots(figsize=(12, 8))

    # NUTS3 polygons
    nuts3_at.plot(
        ax=ax,
        color="#e8f4ea",
        edgecolor="#6aaa6a",
        linewidth=0.8,
        label="NUTS3 regions",
    )

    # 110 kV lines
    lines_gdf.plot(
        ax=ax,
        color="#e05c1a",
        linewidth=0.9,
        alpha=0.8,
        label="110 kV lines",
    )

    # 110 kV substations / buses
    buses_gdf.plot(
        ax=ax,
        color="#1a5fe0",
        markersize=10,
        marker="o",
        alpha=0.85,
        label="110 kV substations",
    )

    # Legend
    _legend_handles = [
        mpatches.Patch(facecolor="#e8f4ea", edgecolor="#6aaa6a", label="NUTS3 regions"),
        mpatches.Patch(facecolor="#e05c1a", label="110 kV lines"),
        mpatches.Patch(facecolor="#1a5fe0", label="110 kV substations"),
    ]
    ax.legend(handles=_legend_handles, loc="lower left", fontsize=10)

    ax.set_title(
        "Austrian NUTS3 Regions + OSM 110 kV Transmission Network", fontsize=14
    )
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    ax.set_aspect("equal")

    plt.tight_layout()
    fig
    return


@app.cell
def _(mo):
    mo.md("""
    ## 4. Map — NUTS3 Regions + All Voltage Levels
    """)
    return


@app.cell
def _(gpd, osm_dir, pd, wkt):
    # osm_dir_all = Path("data/osm/archive/v0.2-at")

    buses_raw_all = pd.read_csv(osm_dir / "buses.csv", quotechar="'")
    lines_raw_all = pd.read_csv(osm_dir / "lines.csv", quotechar="'")

    # All AT buses (any voltage)
    at_buses_all_v = buses_raw_all[buses_raw_all["country"] == "AT"].copy()
    at_buses_all_v["geometry"] = at_buses_all_v["geometry"].apply(wkt.loads)
    buses_gdf_all = gpd.GeoDataFrame(
        at_buses_all_v, geometry="geometry", crs="EPSG:4326"
    )

    # Lines where at least one end is an AT bus
    at_bus_ids_v = set(at_buses_all_v["bus_id"])
    lines_at_all = lines_raw_all[
        lines_raw_all["bus0"].isin(at_bus_ids_v)
        | lines_raw_all["bus1"].isin(at_bus_ids_v)
    ].copy()
    lines_at_all["geometry"] = lines_at_all["geometry"].apply(wkt.loads)
    lines_gdf_all = gpd.GeoDataFrame(lines_at_all, geometry="geometry", crs="EPSG:4326")

    print(f"Buses (AT, all voltages): {len(buses_gdf_all)}")
    print(lines_gdf_all.groupby("voltage").size().rename("lines").to_string())
    return buses_gdf_all, lines_gdf_all


@app.cell
def _(buses_gdf_all, lines_gdf_all, mpatches, nuts3_at, plt):
    # Voltage → colour mapping
    _voltage_colours = {
        110.0: "#e05c1a",
        220.0: "#1a5fe0",
        380.0: "#8B008B",
    }
    _default_colour = "#999999"

    fig3, ax3 = plt.subplots(figsize=(12, 8))

    # NUTS3 polygons
    nuts3_at.plot(
        ax=ax3,
        color="#e8f4ea",
        edgecolor="#6aaa6a",
        linewidth=0.8,
    )

    # Lines grouped by voltage level
    _seen_voltages = []
    for _v, _grp in lines_gdf_all.groupby("voltage"):
        _col = _voltage_colours.get(_v, _default_colour)
        _grp.plot(ax=ax3, color=_col, linewidth=0.9, alpha=0.85)
        _seen_voltages.append((_v, _col))

    # Buses (all voltages, single style)
    buses_gdf_all.plot(
        ax=ax3,
        color="#333333",
        markersize=3,
        marker="o",
        alpha=0.6,
    )

    # Legend
    _legend_handles = [
        mpatches.Patch(facecolor="#e8f4ea", edgecolor="#6aaa6a", label="NUTS3 regions"),
        mpatches.Patch(facecolor="#333333", label="Substations (all voltages)"),
    ] + [
        mpatches.Patch(facecolor=_c, label=f"{int(_v)} kV lines")
        for _v, _c in sorted(_seen_voltages)
    ]
    ax3.legend(handles=_legend_handles, loc="lower left", fontsize=9)

    ax3.set_title(
        "Austrian NUTS3 Regions + OSM Transmission Network (All Voltage Levels)",
        fontsize=13,
    )
    ax3.set_xlabel("Longitude")
    ax3.set_ylabel("Latitude")
    ax3.set_aspect("equal")

    plt.tight_layout()
    fig3
    return


@app.cell
def _(mo):
    mo.md("""
    ## 5. Cross-Border International Lines (AT ↔ Neighbours)
    """)
    return


@app.cell
def _(gpd, osm_dir, pd, wkt):
    # osm_dir_xb = Path("data/osm/archive/v0.1-at")

    buses_all = pd.read_csv(osm_dir / "buses.csv", quotechar="'")
    lines_all = pd.read_csv(osm_dir / "lines.csv", quotechar="'")

    # Map bus_id → country for quick lookup
    bus_country = buses_all.set_index("bus_id")["country"].to_dict()

    at_bus_ids_all = set(buses_all.loc[buses_all["country"] == "AT", "bus_id"])

    # Cross-border: exactly one end in AT
    xb_mask = (lines_all["bus0"].isin(at_bus_ids_all)) != (
        lines_all["bus1"].isin(at_bus_ids_all)
    )
    lines_xb = lines_all[xb_mask].copy()

    # Determine the foreign country for each line
    def _foreign_country(row):
        c0 = bus_country.get(row["bus0"], "?")
        c1 = bus_country.get(row["bus1"], "?")
        return c1 if c0 == "AT" else c0

    lines_xb["foreign_country"] = lines_xb.apply(_foreign_country, axis=1)

    lines_xb["geometry"] = lines_xb["geometry"].apply(wkt.loads)
    lines_xb_gdf = gpd.GeoDataFrame(lines_xb, geometry="geometry", crs="EPSG:4326")

    print(f"Cross-border lines: {len(lines_xb_gdf)}")
    print(lines_xb_gdf.groupby("foreign_country").size().rename("count").to_string())
    return buses_all, lines_xb_gdf


@app.cell
def _(lines_xb_gdf, mpatches, nuts3_all, nuts3_at, plt):
    # Neighbour country outlines (for context)
    neighbour_codes = set(lines_xb_gdf["foreign_country"].unique())
    nuts3_neighbours = nuts3_all[nuts3_all["CNTR_CODE"].isin(neighbour_codes)].copy()

    # Colour palette per foreign country
    _palette = [
        "#e41a1c",
        "#377eb8",
        "#4daf4a",
        "#984ea3",
        "#ff7f00",
        "#a65628",
        "#f781bf",
        "#999999",
    ]
    countries_sorted = sorted(neighbour_codes)
    country_colour = {
        c: _palette[i % len(_palette)] for i, c in enumerate(countries_sorted)
    }

    fig2, ax2 = plt.subplots(figsize=(14, 9))

    # Neighbour country fills (light grey)
    if len(nuts3_neighbours):
        nuts3_neighbours.plot(
            ax=ax2,
            color="#f0f0f0",
            edgecolor="#cccccc",
            linewidth=0.5,
        )

    # AT NUTS3 polygons
    nuts3_at.plot(
        ax=ax2,
        color="#e8f4ea",
        edgecolor="#6aaa6a",
        linewidth=0.8,
    )

    # Cross-border lines, coloured by foreign country
    for country, group in lines_xb_gdf.groupby("foreign_country"):
        group.plot(
            ax=ax2,
            color=country_colour[country],
            linewidth=1.8,
            alpha=0.9,
            label=country,
        )

    # Legend
    _legend_handles = [
        mpatches.Patch(
            facecolor="#e8f4ea", edgecolor="#6aaa6a", label="AT NUTS3 regions"
        ),
        mpatches.Patch(
            facecolor="#f0f0f0", edgecolor="#cccccc", label="Neighbouring countries"
        ),
    ] + [
        mpatches.Patch(facecolor=country_colour[c], label=f"AT ↔ {c}")
        for c in countries_sorted
    ]
    ax2.legend(handles=_legend_handles, loc="lower left", fontsize=9)

    ax2.set_title(
        "Cross-Border Transmission Lines: Austria ↔ Neighbouring Countries", fontsize=14
    )
    ax2.set_xlabel("Longitude")
    ax2.set_ylabel("Latitude")
    ax2.set_aspect("equal")

    # Zoom to bounding box of AT + a small buffer
    _bounds = nuts3_at.total_bounds  # minx, miny, maxx, maxy
    _buf = 1.5
    ax2.set_xlim(_bounds[0] - _buf, _bounds[2] + _buf)
    ax2.set_ylim(_bounds[1] - _buf, _bounds[3] + _buf)

    plt.tight_layout()
    fig2
    return


@app.cell
def _(mo):
    mo.md("""
    ## 6. Clustered NUTS3 Shapes (Administrative Clustering)
    """)
    return


@app.cell
def _(Path, gpd):
    clustered_path = Path("resources/regions_onshore_base_s_adm.geojson")
    regions_all = gpd.read_file(clustered_path)
    regions_all_formatted = regions_all.reset_index(drop=True)
    regions_at = regions_all[regions_all["name"].str.startswith("AT")].copy()
    regions_at = regions_at.reset_index(drop=True)
    print(f"Clustered AT regions: {len(regions_at)}")
    regions_at[["name", "geometry"]]
    return (regions_all_formatted,)


@app.cell
def _(mpatches, plt, regions_all_formatted):
    fig4, ax4 = plt.subplots(figsize=(12, 7))

    # Filled contour of clustered NUTS3 shapes
    regions_all_formatted.plot(
        ax=ax4,
        color="#ffffff",
        edgecolor="#000000",
        linewidth=1,
        alpha=1.0,
    )

    # Label each region with its name
    for _, _row in regions_all_formatted.iterrows():
        _centroid = _row.geometry.centroid
        # ax4.annotate(
        #    _row["name"],
        #    xy=(_centroid.x, _centroid.y),
        #    fontsize=6,
        #    ha="center",
        #    va="center",
        #    color="#0d2a6e",
        # )

    _legend_handles = [
        mpatches.Patch(
            facecolor="#cce5ff", edgecolor="#1a5fe0", label="Clustered NUTS3 regions"
        ),
    ]
    ax4.legend(handles=_legend_handles, loc="lower left", fontsize=10)

    ax4.set_title(
        "Clustered Austrian NUTS3 Regions (Administrative Clustering, adm)", fontsize=14
    )
    ax4.set_xlabel("Longitude")
    ax4.set_ylabel("Latitude")
    ax4.set_aspect("equal")

    plt.tight_layout()
    fig4
    return


@app.cell
def _(mo):
    mo.md("""
    ## 7. Remove Cross-Border Lines ≤ 110 kV
    """)
    return


@app.cell
def _(gpd, pd):
    def remove_cross_border_lines_lv(
        lines_df: pd.DataFrame,
        buses_df: pd.DataFrame,
        max_voltage: float = 110.0,
    ) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
        """
        Remove cross-border lines at or below *max_voltage* kV from *lines_df*.

        A line is considered cross-border when exactly one of its endpoints (bus0,
        bus1) belongs to Austria.

        Parameters
        ----------
        lines_df:
            Raw lines DataFrame with columns ``bus0``, ``bus1``, ``voltage``,
            ``geometry`` (WKT string).
        buses_df:
            Raw buses DataFrame with columns ``bus_id``, ``country``.
        max_voltage:
            Voltage threshold in kV (inclusive).  Lines with
            ``voltage <= max_voltage`` that cross the Austrian border are removed.

        Returns
        -------
        kept : GeoDataFrame
            Austrian lines with cross-border low-voltage lines removed.
        removed : GeoDataFrame
            The cross-border low-voltage lines that were dropped.
        """
        from shapely import wkt as _wkt

        at_bus_ids = set(buses_df.loc[buses_df["country"] == "AT", "bus_id"])

        # All lines that touch at least one AT bus
        at_lines = lines_df[
            lines_df["bus0"].isin(at_bus_ids) | lines_df["bus1"].isin(at_bus_ids)
        ].copy()

        # Cross-border mask: exactly one endpoint in AT
        xb_mask = at_lines["bus0"].isin(at_bus_ids) != at_lines["bus1"].isin(at_bus_ids)

        removed_mask = xb_mask & (at_lines["voltage"] <= max_voltage)
        removed_df = at_lines[removed_mask].copy()
        kept_df = at_lines[~removed_mask].copy()

        for df in (kept_df, removed_df):
            df["geometry"] = df["geometry"].apply(_wkt.loads)

        kept = gpd.GeoDataFrame(kept_df, geometry="geometry", crs="EPSG:4326")
        removed = gpd.GeoDataFrame(removed_df, geometry="geometry", crs="EPSG:4326")
        return kept, removed

    return (remove_cross_border_lines_lv,)


@app.cell
def _(osm_dir, pd, remove_cross_border_lines_lv):
    # _osm_dir = Path("data/osm/archive/v0.1-at")
    _buses_raw = pd.read_csv(osm_dir / "buses.csv", quotechar="'")
    _lines_raw = pd.read_csv(osm_dir / "lines.csv", quotechar="'")

    lines_kept, lines_removed = remove_cross_border_lines_lv(_lines_raw, _buses_raw)

    print(f"AT lines kept   : {len(lines_kept)}")
    print(f"AT lines removed: {len(lines_removed)}")
    print("\nRemoved lines by voltage:")
    print(lines_removed.groupby("voltage").size().rename("count").to_string())
    return lines_kept, lines_removed


@app.cell
def _(lines_kept, lines_removed, mpatches, nuts3_at, plt):
    fig5, ax5 = plt.subplots(figsize=(14, 9))

    # NUTS3 background
    nuts3_at.plot(
        ax=ax5,
        color="#e8f4ea",
        edgecolor="#6aaa6a",
        linewidth=0.8,
    )

    # Kept AT lines (grey, thin)
    lines_kept.plot(
        ax=ax5,
        color="#aaaaaa",
        linewidth=0.6,
        alpha=0.6,
        label="Kept AT lines",
    )

    # Removed cross-border low-voltage lines (red, thick)
    lines_removed.plot(
        ax=ax5,
        color="#e05c1a",
        linewidth=2.0,
        alpha=0.95,
        label="Removed cross-border ≤110 kV",
    )

    _legend_handles = [
        mpatches.Patch(facecolor="#e8f4ea", edgecolor="#6aaa6a", label="NUTS3 regions"),
        mpatches.Patch(facecolor="#aaaaaa", label="Kept AT lines"),
        mpatches.Patch(
            facecolor="#e05c1a",
            label=f"Removed cross-border ≤110 kV ({len(lines_removed)})",
        ),
    ]
    ax5.legend(handles=_legend_handles, loc="lower left", fontsize=9)

    ax5.set_title(
        "Cross-Border Lines ≤110 kV Removed from Austrian Network", fontsize=14
    )
    ax5.set_xlabel("Longitude")
    ax5.set_ylabel("Latitude")
    ax5.set_aspect("equal")

    # Zoom to AT + small buffer
    _bounds = nuts3_at.total_bounds
    _buf = 0.5
    ax5.set_xlim(_bounds[0] - _buf, _bounds[2] + _buf)
    ax5.set_ylim(_bounds[1] - _buf, _bounds[3] + _buf)

    plt.tight_layout()
    fig5.savefig("removed_lines.png")
    return


@app.cell
def _(lines_removed):
    print(lines_removed.to_markdown())
    return


@app.cell
def _(buses_all, lines_removed):
    lines_removed["bus0"].map(buses_all["bus_id"])
    return


@app.cell
def _(lines_removed):
    print(
        lines_removed[
            ["line_id", "bus0", "bus1", "voltage", "circuits", "length", "tags"]
        ]
        .reset_index()
        .to_markdown()
    )
    return


@app.cell
def _():
    return


if __name__ == "__main__":
    app.run()
