# SPDX-FileCopyrightText: Contributors to PyPSA-Eur <https://github.com/pypsa/pypsa-eur>
#
# SPDX-License-Identifier: MIT
"""A module for functions that augment existing pypsa-eur or pypsa-de modules."""

from math import isnan

import pandas as pd
import pypsa


def calculate_additional_tooltip_statistics(
    n: pypsa.Network, carrier: str, carriers_in_eb: pd.Index
) -> dict:
    flow_peak = n.statistics.transmission(
        groupby=False, bus_carrier=carrier, at_port=[0], groupby_time="max"
    )

    capacity_kwargs = dict(
        groupby=False,
        bus_carrier=carrier,
        at_port=[0],
        components=["Line", "Link"],
        carrier=carriers_in_eb.tolist(),
        aggregate_across_components=True,
    )

    p_opt = n.statistics.optimal_capacity(**capacity_kwargs).div(1e3)
    p_opt.attrs["unit"] = "GW"
    p_installed = n.statistics.installed_capacity(**capacity_kwargs).div(1e3)
    p_installed.attrs["unit"] = "GW"
    p_expanded = n.statistics.expanded_capacity(**capacity_kwargs).div(1e3)
    p_expanded.attrs["unit"] = "GW"
    return {
        "flow_peak": flow_peak,
        "p_opt": p_opt,
        "p_installed": p_installed,
        "p_expanded": p_expanded,
    }


def get_flow_unit(unit_conversion: float, settings: dict) -> str:
    if unit_conversion == 1:
        return "MWh/year"
    elif unit_conversion == 1_000:
        return "GWh/year"
    elif unit_conversion == 1_000_000:
        return "TWh/year"
    else:  # fallback to config or default
        return settings.get("flow_unit", "MWh/year")


def get_import_node_coordinates(settings: dict) -> dict:
    # ToDo: define import node coordinates in config
    #   Example: import_node_coords = {"EU gas": {"x": 10.5, "y": 49.0, "label": "EU Gas Import"}}
    return settings.get("import_node_coords", {})


def remove_redundant_layer_items(layer, value, threshold=0.001):
    return [
        d
        for d in layer.data
        if not isnan(d.get(value, 0)) and d.get(value, 0) > threshold
    ]


def update_pydeck_layer_tooltip_for_paths(deck, stats: dict, flow_unit: str) -> None:
    paths_layer_index = {
        i for i, layer in enumerate(deck.layers) if layer.type == "PathLayer"
    }
    # if len(first_paths_layer_index) > 1:
    #     raise KeyError(f"Multiple PathLayer objects detected: {first_paths_layer_index}")

    layer = deck.layers[paths_layer_index.pop()]

    # remove irrelevant paths to save disk space
    layer.data = remove_redundant_layer_items(layer, "width")

    for item in layer.data:
        # make width absolute value. The flow arrow contains direction info.
        item["width"] = abs(item["width"])
        item["width_pdk"] = abs(item["width_pdk"])

        name = item["name"]

        item["tooltip_html"] = (
            f"<b>{name}</b>\n<table>\n"
            f"<tr><td style='font-weight:bold'>bus0:</td>"
            f"<td style='text-align:left'>{item['bus0']}</td></tr>\n"
            f"<tr><td style='font-weight:bold'>bus1:</td>"
            f"<td style='text-align:left'>{item['bus1']}</td></tr>\n"
            f"<tr><td style='font-weight:bold'>Net flow:</td>"
            f"<td style='text-align:left'>{item['width']:.2f} {flow_unit}</td></tr>\n"
            f"<tr><td style='font-weight:bold'>Total capacity:</td>"
            f"<td style='text-align:left'>{stats['p_opt'].loc[name]:.2f} {stats['p_opt'].attrs['unit']}</td></tr>\n"
            f"<tr><td style='font-weight:bold'>Installed capacity:</td>"
            f"<td style='text-align:left'>{stats['p_expanded'].loc[name]:.2f} {stats['p_expanded'].attrs['unit']}</td></tr>\n"
            f"<tr><td style='font-weight:bold'>Existing capacity:</td>"
            f"<td style='text-align:left'>{stats['p_installed'].get(name, 0):.2f} {stats['p_installed'].attrs['unit']}</td></tr>\n"
            f"</table>"
        )


