# SPDX-FileCopyrightText: Contributors to PyPSA-Eur <https://github.com/pypsa/pypsa-eur>
#
# SPDX-License-Identifier: MIT
"""
Create interactive energy balance maps for the defined carriers using `n.explore()`.
"""

from math import isnan

import geopandas as gpd
import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
import pydeck as pdk
import pypsa
from pypsa.plot.maps.interactive import PydeckPlotter
from pypsa.statistics import get_transmission_carriers

from scripts._helpers import (
    configure_logging,
    set_scenario_config,
    update_config_from_wildcards,
)
from scripts.add_electricity import sanitize_carriers

VALID_MAP_STYLES = PydeckPlotter.VALID_MAP_STYLES


def build_legend_html(carrier: str, region_unit: str, flow_unit: str) -> str:
    """
    Build an HTML legend overlay describing layers and semantics.

    Parameters
    ----------
    carrier : str
        Carrier name (e.g., "gas", "H2", "AC")
    region_unit : str
        Unit for choropleth (e.g., "€/MWh")
    flow_unit : str
        Unit for flows/capacities (e.g., "MWh/year", "GW")

    Returns
    -------
    str
        HTML string for the legend overlay.
    """
    legend_html = f"""
    <div style="position: fixed;
                bottom: 20px; right: 20px; width: 280px;
                background-color: white; border: 2px solid #333;
                border-radius: 6px; padding: 15px;
                font-family: Arial, sans-serif; font-size: 12px;
                z-index: 9999; box-shadow: 0 2px 8px rgba(0,0,0,0.2);">
        <h4 style="margin: 0 0 10px 0; font-size: 14px; font-weight: bold;">
            Legend: {carrier.title()} Map
        </h4>
        <div style="margin-bottom: 12px; border-top: 1px solid #ddd; padding-top: 10px;">
            <b>Pie Charts (Buses)</b><br>
            <span style="color: #666;">
                ▲ Upper half: Annual supply ({flow_unit})<br>
                ▼ Lower half: Annual demand ({flow_unit})<br>
                Each color = one carrier type
            </span>
        </div>
        <div style="margin-bottom: 12px; border-top: 1px solid #ddd; padding-top: 10px;">
            <b>Flows & Arrows</b><br>
            <span style="color: #666;">
                Line width ∝ net annual flow ({flow_unit})<br>
                Arrow direction = flow direction<br>
                Arrow size ∝ |flow magnitude|
            </span>
        </div>
        <div style="margin-bottom: 12px; border-top: 1px solid #ddd; padding-top: 10px;">
            <b>Regional Colors</b><br>
            <span style="color: #666;">
                Choropleth = weighted price ({region_unit})<br>
                Time-averaged nodal marginal price
            </span>
        </div>
        <div style="border-top: 1px solid #ddd; padding-top: 10px;">
            <b>Import Nodes</b><br>
            <span style="color: #666;">
                Nodes outside country boundary<br>
                represent external supply sources
            </span>
        </div>
        <p style="margin-top: 10px; font-size: 11px; color: #999;">
            💡 Hover over elements for details
        </p>
    </div>
    """
    return legend_html


def scalar_to_rgba(
    value: float,
    *,
    norm: mcolors.Normalize,
    cmap: mcolors.Colormap,
    alpha: float = 1.0,
) -> list[int]:
    """
    Map a scalar float value to an RGBA color encoded as 8-bit integers.

    Parameters
    ----------
    value : float
        Scalar input to map through the normalization and colormap.
    norm : matplotlib.colors.Normalize
        Normalization defining vmin and vmax used for scaling.
    cmap : matplotlib.colors.Colormap
        Colormap used to convert normalized values to RGBA colors.
    alpha : float, optional (default = 1.0)
        Opacity in the range [0, 1]. Overrides the colormap's alpha.

    Returns
    -------
    List[int]
        A list ``[R, G, B, A]`` where each channel is an integer in the 0–255 range.
    """

    # Clamp to normalization bounds
    p = max(norm.vmin, min(norm.vmax, value))

    # Convert to RGBA floats (0–1)
    r, g, b, _ = cmap(norm(p))

    # Clamp and apply alpha
    a = alpha if 0.0 <= alpha <= 1.0 else 1.0

    # Convert to 8-bit integers
    return [
        int(r * 255),
        int(g * 255),
        int(b * 255),
        int(a * 255),
    ]


