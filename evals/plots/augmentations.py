# SPDX-FileCopyrightText: Contributors to PyPSA-Eur <https://github.com/pypsa/pypsa-eur>
#
# SPDX-License-Identifier: MIT
"""A module for functions that augment existing pypsa-eur or pypsa-de modules."""

from math import isnan

import numpy as np
import pandas as pd
import pypsa
from pypsa.statistics import get_transmission_carriers

from evals.utils import drop_from_multtindex_by_regex

# def combined_branch_capacity_by_corridor(
#     p_opt_branch: pd.Series, links: pd.DataFrame, lines: pd.DataFrame
# ) -> dict:
#     """
#     Sum per-branch optimal capacity into one value per unordered bus pair.
#
#     A bidirectional pipeline is modelled as a forward ``Link`` plus a
#     ``reversed`` mirror copy with swapped buses and identical capacity. The
#     mirror is an optimisation artefact, not extra physical capacity, so it is
#     skipped here. Multiple distinct branches between the same two buses (e.g. a
#     ``->`` and a ``<->`` pipeline) are genuine parallel capacity and summed.
#
#     Parameters
#     ----------
#     p_opt_branch
#         Optimal capacity per branch, indexed by branch name.
#     links
#         ``n.links`` (must carry a ``reversed`` boolean column).
#     lines
#         ``n.lines`` (lines have no mirror copies, so all are kept).
#
#     Returns
#     -------
#     Mapping of ``frozenset({bus0, bus1})`` to the combined capacity.
#     """
#     out: dict = {}
#     for name, capacity in p_opt_branch.items():
#         if name in links.index:
#             if bool(links.at[name, "reversed"]):
#                 continue
#             pair = frozenset((links.at[name, "bus0"], links.at[name, "bus1"]))
#         elif name in lines.index:
#             pair = frozenset((lines.at[name, "bus0"], lines.at[name, "bus1"]))
#         else:
#             continue
#         out[pair] = out.get(pair, 0.0) + abs(capacity)
#     return out


#
# def collapse_items_to_corridors(items: list, p_opt_pair: dict) -> list:
#     """
#     Collapse overlapping branch path-items into one representative per corridor.
#
#     All path-items sharing an unordered bus pair (the parallel ``->``/``<->``
#     pipes and their ``-reversed`` mirrors) draw on top of each other. They are
#     reduced to a single representative carrying the corridor's combined optimal
#     capacity. Duplicates get zero capacity so the caller can purge them.
#
#     The representative is a non-reversed item; its ``net_flow`` becomes the sum
#     of the non-reversed members' net flows (mirror flows are already folded into
#     their forward partners upstream).
#
#     Parameters
#     ----------
#     items
#         Branch path-layer data items. Each must have ``name``, ``bus0``,
#         ``bus1`` and (optionally) ``net_flow``.
#     p_opt_pair
#         Combined capacity per ``frozenset({bus0, bus1})`` corridor.
#
#     Returns
#     -------
#     The representative items (one per corridor), mutated in place.
#     """
#     groups: dict = defaultdict(list)
#     for item in items:
#         groups[frozenset((item["bus0"], item["bus1"]))].append(item)
#
#     representatives = []
#     for pair, group in groups.items():
#         non_reversed = [it for it in group if not it["name"].endswith("-reversed")]
#         members = non_reversed or group
#         representative = members[0]
#         representative["capacity"] = abs(p_opt_pair.get(pair, 0.0))
#         representative["net_flow"] = sum(it.get("net_flow", 0.0) for it in members)
#         for item in group:
#             if item is not representative:
#                 item["capacity"] = 0.0
#         representatives.append(representative)
#     return representatives
#
def get_transmission_corridor(func, carriers: list) -> pd.Series:
    """
    Calculate transmission corridor sums for bus pairs.

    Parameters
    ----------
    func
        The statistics function to use.
    carriers
        Transmission technologies to filter for.

    Returns
    -------
    :
        Aggregated values per bus0/1 pair in GW.
    """
    p = (
        func(
            groupby=["name", "bus0", "bus1", "carrier", "bus_carrier"],
            components=["Line", "Link"],
            carrier=carriers,
        )
        .pipe(drop_from_multtindex_by_regex, "-reversed", level="name")
        .groupby(["bus0", "bus1"])
        .sum()
        .div(1e3)
    )
    p.attrs["unit"] = "GW"
    b0 = p.index.get_level_values("bus0")
    b1 = p.index.get_level_values("bus1")

    # sort each pair so (A,B) and (B,A) map to the same key
    pair = pd.MultiIndex.from_arrays(
        np.sort(np.column_stack([b0, b1]), axis=1).T,
        names=["bus0", "bus1"],
    )

    return p.groupby(pair).sum()