def update_pydeck_layer_tooltip_for_circles(deck, stats: dict, flow_unit: str) -> None:
    circles_layers_index = [
        i for i, layer in enumerate(deck.layers) if layer.type == "PolygonLayer"
    ]
    for idx in circles_layers_index:
        if is_arrow := "arrow" in deck.layers[idx].data[0]:
            value = "flow"
        else:
            value = "size"

        layer = deck.layers[idx]
        layer.data = remove_redundant_layer_items(layer, value)

        for item in layer.data:
            if is_arrow:
                item["tooltip_html"] = (
                    f"<b>{item['name']}</b>\n<table>\n"
                    f"<tr><td style='font-weight:bold'>Flow:</td>"
                    f"<td style='text-align:left'>{item['flow']:.2f} {flow_unit}</td></tr>\n"
                    f"</table>"
                )
            else:
                direction = "Supply" if item["size"] >= 0 else "Withdrawal"
                item["tooltip_html"] = (
                    f"<b>{item['bus']}</b>\n<table>\n"
                    f"<tr><td style='font-weight:bold'>Technology:</td>"
                    f"<td style='text-align:left'>{item['label']}</td></tr>\n"
                    f"<tr><td style='font-weight:bold'>{direction}:</td>"
                    f"<td style='text-align:left'>{abs(item['size']):.2f} {flow_unit}</td></tr>\n"
                    f"</table>"
                )


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
    title = carrier
    if isinstance(carrier, list) and "low voltage" in carrier:
        title = "AC"
    return f"""
    <div style="position: fixed;
                bottom: 20px; right: 20px; width: 280px;
                background-color: white; border: 2px solid #333;
                border-radius: 6px; padding: 15px;
                font-family: Arial, sans-serif; font-size: 12px;
                z-index: 9999; box-shadow: 0 2px 8px rgba(0,0,0,0.2);">
        <h4 style="margin: 0 0 10px 0; font-size: 14px; font-weight: bold;">
            Legend: {title} Map
        </h4>
        <div style="margin-bottom: 12px; border-top: 1px solid #ddd; padding-top: 10px;">
            <b>Pie Charts (Buses)</b><br>
            <span style="color: #666;">
                ⯊ Upper half: Annual supply ({flow_unit})<br>
                ⯋ Lower half: Annual demand ({flow_unit})<br>
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


def augment_deck_before_export(
    deck,
    n: pypsa.Network,
    carrier,
    carriers_in_eb,
    unit_conversion: float,
    settings: dict,
    region_unit: str,
    output_path,
) -> None:
    """
    Apply all augmentations to the deck and export as an HTML file.

    Parameters
    ----------
    deck
        The interactive map deck to augment.
    n
        The solved network.
    carrier
        The carrier(s) being visualised.
    carriers_in_eb
        Carriers present in the energy balance.
    unit_conversion
        Divisor applied to flow values (1, 1_000, or 1_000_000).
    settings
        Interactive map settings from snakemake params.
    region_unit
        Unit label for the regional choropleth price (e.g. "€/MWh").
    output_path
        Destination path for the HTML file.
    """
    stats = calculate_additional_tooltip_statistics(n, carrier, carriers_in_eb)
    flow_unit = get_flow_unit(unit_conversion, settings)

    update_pydeck_layer_tooltip_for_paths(deck, stats, flow_unit)
    update_pydeck_layer_tooltip_for_circles(deck, stats, flow_unit)

    html_output = deck.to_html(offline=False, as_string=True)

    legend = build_legend_html(carrier, region_unit, flow_unit)
    if "</body>" in html_output:
        html_output = html_output.replace("</body>", f"{legend}\n</body>")
    else:
        html_output += legend

    with open(output_path, "w") as f:
        f.write(html_output)