if __name__ == "__main__":
    if "snakemake" not in globals():
        from scripts._helpers import mock_snakemake

        snakemake = mock_snakemake(
            "plot_balance_map_interactive",
            run="AT_KN2040",
            clusters="adm",
            opts="",
            sector_opts="none",
            planning_horizons="2030",
            carrier="gas",
        )

    configure_logging(snakemake)
    set_scenario_config(snakemake)
    update_config_from_wildcards(snakemake.config, snakemake.wildcards)

    # Interactive map settings
    settings = snakemake.params.settings
    unit_conversion = settings["unit_conversion"]
    cmap = settings["cmap"]
    region_alpha = settings["region_alpha"]
    region_unit = settings["region_unit"]
    branch_color = settings["branch_color"]
    arrow_size_factor = settings["arrow_size_factor"]
    bus_size_max = settings["bus_size_max"]
    branch_width_max = settings["branch_width_max"]
    map_style = settings.get("map_style")
    map_style = VALID_MAP_STYLES.get(map_style, "road")
    tooltip = settings["tooltip"]

    # Import
    n = pypsa.Network(snakemake.input.network)
    sanitize_carriers(n, snakemake.config)
    pypsa.options.params.statistics.round = 8
    pypsa.options.params.statistics.drop_zero = True
    pypsa.options.params.statistics.nice_names = False

    regions = gpd.read_file(snakemake.input.regions).set_index("name")
    carrier = snakemake.wildcards.carrier
    carrier = carrier.replace("_", " ")

    # Fill missing carrier colors
    missing_color = "#808080"
    b_missing = n.carriers.query("color == '' or color.isnull()").index
    n.carriers.loc[b_missing, "color"] = missing_color

    transmission_carriers = get_transmission_carriers(n, bus_carrier=carrier).rename(
        {"name": "carrier"}
    )
    components = transmission_carriers.unique("component")
    carriers = transmission_carriers.unique("carrier")

    # Pie charts - compute energy balance per bus and carrier
    eb = n.statistics.energy_balance(
        bus_carrier=carrier,
        groupby=["bus", "carrier"],
    )

    # Only carriers that are also in the energy balance
    carriers_in_eb = carriers[carriers.isin(eb.index.get_level_values("carrier"))]

    eb.loc[components] = eb.loc[components].drop(index=carriers_in_eb, level="carrier")
    eb = eb.dropna()
    bus_size = eb.groupby(level=["bus", "carrier"]).sum()

    # Line and links widths according to net annual flow
    flow = n.statistics.transmission(groupby=False, bus_carrier=carrier, at_port=[0])
    flow_peak = n.statistics.transmission(
        groupby=False, bus_carrier=carrier, at_port=[0], groupby_time="max"
    )
    p_opt = n.statistics.optimal_capacity(
        groupby=False,
        bus_carrier=carrier,
        components=["Line", "Link"],
        carrier=carriers_in_eb.tolist(),
    )  # .filter(regex="Link|Line")
    p_installed = n.statistics.installed_capacity(
        groupby=False,
        bus_carrier=carrier,
        at_port=[0],
        components=["Line", "Link"],
        carrier=carriers_in_eb.tolist(),
    )
    p_expanded = n.statistics.expanded_capacity(
        groupby=False,
        bus_carrier=carrier,
        at_port=[0],
        components=["Line", "Link"],
        carrier=carriers_in_eb.tolist(),
    )
    # todo: capacity: n.statistics.optimal_capacity(groupby=False, bus_carrier=carrier, at_port=[0]).filter(regex="Link|Line")
    if not flow.empty:
        flow_reversed_mask = flow.index.get_level_values(1).str.contains("reversed")
        flow_reversed = flow[flow_reversed_mask].rename(
            lambda x: x.replace("-reversed", "")
        )
        flow = flow[~flow_reversed_mask].subtract(flow_reversed, fill_value=0)

    # Extract line and link flows separately
    line_flow = (
        flow.loc[flow.index.get_level_values(0).str.contains("Line")]
        .copy()
        .droplevel(0)
    )
    link_flow = (
        flow.loc[flow.index.get_level_values(0).str.contains("Link")]
        .copy()
        .droplevel(0)
    )

    branch_components = ["Link"]
    if carrier == "AC":
        branch_components = ["Line", "Link"]

    # Enhanced tooltips for buses (with units)
    # Determine flow unit based on unit_conversion factor
    if unit_conversion == 1:
        flow_unit = "MWh/year"
    elif unit_conversion == 1_000:
        flow_unit = "GWh/year"
    elif unit_conversion == 1_000_000:
        flow_unit = "TWh/year"
    else:
        flow_unit = settings.get(
            "flow_unit", "MWh/year"
        )  # fallback to config or default

    # Import nodes - hardcoded by user for external supply sources
    # User should define import node coordinates in config or hardcode here
    # Example: import_node_coords = {"EU gas": {"x": 10.5, "y": 49.0, "label": "EU Gas Import"}}
    import_node_coords = settings.get("import_node_coords", {})

    # Weighted nodal marginal prices for regional choropleth
    buses = n.buses.query("carrier in @carrier").index
    demand = (
        n.statistics.energy_balance(
            bus_carrier=carrier, aggregate_time=False, groupby=["bus", "carrier"]
        )
        .clip(lower=0)
        .groupby("bus")
        .sum()
        .reindex(buses)
        .rename(n.buses.location)
        .T
    )

    weights = n.snapshot_weightings.generators
    price = (
        weights
        @ n.buses_t.marginal_price.reindex(buses, axis=1).rename(
            n.buses.location, axis=1
        )
        / weights.sum()
    )

    if carrier == "co2 stored" and "CO2Limit" in n.global_constraints.index:
        co2_price = n.global_constraints.loc["CO2Limit", "mu"]
        price = price - co2_price

    # If only one price is available, use it for all regions
    if price.size == 1:
        regions["price"] = price.values[0]
        shift = round(abs(price.values[0]) / 20, 0)
    else:
        regions["price"] = price.reindex(regions.index).fillna(0)
        shift = 0

    vmin, vmax = regions.price.min() - shift, regions.price.max() + shift
    if settings["vmin"] is not None:
        vmin = settings["vmin"]
    if settings["vmax"] is not None:
        vmax = settings["vmax"]

    # Map colors using colormap normalization
    norm = mcolors.Normalize(vmin=vmin, vmax=vmax)
    cmap = plt.get_cmap(cmap)

    regions["color"] = regions["price"].apply(
        scalar_to_rgba,
        norm=norm,
        cmap=cmap,
        alpha=region_alpha,
    )

    # Create tooltips with units
    regions["tooltip_html"] = (
        "<b>"
        + regions.index
        + "</b><br>"
        + "<b>Weighted price:</b> "
        + regions["price"].round(2).astype(str)
        + " "
        + region_unit
    )

    # Regional choropleth layer
    regions_layer = pdk.Layer(
        "GeoJsonLayer",
        regions,
        stroked=True,
        filled=True,
        get_fill_color="color",
        get_line_color=[255, 255, 255, 255],
        line_width_min_pixels=1,
        pickable=True,
        auto_highlight=True,
    )

    # # Enhanced bus tooltip with units
    # # Build bus metadata for better tooltips
    # bus_tooltip_meta = {}
    # for (bus_name, carrier_name), value in bus_size.items():
    #     key = (bus_name, carrier_name)
    #     if key not in bus_tooltip_meta:
    #         bus_tooltip_meta[key] = {
    #             "value": value / unit_conversion,
    #             "unit": flow_unit,
    #         }

    # # Enhanced link tooltip with installed capacity and units
    # link_tooltip_meta = {}
    # if not n.links.empty:
    #     for link_idx in n.links.index:
    #         link_data = n.links.loc[link_idx]
    #         # Get flow (already computed)
    #         try:
    #             flow_val = link_flow.get(link_idx, 0)
    #         except KeyError:
    #             flow_val = 0
    #
    #         # Compute installed capacity (additional capacity beyond original)
    #         p_nom = link_data.get("p_nom", 0)
    #         p_nom_opt = link_data.get("p_nom_opt", 0)
    #         installed = (
    #             max(0, p_nom_opt - p_nom)
    #             if pd.notna(p_nom_opt) and pd.notna(p_nom)
    #             else 0
    #         )
    #
    #         link_tooltip_meta[link_idx] = {
    #             "flow": flow_val / unit_conversion if flow_val != 0 else 0,
    #             "capacity": p_nom_opt / unit_conversion if pd.notna(p_nom_opt) else 0,  # fixme: p_nom is GW base not MW
    #             "installed": installed / unit_conversion,
    #             "flow_unit": flow_unit,
    #             "capacity_unit": "GW"
    #             if "GW" in flow_unit or "MW" not in flow_unit
    #             else "MW",
    #         }

    deck = n.explore(
        branch_components=branch_components,
        bus_size=bus_size.div(unit_conversion),
        bus_split_circle=True,
        line_width=line_flow.div(unit_conversion),
        line_flow=line_flow.div(unit_conversion),
        line_color="rosybrown",
        link_width=link_flow.div(unit_conversion),
        link_flow=link_flow.div(unit_conversion),
        link_color=branch_color,
        arrow_size_factor=arrow_size_factor,
        tooltip=tooltip,
        auto_scale=True,
        branch_width_max=branch_width_max,
        bus_size_max=bus_size_max,
        map_style=map_style,
    )

    # purge irrelevant paths from tooltip to safe disk space
    idx_paths_layer = {
        i for i, l in enumerate(deck.layers) if l.type == "PathLayer"
    }.pop()
    paths = deck.layers[idx_paths_layer]
    paths.data = [d for d in paths.data if not isnan(d["width"])]

    # inplace edit the paths layer
    for item in paths.data:
        # make width absolute value. The flow arrow contains this info.
        item["width"] = abs(item["width"])
        item["width_pdk"] = abs(item["width_pdk"])

        # # update tooltip info boxes
        # meta = link_tooltip_meta.get(item["name"])
        # if meta:
        item["tooltip_html"] = (
            f"<b>{item['name']}</b>\n<table>\n"
            f"<tr><td style='font-weight:bold'>bus0:</td>"
            f"<td style='text-align:left'>{item['bus0']}</td></tr>\n"
            f"<tr><td style='font-weight:bold'>bus1:</td>"
            f"<td style='text-align:left'>{item['bus1']}</td></tr>\n"
            f"<tr><td style='font-weight:bold'>Net flow:</td>"
            f"<td style='text-align:left'>{item['width']:.2f} {flow_unit}</td></tr>\n"
            # f"<tr><td style='font-weight:bold'>Total capacity:</td>"
            # f"<td style='text-align:left'>{meta['capacity']:.2f} {meta['capacity_unit']}</td></tr>\n"
            # f"<tr><td style='font-weight:bold'>Newly installed:</td>"
            # f"<td style='text-align:left'>{meta['installed']:.2f} {meta['capacity_unit']}</td></tr>\n"
            f"</table>"
        )

    deck.layers.insert(0, regions_layer)

    # Generate HTML and inject legend overlay
    html_output = deck.to_html(offline=False, as_string=True)
    # todo: minify unnecessarily large HTML string

    # Inject legend before closing body tag
    legend = build_legend_html(carrier, region_unit, flow_unit)
    if "</body>" in html_output:
        html_output = html_output.replace("</body>", f"{legend}\n</body>")
    else:
        html_output += legend

    # Write enhanced HTML file
    with open(snakemake.output[0], "w") as f:
        f.write(html_output)