def calculate_additional_tooltip_statistics(n: pypsa.Network, carrier: list) -> dict:

    try:
        p_opt = get_transmission_corridor(n.statistics.optimal_capacity, carrier)
        p_installed = get_transmission_corridor(
            n.statistics.installed_capacity, carrier
        )
        p_expanded = get_transmission_corridor(n.statistics.expanded_capacity, carrier)
    except KeyError:
        # For carrier groups without transmission infrastructure such as oil
        p_opt = p_installed = p_expanded = pd.Series()

    # # scratch to correct capacities
    #
    # # ground truth: DC example location=FR components=Links
    #
    # # all Links from France
    # dc_france_from = n.links.query("carrier == 'DC' & bus0 == 'FR' & ~reversed & active")
    #
    # # all Links to France but reversed (=same as from FR)
    # dc_france_to = n.links.query("carrier == 'DC' & bus1 == 'FR' & reversed & active")
    #
    # assert dc_france_from["p_nom_opt"].sum() - dc_france_to["p_nom_opt"].sum() < 0.1, "Reversed assets do not have the same capacity as directed assets"
    #
    # # DC
    # for loc in n.buses["location"].unique():
    #     dc_from = n.links.query(f"carrier == 'DC' & bus0 == '{loc}' & ~reversed & active")
    #     dc_to = n.links.query(f"carrier == 'DC' & bus1 == '{loc}' & reversed & active")
    #     assert (
    #         dc_from["p_nom_opt"].sum() - dc_to["p_nom_opt"].sum() < 0.1
    #     ), "Reversed assets do not have the same capacity as directed assets"
    #
    # # gas pipelines
    # for loc in n.buses["location"].unique():
    #     gas_from = n.links.query(f"carrier.str.contains('gas pipeline') & bus0 == '{loc} gas' & ~reversed & active")
    #     gas_to = n.links.query(f"carrier.str.contains('gas pipeline') & bus1 == '{loc} gas' & reversed & active")
    #     assert (
    #         gas_from["p_nom_opt"].sum() - gas_to["p_nom_opt"].sum() < 0.1
    #     ), f"Reversed gas pipelines do not have the same capacity as directed assets in {loc}: {gas_from["p_nom_opt"]}\n{gas_to["p_nom_opt"]}"
    #
    # # H2 pipelines
    # for loc in n.buses["location"].unique():
    #     gas_from = n.links.query(f"carrier.str.contains('H2 pipeline') & bus0 == '{loc} gas' & ~reversed & active")
    #     gas_to = n.links.query(f"carrier.str.contains('H2 pipeline') & bus1 == '{loc} gas' & reversed & active")
    #     assert (
    #         gas_from["p_nom_opt"].sum() - gas_to["p_nom_opt"].sum() < 0.1
    #     ), f"Reversed H2 pipelines do not have the same capacity as directed assets in {loc}: {gas_from["p_nom_opt"]}\n{gas_to["p_nom_opt"]}"
    #
    # # CO2 pipelines
    # for loc in n.buses["location"].unique():
    #     gas_from = n.links.query(f"carrier.str.contains('CO2 pipeline') & bus0 == '{loc} gas' & ~reversed & active")
    #     gas_to = n.links.query(f"carrier.str.contains('CO2 pipeline') & bus1 == '{loc} gas' & reversed & active")
    #     assert (
    #         gas_from["p_nom_opt"].sum() - gas_to["p_nom_opt"].sum() < 0.1
    #     ), f"Reversed CO2 pipelines do not have the same capacity as directed assets in {loc}: {gas_from["p_nom_opt"]}\n{gas_to["p_nom_opt"]}"
    #
    # optimal_capacity = n.statistics.optimal_capacity(
    #     groupby=["name", "bus0", "bus1", "carrier", "bus_carrier"],
    #     # bus_carrier=carrier,
    #     components=["Line", "Link"],
    #     carrier=carriers_in_eb.tolist(),
    # ).pipe(drop_from_multtindex_by_regex, "-reversed", level="name").groupby("bus0").sum()
    #
    # # calculate FR sums
    # fr = optimal_capacity.xs("FR")
    #
    # lines_fr = n.lines.query("bus0 == 'FR' & active")["s_nom_opt"]
    # links_fr = n.links.query("bus0 == 'FR' & carrier == 'DC' & active & ~reversed")["p_nom_opt"]
    #
    # fr_direct = lines_fr.sum() + links_fr.sum()
    #
    # assert fr - fr_direct < 0.1, f"Statistics return differently than direct calculations for {loc}"
    #
    # # AC and DC
    # stat_carrier = ["AC", "DC"]
    # optimal_capacity = n.statistics.optimal_capacity(
    #     groupby=["name", "bus0", "bus1", "carrier", "bus_carrier"],
    #     # bus_carrier=carrier,
    #     components=["Line", "Link"],
    #     carrier=stat_carrier,
    # ).pipe(drop_from_multtindex_by_regex, "-reversed", level="name").groupby("bus0").sum()
    # for loc in n.buses["location"].unique():
    #     b = n.links.query(f"bus0 == '{loc}' & carrier in @stat_carrier & active & ~reversed")["p_nom_opt"].sum()
    #     c = n.lines.query(f"bus0 == '{loc}' & carrier in @stat_carrier & active")["s_nom_opt"].sum()
    #     if b == 0:  # pipelines do not exist in the network
    #         continue
    #     a = optimal_capacity.xs(f"{loc}")
    #     assert a - b - c < 0.1
    #
    # # gas pipelines
    # stat_carrier = ["gas pipeline", "gas pipeline new"]
    # optimal_capacity = n.statistics.optimal_capacity(
    #     groupby=["name", "bus0", "bus1", "carrier", "bus_carrier"],
    #     # bus_carrier=carrier,
    #     components=["Line", "Link"],
    #     carrier=stat_carrier,
    #     drop_zero=False,
    #     # at_port=0,
    # ).pipe(drop_from_multtindex_by_regex, "-reversed", level="name").groupby("bus0").sum()
    #
    # for loc in n.buses["location"].unique():
    #     b = n.links.query(f"bus0 == '{loc} gas' & carrier in @stat_carrier & active & ~reversed")["p_nom_opt"].sum()
    #     if b == 0:  # pipelines do not exist in the network
    #         continue
    #     a = optimal_capacity.xs(f"{loc} gas")
    #     assert a - b < 0.1
    #
    # # H2 pipelines
    # stat_carrier = ["H2 pipeline", "H2 pipeline new", "H2 pipeline retrofit", "H2 pipeline (Kernnetz)"]
    # optimal_capacity = (
    #     n.statistics.optimal_capacity(
    #         groupby=["name", "bus0", "bus1", "carrier", "bus_carrier"],
    #         # bus_carrier=carrier,
    #         components=["Line", "Link"],
    #         carrier=stat_carrier,
    #         drop_zero=False,
    #     )
    #     .pipe(drop_from_multtindex_by_regex, "-reversed", level="name")
    #     .groupby("bus0")
    #     .sum()
    # )
    #
    # for loc in n.buses["location"].unique():
    #     b = n.links.query(
    #         f"bus0 == '{loc} gas' & carrier in @stat_carrier & active & ~reversed"
    #     )["p_nom_opt"].sum()
    #     if b == 0:  # pipelines do not exist in the network
    #         continue
    #     a = optimal_capacity.xs(f"{loc} gas")
    #     assert a - b < 0.1

    # we do not need pairs anymore. Simply add the correctly aggregated
    # values per bus0 locations
    # # Combine parallel/reversed branches into one value per corridor so the map
    # # draws a single line whose width reflects the total capacity between two
    # # locations (mirror links excluded, parallel pipes summed).
    # p_opt_pair = combined_branch_capacity_by_corridor(p_opt, n.links, n.lines)
    # p_installed_pair = combined_branch_capacity_by_corridor(
    #     p_installed, n.links, n.lines
    # )
    # p_expanded_pair = combined_branch_capacity_by_corridor(p_expanded, n.links, n.lines)

    # aggregate bus0/bus1 with bus1/bus0 duplicates
    # for s in (p_opt, p_installed, p_expanded)
    #     b0 = s.index.get_level_values("bus0")
    #     b1 = s.index.get_level_values("bus1")
    #
    #     # sort each pair so (A,B) and (B,A) map to the same key
    #     pair = pd.MultiIndex.from_arrays(
    #         np.sort(np.column_stack([b0, b1]), axis=1).T,
    #         names=["bus0", "bus1"],
    #     )
    #
    #     result = s.groupby(pair).sum()

    return {
        # "flow_peak": flow_peak,
        "p_opt": p_opt,
        "p_installed": p_installed,
        "p_expanded": p_expanded,
        # "p_opt_pair": p_opt_pair,
        # "p_installed_pair": p_installed_pair,
        # "p_expanded_pair": p_expanded_pair,
    }


def scale_branch_widths_to_pdk(
    values: pd.Series, branch_width_max: float, global_max: float
) -> pd.Series:
    """
    Replicate pypsa's auto-scaled branch ``width_pdk`` for given data values.

    width_pdk = value / global_max * branch_width_max * 1000

    Parameters
    ----------
    values
        Branch data values (e.g. optimal capacities). Treated as absolute.
    branch_width_max
        The map's maximum branch width setting.
    global_max
        Maximum absolute value across all branch components plotted.

    Returns
    -------
    Pixel widths matching pypsa's auto-scaling. Returns zeros when
    ``global_max`` is not positive (avoids division by zero).
    """
    if global_max <= 0:
        return pd.Series(0.0, index=values.index)
    return values.abs() / global_max * branch_width_max * 1000


def get_flow_unit(unit_conversion: float, settings: dict) -> str:
    if unit_conversion == 1:
        return "MWh/year"
    elif unit_conversion == 1_000:
        return "GWh/year"
    elif unit_conversion == 1_000_000:
        return "TWh/year"
    else:  # fallback to config or default
        return settings.get("flow_unit", "MWh/year")


# def get_import_node_coordinates(settings: dict) -> dict:
#     # ToDo: define import node coordinates in config
#     #   Example: import_node_coords = {"EU gas": {"x": 10.5, "y": 49.0, "label": "EU Gas Import"}}
#     return settings.get("import_node_coords", {})


def remove_redundant_layer_items(deck, layer, value, threshold=0.1):
    return [
        d
        for d in deck.layers[layer].data
        if not isnan(d.get(value, 0)) and d.get(value, 0) > threshold
    ]


def update_pydeck_layer_tooltip_for_paths(
    deck, stats: dict, flow_unit: str, branch_width_max: float
) -> None:
    # Iterate over *all* PathLayers. For carrier AC both Line and Link are
    # plotted (two layers); for most carriers only Link is plotted (one layer).
    path_layer_indices = [
        i for i, layer in enumerate(deck.layers) if layer.type == "PathLayer"
    ]
    # p_opt_pair = stats["p_opt_pair"]
    # p_installed_pair = stats["p_installed_pair"]
    # p_expanded_pair = stats["p_expanded_pair"]

    items = [item for i in path_layer_indices for item in deck.layers[i].data]

    global_max = stats["p_opt"].abs().max()
    scaled = scale_branch_widths_to_pdk(stats["p_opt"], branch_width_max, global_max)

    # One line per node pair. reversed will be dropped because they are checked last
    items.sort(key=lambda it: it["name"].endswith("-reversed"))
    seen = set()
    for item in items:
        bus_pair = tuple(sorted((item["bus0"], item["bus1"])))

        if bus_pair in seen:
            # will be removed later because of 0 width
            item["width"] = 0.0
            item["width_pdk"] = 0.0
            continue
        seen.add(bus_pair)

        scaled_width = scaled.get(bus_pair, 0)
        capacity = stats["p_opt"].get(bus_pair, 0)

        # FixMe: the netted flow below is on a per-asset level. An aggergation logic is
        #    need
        # item["net_flow"] = abs(item.get("width", 0))
        item["net_flow"] = 0

        item["width"] = capacity
        item["width_pdk"] = scaled_width

        name = item["name"]
        item["tooltip_html"] = (
            f"<b>{name}</b>\n<table>\n"
            f"<tr><td style='font-weight:bold'>bus0:</td>"
            f"<td style='text-align:left'>{item['bus0']}</td></tr>\n"
            f"<tr><td style='font-weight:bold'>bus1:</td>"
            f"<td style='text-align:left'>{item['bus1']}</td></tr>\n"
            f"<tr><td style='font-weight:bold'>Optimal capacity:</td>"
            f"<td style='text-align:left'>{item['width']:.2f} {stats['p_opt'].attrs.get('unit')}</td></tr>\n"
            f"<tr><td style='font-weight:bold'>Net flow:</td>"
            f"<td style='text-align:left'>{item['net_flow']:.2f} {flow_unit}</td></tr>\n"
            f"<tr><td style='font-weight:bold'>Expanded capacity:</td>"
            f"<td style='text-align:left'>{stats['p_expanded'].get(bus_pair, 0):.2f} {stats['p_expanded'].attrs.get('unit')}</td></tr>\n"
            f"<tr><td style='font-weight:bold'>Existing capacity:</td>"
            f"<td style='text-align:left'>{stats['p_installed'].get(bus_pair, 0):.2f} {stats['p_installed'].attrs.get('unit')}</td></tr>\n"
            f"</table>"
        )

    for i in path_layer_indices:
        deck.layers[i].data = remove_redundant_layer_items(deck, i, "width")


def remove_arrow_layers(deck) -> None:
    """
    Drop directional flow-arrow PolygonLayers from the deck.

    Branches are sized by optimal capacity, which has no direction, so the
    flow arrows are removed. Pie-chart PolygonLayers (which carry a ``"size"``
    key instead of ``"arrow"``) are kept.
    """
    deck.layers = [
        layer
        for layer in deck.layers
        if not (
            layer.type == "PolygonLayer" and layer.data and "arrow" in layer.data[0]
        )
    ]


def update_pydeck_layer_tooltip_for_circles(deck) -> None:
    idx_circles_layers = [
        i for i, layer in enumerate(deck.layers) if layer.type == "PolygonLayer"
    ]
    for idx in idx_circles_layers:
        deck.layers[idx].data = remove_redundant_layer_items(deck, idx, "size")


def build_legend_html(
    carrier: str | list[str], region_unit: str, flow_unit: str, capacity_unit: str
) -> str:
    """
    Build an HTML legend overlay describing layers and semantics.

    Parameters
    ----------
    carrier
        Carrier name (e.g., "gas", "H2", "AC")
    region_unit
        Unit for choropleth (e.g., "€/MWh")
    flow_unit
        Unit for annual energy flows in the pie charts (e.g., "TWh/year")
    capacity_unit
        Unit for branch optimal capacity (e.g., "GW")

    Returns
    -------
    :
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
            <b>Branch Capacity</b><br>
            <span style="color: #666;">
                Line width ∝ optimal capacity ({capacity_unit})
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


def augment_and_export_html(
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
    transmission_carrier = (
        get_transmission_carriers(n, carrier).get_level_values("carrier").tolist()
    )
    stats = calculate_additional_tooltip_statistics(n, transmission_carrier)
    flow_unit = get_flow_unit(unit_conversion, settings)
    branch_width_max = settings["branch_width_max"]
    capacity_unit = stats["p_opt"].attrs.get("unit", "")

    update_pydeck_layer_tooltip_for_paths(deck, stats, flow_unit, branch_width_max)
    remove_arrow_layers(deck)

    # Only pie-chart PolygonLayers remain (arrow layers already removed).
    update_pydeck_layer_tooltip_for_circles(deck)

    html_output = deck.to_html(offline=False, as_string=True)

    legend = build_legend_html(carrier, region_unit, flow_unit, capacity_unit)
    if "</body>" in html_output:
        html_output = html_output.replace("</body>", f"{legend}\n</body>")
    else:
        html_output += legend

    with open(output_path, "w") as f:
        f.write(html_output)
